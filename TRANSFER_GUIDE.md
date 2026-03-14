# Windows → Raspberry Pi Audio Transfer Guide

This guide copies your Windows audio library into the exact relative paths expected by `stations.yaml`.

## Goal

Your `stations.yaml` uses paths relative to:

- `/home/radio/audio/`

So:

- Windows folder `C:\Users\J\Documents\Radio_Project\Sync\Audio\music\shows\AliceCooper`
  becomes Pi folder `/home/radio/audio/shows/AliceCooper`
- Windows file `C:\Users\J\Documents\Radio_Project\Sync\Audio\music\tracks\The Blue Ark - GTA V.mp3`
  becomes Pi file `/home/radio/audio/tracks/The Blue Ark - GTA V.mp3`

## Path mapping rule

Copy the **contents of**:

- `C:\Users\J\Documents\Radio_Project\Sync\Audio\music\`

into:

- `/home/radio/audio/`

That preserves all relative paths used in `stations.yaml` (for example `shows/...` and `tracks/...`).

## 0) One-time prep on the Pi (important)

The `pi` user often cannot write directly to `/home/radio/audio` until it exists and permissions are set.

SSH in and run:

```bash
ssh pi@radio.local
sudo mkdir -p /home/radio/audio
sudo chown -R pi:pi /home/radio/audio
```

If `radio.local` is flaky, use your Pi IP instead:

```bash
ssh pi@192.168.1.50
```

## Option A (recommended): copy everything in one command

Use username `pi` in the commands below. (If your Pi uses a different login, replace `pi` with that username.)

Run this from **PowerShell on your Windows PC**:

```powershell
scp -4 -r "C:\Users\J\Documents\Radio_Project\Sync\Audio\music\*" pi@radio.local:/home/radio/audio/
```

If `radio.local` does not resolve reliably, replace it with your Pi IP:

```powershell
scp -4 -r "C:\Users\J\Documents\Radio_Project\Sync\Audio\music\*" pi@192.168.1.50:/home/radio/audio/
```

## Option B: copy only specific items

### Copy one show directory

```powershell
scp -4 -r "C:\Users\J\Documents\Radio_Project\Sync\Audio\music\shows\AliceCooper" pi@radio.local:/home/radio/audio/shows/
```

### Copy one track file

```powershell
scp -4 "C:\Users\J\Documents\Radio_Project\Sync\Audio\music\tracks\The Blue Ark - GTA V.mp3" pi@radio.local:/home/radio/audio/tracks/
```


## Option C: Use WSL + `rsync` (best for large or flaky transfers)

If you have WSL installed, `rsync` is usually more reliable than `scp` for big libraries because you can resume interrupted transfers.

### 1) In WSL, install rsync once

```bash
sudo apt update
sudo apt install -y rsync openssh-client
```

### 2) Make sure destination exists on Pi

```bash
ssh pi@radio.local "sudo mkdir -p /home/radio/audio && sudo chown -R pi:pi /home/radio/audio"
```

### 3) Run rsync from WSL

```bash
rsync -avh --progress --partial --append-verify \
  /mnt/c/Users/J/Documents/Radio_Project/Sync/Audio/music/ \
  pi@radio.local:/home/radio/audio/
```

Notes:
- The trailing `/` on `music/` is important; it copies the contents into `/home/radio/audio/`.
- If `radio.local` is unreliable, replace it with your Pi IP.
- Re-run the same command anytime; `rsync` sends only changed/missing data.

### 4) Verify and refresh library

```bash
ssh pi@radio.local
ls -lah /home/radio/audio/shows/AliceCooper
ls -lah "/home/radio/audio/tracks/The Blue Ark - GTA V.mp3"
mpc update
```

## Verify on the Pi

Run:

```bash
ls -lah /home/radio/audio/shows/AliceCooper
ls -lah "/home/radio/audio/tracks/The Blue Ark - GTA V.mp3"
```

Then refresh MPD's library:

```bash
mpc update
```

## Fixes for the exact errors you saw

### Error: `Connection closed by ... port 22`

Usually DNS/IPv6/network instability. Try:

1. Confirm SSH works first:
   ```powershell
   ssh -4 pi@radio.local
   ```
2. If that fails, use IP instead of mDNS name:
   ```powershell
   ssh -4 pi@192.168.1.50
   ```
3. Re-run `scp` with `-4` and the same host form that worked for SSH.

### Error: `stat remote: No such file or directory`

This means the destination path did not exist (or was not writable). Fix it on Pi:

```bash
sudo mkdir -p /home/radio/audio/{shows,tracks}
sudo chown -R pi:pi /home/radio/audio
```

Then retry the same `scp` command.


### Error: `Broken pipe` / `Connection reset` during a large copy

This usually means Wi-Fi briefly dropped or SSH timed out during a long transfer.

Try these fixes (in order):

1. Use SSH keepalives and IPv4:
   ```powershell
   scp -4 -o ServerAliveInterval=30 -o ServerAliveCountMax=6 -r "C:\Users\J\Documents\Radio_Project\Sync\Audio\music\*" pi@radio.local:/home/radio/audio/
   ```
2. Copy in smaller chunks instead of everything at once:
   ```powershell
   scp -4 -o ServerAliveInterval=30 -o ServerAliveCountMax=6 -r "C:\Users\J\Documents\Radio_Project\Sync\Audio\music\shows\*" pi@radio.local:/home/radio/audio/shows/
   scp -4 -o ServerAliveInterval=30 -o ServerAliveCountMax=6 -r "C:\Users\J\Documents\Radio_Project\Sync\Audio\music\tracks\*" pi@radio.local:/home/radio/audio/tracks/
   ```
3. If it still drops, use Pi IP instead of `radio.local`:
   ```powershell
   scp -4 -o ServerAliveInterval=30 -o ServerAliveCountMax=6 -r "C:\Users\J\Documents\Radio_Project\Sync\Audio\music\tracks\*" pi@192.168.1.50:/home/radio/audio/tracks/
   ```
4. Re-run the same command; files that already finished will be skipped/overwritten quickly, and remaining files continue.

Tip: A wired Ethernet connection for the transfer is much more reliable than Wi-Fi for large libraries.

## Quick sanity check against `stations.yaml`

If a station has:

```yaml
type: dir
path: "shows/AliceCooper"
```

then the Pi must have:

- `/home/radio/audio/shows/AliceCooper`

If a station has:

```yaml
type: file
path: "tracks/The Blue Ark - GTA V.mp3"
```

then the Pi must have:

- `/home/radio/audio/tracks/The Blue Ark - GTA V.mp3`

## Common mistakes to avoid

- Copying `music` into `/home/radio/audio/music` (adds an extra folder level and breaks paths).
- Copying to `/home/pi/...` instead of `/home/radio/audio/...`.
- Forgetting quotes around paths that contain spaces.
- Forgetting to run `mpc update` after adding new files.
