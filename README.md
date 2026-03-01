# soulseek-web

Web UI for [slskd](https://github.com/slskd/slskd) — a Soulseek daemon. Search, download albums and songs, and browse your local music library from the browser.

Built with **FastAPI** + **Alpine.js**. No build step required.

![screenshot](https://i.imgur.com/placeholder.png)

## Features

- 🔍 Search albums and songs across the Soulseek network
- 📀 Album view with expandable track list and cover art (via Deezer API)
- ⬇️ Download full albums or individual tracks
- 📚 Local music library browser with cover art
- 📱 Responsive — mobile-friendly with bottom navigation bar
- 🏅 Results ranked by Deezer popularity + peer count, FLAC first

## Requirements

- [slskd](https://github.com/slskd/slskd) running and accessible
- Python 3.11+

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

Set these environment variables (or copy `.env.example` to `.env`):

| Variable | Default | Description |
|---|---|---|
| `SLSKD_URL` | `http://localhost:5030` | URL of your slskd instance |
| `SLSKD_API_KEY` | — | API key from slskd config |
| `MUSIC_PATH` | `/mnt/music/downloads` | Path to your local music library |

## Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8080
```

## Run as systemd service

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

## License

MIT
