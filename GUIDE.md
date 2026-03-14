# Simplified Pi Radio — Step-by-Step Guide

## What changed (original → simplified)

| Original | Simplified | Why |
|----------|-----------|-----|
| 15+ files, ~5,500 lines | **3 files, ~400 lines** | Less to break, easier to understand |
| Separate `rotary-controller`, `radio-play`, `radio_lib.py` | **Single `radio.py`** | One file does everything |
| 1,076-line web backend + 1,824-line web UI | **Removed** | Hardware switches only |
| Auto-update stations from GitHub | **Removed** | Edit `stations.yaml` directly on the Pi |
| WiFi AP fallback + provisioning | **Removed** | Set up WiFi with `raspi-config` or Pi Imager |
| Fuzzy media matching (roman numerals, legacy prefixes) | **Removed** | Just use correct paths |
| 6 station types with aliases | **4 types: `stream`, `file`, `file_once`, `dir`** | Covers all real usage |
| BCD decode maps, stability windows, glitch filters | **Simple debounce only** | Kept minimal; add back if switches misbehave |
| Playback watchdog with exponential backoff | **Simple watchdog** | Restarts dead streams, no complex backoff |
| 5 systemd services + 1 timer | **1 systemd service** | Just `radio.py` |
| Full config validation (50+ checks) | **Fail-fast on missing keys** | Python will tell you what's wrong |
| `deploy-rotary.sh` + `install-rotary.sh` | **Single `install.sh`** | One script, run once |

---

## Files in this project

```
radio-simple/
├── GUIDE.md              ← You're reading this
├── install.sh            ← Run once on a fresh Pi
├── radio.py              ← The entire radio controller
├── stations.yaml         ← Your stations (edit this)
└── radio.service         ← Systemd service
```

---

## Step 1: Prepare your Raspberry Pi

Use **Raspberry Pi Imager** to flash **Raspberry Pi OS Lite 64-bit (Bookworm)**.

In Imager's advanced settings, configure:
- Hostname (e.g. `radio`)
- Username / password
- WiFi credentials
- Enable SSH

Boot the Pi and SSH in.

## Step 2: Get the files onto the Pi

Option A — clone from a repo (if you push these files to GitHub):
```bash
cd ~
sudo apt update
sudo apt install -y git
git clone https://github.com/jodazsa/radio.git
cd radio
```

Option B — copy files manually:
```bash
# From your computer:
scp -r radio/ pi@radio.local:~/radio/
# Then on the Pi:
cd ~/radio
```

## Step 3: Run the installer

```bash
chmod +x install.sh
./install.sh
```

This will:
1. Update system packages
2. Enable I2C
3. Install MPD, mpc, Python libraries
4. Create the `radio` user and directories
5. Configure MPD and the HiFiBerry DAC
6. Copy `radio.py` and `stations.yaml` into place
7. Install and start the systemd service

**Reboot when prompted:**
```bash
sudo reboot
```

## Step 4: Verify it works

After reboot, SSH back in and check:

```bash
# Is the service running?
sudo systemctl status radio

# Can you see the I2C volume encoder?
i2cdetect -y 1    # Should show device at 0x36

# Is MPD running?
mpc status

# Watch the logs live
sudo journalctl -u radio -f
```

Turn the station and bank switches — you should hear audio and see log entries.

## Step 5: Edit your stations

```bash
sudo nano /home/radio/stations.yaml
```

After editing, restart the service to pick up changes (or just turn a switch — it reloads automatically):

```bash
sudo systemctl restart radio
```

### Station types

**stream** — Internet radio:
```yaml
0:
  name: "WWOZ New Orleans"
  type: stream
  url: "http://wwoz-sc.streamguys.com/wwoz-hi.mp3"
```

**file** — Single local audio file (loops forever):
```yaml
1:
  name: "Rain Sounds"
  type: file
  path: "ambient/rain.mp3"
```
Paths are relative to `/home/radio/audio/`.

**file_once** — Single local audio file from the beginning, no repeat:
```yaml
2:
  name: "Station ID"
  type: file_once
  path: "ids/jingle.mp3"
```

