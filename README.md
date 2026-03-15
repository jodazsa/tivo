# tivo

Two knobs and a display — a Raspberry Pi internet radio with physical controls.

A station selector knob, a volume knob, a play/stop toggle, and a 128x32 OLED display. Tunes internet radio streams and local audio files. Survives power loss and runs unattended.

## Hardware

| Component | Type | Interface |
|-----------|------|-----------|
| Station selector | BCD rotary switch (10-position) | GPIO 9, 10, 22, 17 |
| Volume control | BCD rotary switch (10-position) | GPIO 13, 6, 5, 11 |
| Play/stop toggle | Toggle switch | GPIO 24 |
| OLED display | SSD1306 128x32 | I2C at 0x3C |
| DAC | HiFiBerry DAC | I2S |

## Files

```
tivo/
├── radio.py              ← The entire radio controller
├── stations.yaml         ← Station definitions (edit this)
├── install.sh            ← One-time Pi setup script (safe to re-run)
├── radio.service         ← systemd service
├── update_files.sh       ← Deploy radio.py + stations.yaml, restart service
├── update_main_and_reboot.sh  ← Pull from GitHub + deploy + reboot
├── GUIDE.md              ← Detailed setup & wiring reference
└── TRANSFER_GUIDE.md     ← Windows → Pi audio transfer guide
```

---

## First-time Pi setup

### 1. Flash the SD card

Use **Raspberry Pi Imager** to flash **Raspberry Pi OS Lite 64-bit (Bookworm)**.

In Imager's advanced settings, configure:
- Hostname (e.g. `tivo`)
- Username / password (e.g. `pi`)
- WiFi credentials
- Enable SSH

Insert the SD card and boot the Pi.

### 2. SSH into the Pi

```bash
ssh pi@tivo.local
```

If `tivo.local` doesn't resolve, find the Pi's IP on your router and use that instead:

```bash
ssh pi@192.168.1.50
```

### 3. Clone the repo

```bash
cd ~
sudo apt update
sudo apt install -y git
git clone https://github.com/jodazsa/tivo.git
cd tivo
```

### 4. Run the installer

```bash
chmod +x install.sh
./install.sh
```

This handles everything:
- System packages (MPD, mpc, Python, I2C tools)
- I2C and HiFiBerry DAC configuration
- Python virtual environment with OLED display libraries
- `pi` user audio directories
- MPD configuration
- systemd service install and start
- Power loss resilience hardening (watchdog, volatile journal, tmpfs, swap off, noatime)

### 5. Reboot

```bash
sudo reboot
```

### 6. Verify

SSH back in and check:

```bash
sudo systemctl status radio       # Service running?
i2cdetect -y 1                    # OLED at 0x3c?
mpc status                        # MPD running?
sudo journalctl -u radio -f       # Live logs
```

Turn the station switch — you should hear audio and see the OLED update.

---

## Transferring music from Windows

Local audio files go in `/home/pi/audio/` on the Pi. Paths in `stations.yaml` are relative to that directory (e.g. `shows/BobDylan` → `/home/pi/audio/shows/BobDylan`).

### Prep the Pi (one time)

```bash
ssh pi@tivo.local
sudo mkdir -p /home/pi/audio
sudo chown -R pi:pi /home/pi/audio
```

### Using WSL + rsync (recommended)

rsync is best for large libraries — it can resume interrupted transfers and only sends changed files.

**1. Install rsync in WSL:**

```bash
sudo apt update
sudo apt install -y rsync openssh-client
```

**2. Make sure the destination exists on the Pi:**

```bash
ssh pi@tivo.local "sudo mkdir -p /home/pi/audio && sudo chown -R pi:pi /home/pi/audio"
```

**3. Run rsync:**

```bash
rsync -avh --progress --partial --append-verify \
  /mnt/c/Users/J/Documents/Radio_Project/Sync/Audio/music/ \
  pi@tivo.local:/home/pi/audio/
```

The trailing `/` on `music/` is important — it copies the *contents* into `/home/pi/audio/` without creating an extra `music/` subfolder.

Replace `/mnt/c/Users/J/Documents/Radio_Project/Sync/Audio/music/` with the WSL path to your audio folder. Windows paths map to WSL as `/mnt/c/...`.

**4. Re-run anytime** — rsync only sends new or changed files.

**5. Refresh MPD's library:**

```bash
ssh pi@tivo.local "mpc update"
```

### Using scp from PowerShell

If you don't have WSL, use scp from PowerShell:

```powershell
scp -4 -r "C:\Users\J\Documents\Radio_Project\Sync\Audio\music\*" pi@tivo.local:/home/pi/audio/
```

For large transfers, add keepalives to prevent timeouts:

```powershell
scp -4 -o ServerAliveInterval=30 -o ServerAliveCountMax=6 -r "C:\Users\J\Documents\Radio_Project\Sync\Audio\music\*" pi@tivo.local:/home/pi/audio/
```

### Path mapping

Your Windows audio folder structure should match what `stations.yaml` expects:

```
Windows:  ...\Audio\music\shows\BobDylan\*.mp3
Pi:       /home/pi/audio/shows/BobDylan/*.mp3
stations.yaml path:    "shows/BobDylan"

Windows:  ...\Audio\music\tracks\rain.mp3
Pi:       /home/pi/audio/tracks/rain.mp3
stations.yaml path:    "tracks/rain.mp3"
```

### Common mistakes

