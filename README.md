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

- [slskd](https://github.com/slskd/slskd) running and accessible
- Python 3.11+

---

## Setup

```bash
git clone https://github.com/sgutierrezbe/soulseek-web.git
cd soulseek-web

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your slskd URL and API key
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `SLSKD_URL` | `http://localhost:5030` | URL of your slskd instance |
| `SLSKD_API_KEY` | — | API key from your slskd config |
| `MUSIC_PATH` | `/mnt/music/downloads` | Path to your local music library |

## Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8080
```

## Run as a systemd service

```ini
[Unit]
Description=Soulseek Web UI
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/soulseek-web
ExecStart=/opt/soulseek-web/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

---

## License

MIT
