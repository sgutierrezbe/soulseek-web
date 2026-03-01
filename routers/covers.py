from fastapi import APIRouter
from fastapi.responses import Response
from pathlib import Path
import httpx
import re

router = APIRouter()

# Cache en memoria para no repetir requests
cover_cache = {}


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
    except Exception:
        pass
    return None, None


@router.get("/search")
async def cover_from_search(artist: str, album: str):
    """Para resultados de búsqueda — usa iTunes Search API"""
    data = await fetch_cover(artist, album)
    if data:
        return Response(content=data, media_type="image/jpeg")
    return Response(status_code=404)


@router.get("/local")
async def cover_from_file(path: str):
    """Para librería local — usa arte embebido o cover.jpg"""
    import os
    from config import MUSIC_PATH

    # Reject traversal attempts: resolve the path and verify it stays under MUSIC_PATH
    try:
        resolved = os.path.realpath(path)
        music_root = os.path.realpath(MUSIC_PATH)
        if os.path.commonpath([resolved, music_root]) != music_root:
            return Response(status_code=403)
    except Exception:
        return Response(status_code=400)

    if not os.path.exists(resolved):
        return Response(status_code=404)

    # Intentar arte embebido
    data, mime = get_embedded_cover(resolved)
    if data:
        return Response(content=data, media_type=mime or "image/jpeg")

    # Fallback: cover.jpg en la carpeta
    folder = Path(resolved).parent
    for name in ["cover.jpg", "cover.png", "folder.jpg", "front.jpg", "Cover.jpg"]:
        cover_path = folder / name
        if cover_path.exists():
            return Response(content=cover_path.read_bytes(), media_type="image/jpeg")

    return Response(status_code=404)