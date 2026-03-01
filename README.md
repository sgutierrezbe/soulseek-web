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

## Instalación

### Opción 1 — Un solo comando (Linux, recomendado)

```bash
curl -sSL https://raw.githubusercontent.com/sgutierrezbe/soulseek-web/main/install.sh | sudo bash
```

Esto clona el repo en `/opt/soulseek-web`, instala las dependencias, crea y habilita un servicio systemd que arranca solo con el sistema.

Al terminar, abrí `http://<tu-ip>:8080` en el navegador — la primera vez te pedirá la URL de slskd y tu API key.

Para actualizar a la última versión, simplemente volvé a correr el mismo comando.

---

### Opción 2 — Windows (totalmente autónomo)

No necesitás nada instalado previamente. El script instala todo solo.

Abrí **PowerShell** y pegá esto:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force; irm https://raw.githubusercontent.com/sgutierrezbe/soulseek-web/main/install.ps1 | iex
```

**Qué hace:**
1. Instala Python y Git si no están (vía winget)
2. Descarga e instala **slskd** (el motor de Soulseek) automáticamente
3. Clona e instala soulseek-web
4. Registra ambos programas para que arranquen solos con Windows
5. Abre el navegador en `http://localhost:8080`

Al abrirse por primera vez, solo te pedirá tu **usuario y contraseña de Soulseek**. Eso es todo.

> Si no tenés cuenta de Soulseek, creá una gratis en [slsknet.org](https://www.slsknet.org/).

Para actualizar, volvé a ejecutar el mismo comando.

---

### Opción 3 — Docker

```bash
git clone https://github.com/sgutierrezbe/soulseek-web.git
cd soulseek-web
docker compose up -d
```

Editá el `docker-compose.yml` para ajustar la ruta de tu carpeta de música (`/mnt/music`).

---

### Opción 4 — Manual (cualquier SO)

```bash
git clone https://github.com/sgutierrezbe/soulseek-web.git
cd soulseek-web
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080
```

---

## Configuración

La primera vez que abrís la UI en el navegador, un wizard te pedirá:

- **URL de slskd** — dónde corre tu daemon (ej: `http://192.168.1.10:5030`)
- **API key** — la encontrás en tu `slskd.yml` bajo `web.authentication.apiKey`
- **Carpeta de descargas** — ruta donde slskd guarda los archivos

La configuración se guarda en `credentials.json` y persiste entre reinicios.

Si preferís configurar por variables de entorno:

| Variable | Default | Descripción |
|---|---|---|
| `SLSKD_URL` | `http://localhost:5030` | URL de tu instancia de slskd |
| `SLSKD_API_KEY` | — | API key de tu config de slskd |
| `MUSIC_PATH` | `/mnt/music/downloads` | Ruta a tu librería de música local |

---

## Comandos útiles (systemd)

```bash
sudo systemctl status soulseek-web
sudo systemctl restart soulseek-web
sudo journalctl -u soulseek-web -f
```

---

## License

MIT
