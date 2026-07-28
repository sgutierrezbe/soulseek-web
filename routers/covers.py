"""Cover art, from whichever source answers first.

For downloaded albums: artwork embedded in the audio tags, then an image file
sitting in the folder, then Deezer. For search results there is nothing on disk
yet, so Deezer is the only option.

Every response carries an ETag and a long max-age. Covers are the bulk of the
bytes this app serves, and without cache headers a phone re-downloads all of
them on every render.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

import paths
import slskd
from cache import covers as cover_cache
from cache import metadata

router = APIRouter()

_YEAR_RE = re.compile(r"[\(\[]\s*(?:19|20)\d{2}\s*[\)\]]")
_BRACKETS_RE = re.compile(r"\[.*?\]")
_QUALITY_RE = re.compile(
    r"\b(FLAC|MP3|AAC|OGG|OPUS|WAV|24bit|16bit|320|256|192|kbps|CBR|VBR|"
    r"Lossless|Hi[\-\s]?Res|WEB|CDRip|CD|Vinyl|Remaster(?:ed)?|Deluxe)\b",
    re.IGNORECASE,
)

_IMAGE_MIMES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}

_CACHE_HEADERS = {"Cache-Control": "public, max-age=604800"}
# Retry a miss sooner -- the album may finish downloading a moment later.
_MISS_HEADERS = {"Cache-Control": "public, max-age=600"}


def _image_response(request: Request, key: str, data: bytes, mime: str) -> Response:
    etag = cover_cache.etag(key)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={**_CACHE_HEADERS, "ETag": etag})
    return Response(
        content=data, media_type=mime, headers={**_CACHE_HEADERS, "ETag": etag}
    )


def _not_found() -> Response:
    return Response(status_code=404, headers=_MISS_HEADERS)


def clean_for_search(artist: str, album: str) -> tuple[str, str]:
    """Strip year, format and quality tags before querying a metadata API."""

    def strip(name: str) -> str:
        name = _YEAR_RE.sub("", name)
        name = _BRACKETS_RE.sub("", name)
        name = _QUALITY_RE.sub("", name)
        return re.sub(r"\s+", " ", name).strip(" -_.")

    if " - " in album and not artist.strip():
        head, _, tail = album.partition(" - ")
        artist, album = head.strip(), tail.strip()
    return strip(artist), strip(album)


async def fetch_remote_cover(artist: str, album: str) -> bytes | None:
    """Look the album up on Deezer and download its highest-resolution cover."""
    key = f"search::{artist}::{album}".lower()
    cached = cover_cache.get(key)
    if cached is not None:
        return cached[0]
    if cover_cache.is_missing(key):
        return None

    clean_artist, clean_album = clean_for_search(artist, album)
    queries = [q for q in (f"{clean_artist} {clean_album}".strip(), clean_album, clean_artist) if q]

    client = slskd.external_client()
    for query in dict.fromkeys(queries):
        try:
            response = await client.get(
                "https://api.deezer.com/search/album", params={"q": query, "limit": 10}
            )
            results = response.json().get("data", [])
        except Exception:
            continue
        if not results:
            continue

        wanted = clean_album.lower()
        best = next(
            (r for r in results if wanted and wanted in r.get("title", "").lower()),
            results[0],
        )
        # cover_big is 500x500 -- ample for a grid card even at 2x DPR, and
        # roughly a quarter the bytes of cover_xl (1000x1000), which matters
        # when a search paints 20 of them over mobile data.
        url = best.get("cover_big") or best.get("cover_xl") or best.get("cover_medium")
        if not url:
            continue
        try:
            image = await client.get(url)
        except Exception:
            continue
        if image.status_code == 200 and image.content:
            cover_cache.set(key, image.content, "image/jpeg")
            return image.content

    cover_cache.mark_missing(key)
    return None


def get_embedded_cover(filepath: Path) -> tuple[bytes | None, str | None]:
    """Pull artwork out of an audio file's tags. Runs in a worker thread."""
    ext = filepath.suffix.lower()
    try:
        if ext == ".flac":
            from mutagen.flac import FLAC

            pictures = FLAC(filepath).pictures
            if pictures:
                return pictures[0].data, pictures[0].mime
        elif ext == ".mp3":
            from mutagen.id3 import ID3

            for tag in ID3(filepath).values():
                if getattr(tag, "FrameID", None) == "APIC":
                    return tag.data, tag.mime
        elif ext in (".m4a", ".aac", ".mp4"):
            from mutagen.mp4 import MP4

            tags = MP4(filepath).tags
            artwork = tags.get("covr") if tags else None
            if artwork:
                image = artwork[0]
                mime = "image/png" if getattr(image, "imageformat", 13) == 14 else "image/jpeg"
                return bytes(image), mime
        elif ext in (".ogg", ".opus"):
            from mutagen.flac import Picture
            from mutagen.oggopus import OggOpus
            from mutagen.oggvorbis import OggVorbis

            audio = (OggOpus if ext == ".opus" else OggVorbis)(filepath)
            block = audio.get("metadata_block_picture", [])
            if block:
                picture = Picture(base64.b64decode(block[0]))
                return picture.data, picture.mime
    except Exception:
        pass
    return None, None


