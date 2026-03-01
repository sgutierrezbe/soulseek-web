# soulseek-web

Una interfaz web minimalista para [slskd](https://github.com/slskd/slskd) pensada para hacer que buscar y descargar música en Soulseek sea simple, rápido y cómodo — desde cualquier dispositivo y sin necesidad de instalar ningún cliente de escritorio.

La idea es eliminar la fricción: buscás un artista o álbum, ves los resultados organizados y rankeados, y descargás con un clic. Nada más.

---

## Características

- 🔍 **Búsqueda de álbumes y canciones** en la red Soulseek
- 📀 **Vista de álbumes** con lista de tracks expandible y portadas automáticas
- ⬇️ **Descarga álbumes completos** o canciones individuales
- 🏅 **Resultados inteligentes**: ordenados por popularidad real (Deezer), formato (FLAC primero), bitrate y disponibilidad del peer
- 🖼️ **Portadas automáticas** obtenidas en tiempo real
- 📱 **Responsive**: navegación inferior en móvil, tabla completa en escritorio
- 🔎 **Filtros por formato**: TODOS / FLAC / MP3

---

## Stack

- **Backend**: [FastAPI](https://fastapi.tiangolo.com/) + [httpx](https://www.python-httpx.org/)
- **Frontend**: [Alpine.js](https://alpinejs.dev/) — sin build step, sin dependencias de Node
- **Audio metadata**: [Mutagen](https://mutagen.readthedocs.io/)

---

## APIs utilizadas y agradecimientos

Este proyecto no sería posible sin estas herramientas y servicios:

- **[slskd](https://github.com/slskd/slskd)** — el daemon de Soulseek que hace todo el trabajo pesado. Toda la búsqueda y descarga va a través de su API REST. Gracias al equipo de slskd por construir un cliente tan sólido y con una API tan limpia.

- **[Deezer API](https://developers.deezer.com/)** — usada para dos cosas: obtener las portadas de los álbumes en alta resolución, y rankear los resultados de búsqueda según la popularidad real de los álbumes. Gratuita, sin API key requerida.

- **[Soulseek](https://www.slsknet.org/)** — la red P2P de música que lleva más de 20 años siendo un recurso invaluable para descubrir y compartir música, especialmente la más difícil de encontrar en plataformas de streaming.

---

## Requisitos

- [slskd](https://github.com/slskd/slskd) corriendo y accesible
- Python 3.11+

---

## Instalación

```bash
git clone https://github.com/sgutierrezbe/soulseek-web.git
cd soulseek-web

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Editá .env con la URL y API key de tu instancia de slskd
```

## Configuración

| Variable | Default | Descripción |
|---|---|---|
| `SLSKD_URL` | `http://localhost:5030` | URL de tu instancia de slskd |
| `SLSKD_API_KEY` | — | API key configurada en slskd |
| `MUSIC_PATH` | `/mnt/music/downloads` | Ruta a tu librería local |

## Correr

```bash
uvicorn main:app --host 0.0.0.0 --port 8080
```

## Correr como servicio systemd

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

## Licencia

MIT
