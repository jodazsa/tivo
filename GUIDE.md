# Pi Radio with OLED Display — Step-by-Step Guide

## Hardware overview

| Component | Type | Interface | Purpose |
|-----------|------|-----------|---------|
| **Station selector** | BCD rotary switch (10-position) | GPIO (active LOW) | Cycles through flat station list |
| **Volume control** | BCD rotary switch (10-position) | GPIO (active LOW) | 10 volume levels (30%-100%) |
| **OLED display** | SSD1306 128x32 mono | I2C at 0x3D | Shows station name + volume |
| **Play/stop toggle** | Toggle switch | GPIO 24 (active HIGH) | ON=play, OFF=stop |
| **DAC** | HiFiBerry DAC | I2S | Audio output |

## Files in this project

```
tivo/
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

Option A — clone from a repo:
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
3. Install MPD, mpc, Python libraries (Blinka, SSD1306, Pillow)
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

# Can you see the OLED display on I2C?
i2cdetect -y 1    # Should show device at 0x3d

# Is MPD running?
mpc status

# Watch the logs live
sudo journalctl -u radio -f
```

Turn the station switch — you should hear audio, see log entries, and the OLED display should update.

## Step 5: Edit your stations

```bash
sudo nano /home/radio/stations.yaml
```

Stations are a flat list. The station knob (positions 0-9) indexes into the list with wrapping. Reorder the list to put your favorites in the first 10 positions.

After editing, restart the service (or just turn a switch — it reloads automatically every 30s):

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

**file** — Single local audio file (loops forever):
```yaml
- name: "Rain Sounds"
  type: file
  path: "ambient/rain.mp3"
```
Paths are relative to `/home/radio/audio/`.

**file_once** — Single local audio file from the beginning, no repeat:
```yaml
- name: "Station ID"
  type: file_once
  path: "ids/jingle.mp3"
```

**dir** — Play all files in a directory:
```yaml
- name: "Bob Dylan"
  type: dir
  path: "shows/BobDylan"
```

## Step 5b: Push changes to GitHub and pull them on the Pi

### On your computer (local repo)

```bash
cd ~/path/to/radio
git add stations.yaml radio.py GUIDE.md
git commit -m "Update stations and playback behavior"
git push origin main
```

### On the Raspberry Pi (pull + deploy)

One-command option (from anywhere):

```bash
~/radio/update_main_and_reboot.sh
```

Manual option:

```bash
cd ~/radio
git fetch origin
git checkout main
git pull --ff-only origin main
./install.sh
sudo systemctl restart radio
mpc update
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

**Station BCD switch** (10-position) → GPIO pins:
- bit0 (value 1): GPIO 9
- bit1 (value 2): GPIO 10
- bit2 (value 4): GPIO 22
- bit3 (value 8): GPIO 17

**Volume BCD switch** (10-position, was bank switch) → GPIO pins:
- bit0 (value 1): GPIO 13
- bit1 (value 2): GPIO 6
- bit2 (value 4): GPIO 5
- bit3 (value 8): GPIO 11

**Volume levels by switch position:**
| Position | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|----------|---|---|---|---|---|---|---|---|---|---|
| Volume % | 30 | 38 | 46 | 54 | 62 | 70 | 78 | 86 | 93 | 100 |

**OLED display**: I2C at address `0x3D` (Adafruit 4440, SSD1306 128x32)
- SDA: GPIO 2
- SCL: GPIO 3

**Play/stop toggle switch**: GPIO 24

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

**OLED display not found:**
```bash
i2cdetect -y 1   # Should show 0x3d
```

**Display shows nothing:**
- Check I2C wiring (SDA to GPIO 2, SCL to GPIO 3)
- Verify address jumper on Adafruit 4440 (default 0x3D)

**Service won't start:**
```bash
sudo journalctl -u radio -n 50 --no-pager
```

---

## Power loss resilience

This radio is designed to survive unplanned power loss and run unattended for years. The installer configures multiple layers of protection:

### What happens on power loss

1. Power is cut — the Pi shuts down immediately (no graceful shutdown)
2. On power restore, the Pi boots normally
3. systemd starts MPD, then the radio service
4. The radio controller reads volume from the BCD switch position
5. It reads the station switch position and starts the correct station
6. The stream watchdog monitors for playback health

**Recovery is fully automatic — no user intervention required.**

### Protection layers

| Layer | What it does | Protects against |
|-------|-------------|-----------------|
| **State persistence** | Station index saved to `/home/radio/state.json` using atomic writes | Station reset after power loss |
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

### State file format

```json
{"volume": 62, "station": 3, "timestamp": 1709000000}
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