- Copying `music/` into `/home/pi/audio/music/` (extra folder level, breaks paths)
- Copying to `/home/pi/` instead of `/home/pi/audio/`
- Forgetting quotes around paths with spaces
- Forgetting `mpc update` after adding files

---

## Editing stations

Edit the station list:

```bash
sudo nano /home/pi/stations.yaml
```

The station knob (positions 0–9) indexes into the flat list with wrapping. Put your favorites in the first 10 positions.

Changes are detected automatically every 30 seconds, or restart to apply immediately:

```bash
sudo systemctl restart radio
```

### Station types

**stream** — Internet radio:
```yaml
- name: "WWOZ New Orleans"
  type: stream
  url: "http://wwoz-sc.streamguys.com/wwoz-hi.mp3"
```

**file** — Single local file, loops forever (seeks to random position on start):
```yaml
- name: "Rain Sounds"
  type: file
  path: "ambient/rain.mp3"
```

**file_once** — Single local file, plays from start, no repeat:
```yaml
- name: "Guided Meditation"
  type: file_once
  path: "tracks/meditation.mp3"
```

**dir** — All files in a directory (randomized start, loops):
```yaml
- name: "Bob Dylan"
  type: dir
  path: "shows/BobDylan"
```

Paths are relative to `/home/pi/audio/`.

---

## Updating the Pi from GitHub

There are three ways to apply changes from the repo, depending on what changed.

### Option 1 — Pull and reboot (recommended for most updates)

Pulls the latest `main` branch, deploys `radio.py` and `stations.yaml`, and reboots:

```bash
~/tivo/update_main_and_reboot.sh
```

What it does:
1. `git fetch origin` + `git checkout main` + `git pull --ff-only origin main`
2. Copies `radio.py` → `/usr/local/bin/radio.py`
3. Copies `stations.yaml` → `/home/pi/stations.yaml`
4. Reloads systemd daemon and restarts the `radio` service
5. Reboots the Pi

Use this for code changes (`radio.py`) or station list changes (`stations.yaml`) where a clean reboot is acceptable.

### Option 2 — Deploy files only (no git pull, no reboot)

Deploys the local repo's `radio.py` and `stations.yaml` to the system and restarts the service, without touching git or rebooting:

```bash
cd ~/tivo
./update_files.sh
```

What it does:
1. Copies `radio.py` → `/usr/local/bin/radio.py`
2. Copies `stations.yaml` → `/home/pi/stations.yaml`
3. Reloads systemd daemon and restarts the `radio` service

Use this when you've already pulled (or made local edits) and just want to push changes live without rebooting. Also useful when testing local changes before committing.

### Option 3 — Full reinstall (for system-level changes)

Re-runs the full installer after pulling from GitHub. Required when the update includes changes to system packages, the systemd service file, hardware configuration, or power loss hardening settings:

```bash
cd ~/tivo
git pull --ff-only origin main
./install.sh
sudo reboot
```

Use this after any update that touches `install.sh`, `radio.service`, or Pi system configuration. The installer is safe to re-run on an already-configured Pi.

### When to use which

| What changed | Option |
|---|---|
| `radio.py` or `stations.yaml` only | Option 1 or 2 |
| `install.sh`, `radio.service`, or system config | Option 3 |
| Local edits, testing before commit | Option 2 |

---

## Wiring reference

**Station BCD switch** (10-position):

| Bit | Value | GPIO |
|-----|-------|------|
| 0 | 1 | 9 |
| 1 | 2 | 10 |
| 2 | 4 | 22 |
| 3 | 8 | 17 |

**Volume BCD switch** (10-position):

| Bit | Value | GPIO |
|-----|-------|------|
| 0 | 1 | 13 |
| 1 | 2 | 6 |
| 2 | 4 | 5 |
| 3 | 8 | 11 |

**Volume levels by switch position:**

| Position | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|----------|---|---|---|---|---|---|---|---|---|---|
| Volume % | 30 | 38 | 46 | 54 | 62 | 70 | 78 | 86 | 93 | 100 |

**OLED display** — I2C address `0x3C`, SDA on GPIO 2, SCL on GPIO 3.

**Play/stop toggle** — GPIO 24. All switch pins use internal pull-ups (active LOW).

---

## Power loss resilience

The radio survives unplanned power loss and recovers automatically on boot. The installer configures:

- **Hardware watchdog** — reboots Pi if the OS hangs
- **Service watchdog** — restarts radio.py if it stops responding (30s timeout)
- **Auto-restart** — systemd restarts on crash (up to 10 times per 5 minutes)
- **State persistence** — station/volume saved to `/home/pi/state.json` with atomic writes
- **Stream watchdog** — restarts dead streams after 15s grace period
- **Config hot-reload** — `stations.yaml` changes detected every 30s
- **SD card protection** — volatile journal, tmpfs, noatime, commit=60, swap disabled
- **Daily filesystem health check** — early warning of SD card failure

---

## Troubleshooting

**No sound:**
```bash
aplay -l                           # Check audio devices
mpc outputs                        # Check MPD outputs
sudo systemctl restart mpd radio   # Restart everything
```

**OLED display not found:**
```bash
i2cdetect -y 1                    # Should show 0x3c
```

**Service won't start:**
```bash
sudo journalctl -u radio -n 50 --no-pager
```

**Transfer errors** — see [TRANSFER_GUIDE.md](TRANSFER_GUIDE.md) for fixes for connection drops, broken pipes, and path issues.
