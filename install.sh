#!/bin/bash
# install.sh — One-time setup for simplified Pi radio
# Includes hardening for power loss resilience and long-term SD card reliability
set -e

echo "=== Simplified Pi Radio — Install ==="
echo ""

if [ "$EUID" -eq 0 ]; then
    echo "Please run as regular user, not root."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 1. System packages
echo "→ Updating system and installing packages..."
sudo apt update && sudo apt upgrade -y
sudo apt install -y mpd mpc python3-pip python3-venv python3-yaml python3-rpi.gpio i2c-tools

# 2. Enable I2C
echo "→ Enabling I2C..."
sudo raspi-config nonint do_i2c 0

# 3. HiFiBerry DAC
echo "→ Configuring HiFiBerry DAC..."
if [ -f /boot/firmware/config.txt ]; then
    CONFIG_FILE="/boot/firmware/config.txt"
elif [ -f /boot/config.txt ]; then
    CONFIG_FILE="/boot/config.txt"
else
    echo "WARNING: Boot config not found, skipping DAC setup"
    CONFIG_FILE=""
fi

if [ -n "$CONFIG_FILE" ]; then
    grep -q "dtoverlay=hifiberry-dac" "$CONFIG_FILE" \
        || echo "dtoverlay=hifiberry-dac" | sudo tee -a "$CONFIG_FILE"
    sudo sed -i 's/^dtparam=audio=on/#dtparam=audio=on/' "$CONFIG_FILE" 2>/dev/null || true
fi

# 4. Python libraries (Seesaw for I2C encoder) in a virtual environment
echo "→ Installing Python libraries..."
sudo python3 -m venv /opt/radio-venv --system-site-packages
sudo /opt/radio-venv/bin/pip install Adafruit-Blinka adafruit-circuitpython-seesaw

# 5. Create radio user and directories
echo "→ Setting up radio user..."
id -u radio &>/dev/null || sudo useradd -m -s /bin/bash radio
sudo usermod -aG audio,i2c,gpio radio
sudo mkdir -p /home/radio/audio /home/radio/logs
sudo chmod 755 /home/radio /home/radio/audio /home/radio/logs

# 6. Install radio files
echo "→ Installing radio files..."
sudo cp "$SCRIPT_DIR/radio.py" /usr/local/bin/radio.py
sudo chmod +x /usr/local/bin/radio.py

# Always sync stations.yaml from the repo so Pi stations match GitHub main
sudo cp "$SCRIPT_DIR/stations.yaml" /home/radio/stations.yaml
sudo chown radio:radio /home/radio/stations.yaml
echo "  Synced stations.yaml from repository"

# 7. Configure MPD
echo "→ Configuring MPD..."
sudo tee /etc/mpd.conf > /dev/null << 'MPDCONF'
music_directory     "/home/radio/audio"
playlist_directory  "/var/lib/mpd/playlists"
db_file             "/var/lib/mpd/tag_cache"
log_file            "/var/log/mpd/mpd.log"
pid_file            "/run/mpd/pid"
state_file          "/var/lib/mpd/state"
sticker_file        "/var/lib/mpd/sticker.sql"

bind_to_address     "localhost"
port                "6600"

auto_update         "yes"

input {
    plugin "curl"
}

audio_output {
    type        "alsa"
    name        "HiFiBerry DAC"
    mixer_type  "software"
}
MPDCONF

sudo systemctl restart mpd
sudo systemctl enable mpd

# 8. Install systemd services
echo "→ Installing radio services..."
sudo cp "$SCRIPT_DIR/radio.service" /etc/systemd/system/radio.service
sudo systemctl daemon-reload
sudo systemctl enable radio
sudo systemctl start radio

# ── 9. Power loss resilience hardening ─────────────────────
echo ""
echo "→ Applying power loss resilience hardening..."

# 9a. Enable hardware watchdog
# The bcm2835_wdt module resets the Pi if the system hangs
echo "→ Enabling hardware watchdog..."
if ! grep -q "dtparam=watchdog=on" "$CONFIG_FILE" 2>/dev/null; then
    echo "dtparam=watchdog=on" | sudo tee -a "$CONFIG_FILE"
