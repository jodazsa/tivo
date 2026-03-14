#!/usr/bin/env python3
"""Simplified Raspberry Pi radio controller.

Single script that handles:
- BCD rotary switches for bank/station selection
- I2C volume encoder (Adafruit Seesaw)
- Stop/start toggle switch
- MPD playback via mpc commands
- Stream watchdog (auto-restarts dead streams)
- State persistence across power loss
- Systemd watchdog integration
"""

import json
import logging
import os
import random
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import board
import busio
import RPi.GPIO as GPIO
import yaml
from adafruit_seesaw.seesaw import Seesaw
from adafruit_seesaw.rotaryio import IncrementalEncoder

# ── Paths ──────────────────────────────────────────────────
STATIONS_PATH = Path("/home/radio/stations.yaml")
AUDIO_ROOT = Path("/home/radio/audio")
AUDIO_EXTS = (".mp3", ".flac", ".ogg", ".m4a", ".wav", ".aac")
STATE_PATH = Path("/home/radio/state.json")
STATE_BACKUP_PATH = Path("/home/radio/state.backup.json")

# ── Hardware pin mappings ──────────────────────────────────
# Station BCD switch
STATION_PINS = {"bit0": 9, "bit1": 10, "bit2": 22, "bit3": 17}
# Bank BCD switch
BANK_PINS = {"bit0": 13, "bit1": 6, "bit2": 5, "bit3": 11}
# Stop/start toggle switch
STOP_START_PIN = 24
# Volume encoder I2C address and Seesaw button pin
VOLUME_I2C_ADDR = 0x36
SEESAW_BUTTON_PIN = 24

# ── Tuning ─────────────────────────────────────────────────
POLL_INTERVAL = 0.1       # Main loop sleep (seconds)
DEBOUNCE_TIME = 0.15      # Ignore switch changes faster than this
VOLUME_STEP = 4           # Volume change per encoder click
MAX_VOLUME_DELTA = 4      # Ignore encoder jumps larger than this (I2C glitch guard)
VOLUME_MIN = 0
VOLUME_MAX = 100
DEFAULT_VOLUME = 60
WATCHDOG_INTERVAL = 10.0  # Seconds between stream health checks
WATCHDOG_GRACE = 15.0     # Wait this long before restarting a dead stream
STATE_SAVE_INTERVAL = 5.0 # Seconds between state file writes
CONFIG_CHECK_INTERVAL = 30.0  # Seconds between stations.yaml mtime checks
WATCHDOG_NOTIFY_INTERVAL = 10.0  # Seconds between systemd watchdog keepalives

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("radio")

# ── Shutdown flag ────────────────────────────────────────────
_shutdown = False


def _handle_signal(signum, frame):
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    global _shutdown
    _shutdown = True
    log.info("Received signal %d, shutting down", signum)


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# ── Systemd watchdog ─────────────────────────────────────────

def _watchdog_enabled():
    """Check if systemd watchdog is configured."""
    usec = os.environ.get("WATCHDOG_USEC")
    return usec is not None and int(usec) > 0


def _sd_notify(msg: bytes):
    """Send a notification message to systemd via NOTIFY_SOCKET."""
    try:
        addr = os.environ.get("NOTIFY_SOCKET")
        if not addr:
            return
        if addr.startswith("@"):
            addr = "\0" + addr[1:]
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            sock.connect(addr)
            sock.sendall(msg)
        finally:
            sock.close()
    except Exception:
        pass


def _notify_watchdog():
    """Send keepalive to systemd watchdog."""
    _sd_notify(b"WATCHDOG=1")


def _notify_ready():
    """Tell systemd we're ready (Type=notify)."""
    _sd_notify(b"READY=1")


# ── State persistence ────────────────────────────────────────

