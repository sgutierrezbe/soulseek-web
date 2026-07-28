"""Search the Soulseek network through slskd and group results into albums.

Results arrive as a flat list of files per peer. We fold them into one entry per
remote folder, drop obvious duplicates, and rank by a mix of real-world album
popularity (Deezer), audio quality, and how likely the peer is to actually serve
the transfer.

The Deezer lookup is cached: the UI polls this endpoint roughly every 1.5s while
a search runs, and the previous version issued a fresh Deezer request on every
one of those polls.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import slskd
from cache import metadata

router = APIRouter()

AUDIO_EXTS = {"mp3", "flac", "ogg", "aac", "opus", "m4a", "wav", "aiff", "ape", "wv"}
LOSSLESS_EXTS = {"FLAC", "WAV", "AIFF", "APE", "WV"}

# Folder names too generic to be a useful artist guess.
JUNK_NAMES = {
    "albumes", "albums", "música", "musica", "downloads", "descargas", "music",
    "mp3", "flac", "various", "various artists", "va", "mixed", "shared", "media",
    "complete", "discography", "discografia", "discografía", "soulseek", "temp",
}

_YEAR_RE = re.compile(r"[\(\[]\s*((?:19|20)\d{2})\s*[\)\]]")
_BRACKETS_RE = re.compile(r"\[.*?\]")
_QUALITY_RE = re.compile(
    r"\b(FLAC|MP3|AAC|OGG|OPUS|WAV|WEB|CDRip|CD|Vinyl|Lossless|Remaster(?:ed)?|"
    r"Deluxe|Reissue|24bit|16bit|320|256|192|kbps|CBR|VBR|Hi[\-\s]?Res)\b",
    re.IGNORECASE,
)
_LEADING_TAGS_RE = re.compile(r"^(\s*[\[\(][^\]\)]*[\]\)]\s*)+")


def extract_year(name: str) -> int | None:
    match = _YEAR_RE.search(name)
    return int(match.group(1)) if match else None


def normalize_folder(name: str) -> str:
    """Reduce a folder name to a comparable album key.

    Strips years, format/quality tags and any leading "Artist - " so that
    variants of the same album collapse onto one entry.
    """
    name = _YEAR_RE.sub("", name)
    name = _BRACKETS_RE.sub("", name)
    name = _QUALITY_RE.sub("", name)
    if " - " in name:
        name = name.split(" - ", 1)[-1]
    return re.sub(r"\s+", " ", name).strip(" -_.").lower()


async def deezer_album_ranks(query: str) -> dict[str, int]:
    """Map normalized album title -> chart position (0 = most popular)."""
    if not query:
        return {}
    key = f"deezer-ranks::{query.lower()}"
    cached = metadata.get(key)
    if cached is not None:
        return cached

    try:
        response = await slskd.external_client().get(
            "https://api.deezer.com/search/album", params={"q": query, "limit": 50}
        )
        entries = response.json().get("data", [])
        ranks = {
            normalize_folder(entry.get("title", "")): index
            for index, entry in enumerate(entries)
        }
        metadata.set(key, ranks)
    except Exception:
        # Don't cache a failure for the full TTL -- the next search should retry.
        ranks = {}
        metadata.set(key, ranks, ttl=60)
    return ranks


class SearchRequest(BaseModel):
    query: str


def _folder_of(filename: str) -> str:
    normalized = filename.replace("\\", "/")
    return normalized.rsplit("/", 1)[0] if "/" in normalized else normalized


def _leaf(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").split("/")[-1]


def _build_albums(responses: list[dict], advanced: bool) -> list[dict]:
    """Fold slskd's per-peer file lists into one entry per remote folder."""
    albums: list[dict] = []

    for response in responses:
        username = response.get("username", "")
        upload_speed = response.get("uploadSpeed", 0) or 0
        queue_length = response.get("queueLength", 0) or 0
        free_slots = bool(response.get("hasFreeUploadSlot", False))

        folders: dict[str, list[dict]] = defaultdict(list)
        for file in response.get("files", []):
            folders[_folder_of(file.get("filename", ""))].append(file)

        for folder_path, files in folders.items():
            audio = [
                f
                for f in files
                if f.get("filename", "").rsplit(".", 1)[-1].lower() in AUDIO_EXTS
            ]

            if advanced:
                # Advanced mode shows everything, including single files and
                # folders slskd reported without a recognised audio extension.
                if not files:
                    continue
                display_files = files
                counted = audio or files
            else:
                if len(audio) < 2:
                    continue
                display_files = counted = audio

            extensions = Counter(
                f.get("filename", "").rsplit(".", 1)[-1].upper() for f in counted
            )
            dominant_ext = extensions.most_common(1)[0][0] if extensions else "?"

            bitrate = next((f.get("bitRate") for f in counted if f.get("bitRate")), None)
            sample_rate = next((f.get("sampleRate") for f in counted if f.get("sampleRate")), None)
            bit_depth = next((f.get("bitDepth") for f in counted if f.get("bitDepth")), None)
            duration = sum(f.get("length") or 0 for f in counted)

            folder_name = _leaf(folder_path)
            if not advanced:
                folder_name = _LEADING_TAGS_RE.sub("", folder_name).strip()

            segments = folder_path.replace("\\", "/").split("/")
            artist_guess = segments[-2] if len(segments) >= 2 else ""

            albums.append(
                {
                    "id": f"{username}::{folder_path}",
                    "username": username,
                    "upload_speed": upload_speed,
                    "queue_length": queue_length,
                    "free_slots": free_slots,
                    "folder_path": folder_path,
                    "folder_name": folder_name or _leaf(folder_path),
                    "artist_guess": artist_guess,
                    "year": extract_year(_leaf(folder_path)),
                    "track_count": len(counted),
                    "total_size": sum(f.get("size", 0) or 0 for f in display_files),
                    "duration": duration,
                    "extension": dominant_ext,
                    "lossless": dominant_ext in LOSSLESS_EXTS,
                    "bitrate": bitrate,
                    "sample_rate": sample_rate,
                    "bit_depth": bit_depth,
                    "files": [
                        {"filename": f.get("filename", ""), "size": f.get("size", 0) or 0}
                        for f in display_files
                    ],
                }
            )

    return albums


