"""Play and retrieve downloaded audio.

Range requests are honoured so the browser's <audio> element can seek without
pulling the whole file first -- which matters a lot for FLAC, where a single
track is routinely 40 MB.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

import paths

router = APIRouter()

_CHUNK_SIZE = 256 * 1024
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def _resolve_track(path: str) -> tuple[Path, int]:
    target = paths.resolve_within(path)
    if target is None or not target.is_file():
        raise HTTPException(404, "Track not found.")
    if target.suffix.lower() not in paths.AUDIO_EXTS:
        raise HTTPException(415, "Not an audio file.")
    return target, target.stat().st_size


def _parse_range(header: str, size: int) -> tuple[int, int] | None:
    """Return an inclusive (start, end) byte range, or None if unsatisfiable."""
    match = _RANGE_RE.fullmatch(header.strip())
    if not match:
        return None
    raw_start, raw_end = match.groups()
    if raw_start:
        start = int(raw_start)
        end = int(raw_end) if raw_end else size - 1
    elif raw_end:
        # "bytes=-500" means the final 500 bytes.
        start = max(size - int(raw_end), 0)
        end = size - 1
    else:
        return None
    end = min(end, size - 1)
    if start > end or start >= size:
        return None
    return start, end


def _iter_file(target: Path, start: int, end: int):
    remaining = end - start + 1
    with open(target, "rb") as handle:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/audio")
async def stream_audio(request: Request, path: str):
    target, size = _resolve_track(path)
    media_type = paths.MIME_BY_EXT.get(target.suffix.lower(), "application/octet-stream")
    common = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=3600",
    }

    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(target, media_type=media_type, headers=common)

    span = _parse_range(range_header, size)
    if span is None:
        return Response(
            status_code=416, headers={**common, "Content-Range": f"bytes */{size}"}
        )

    start, end = span
    return StreamingResponse(
        _iter_file(target, start, end),
        status_code=206,
        media_type=media_type,
        headers={
            **common,
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(end - start + 1),
        },
    )


@router.get("/download")
async def download_track(path: str):
    """Send a downloaded file to the browser as an attachment."""
    target, _ = _resolve_track(path)
    return FileResponse(
        target,
        media_type="application/octet-stream",
        filename=target.name,
        headers={"Cache-Control": "private, max-age=3600"},
    )