def _atomic_write_json(path: Path, payload: dict):
    """Atomically write JSON payload and fsync file + parent directory."""
    dirpath = path.parent
    fd, tmp_path = tempfile.mkstemp(dir=str(dirpath), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
        dfd = os.open(str(dirpath), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save_state(volume, bank, station):
    """Atomically save state to disk and rotate a backup copy."""
    state = {
        "volume": volume,
        "bank": bank,
        "station": station,
        "timestamp": int(time.time()),
    }
    try:
        _atomic_write_json(STATE_PATH, state)
        _atomic_write_json(STATE_BACKUP_PATH, state)
    except Exception as e:
        log.warning("Failed to save state: %s", e)


def _validate_state(data):
    """Validate loaded state and normalize values."""
    if not isinstance(data, dict):
        return None

    volume = data.get("volume")
    bank = data.get("bank")
    station = data.get("station")
    if not all(isinstance(v, int) for v in (volume, bank, station)):
        return None

    if not (VOLUME_MIN <= volume <= VOLUME_MAX):
        return None
    if not (-1 <= bank <= 9 and -1 <= station <= 9):
        return None

    return {
        "volume": volume,
        "bank": bank,
        "station": station,
        "timestamp": data.get("timestamp"),
    }


def load_state():
    """Load saved state from disk. Falls back to backup file if needed."""
    for path in (STATE_PATH, STATE_BACKUP_PATH):
        try:
            if not path.exists():
                continue
            with open(path) as f:
                data = json.load(f)
            validated = _validate_state(data)
            if validated:
                log.info("Restored state from %s: volume=%d bank=%d station=%d",
                         path.name,
                         validated["volume"],
                         validated["bank"],
                         validated["station"])
                return validated
            log.warning("Invalid state data in %s", path)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Could not load %s: %s", path, e)

    return None


# ── Helpers ────────────────────────────────────────────────

def mpc(*args):
    """Run an mpc command, return stdout. Swallow errors."""
    try:
        r = subprocess.run(
            ["mpc"] + list(args),
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip()
    except Exception as e:
        log.warning("mpc %s failed: %s", " ".join(args), e)
        return ""


def read_bcd(pins: dict) -> int:
    """Read 4-bit BCD value from GPIO pins (active LOW)."""
    val = 0
    if GPIO.input(pins["bit0"]) == GPIO.LOW: val += 1
    if GPIO.input(pins["bit1"]) == GPIO.LOW: val += 2
    if GPIO.input(pins["bit2"]) == GPIO.LOW: val += 4
    if GPIO.input(pins["bit3"]) == GPIO.LOW: val += 8
    return val


def load_stations():
    """Load and return stations.yaml as a dict."""
    if not STATIONS_PATH.exists():
        log.error("stations.yaml not found at %s", STATIONS_PATH)
        return {}
    with open(STATIONS_PATH) as f:
        return yaml.safe_load(f) or {}


def get_station(data, bank_id, station_id):
    """Look up a station entry. Returns (bank_dict, station_dict) or (None, None)."""
    banks = data.get("banks", {})
    bank = banks.get(bank_id)
    if not isinstance(bank, dict):
        return None, None
    stations = bank.get("stations", {})
    station = stations.get(station_id)
    if not isinstance(station, dict):
        return None, None
    return bank, station


def clamp(val, lo, hi):
    return max(lo, min(hi, val))


# ── Playback ───────────────────────────────────────────────

def play_stream(url):
    """Play an internet radio stream."""
    log.info("Playing stream: %s", url)
    mpc("clear")
    mpc("add", url)
    mpc("play")


def play_file(path_str):
    """Play a single local file on loop, starting at a random position."""
    resolved = _resolve_path(path_str)
    if not resolved.exists():
        log.error("File not found: %s", resolved)
        return

    rel = _mpd_relpath(resolved)
    log.info("Playing file (loop): %s", rel)
    mpc("clear")
    mpc("repeat", "off")
    mpc("single", "off")
    mpc("random", "off")
    mpc("add", rel)
    mpc("repeat", "on")
    mpc("play")
    # Wait for playback to start, then seek to a random position
    if _wait_for_playing():
        _seek_random()


def play_file_once(path_str):
    """Play a single local file from the beginning once, then stop."""
    resolved = _resolve_path(path_str)
    if not resolved.exists():
        log.error("File not found: %s", resolved)
        return

    rel = _mpd_relpath(resolved)
    log.info("Playing file once: %s", rel)
    mpc("clear")
    mpc("repeat", "off")
    mpc("single", "off")
    mpc("random", "off")
    mpc("add", rel)
    mpc("play")


def play_dir(path_str):
    """Play a directory from a random track and random position, then continue in order."""
    resolved = _resolve_path(path_str)
    if not resolved.is_dir():
        log.error("Directory not found: %s", resolved)
        return

    files = sorted(
        [f for f in resolved.rglob("*") if f.suffix.lower() in AUDIO_EXTS],
        key=lambda p: str(p).lower(),
    )
    if not files:
        log.error("No audio files in: %s", resolved)
        return

    log.info("Playing directory: %s (%d files)", resolved, len(files))
    mpc("clear")
    mpc("repeat", "off")
    mpc("single", "off")
    mpc("random", "off")
    # Batch-add all files in a single subprocess call
    file_list = "\n".join(_mpd_relpath(f) for f in files)
    try:
        subprocess.run(
            ["mpc", "add"],
            input=file_list, text=True, timeout=30,
            capture_output=True,
        )
    except Exception as e:
        log.warning("mpc batch add failed: %s", e)

    start = random.randint(1, len(files))
    mpc("play", str(start))
    # Wait for playback, then seek to a random position in the first track.
    # MPD will continue to subsequent tracks from their beginnings.
    if _wait_for_playing():
        _seek_random()


def _resolve_path(raw: str) -> Path:
    """Resolve a station path relative to AUDIO_ROOT."""
    raw = raw.strip()
    if raw.startswith("/"):
        return Path(raw)
    return AUDIO_ROOT / raw


def _mpd_relpath(path: Path) -> str:
    """Convert absolute path to MPD-relative path (relative to AUDIO_ROOT)."""
    try:
        return str(path.resolve().relative_to(AUDIO_ROOT.resolve()))
    except ValueError:
        log.error("Path outside audio root: %s", path)
        return str(path)


def _seek_random():
    """Seek to a random position in the current track."""
    output = mpc("status")
    for line in output.splitlines():
        if "/" in line and ":" in line and "%" in line:
            # Parse something like "   [playing] #1/1   0:05/3:42 (2%)"
            for token in line.split():
                if "/" in token and ":" in token:
                    try:
                        _, total_str = token.split("/", 1)
                        parts = [int(p) for p in total_str.split(":")]
                        if len(parts) == 2:
                            total_sec = parts[0] * 60 + parts[1]
                        elif len(parts) == 3:
                            total_sec = parts[0] * 3600 + parts[1] * 60 + parts[2]
                        else:
                            return
                        if total_sec > 10:
                            target = random.randint(0, total_sec - 5)
                            mpc("seek", str(target))
                    except (ValueError, IndexError):
                        pass
                    return


def _wait_for_playing(timeout=2.0):
    """Poll mpc status until [playing] appears, or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = mpc("status")
        if "[playing]" in status:
            return True
        time.sleep(0.1)
    log.warning("Timed out waiting for [playing] state")
    return False


def play_station(data, bank_id, station_id):
    """Play a station by bank/station ID. Returns True if successful."""
    bank, station = get_station(data, bank_id, station_id)
    if station is None:
        log.warning("Station not found: bank=%d station=%d", bank_id, station_id)
        return False

    name = station.get("name", f"Bank {bank_id} / Station {station_id}")
    stype = station.get("type", "").strip().lower()
    log.info("▶ %s [%s]", name, stype)

    if stype == "stream":
        url = station.get("url", "").strip()
        if not url:
            log.error("Stream station '%s' has no url", name)
            return False
        play_stream(url)
        return True

    if stype == "file":
        path = station.get("path", "").strip()
        if not path:
            log.error("File station '%s' has no path", name)
            return False
        play_file(path)
        return True

    if stype == "dir":
        path = station.get("path", "").strip()
        if not path:
            log.error("Dir station '%s' has no path", name)
            return False
        play_dir(path)
        return True

    if stype in ("file_once", "single_file"):
        path = (station.get("path") or station.get("file") or "").strip()
        if not path:
            log.error("File-once station '%s' has no path", name)
            return False
        play_file_once(path)
        return True

    log.error("Unknown station type '%s' for '%s'", stype, name)
    return False


# ── Main loop ──────────────────────────────────────────────

def wait_for_mpd(retries=15, delay=2.0):
    """Block until MPD is reachable."""
    for i in range(retries):
        if _shutdown:
            return False
        r = subprocess.run(["mpc", "status"], capture_output=True, text=True)
        if r.returncode == 0:
            log.info("MPD ready (attempt %d/%d)", i + 1, retries)
            return True
        log.warning("Waiting for MPD... (%d/%d)", i + 1, retries)
        time.sleep(delay)
    log.error("MPD not available after %d attempts", retries)
    return False


def main():
    log.info("=" * 40)
    log.info("Radio controller starting")
    log.info("=" * 40)

    if not wait_for_mpd():
        sys.exit(1)

    # ── GPIO setup ──
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    all_pins = (
        list(STATION_PINS.values())
        + list(BANK_PINS.values())
        + [STOP_START_PIN]
    )
    for pin in all_pins:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # ── I2C / volume encoder setup ──
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        seesaw = Seesaw(i2c, addr=VOLUME_I2C_ADDR)
        seesaw.pin_mode(SEESAW_BUTTON_PIN, seesaw.INPUT_PULLUP)
        vol_encoder = IncrementalEncoder(seesaw, 0)
        last_vol_pos = vol_encoder.position
        resync_volume_encoder = False
        last_button = seesaw.digital_read(SEESAW_BUTTON_PIN)
        log.info("Volume encoder ready at 0x%02x", VOLUME_I2C_ADDR)
    except Exception as e:
        log.error("I2C init failed: %s", e)
        sys.exit(1)

    # ── Load saved state (survives power loss) ──
    saved_state = load_state()

    # ── Load stations and read initial state ──
    stations_data = load_stations()
    stations_mtime = STATIONS_PATH.stat().st_mtime if STATIONS_PATH.exists() else 0

    cur_bank = read_bcd(BANK_PINS)
    cur_station = read_bcd(STATION_PINS)
    if cur_bank > 9: cur_bank = 0
    if cur_station > 9: cur_station = 0

    playing_bank = -1
    playing_station = -1
    play_enabled = GPIO.input(STOP_START_PIN) == GPIO.HIGH
    last_switch_change = 0.0

    # Restore volume from saved state, or use default
    if saved_state and 0 <= saved_state.get("volume", -1) <= VOLUME_MAX:
        volume = saved_state["volume"]
        log.info("Restored volume: %d", volume)
    else:
        volume = DEFAULT_VOLUME

    # Set initial volume
    mpc("volume", str(volume))

    # Play initial station
    if play_enabled and get_station(stations_data, cur_bank, cur_station)[1]:
        play_station(stations_data, cur_bank, cur_station)
        playing_bank = cur_bank
        playing_station = cur_station
    elif not play_enabled:
        log.info("Stop/start switch is OFF at startup — stopped")
        mpc("stop")

    log.info("Initial: bank=%d station=%d volume=%d play=%s",
             cur_bank, cur_station, volume, play_enabled)

    # ── Watchdog state ──
    watchdog_last_check = 0.0
    watchdog_stop_since = 0.0

    # ── State persistence tracking ──
    last_state_save = 0.0
    state_dirty = True  # Save initial state on first opportunity

    # ── Config reload tracking ──
    last_config_check = 0.0

    # ── Systemd watchdog notify tracking ──
    last_watchdog_notify = 0.0

    # Tell systemd we're ready
    _notify_ready()

    # ── Main loop ──
    log.info("Entering main loop")
    while not _shutdown:
        try:
            now = time.monotonic()

            # ── Reload stations.yaml if it changed (throttled) ──
            if now - last_config_check >= CONFIG_CHECK_INTERVAL:
                last_config_check = now
                try:
                    mt = STATIONS_PATH.stat().st_mtime
                    if mt != stations_mtime:
                        stations_data = load_stations()
                        stations_mtime = mt
                        log.info("Reloaded stations.yaml")
                        mpc("update")
                except FileNotFoundError:
                    pass

            # ── Read BCD switches ──
            raw_bank = read_bcd(BANK_PINS)
            raw_station = read_bcd(STATION_PINS)
            new_bank = raw_bank if 0 <= raw_bank <= 9 else cur_bank
            new_station = raw_station if 0 <= raw_station <= 9 else cur_station

            # ── Switch change (with debounce) ──
            if (new_bank != cur_bank or new_station != cur_station):
                if now - last_switch_change >= DEBOUNCE_TIME:
                    last_switch_change = now

                    if new_bank != cur_bank:
                        log.info("Bank: %d → %d", cur_bank, new_bank)
                    if new_station != cur_station:
                        log.info("Station: %d → %d", cur_station, new_station)

                    cur_bank = new_bank
                    cur_station = new_station

                    # Play new station
                    if get_station(stations_data, cur_bank, cur_station)[1]:
                        if cur_bank != playing_bank or cur_station != playing_station:
                            play_station(stations_data, cur_bank, cur_station)
                            playing_bank = cur_bank
                            playing_station = cur_station
                            watchdog_stop_since = 0.0
                            state_dirty = True
                    else:
                        log.warning("No station at bank=%d station=%d", cur_bank, cur_station)

            # ── Volume encoder ──
            try:
                vol_pos = vol_encoder.position
            except OSError:
                vol_pos = last_vol_pos
                resync_volume_encoder = True
                time.sleep(0.1)

            if vol_pos != last_vol_pos:
                if resync_volume_encoder:
                    log.warning("Volume encoder recovered after I2C error; resyncing position")
                    last_vol_pos = vol_pos
                    resync_volume_encoder = False
                else:
                    delta = last_vol_pos - vol_pos
                    last_vol_pos = vol_pos
                    if abs(delta) > MAX_VOLUME_DELTA:
                        log.warning(
                            "Ignoring suspicious volume encoder jump: %d steps",
                            delta,
                        )
                    else:
                        volume = clamp(volume + delta * VOLUME_STEP, VOLUME_MIN, VOLUME_MAX)
                        mpc("volume", str(volume))
                        log.debug("Volume: %d", volume)
                        state_dirty = True

            # ── Encoder button (play/pause toggle) ──
            try:
                btn = seesaw.digital_read(SEESAW_BUTTON_PIN)
                if last_button == 1 and btn == 0:  # Falling edge
                    log.info("Encoder button pressed → toggle play/pause")
                    mpc("toggle")
                last_button = btn
            except OSError:
                pass

            # ── Stop/start switch ──
            new_play = GPIO.input(STOP_START_PIN) == GPIO.HIGH
            if new_play != play_enabled:
                play_enabled = new_play
                if play_enabled:
                    log.info("Stop/start switch → ON")
                    if get_station(stations_data, cur_bank, cur_station)[1]:
                        play_station(stations_data, cur_bank, cur_station)
                        playing_bank = cur_bank
                        playing_station = cur_station
                else:
                    log.info("Stop/start switch → OFF")
                    mpc("stop")

            # ── Stream watchdog ──
            if play_enabled and now - watchdog_last_check >= WATCHDOG_INTERVAL:
                watchdog_last_check = now
                _, stn = get_station(stations_data, playing_bank, playing_station)
                if stn and stn.get("type", "").strip().lower() == "stream":
                    status = mpc("status")
                    if "[playing]" not in status and "[paused]" not in status:
                        if watchdog_stop_since == 0.0:
                            watchdog_stop_since = now
                            log.warning("Stream appears stopped, waiting %.0fs...", WATCHDOG_GRACE)
                        elif now - watchdog_stop_since >= WATCHDOG_GRACE:
                            log.info("Watchdog: restarting stream (bank=%d station=%d)",
                                     playing_bank, playing_station)
                            play_station(stations_data, playing_bank, playing_station)
                            watchdog_stop_since = 0.0
                    else:
                        watchdog_stop_since = 0.0

            # ── Save state to disk (throttled, only when changed) ──
            if state_dirty and now - last_state_save >= STATE_SAVE_INTERVAL:
                save_state(volume, playing_bank, playing_station)
                last_state_save = now
                state_dirty = False

            # ── Systemd watchdog keepalive (throttled) ──
            if now - last_watchdog_notify >= WATCHDOG_NOTIFY_INTERVAL:
                _notify_watchdog()
                last_watchdog_notify = now

            time.sleep(POLL_INTERVAL)

        except Exception as e:
            log.error("Error: %s", e, exc_info=True)
            time.sleep(1.0)

    # ── Graceful shutdown ──
    log.info("Shutting down gracefully")
    save_state(volume, playing_bank, playing_station)
    GPIO.cleanup()


if __name__ == "__main__":
    main()
