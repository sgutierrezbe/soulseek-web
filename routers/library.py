"""Browse what has actually been downloaded.

Scans the music folder for album directories. slskd writes either
``downloads/<album>/`` or ``downloads/<artist>/<album>/`` depending on how the
peer had things organised, so both shapes are handled.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

import paths
from cache import metadata

router = APIRouter()

_MAX_ALBUMS = 2000


def _read_tags(track: Path) -> dict:
    """Best-effort title/artist/track-number from the file's tags."""
    try:
        from mutagen import File as MutagenFile

        # Easy mode gives normalised tag names but doesn't cover every format;
        # fall back so at least the duration is read.
        #
        # Compare against None rather than testing truthiness: mutagen's
        # FileType is dict-like, so a file with no tags is itself falsy.
        audio = MutagenFile(track, easy=True)
        if audio is None:
            audio = MutagenFile(track)
        if audio is None:
            return {}
        tags = audio.tags or {}

        def first(key: str) -> str:
            value = tags.get(key)
            if isinstance(value, list):
                return str(value[0]) if value else ""
            return str(value) if value else ""

        number = first("tracknumber").split("/")[0]
        return {
            "title": first("title"),
            "artist": first("artist"),
            "track_no": int(number) if number.isdigit() else None,
            "duration": round(getattr(getattr(audio, "info", None), "length", 0) or 0),
        }
    except Exception:
        return {}


def _album_entry(folder: Path, root: Path) -> dict | None:
    tracks = paths.audio_files(folder)
    if not tracks:
        return None
    relative = folder.relative_to(root).as_posix()
    parent = folder.parent
    return {
        "path": relative,
        "album": folder.name,
        "artist": parent.name if parent != root else "",
        "track_count": len(tracks),
        "total_size": sum(t.stat().st_size for t in tracks if t.is_file()),
        "has_cover": paths.find_cover_file(folder) is not None,
    }


def _scan_library() -> list[dict]:
    root = paths.music_root()
    if not root.is_dir():
        return []

    albums: list[dict] = []
    try:
        top_level = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return []

    for entry in top_level:
        if entry.name.lower() in paths.IGNORED_ENTRIES:
            continue
        # A folder holding audio directly is an album; otherwise treat it as an
        # artist folder and look one level deeper.
        album = _album_entry(entry, root)
        if album is not None and any(
            p.suffix.lower() in paths.AUDIO_EXTS for p in entry.iterdir() if p.is_file()
        ):
            albums.append(album)
            continue
        try:
            children = sorted(p for p in entry.iterdir() if p.is_dir())
        except OSError:
            children = []
        for child in children:
            nested = _album_entry(child, root)
            if nested is not None:
                albums.append(nested)
        if not children and album is not None:
            albums.append(album)
        if len(albums) >= _MAX_ALBUMS:
            break

    albums.sort(key=lambda a: (a["artist"].lower(), a["album"].lower()))
    return albums


@router.get("/albums")
async def get_albums(refresh: bool = False):
    """Downloaded albums. Cached briefly -- a big library is slow to walk."""
    if not refresh:
        cached = metadata.get("library")
        if cached is not None:
            return cached

    albums = await run_in_threadpool(_scan_library)
    metadata.set("library", albums, ttl=60)
    return albums


@router.get("/tracks")
async def get_tracks(path: str):
    """Track listing for one album folder, with tags where they're readable."""
    folder = paths.resolve_within(path)
    if folder is None or not folder.is_dir():
        raise HTTPException(404, "Album folder not found.")

    root = paths.music_root()

    def build() -> list[dict]:
        tracks = []
        for index, track in enumerate(paths.audio_files(folder), start=1):
            tags = _read_tags(track)
            try:
                size = track.stat().st_size
            except OSError:
                size = 0
            tracks.append(
                {
                    "path": track.relative_to(root).as_posix(),
                    "filename": track.name,
                    "title": tags.get("title") or track.stem,
                    "artist": tags.get("artist", ""),
                    "track_no": tags.get("track_no") or index,
                    "duration": tags.get("duration", 0),
                    "size": size,
                    "extension": track.suffix.lstrip(".").upper(),
                }
            )
        tracks.sort(key=lambda t: (t["track_no"], t["filename"].lower()))
        return tracks

    return await run_in_threadpool(build)
