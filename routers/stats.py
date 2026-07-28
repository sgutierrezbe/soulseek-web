"""Sharing statistics: what other users have taken from this library.

Live transfers come straight from slskd; lifetime totals come from the
aggregate in `stats.py`, which survives slskd clearing its own history.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

import slskd
from cache import metadata
from stats import stats

router = APIRouter()

POLL_SECONDS = 30


def _flatten_uploads(user_groups: list[dict]) -> list[dict]:
    """slskd nests uploads user -> directory -> file; we want a flat list."""
    flat = []
    for group in user_groups or []:
        username = group.get("username", "")
        for directory in group.get("directories", []):
            for file in directory.get("files", []):
                flat.append({**file, "username": file.get("username") or username})
    return flat


async def fetch_uploads(include_removed: bool = True) -> list[dict]:
    payload = await slskd.get_json(
        "transfers/uploads",
        default=[],
        params={"includeRemoved": str(include_removed).lower()},
        timeout=10,
    )
    return _flatten_uploads(payload)


async def ingest_once() -> int:
    """Sample slskd's upload list and fold new completions into the aggregate."""
    uploads = await fetch_uploads()
    added = stats.record(uploads)
    if added:
        await asyncio.to_thread(stats.save)
    return added


async def poller() -> None:
    """Background loop. Failures are ignored -- slskd may simply be down."""
    while True:
        try:
            await ingest_once()
        except (slskd.SlskdError, asyncio.TimeoutError):
            pass
        except Exception:
            pass
        try:
            await asyncio.sleep(POLL_SECONDS)
        except asyncio.CancelledError:
            # Flush before shutdown so the last samples aren't lost.
            await asyncio.to_thread(stats.save, True)
            raise


@router.get("/uploads")
async def upload_stats(top: int = Query(10, ge=1, le=50), days: int = Query(30, ge=7, le=365)):
    """Lifetime sharing totals, leaderboards and a daily timeline."""
    # Ingest opportunistically too, so the numbers are fresh on open even if the
    # poller has not ticked since the last upload finished.
    try:
        await ingest_once()
    except slskd.SlskdError:
        pass
    return stats.summary(top=top, days=days)


@router.get("/uploads/active")
async def active_uploads():
    """Transfers other users are pulling from us right now."""
    try:
        uploads = await fetch_uploads(include_removed=False)
    except slskd.SlskdError as exc:
        raise HTTPException(502, exc.message) from exc

    active = []
    for transfer in uploads:
        state = transfer.get("state", "")
        if "Completed" in state:
            continue
        filename = str(transfer.get("filename", "")).replace("\\", "/")
        active.append(
            {
                "username": transfer.get("username", ""),
                "filename": filename.split("/")[-1],
                "folder": filename.split("/")[-2] if "/" in filename else "",
                "state": state,
                "percent": transfer.get("percentComplete", 0) or 0,
                "size": transfer.get("size", 0) or 0,
                "speed": transfer.get("averageSpeed", 0) or 0,
                "queue_position": transfer.get("placeInQueue"),
            }
        )
    active.sort(key=lambda t: (-t["speed"], t["username"]))
    return active


@router.get("/shares")
async def share_stats():
    """What this instance is offering to the network."""
    cached = metadata.get("shares")
    if cached is not None:
        return cached

    try:
        hosts = await slskd.get_json("shares", default={}, timeout=10)
    except slskd.SlskdError as exc:
        raise HTTPException(502, exc.message) from exc

    shares = []
    for host_name, host_shares in (hosts or {}).items():
        for share in host_shares or []:
            if share.get("isExcluded"):
                continue
            shares.append(
                {
                    "host": host_name,
                    "alias": share.get("alias") or share.get("remotePath") or "",
                    "path": share.get("localPath", ""),
                    "directories": share.get("directories") or 0,
                    "files": share.get("files") or 0,
                }
            )

    result = {
        "shares": shares,
        "directories": sum(s["directories"] for s in shares),
        "files": sum(s["files"] for s in shares),
    }
    metadata.set("shares", result, ttl=300)
    return result


@router.delete("/uploads")
async def reset_stats():
    """Clear the accumulated history and start counting again."""
    stats.reset()
    return {"ok": True}
