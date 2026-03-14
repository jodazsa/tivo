#!/bin/bash
# update_files.sh — Deploy updated radio files and restart the service
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "→ Deploying radio.py..."
sudo cp "$SCRIPT_DIR/radio.py" /usr/local/bin/radio.py
sudo chmod +x /usr/local/bin/radio.py

echo "→ Syncing stations.yaml..."
sudo cp "$SCRIPT_DIR/stations.yaml" /home/pi/stations.yaml
sudo chown pi:pi /home/pi/stations.yaml

echo "→ Restarting radio service..."
sudo systemctl daemon-reload
sudo systemctl restart radio

echo "=== Files deployed ==="
