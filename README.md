# soulseek-web

A minimalist web UI for [slskd](https://github.com/slskd/slskd) designed to make searching and downloading music on Soulseek simple, fast, and comfortable — from any device, without installing any desktop client.

The goal is to remove friction: search for an artist or album, see organized and ranked results, and download with one click. That's it.

---

## Features

- 🔍 **Search albums and songs** across the Soulseek network
- 📀 **Album view** with expandable track list and automatic cover art
- ⬇️ **Download full albums** or individual tracks
- 🏅 **Smart results**: ranked by real popularity (Deezer), format (FLAC first), bitrate, and peer availability
- 🖼️ **Automatic cover art** fetched in real time
- 📱 **Responsive**: bottom navigation on mobile, full table on desktop
- 🔎 **Format filters**: ALL / FLAC / MP3

---

## Stack

- **Backend**: [FastAPI](https://fastapi.tiangolo.com/) + [httpx](https://www.python-httpx.org/)
- **Frontend**: [Alpine.js](https://alpinejs.dev/) — no build step, no Node dependencies
- **Audio metadata**: [Mutagen](https://mutagen.readthedocs.io/)

---

## APIs & Acknowledgements

This project wouldn't be possible without these tools and services:

- **[slskd](https://github.com/slskd/slskd)** — the Soulseek daemon that does all the heavy lifting. All searching and downloading goes through its REST API. Huge thanks to the slskd team for building such a solid client with such a clean API.

- **[Deezer API](https://developers.deezer.com/)** — used for two things: fetching high-resolution album cover art, and ranking search results based on real album popularity. Free, no API key required.

- **[Soulseek](https://www.slsknet.org/)** — the P2P music network that has been an invaluable resource for discovering and sharing music for over 20 years, especially music that's hard to find on streaming platforms.

---

## Requirements

- Python 3.11+
- For Linux/Docker: [slskd](https://github.com/slskd/slskd) running and accessible
- For Windows: nothing — the installer handles everything

---

## Installation

### Option 1 — Linux (recommended)

```bash
curl -sSL https://raw.githubusercontent.com/sgutierrezbe/soulseek-web/main/install.sh | sudo bash
```

Clones the repo to `/opt/soulseek-web`, installs dependencies, and creates a systemd service that starts automatically with the system.

Open `http://<your-ip>:8080` — on first launch you'll be prompted for your slskd URL and API key.

To update to the latest version, just run the same command again.

---

### Option 2 — Windows (fully standalone)

No prerequisites needed. The script installs everything.

Open **PowerShell** and paste:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force; irm https://raw.githubusercontent.com/sgutierrezbe/soulseek-web/main/install.ps1 | iex
```

**What it does:**
1. Installs Python and Git if missing (via winget)
2. Downloads and installs **slskd** (the Soulseek daemon) automatically
3. Clones and installs soulseek-web
4. Registers both programs to start automatically with Windows
5. Opens the browser at `http://localhost:8080`

On first launch, it will only ask for your **Soulseek username and password**. That's it.

> No Soulseek account? Create one for free at [slsknet.org](https://www.slsknet.org/).

To update, just run the same command again.

---

### Option 3 — Docker

```bash
git clone https://github.com/sgutierrezbe/soulseek-web.git
cd soulseek-web
docker compose up -d
```

Edit `docker-compose.yml` to set your music folder path (`/mnt/music`).

---

### Option 4 — Manual (any OS)

```bash
git clone https://github.com/sgutierrezbe/soulseek-web.git
cd soulseek-web
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080
```

---

## Configuration

On first launch, a setup wizard will ask for:

- **slskd URL** — where your daemon is running (e.g. `http://192.168.1.10:5030`)
- **API key** — found in your `slskd.yml` under `web.authentication.apiKey`
- **Download folder** — path where slskd saves downloaded files

Settings are saved to `credentials.json` and persist across restarts.

You can also configure via environment variables:

| Variable | Default | Description |
|---|---|---|
| `SLSKD_URL` | `http://localhost:5030` | URL of your slskd instance |
| `SLSKD_API_KEY` | — | API key from your slskd config |
| `MUSIC_PATH` | `/mnt/music/downloads` | Path to your local music library |

---

## Useful commands (systemd)

```bash
sudo systemctl status soulseek-web
sudo systemctl restart soulseek-web
sudo journalctl -u soulseek-web -f
```

---

## License

MIT
