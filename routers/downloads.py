"""Queue, monitor and remove downloads.

slskd reports transfers per user/directory; the UI wants one card per album, so
the per-file states are folded into a single summary state and a size-weighted
progress figure.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import paths
import slskd
from cache import covers as cover_cache

router = APIRouter()

# Ordered by precedence: an album with any file in progress reads as InProgress.
_STATE_PRECEDENCE = ("InProgress", "Errored", "Queued", "Requested", "Cancelled")


class DownloadRequest(BaseModel):
    username: str
    filename: str
    size: int


class DownloadFolderRequest(BaseModel):
    username: str
    files: list[dict]


class DeleteFolderRequest(BaseModel):
    username: str
    file_ids: list[str] = []
    local_paths: list[str] = []
    folder_name: str = ""
    filenames: list[str] = []
    delete_files: bool = True


def _group_state(files: list[dict]) -> str:
    states = [f.get("state", "") for f in files]
    for candidate in _STATE_PRECEDENCE:
        if any(candidate in state for state in states):
            return candidate
    if states and all("Completed" in state for state in states):
        return "Completed"
    return states[0] if states else "Unknown"


def _group_progress(files: list[dict]) -> float:
    total = sum(f.get("size", 0) for f in files)
    if total <= 0:
        percents = [f.get("percent", 0) for f in files]
        return sum(percents) / len(percents) if percents else 0.0
    return sum(f.get("size", 0) * f.get("percent", 0) for f in files) / total


@router.post("/")
async def start_download(body: DownloadRequest):
    try:
        response = await slskd.request(
            "POST",
            f"transfers/downloads/{body.username}",
            json=[{"filename": body.filename, "size": body.size}],
        )
    except slskd.SlskdError as exc:
        raise HTTPException(502, exc.message) from exc
    if response.status_code not in (200, 201):
        raise HTTPException(502, f"slskd refused the download: {response.text[:200]}")
    return {"ok": True, "filename": body.filename}


@router.post("/folder")
async def download_folder(body: DownloadFolderRequest):
    if not body.files:
        raise HTTPException(400, "No files to download.")
    payload = [
        {"filename": f["filename"], "size": f.get("size", 0)}
        for f in body.files
        if f.get("filename")
    ]
    try:
        response = await slskd.request(
            "POST", f"transfers/downloads/{body.username}", json=payload
        )
    except slskd.SlskdError as exc:
        raise HTTPException(502, exc.message) from exc
    if response.status_code not in (200, 201):
        raise HTTPException(502, f"slskd refused the download: {response.text[:200]}")
    return {"ok": True, "count": len(payload)}


@router.get("/")
async def get_downloads():
    """One entry per remote folder, with per-file detail nested inside."""
    try:
        user_groups = await slskd.get_json("transfers/downloads", default=[], timeout=8)
    except slskd.SlskdError as exc:
        raise HTTPException(502, exc.message) from exc

    groups: dict[str, dict] = {}
    for user_group in user_groups or []:
        username = user_group.get("username", "")
        for directory in user_group.get("directories", []):
            raw_dir = directory.get("directory", "")
            key = f"{username}::{raw_dir}"
            group = groups.setdefault(
                key,
                {
                    "id": key,
                    "username": username,
                    "directory": raw_dir,
                    "folder_name": raw_dir.replace("\\", "/").rstrip("/").split("/")[-1] or raw_dir,
                    "files": [],
                },
            )
            for file in directory.get("files", []):
                full_path = file.get("filename", "")
                group["files"].append(
                    {
                        "filename": full_path.replace("\\", "/").split("/")[-1],
                        "full_path": full_path,
                        "local_path": file.get("localFilename", "") or "",
                        "file_id": file.get("id", "") or "",
                        "state": file.get("state", "") or "",
                        "percent": file.get("percentComplete", 0) or 0,
                        "size": file.get("size", 0) or 0,
                        "speed": file.get("averageSpeed", 0) or 0,
                        "remaining": file.get("bytesRemaining", 0) or 0,
                    }
                )

    result = []
    for group in groups.values():
        files = group["files"]
        group["state"] = _group_state(files)
        group["progress"] = _group_progress(files)
        group["total_size"] = sum(f["size"] for f in files)
        group["speed"] = sum(f["speed"] for f in files if f["speed"])
        group["file_ids"] = [f["file_id"] for f in files if f["file_id"]]
        group["local_paths"] = [f["local_path"] for f in files if f["local_path"]]
        remaining = sum(f["remaining"] for f in files)
        group["eta"] = int(remaining / group["speed"]) if group["speed"] > 0 else None
        result.append(group)

    # Active transfers first, then queued, then everything finished.
    order = {"InProgress": 0, "Queued": 1, "Requested": 2, "Errored": 3}
    result.sort(key=lambda g: (order.get(g["state"], 4), g["folder_name"].lower()))
    return result


@router.post("/retry")
async def retry_download(body: DownloadRequest):
    """Re-queue a single file that errored out."""
    return await start_download(body)


@router.delete("/completed")
async def clear_completed():
    """Remove finished transfers from the slskd queue, leaving files on disk."""
    try:
        await slskd.request("DELETE", "transfers/downloads/all/completed", timeout=15)
    except slskd.SlskdError as exc:
        raise HTTPException(502, exc.message) from exc
    return {"ok": True}


def _delete_from_disk(request: DeleteFolderRequest) -> list[str]:
    """Delete an album's files, refusing anything outside the music folder."""
    errors: list[str] = []
    root = paths.music_root()

    folder = paths.find_album_folder(request.folder_name) if request.folder_name else None
    if folder is not None and paths.is_within(folder, root) and folder != root:
        try:
            shutil.rmtree(folder)
            return errors
        except OSError as exc:
            errors.append(str(exc))

    targets: list[Path] = []
    for raw in request.local_paths:
        if not raw:
            continue
        try:
            candidate = Path(raw).expanduser().resolve()
        except (OSError, ValueError):
            continue
        # slskd may run on another host, where its local paths mean nothing here.
        if paths.is_within(candidate, root):
            targets.append(candidate)

    if not targets and request.folder_name and request.filenames:
        for name in request.filenames:
            candidate = paths.resolve_within(request.folder_name, name)
            if candidate is not None and candidate.is_file():
                targets.append(candidate)

    touched_dirs: set[Path] = set()
    for target in targets:
        try:
            if target.is_file():
                target.unlink()
                touched_dirs.add(target.parent)
        except OSError as exc:
            errors.append(str(exc))

    for directory in touched_dirs:
        if (
            directory != root
            and paths.is_within(directory, root)
            and paths.is_effectively_empty(directory)
        ):
            shutil.rmtree(directory, ignore_errors=True)

    return errors


@router.delete("/folder")
async def delete_download_folder(body: DeleteFolderRequest):
    """Cancel every transfer in a folder and optionally delete it from disk."""
    errors: list[str] = []

    for file_id in body.file_ids:
        if not file_id:
            continue
        try:
            await slskd.request(
                "DELETE",
                f"transfers/downloads/{body.username}/{file_id}",
                params={"remove": "true"},
                timeout=10,
            )
        except slskd.SlskdError as exc:
            errors.append(exc.message)

    if body.delete_files:
        errors += await run_in_threadpool(_delete_from_disk, body)
        cover_cache.forget(f"folder::{body.folder_name.lower()}")

    return {"ok": True, "errors": errors}


@router.delete("/{username}/{file_id}")
async def cancel_download(username: str, file_id: str, remove: bool = True):
    try:
        await slskd.request(
            "DELETE",
            f"transfers/downloads/{username}/{file_id}",
            params={"remove": str(remove).lower()},
            timeout=10,
        )
    except slskd.SlskdError as exc:
        raise HTTPException(502, exc.message) from exc
    return {"ok": True}
