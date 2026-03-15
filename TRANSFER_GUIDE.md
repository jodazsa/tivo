# Windows → Raspberry Pi Audio Transfer Guide

This guide copies your Windows audio library into the exact relative paths expected by `stations.yaml`.

## Goal

Your `stations.yaml` uses paths relative to:

- `/home/pi/audio/`

So:

- Windows folder `C:\Users\J\Documents\Radio_Project\Sync\Audio\music\shows\AliceCooper`
  becomes Pi folder `/home/pi/audio/shows/AliceCooper`
- Windows file `C:\Users\J\Documents\Radio_Project\Sync\Audio\music\tracks\The Blue Ark - GTA V.mp3`
  becomes Pi file `/home/pi/audio/tracks/The Blue Ark - GTA V.mp3`

## Path mapping rule

Copy the **contents of**:

- `C:\Users\J\Documents\Radio_Project\Sync\Audio\music\`

into:

- `/home/pi/audio/`

That preserves all relative paths used in `stations.yaml` (for example `shows/...` and `tracks/...`).

## 0) One-time prep on the Pi (important)

The `pi` user often cannot write directly to `/home/pi/audio` until it exists and permissions are set.

SSH in and run:

```bash
ssh pi@tivo.local
sudo mkdir -p /home/pi/audio
sudo chown -R pi:pi /home/pi/audio
```

If `tivo.local` is flaky, use your Pi IP instead:

```bash
ssh pi@192.168.4.24
```

## Option A (recommended): copy everything in one command

Use username `pi` in the commands below. (If your Pi uses a different login, replace `pi` with that username.)

Run this from **PowerShell on your Windows PC**:

```powershell
scp -4 -r "C:\Users\J\Documents\Radio_Project\Sync\Audio\music\*" pi@tivo.local:/home/pi/audio/
```

If `tivo.local` does not resolve reliably, replace it with your Pi IP:

```powershell
scp -4 -r "C:\Users\J\Documents\Radio_Project\Sync\Audio\music\*" pi@192.168.4.24:/home/pi/audio/
```

## Option B: copy only specific items

### Copy one show directory

```powershell
scp -4 -r "C:\Users\J\Documents\Radio_Project\Sync\Audio\music\shows\AliceCooper" pi@tivo.local:/home/pi/audio/shows/
```

### Copy one track file

```powershell
scp -4 "C:\Users\J\Documents\Radio_Project\Sync\Audio\music\tracks\The Blue Ark - GTA V.mp3" pi@tivo.local:/home/pi/audio/tracks/
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
ssh pi@tivo.local "sudo mkdir -p /home/pi/audio && sudo chown -R pi:pi /home/pi/audio"
```

### 3) Run rsync from WSL

```bash
rsync -avh --progress --partial --append-verify \
  /mnt/c/Users/J/Documents/Radio_Project/Sync/Audio/music/ \
  pi@tivo.local:/home/pi/audio/
```

Notes:
- The trailing `/` on `music/` is important; it copies the contents into `/home/pi/audio/`.
- If `tivo.local` is unreliable, replace it with your Pi IP.
- Re-run the same command anytime; `rsync` sends only changed/missing data.

### 4) Verify and refresh library

```bash
ssh pi@tivo.local
ls -lah /home/pi/audio/shows/AliceCooper
ls -lah "/home/pi/audio/tracks/The Blue Ark - GTA V.mp3"
mpc update
```

## Verify on the Pi

Run:

```bash
ls -lah /home/pi/audio/shows/AliceCooper
ls -lah "/home/pi/audio/tracks/The Blue Ark - GTA V.mp3"
```

Then refresh MPD's library:

```bash
mpc update
```

## Fixes for the exact errors you saw

### Error: `Connection timed out` (port 22)

This means the Pi is unreachable at the network level — SSH never got through.

Diagnose in order:

1. **Check if the Pi is on the network at all:**
   ```bash
   ping -c 4 192.168.4.24
   ```
   No reply → Pi is powered off, crashed, or booting. Wait and retry.

2. **Find the Pi if its IP changed (DHCP):**
   ```bash
   # From WSL:
   arp -a | grep -i raspberry
   # or scan the subnet:
   nmap -sn 192.168.4.0/24
   ```
   Use whatever IP responds, or assign a static IP on the Pi.

3. **Try the hostname instead of the IP:**
   ```bash
   ssh -4 pi@tivo.local
   ```

4. **Check SSH is running on the Pi** (if you can reach it via another method):
   ```bash
   sudo systemctl status ssh
   sudo systemctl enable --now ssh
   ```

5. **Retry rsync using the correct reachable address:**
   ```bash
   rsync -avh --progress --partial --append-verify \
     /mnt/c/Users/J/Documents/Radio_Project/Sync/Audio/music/ \
     pi@tivo.local:/home/pi/audio/
   ```

### Error: `Connection closed by ... port 22`

Usually DNS/IPv6/network instability. Try:

1. Confirm SSH works first:
   ```powershell
   ssh -4 pi@tivo.local
   ```
2. If that fails, use IP instead of mDNS name:
   ```powershell
   ssh -4 pi@192.168.4.24
   ```
3. Re-run `scp` with `-4` and the same host form that worked for SSH.

### Error: `stat remote: No such file or directory`

This means the destination path did not exist (or was not writable). Fix it on Pi:

```bash
sudo mkdir -p /home/pi/audio/{shows,tracks}
sudo chown -R pi:pi /home/pi/audio
```

Then retry the same `scp` command.


### Error: `Broken pipe` / `Connection reset` during a large copy

This usually means Wi-Fi briefly dropped or SSH timed out during a long transfer.

Try these fixes (in order):

1. Use SSH keepalives and IPv4:
   ```powershell
   scp -4 -o ServerAliveInterval=30 -o ServerAliveCountMax=6 -r "C:\Users\J\Documents\Radio_Project\Sync\Audio\music\*" pi@tivo.local:/home/pi/audio/
   ```
2. Copy in smaller chunks instead of everything at once:
   ```powershell
   scp -4 -o ServerAliveInterval=30 -o ServerAliveCountMax=6 -r "C:\Users\J\Documents\Radio_Project\Sync\Audio\music\shows\*" pi@tivo.local:/home/pi/audio/shows/
   scp -4 -o ServerAliveInterval=30 -o ServerAliveCountMax=6 -r "C:\Users\J\Documents\Radio_Project\Sync\Audio\music\tracks\*" pi@tivo.local:/home/pi/audio/tracks/
   ```
3. If it still drops, use Pi IP instead of `tivo.local`:
   ```powershell
   scp -4 -o ServerAliveInterval=30 -o ServerAliveCountMax=6 -r "C:\Users\J\Documents\Radio_Project\Sync\Audio\music\tracks\*" pi@192.168.4.24:/home/pi/audio/tracks/
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

- `/home/pi/audio/shows/AliceCooper`

If a station has:

```yaml
type: file
path: "tracks/The Blue Ark - GTA V.mp3"
```

then the Pi must have:

- `/home/pi/audio/tracks/The Blue Ark - GTA V.mp3`

## Common mistakes to avoid

- Copying `music` into `/home/pi/audio/music` (adds an extra folder level and breaks paths).
- Copying to `/home/pi/...` instead of `/home/pi/audio/...`.
- Forgetting quotes around paths that contain spaces.
- Forgetting to run `mpc update` after adding new files.
