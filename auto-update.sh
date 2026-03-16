#!/bin/bash
# auto-update.sh — Check GitHub for updates on main and apply them
# Runs daily via systemd timer. Skips reboot; just restarts the radio service.
set -euo pipefail

REPO_DIR="/home/pi/tivo"
LOG_TAG="radio-auto-update"

log() { logger -t "$LOG_TAG" "$*"; echo "$*"; }

cd "$REPO_DIR"

# Fetch latest from origin
if ! git fetch origin main 2>&1; then
    log "ERROR: git fetch failed (network issue?), will retry tomorrow"
    exit 1
fi

# Compare local main with remote
LOCAL=$(git rev-parse main)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    log "Already up to date (${LOCAL:0:8})"
    exit 0
fi

log "Update available: ${LOCAL:0:8} -> ${REMOTE:0:8}"

# Pull changes
git checkout main
git pull --ff-only origin main

# Deploy updated files and restart
log "Deploying updated files..."
bash "$REPO_DIR/update_files.sh"

log "Update complete (now at ${REMOTE:0:8})"
