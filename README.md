# Spotify Downloader (PC)

A self-hosted [spotDL](https://github.com/spotDL/spotify-downloader) web app, in
Docker, for downloading your own music on a **PC** (Windows / macOS / Linux with
Docker Desktop). Paste a Spotify track, album, or playlist link and it fetches the
audio into `./music`, one folder per album/playlist.

This is the PC build of the Raspberry Pi setup — same downloader, but bound to
**localhost only** and with the Pi's FTP server removed (on a PC you just open the
`music/` folder directly).

## Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS)
  or Docker Engine + Compose (Linux).
- Your own free Spotify API credentials (below).

## Setup

1. Get Spotify API credentials — create a free app at
   https://developer.spotify.com/dashboard (any name; the redirect URI can be
   `http://localhost`). Copy the **Client ID** and **Client Secret**.

2. Create your `.env` from the template and paste them in:

   ```bash
   cp .env.example .env     # Windows: copy .env.example .env
   ```

   ```env
   SPOTIFY_CLIENT_ID=your_client_id
   SPOTIFY_CLIENT_SECRET=your_client_secret
   ```

3. Build and start:

   ```bash
   docker compose up --build -d
   ```

4. Open **http://localhost:8800**, paste a Spotify link, and download.
   Files appear in `./music/`.

Stop it with `docker compose down`.

## Notes

- **Downloads are local.** Everything lands in `./music/<album or playlist>/`.
  Open that folder in Explorer/Finder — no FTP, no network share.
- **Localhost only.** The web UI is bound to `127.0.0.1:8800`, so it's not exposed
  to your network. (The Raspberry Pi version binds `0.0.0.0` on purpose; this one
  doesn't.)
- **yt-dlp stays current.** The `Dockerfile` upgrades yt-dlp at build time. If
  downloads start failing with `HTTP Error 403: Forbidden`, YouTube changed again —
  rebuild: `docker compose build --no-cache && docker compose up -d`.
- **Playlist/album fix.** `patches/web_playlist_fix.py` patches spotDL's web UI so
  pasting a playlist or album link works (upstream only handled single tracks) and
  shows live progress through a single download queue.
- **Windows permissions.** If downloads fail to write to `./music`, comment out the
  `user:` line in `docker-compose.yaml` so the container runs as root.

## Legal

This downloads audio for **personal use** from links you already have access to.
Respect Spotify's terms and the rights of artists and labels — don't redistribute.
