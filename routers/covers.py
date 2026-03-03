from fastapi import APIRouter
from fastapi.responses import Response, JSONResponse
from pathlib import Path
import httpx
import os
import re
import time

router = APIRouter()

# Cache en memoria para no repetir requests
cover_cache = {}

AUDIO_EXTS = {".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav", ".aiff", ".ape", ".wv"}


def clean_for_search(artist: str, album: str) -> tuple[str, str]:
    """Limpia nombres antes de buscar: elimina año, formato, tags de calidad."""

    def strip_name(name: str) -> str:
        # Eliminar años entre paréntesis o corchetes: (2025), [2021]
        name = re.sub(r'[\(\[]\s*(?:19|20)\d{2}\s*[\)\]]', '', name)
        # Eliminar tags de formato entre corchetes: [FLAC], [320kbps]
        name = re.sub(r'\[.*?\]', '', name)
        # Eliminar marcadores de calidad sueltos
        name = re.sub(
            r'\b(FLAC|MP3|AAC|OGG|OPUS|WAV|24bit|16bit|320|256|192|kbps|CBR|VBR|Lossless|Hi[\-\s]Res|WEB|CDRip|Vinyl)\b',
            '', name, flags=re.IGNORECASE
        )
        return re.sub(r'\s+', ' ', name).strip(' -_.')

    # Si el álbum tiene formato "Artista - Álbum" y no hay artista, separarlo
    if " - " in album and not artist.strip():
        parts = album.split(" - ", 1)
        artist = parts[0].strip()
        album = parts[1].strip()

    return strip_name(artist), strip_name(album)


async def fetch_cover(artist: str, album: str) -> bytes | None:
    """Busca portada usando Deezer API (gratuita, sin key, rápida y precisa)."""
    cache_key = f"{artist}::{album}".lower()
    if cache_key in cover_cache:
        return cover_cache[cache_key]

    clean_artist, clean_album = clean_for_search(artist, album)

    # Intentar con varias queries en orden de especificidad
    queries = []
    if clean_artist and clean_album:
        queries.append(f"{clean_artist} {clean_album}")
    if clean_album:
        queries.append(clean_album)
    if clean_artist:
        queries.append(clean_artist)

    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for query in queries:
            try:
                resp = await client.get(
                    "https://api.deezer.com/search/album",
                    params={"q": query, "limit": 10},
                )
                results = resp.json().get("data", [])
                if not results:
                    continue

                # Preferir el resultado cuyo título coincida con el álbum buscado
                clean_album_lower = clean_album.lower()
                best = None
                for r in results:
                    title = r.get("title", "").lower()
                    if clean_album_lower and clean_album_lower in title:
                        best = r
                        break
                if not best:
                    best = results[0]

                # Deezer devuelve URLs directas a la imagen — usar cover_xl (1000x1000)
                cover_url = best.get("cover_xl") or best.get("cover_big") or best.get("cover_medium")
                if not cover_url:
                    continue

                img_resp = await client.get(cover_url)
                if img_resp.status_code == 200:
                    cover_cache[cache_key] = img_resp.content
                    return img_resp.content
            except Exception:
                continue

    cover_cache[cache_key] = None
    return None


def get_embedded_cover(filepath: str):
    ext = filepath.split(".")[-1].lower()
    try:
        if ext == "flac":
            from mutagen.flac import FLAC
            audio = FLAC(filepath)
            if audio.pictures:
                pic = audio.pictures[0]
                return pic.data, pic.mime
        elif ext in ("mp3",):
            from mutagen.id3 import ID3
            tags = ID3(filepath)
            for tag in tags.values():
                if hasattr(tag, 'FrameID') and tag.FrameID == "APIC":
                    return tag.data, tag.mime
        elif ext in ("m4a", "aac", "mp4"):
            from mutagen.mp4 import MP4
            audio = MP4(filepath)
            covr = audio.tags.get("covr") if audio.tags else None
            if covr:
                img = covr[0]
                mime = "image/jpeg" if getattr(img, 'imageformat', 13) == 13 else "image/png"
                return bytes(img), mime
        elif ext in ("ogg", "opus"):
            from mutagen.oggvorbis import OggVorbis
            from mutagen.oggopus import OggOpus
            klass = OggOpus if ext == "opus" else OggVorbis
            audio = klass(filepath)
            metadata_block = audio.get("metadata_block_picture", [])
            if metadata_block:
                import base64
                from mutagen.flac import Picture
                pic = Picture(base64.b64decode(metadata_block[0]))
                return pic.data, pic.mime
    except Exception:
        pass
    return None, None