def find_local_cover(folder: Path) -> tuple[bytes | None, str | None]:
    """Embedded artwork from the first audio file, else an image in the folder."""
    for audio in paths.audio_files(folder)[:3]:
        data, mime = get_embedded_cover(audio)
        if data:
            return data, mime or "image/jpeg"

    image = paths.find_cover_file(folder)
    if image is not None:
        try:
            return image.read_bytes(), _IMAGE_MIMES.get(image.suffix.lower(), "image/jpeg")
        except OSError:
            pass
    return None, None


@router.get("/search")
async def cover_from_search(request: Request, artist: str = "", album: str = ""):
    """Cover for a search result -- nothing is on disk yet, so ask Deezer."""
    key = f"search::{artist}::{album}".lower()
    cached = cover_cache.get(key)
    if cached is not None:
        return _image_response(request, key, cached[0], cached[1])

    data = await fetch_remote_cover(artist, album)
    if data:
        return _image_response(request, key, data, "image/jpeg")
    return _not_found()


@router.get("/folder")
async def cover_from_folder(request: Request, folder_name: str):
    """Cover for a downloaded album: embedded art, then an image file, then Deezer."""
    key = f"folder::{folder_name.lower()}"
    cached = cover_cache.get(key)
    if cached is not None:
        return _image_response(request, key, cached[0], cached[1])

    folder = paths.find_album_folder(folder_name)
    if folder is not None:
        data, mime = await run_in_threadpool(find_local_cover, folder)
        if data:
            cover_cache.set(key, data, mime or "image/jpeg")
            return _image_response(request, key, data, mime or "image/jpeg")

    if cover_cache.is_missing(key):
        return _not_found()

    leaf = folder_name.replace("\\", "/").rstrip("/").split("/")[-1]
    artist, _, album = leaf.partition(" - ")
    data = await fetch_remote_cover(artist if album else "", album or leaf)
    if data:
        cover_cache.set(key, data, "image/jpeg")
        return _image_response(request, key, data, "image/jpeg")

    cover_cache.mark_missing(key)
    return _not_found()


@router.get("/local")
async def cover_from_file(request: Request, path: str):
    """Cover for one downloaded file. `path` is relative to the music folder."""
    target = paths.resolve_within(path)
    if target is None or not target.is_file():
        return _not_found()

    key = f"local::{path.lower()}"
    cached = cover_cache.get(key)
    if cached is not None:
        return _image_response(request, key, cached[0], cached[1])

    data, mime = await run_in_threadpool(get_embedded_cover, target)
    if not data:
        data, mime = await run_in_threadpool(find_local_cover, target.parent)
    if data:
        cover_cache.set(key, data, mime or "image/jpeg")
        return _image_response(request, key, data, mime or "image/jpeg")
    return _not_found()


@router.get("/trending")
async def get_trending():
    """Popular albums right now, from the iTunes US top-albums chart."""
    cached = metadata.get("trending")
    if cached is not None:
        return JSONResponse(cached, headers={"Cache-Control": "public, max-age=1800"})

    try:
        response = await slskd.external_client().get(
            "https://itunes.apple.com/us/rss/topalbums/limit=24/json"
        )
        entries = response.json().get("feed", {}).get("entry", [])
    except Exception:
        return JSONResponse([], headers=_MISS_HEADERS)

    albums = []
    for entry in entries:
        try:
            raw_image = entry["im:image"][-1]["label"]
            albums.append(
                {
                    "title": entry["im:name"]["label"],
                    "artist": entry["im:artist"]["label"],
                    # The feed serves 170px thumbnails; ask for something sharper.
                    "cover_url": re.sub(r"\d+x\d+bb", "600x600bb", raw_image),
                }
            )
        except (KeyError, IndexError):
            continue

    metadata.set("trending", albums, ttl=3600)
    return JSONResponse(albums, headers={"Cache-Control": "public, max-age=1800"})