**dir** — Play all files in a directory:
```yaml
3:
  name: "Bob Dylan"
  type: dir
  path: "artists/bob-dylan"
```

## Step 5b: Push changes to GitHub and pull them on the Pi

Use this flow when you edit files on your computer (for example `stations.yaml` or `radio.py`) and want the Pi to run the latest version.

### On your computer (local repo)

```bash
# Make sure you're in your local clone
cd ~/path/to/radio

# Create a branch (optional but recommended)
git checkout -b update-stations

# Stage + commit
git add stations.yaml radio.py GUIDE.md
git commit -m "Update stations and playback behavior"

# Push to GitHub
git push -u origin update-stations
```

If you commit directly to `main`, push with:

```bash
git push origin main
```

### On the Raspberry Pi (pull + deploy)

One-command option (from anywhere):

```bash
~/radio/update_main_and_reboot.sh
```

This runs:

```bash
cd ~/radio
git fetch origin
git checkout main
git pull --ff-only origin main
./install.sh
sudo reboot
```

Manual option:

```bash
cd ~/radio

# Fetch latest refs
git fetch origin

# If using main branch
git checkout main
git pull --ff-only origin main

# If using a feature branch
git checkout update-stations
git pull --ff-only origin update-stations
```

Reinstall updated service/config files into `/home/radio` and restart:

```bash
./install.sh
sudo systemctl restart radio
mpc update
```

### Quick verification after pull

```bash
sudo systemctl status radio --no-pager
sudo journalctl -u radio -n 50 --no-pager
mpc status
```

## Step 6: Add local music (optional)

For a Windows-to-Pi path mapping guide that matches `stations.yaml`, see `TRANSFER_GUIDE.md`.

```bash
# From your computer, copy files to the Pi:
scp -r "my-music/" radio@radio.local:/home/radio/audio/my-music/

# On the Pi, tell MPD to scan for new files:
mpc update
```

---

## Hardware wiring reference

This matches the original project's wiring. No changes needed.

**Station BCD switch** (10-position) → GPIO pins:
- bit0 (value 1): GPIO 9
- bit1 (value 2): GPIO 10
- bit2 (value 4): GPIO 22
- bit3 (value 8): GPIO 17

**Bank BCD switch** (10-position) → GPIO pins:
- bit0 (value 1): GPIO 5
- bit1 (value 2): GPIO 6
- bit2 (value 4): GPIO 13
- bit3 (value 8): GPIO 11

**Volume encoder**: I2C via Adafruit Seesaw at address `0x36`

**Play/pause toggle switch**: GPIO 24

All switch pins use internal pull-ups (active LOW).

---

## Troubleshooting

**No sound:**
```bash
aplay -l                           # Check audio devices
mpc outputs                        # Check MPD outputs
sudo systemctl restart mpd radio  # Restart everything
```

**Switches not responding:**
```bash
# Check GPIO reads directly
python3 -c "import RPi.GPIO as GPIO; GPIO.setmode(GPIO.BCM); GPIO.setup(9, GPIO.IN, pull_up_down=GPIO.PUD_UP); print(GPIO.input(9))"
```

**Volume encoder not found:**
```bash
i2cdetect -y 1   # Should show 0x36
```

**Service won't start:**
```bash
sudo journalctl -u radio -n 50 --no-pager
```

### Scenario: Bank knob at 8 or 9 does not play recorded audio

If internet stations (banks 0-7) work but banks 8-9 are silent, this is usually a
`stations.yaml` schema mismatch.

#### Why this happens

`radio.py` expects local `file` and `dir` stations to use a `path:` key.

However, in the provided `stations.yaml`, many Bank 8 and Bank 9 entries use legacy
keys (`file:` and `dir:`) while still declaring `type: file` or `type: dir`.

Result: the service logs errors like "has no path" and those stations never queue in MPD.

#### Confirm the issue quickly