def _deduplicate(albums: list[dict]) -> list[dict]:
    """Keep the best copy of each album, merging in better metadata as we go."""
    best: dict[str, dict] = {}
    for album in albums:
        key = f"{normalize_folder(album['folder_name'])}::{album['extension']}"
        current = best.get(key)
        if current is None:
            best[key] = album
            continue

        # Prefer the copy most likely to transfer well and sound best.
        better = (album["bitrate"] or 0) > (current["bitrate"] or 0) or (
            album["free_slots"] and not current["free_slots"]
        )
        if better:
            album["artist_guess"] = album["artist_guess"] or current["artist_guess"]
            best[key] = album
            current = album
        elif " - " not in album["folder_name"] and " - " in current["folder_name"]:
            # A bare album title reads better than "Artist - Album".
            current["folder_name"] = album["folder_name"]

        if not current["artist_guess"] or current["artist_guess"].lower() in JUNK_NAMES:
            candidate = album["artist_guess"]
            if candidate and candidate.lower() not in JUNK_NAMES:
                current["artist_guess"] = candidate
        if current["year"] is None and album["year"] is not None:
            current["year"] = album["year"]
    return list(best.values())


@router.post("/")
async def start_search(body: SearchRequest):
    query = body.query.strip()
    if not query:
        raise HTTPException(400, "Search query is empty.")
    try:
        response = await slskd.request(
            "POST", "searches", json={"searchText": query, "fileLimit": 500}
        )
    except slskd.SlskdError as exc:
        raise HTTPException(502, exc.message) from exc

    if response.status_code not in (200, 201) or not response.content:
        raise HTTPException(502, "slskd would not start the search.")
    return {"search_id": response.json()["id"]}


@router.get("/{search_id}")
async def get_results(
    search_id: str,
    advanced: bool = Query(False, alias="raw"),
):
    try:
        responses = await slskd.get_json(
            f"searches/{search_id}/responses", default=[], timeout=30
        )
        state_payload = await slskd.get_json(f"searches/{search_id}", default={}, timeout=10)
    except slskd.SlskdError as exc:
        # The UI polls this; report the failure instead of pretending to search.
        return {"state": "Errored", "albums": [], "total": 0, "error": exc.message}

    state = (state_payload or {}).get("state", "") if isinstance(state_payload, dict) else ""
    albums = _build_albums(responses or [], advanced)

    if advanced:
        albums.sort(key=lambda a: (-a["upload_speed"], not a["free_slots"]))
        return {"state": state, "albums": albums, "total": len(albums)}

    popularity = Counter(
        f"{normalize_folder(a['folder_name'])}::{a['extension']}" for a in albums
    )
    artist_counts = Counter(
        a["artist_guess"]
        for a in albums
        if a["artist_guess"] and a["artist_guess"].lower() not in JUNK_NAMES
    )
    top_artist = artist_counts.most_common(1)[0][0] if artist_counts else ""
    ranks = await deezer_album_ranks(top_artist)

    albums = _deduplicate(albums)
    albums.sort(
        key=lambda a: (
            not a["lossless"],
            ranks.get(normalize_folder(a["folder_name"]), 999),
            -popularity[f"{normalize_folder(a['folder_name'])}::{a['extension']}"],
            -(a["bitrate"] or 0),
            not a["free_slots"],
            -a["upload_speed"],
        )
    )
    return {"state": state, "albums": albums, "total": len(albums)}


@router.delete("/{search_id}")
async def stop_search(search_id: str):
    try:
        await slskd.request("DELETE", f"searches/{search_id}", timeout=5)
    except slskd.SlskdError:
        pass  # The search stops on its own; nothing useful to report here.
    return {"ok": True}
