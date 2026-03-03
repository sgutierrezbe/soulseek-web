# soulseek-web

A minimalist web UI for [slskd](https://github.com/slskd/slskd) — search and download music from the Soulseek network in your browser, from any device, without installing any desktop client.

---

## Features

- 🔍 **Search albums and songs** across the Soulseek network
- 📀 **Album view** with expandable track list and automatic cover art (via Deezer)
- 🏅 **Smart ranking**: sorted by real popularity (Deezer), format (FLAC first), bitrate, and peer availability
- ⬇️ **One-click downloads** — full albums or individual tracks
- 📂 **Downloads tab** — grouped by album with cover art, per-track progress, and delete button (removes from queue + disk)
- 🖼️ **Automatic cover art** — in search results and the downloads list
- ⚙️ **Settings panel** — change Soulseek credentials, slskd connection, and music folder at any time
- 🔄 **In-app update** — pull the latest version from GitHub directly from Settings
- 🎛️ **Format filters**: ALL / FLAC / MP3
- 📱 **Responsive** — bottom navigation on mobile, sidebar on desktop
- 🪟 **Windows standalone** — one PowerShell command, no prior dependencies needed

---

## Stack

- **Backend**: [FastAPI](https://fastapi.tiangolo.com/) + [httpx](https://www.python-httpx.org/)
- **Frontend**: [Alpine.js](https://alpinejs.dev/) — no build step, no Node dependencies
- **Audio metadata**: [Mutagen](https://mutagen.readthedocs.io/)

---

## APIs & Acknowledgements

- **[slskd](https://github.com/slskd/slskd)** — the Soulseek daemon that handles all searching and downloading. Every network call goes through its REST API.
- **[Deezer API](https://developers.deezer.com/)** — album cover art and popularity ranking. Free, no API key required.
- **[Soulseek](https://www.slsknet.org/)** — the P2P music network that has been running for 25 years, full of music you can't find anywhere else.

---

## Requirements

- Python 3.11+
- A running [slskd](https://github.com/slskd/slskd) instance with API access
- **Windows**: nothing — the installer handles everything automatically

---

## Installation

### Option 1 — Linux (recommended for servers / NAS)

```bash
curl -sSL https://raw.githubusercontent.com/sgutierrezbe/soulseek-web/main/install.sh | sudo bash
```

Clones the repo to `/opt/soulseek-web`, sets up a Python virtualenv, installs dependencies, and registers a **systemd service** that starts automatically on boot.

Open `http://<your-ip>:8080` — on first launch you'll be prompted for your slskd URL and API key.

**To update:** run the same command again, or use the **Update** button in the Settings panel.

---

### Option 2 — Windows (fully standalone)

No prerequisites needed. The script installs Python, Git, and slskd automatically.

Open **PowerShell** and paste:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force; irm https://raw.githubusercontent.com/sgutierrezbe/soulseek-web/main/install.ps1 | iex
```

**What it does:**
1. Installs Python 3.12 if missing (via winget, or direct download from python.org)
2. Installs Git if missing (via winget, or direct download)
3. Downloads and configures **slskd** (the Soulseek daemon)
4. Clones soulseek-web and installs Python dependencies
5. Creates a **"Soulseek Web" shortcut** on your desktop
6. Opens the browser at `http://localhost:8080`

On first launch, enter your Soulseek username and password. That's it.

> No Soulseek account? Create one for free at [slsknet.org](https://www.slsknet.org/).

**To update:** use the **Update** button in the Settings panel, then close and reopen the app.

---

### Option 3 — Docker

```bash
docker compose up -d
```

Edit `docker-compose.yml` to set your `SLSKD_URL`, `SLSKD_API_KEY`, and `MUSIC_PATH` environment variables.

---

### Option 4 — Manual

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

On first launch, the setup wizard asks for:
- **slskd URL** — e.g. `http://localhost:5030`
- **API Key** — from your slskd config (`web.authentication.api_keys`)
- **Music folder** — where slskd saves downloads

All settings can be changed later in the **Settings panel** (⚙ in the sidebar).

### Environment variables (optional)

| Variable | Default | Description |
|---|---|---|
| `SLSKD_URL` | `http://localhost:5030` | slskd base URL |
| `SLSKD_API_KEY` | *(none)* | slskd API key |
| `MUSIC_PATH` | `/mnt/music/downloads` | Local path to downloads folder |

---

## Usage

1. **Search** — type an artist or album name. Results are grouped by album and ranked by popularity + quality.
2. **Download** — click **↓ ÁLBUM** to grab all tracks, or expand to pick individual songs.
3. **Downloads tab** — see active and completed downloads grouped by album, with progress and cover art. Expand a card to see track-level detail. Use **✕ BORRAR** to delete from the queue and disk.
4. **Settings** — update credentials, connection, music folder, or the app itself.

---

## Useful commands (Linux / systemd)

```bash
sudo systemctl status soulseek-web
sudo systemctl restart soulseek-web
sudo journalctl -u soulseek-web -f
```

---

## Notes

- Soulseek does not allow the same account to be logged in from two places simultaneously. If you run soulseek-web on a server **and** want a local Windows install, you'll need a second Soulseek account.
- The `.incomplete` folder inside your download directory is used by slskd for in-progress files. It is ignored when checking if a folder is empty during deletion.

---

## License

MIT
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