def _find_cover_in_folder(folder: Path):
    """Try embedded art from first audio file, then look for cover image files."""
    # Try embedded first
    for f in sorted(folder.iterdir()):
        if f.is_file() and f.suffix.lower() in AUDIO_EXTS:
            data, mime = get_embedded_cover(str(f))
            if data:
                return data, mime or "image/jpeg"
    # Fallback: image files in the folder
    for name in ["cover.jpg", "cover.png", "folder.jpg", "folder.png",
                  "front.jpg", "front.png", "Cover.jpg", "Cover.png"]:
        p = folder / name
        if p.exists():
            mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
            return p.read_bytes(), mime
    return None, None


@router.get("/search")
async def cover_from_search(artist: str, album: str):
    """Para resultados de búsqueda — usa Deezer API"""
    data = await fetch_cover(artist, album)
    if data:
        return Response(content=data, media_type="image/jpeg")
    return Response(status_code=404)


@router.get("/folder")
async def cover_from_folder(folder_name: str):
    """Para la pestaña de descargas: embedded art > cover.jpg > Deezer."""
    from config import MUSIC_PATH

    cache_key = f"folder::{folder_name.lower()}"
    if cache_key in cover_cache and cover_cache[cache_key]:
        d, m = cover_cache[cache_key]
        return Response(content=d, media_type=m)

    # 1. Try to read from disk
    folder = Path(MUSIC_PATH) / folder_name
    if folder.is_dir():
        data, mime = _find_cover_in_folder(folder)
        if data:
            cover_cache[cache_key] = (data, mime)
            return Response(content=data, media_type=mime)

    # 2. Fallback: Deezer with cleaned folder name
    sep = folder_name.find(" - ")
    artist = folder_name[:sep] if sep > -1 else ""
    album  = folder_name[sep + 3:] if sep > -1 else folder_name
    data = await fetch_cover(artist, album)
    if data:
        cover_cache[cache_key] = (data, "image/jpeg")
        return Response(content=data, media_type="image/jpeg")

    cover_cache[cache_key] = None
    return Response(status_code=404)


@router.get("/trending")
async def get_trending():
    """Devuelve los álbumes en tendencia según el chart de iTunes US (Apple RSS)."""
    cache_key = "__trending__"
    cached = cover_cache.get(cache_key)
    if cached and time.time() - cached["ts"] < 3600:
        return JSONResponse(cached["data"])

    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            resp = await client.get(
                "https://itunes.apple.com/us/rss/topalbums/limit=24/json"
            )
            entries = resp.json().get("feed", {}).get("entry", [])
    except Exception:
        return JSONResponse([])

    albums = []
    for item in entries:
        try:
            artist = item["im:artist"]["label"]
            title  = item["im:name"]["label"]
            # imagen viene en 170x170, escalar a 600x600
            raw_img = item["im:image"][-1]["label"]
            cover = re.sub(r'\d+x\d+bb', '600x600bb', raw_img)
            if title and cover:
                albums.append({"title": title, "artist": artist, "cover_url": cover})
        except (KeyError, IndexError):
            continue

    cover_cache[cache_key] = {"ts": time.time(), "data": albums}
    return JSONResponse(albums)


@router.get("/local")
async def cover_from_file(path: str):
    """Para librería local — usa arte embebido o cover.jpg"""
    if not os.path.exists(path):
        return Response(status_code=404)
    data, mime = get_embedded_cover(path)
    if data:
        return Response(content=data, media_type=mime or "image/jpeg")
    folder = Path(path).parent
    for name in ["cover.jpg", "cover.png", "folder.jpg", "front.jpg", "Cover.jpg"]:
        cover_path = folder / name
        if cover_path.exists():
            return Response(content=cover_path.read_bytes(), media_type="image/jpeg")
    return Response(status_code=404)