```bash
# 1) Watch logs while turning bank/station knobs to 8 or 9
sudo journalctl -u radio -f

# 2) Look for these messages
#    File station '...' has no path
#    Dir station '...' has no path

# 3) Optional: inspect current station definitions
sudo sed -n '360,520p' /home/radio/stations.yaml
```

#### Fix option A (recommended): normalize Bank 8/9 entries to `path:`

Edit the local station file:

```bash
sudo nano /home/radio/stations.yaml
```

Change entries like:

```yaml
type: file
file: "tracks/FlyLo FM - GTA V.mp3"
```

to:

```yaml
type: file
path: "tracks/FlyLo FM - GTA V.mp3"
```

And change entries like:

```yaml
type: dir
dir: "shows/BobDylan"
```

to:

```yaml
type: dir
path: "shows/BobDylan"
```

Then apply changes:

```bash
sudo systemctl restart radio
mpc update
```

#### Fix option B: code compatibility patch

If you want to keep legacy `file:` / `dir:` keys in YAML, patch `radio.py` so
`type: file` also accepts `file`, and `type: dir` also accepts `dir`/`directory`.
This mirrors the existing legacy handling already used for older type names.

---

## Power loss resilience

This radio is designed to survive unplanned power loss and run unattended for years. The installer configures multiple layers of protection:

### What happens on power loss

1. Power is cut — the Pi shuts down immediately (no graceful shutdown)
2. On power restore, the Pi boots normally
3. systemd starts MPD, then the radio service
4. The radio controller restores volume from the saved state file
5. It reads the physical switch positions and starts the correct station
6. The stream watchdog monitors for playback health

**Recovery is fully automatic — no user intervention required.**

### Protection layers

| Layer | What it does | Protects against |
|-------|-------------|-----------------|
| **State persistence** | Volume saved to `/home/radio/state.json` using atomic writes (write-to-temp, fsync, rename) | Volume reset after power loss |
| **Hardware watchdog** | `bcm2835_wdt` kernel module reboots the Pi if the OS hangs | Kernel panic, total system hang |
| **Service watchdog** | systemd restarts radio.py if it stops sending keepalives (30s timeout) | Process hang, deadlock |
| **Auto-restart** | `Restart=always` in systemd with rate limiting (10 restarts per 5 minutes) | Process crash, unexpected exit |
| **Signal handling** | SIGTERM handler saves state before exit | Clean shutdown on `systemctl stop` |
| **Volatile journal** | System logs stored in RAM, not on SD card | SD card wear from logging |
| **tmpfs mounts** | `/tmp` and `/var/tmp` mounted as RAM disks | SD card wear from temp files |
| **Filesystem tuning** | `noatime,commit=60` mount options on root | SD card wear from frequent writes |
| **Swap disabled** | No swap file on SD card | SD card wear from swapping |
| **Stream watchdog** | Auto-restarts dead internet streams after 15s grace period | Stream server disconnects, network glitches |
| **Config hot-reload** | `stations.yaml` changes detected without restart (checked every 30s) | Need to edit stations without downtime |
| **Filesystem health check** | Daily check for ext4 errors and I/O errors in dmesg | Early warning of SD card failure |
| **Resource limits** | Memory capped at 128M, CPU at 50% | Runaway processes consuming resources |
| **I2C error handling** | Transient I2C read failures fall back to last known value | Electrical noise, bus contention |

### State file format

The state file at `/home/radio/state.json` uses atomic writes to prevent corruption:

```json
{"volume": 72, "bank": 3, "station": 5, "timestamp": 1709000000}
```

- Written at most once every 5 seconds (only when state changes)
- Uses write-to-temp → fsync → rename pattern (safe against power loss mid-write)
- If corrupted on read, it's deleted and defaults are used
- On clean shutdown (SIGTERM), state is saved immediately

### SD card longevity tips

- Use a high-endurance SD card (Samsung PRO Endurance, SanDisk MAX Endurance)
- The install script already minimizes writes (volatile journal, tmpfs, noatime)
- Monitor SD health: `sudo dmesg | grep -i "mmc\|error"`
- Keep a backup SD card with the same setup ready to swap in

