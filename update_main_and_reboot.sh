#!/bin/bash
# update_main_and_reboot.sh — Pull latest main, run installer, and reboot
set -euo pipefail

REPO_DIR="${HOME}/tivo"

cd "$REPO_DIR"
git fetch origin
git checkout main
git pull --ff-only origin main
bash ./update_files.sh
sudo reboot