fi

# Configure systemd to use the hardware watchdog as a last resort
sudo mkdir -p /etc/systemd/system.conf.d
sudo tee /etc/systemd/system.conf.d/watchdog.conf > /dev/null << 'EOF'
[Manager]
RuntimeWatchdogSec=15
RebootWatchdogSec=10min
EOF

# 9b. Reduce SD card writes — volatile journal (logs in RAM, not on disk)
echo "→ Configuring volatile journal (RAM-only logging)..."
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/volatile.conf > /dev/null << 'EOF'
[Journal]
Storage=volatile
RuntimeMaxUse=16M
RuntimeMaxFileSize=4M
EOF

# 9c. Mount /tmp and /var/tmp as tmpfs (RAM) to avoid SD card writes
echo "→ Configuring tmpfs for temporary directories..."
if ! grep -q "tmpfs.*/tmp " /etc/fstab; then
    echo "tmpfs /tmp tmpfs defaults,noatime,nosuid,nodev,size=64M 0 0" | sudo tee -a /etc/fstab
fi
if ! grep -q "tmpfs.*/var/tmp " /etc/fstab; then
    echo "tmpfs /var/tmp tmpfs defaults,noatime,nosuid,nodev,size=32M 0 0" | sudo tee -a /etc/fstab
fi

# 9d. Reduce filesystem write frequency — add commit=60 and noatime to root
# This batches writes and eliminates access-time updates
echo "→ Optimizing filesystem mount options..."
if grep -q " / " /etc/fstab; then
    # Add noatime if not present
    if ! grep " / " /etc/fstab | grep -q "noatime"; then
        sudo sed -i '/ \/ /s/defaults/defaults,noatime/' /etc/fstab
    fi
    # Add commit=60 if not present (batches writes to every 60 seconds)
    if ! grep " / " /etc/fstab | grep -q "commit="; then
        sudo sed -i '/ \/ /s/noatime/noatime,commit=60/' /etc/fstab
    fi
fi

# 9e. Disable swap to protect SD card from excessive writes
echo "→ Disabling swap..."
sudo dphys-swapfile swapoff 2>/dev/null || true
sudo dphys-swapfile uninstall 2>/dev/null || true
sudo systemctl disable dphys-swapfile 2>/dev/null || true

# 9f. Set up a daily filesystem check timer
echo "→ Configuring filesystem health check..."
sudo tee /etc/systemd/system/fsck-check.service > /dev/null << 'FSCKSERVICE'
[Unit]
Description=Filesystem health check

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'dmesg | grep -i "ext4.*error\|I/O error\|filesystem.*corrupt" && logger -t fsck-check "WARNING: filesystem errors detected" || logger -t fsck-check "Filesystem OK"'
FSCKSERVICE

sudo tee /etc/systemd/system/fsck-check.timer > /dev/null << 'FSCKTIMER'
[Unit]
Description=Daily filesystem health check

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
FSCKTIMER

sudo systemctl daemon-reload
sudo systemctl enable fsck-check.timer

echo ""
echo "=== Done! ==="
echo "Radio service is running. Reboot to apply all changes:"
echo "  sudo reboot"
echo ""
echo "After reboot, check status with:"
echo "  sudo systemctl status radio"
echo "  sudo journalctl -u radio -f"
echo ""
echo "Power loss resilience features enabled:"
echo "  ✓ Hardware watchdog (auto-reboot on system hang)"
echo "  ✓ Service watchdog (auto-restart on process hang)"
echo "  ✓ Volume/station state saved to disk (survives power loss)"
echo "  ✓ Volatile journal (logs in RAM, not on SD card)"
echo "  ✓ tmpfs for /tmp and /var/tmp"
echo "  ✓ Reduced SD card writes (noatime, commit=60)"
echo "  ✓ Swap disabled"
echo "  ✓ Automatic service restart on crash"
echo "  ✓ Daily filesystem health check"
