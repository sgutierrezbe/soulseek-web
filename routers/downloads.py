from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx
import os
import shutil
from config import SLSKD_URL, SLSKD_API_KEY, MUSIC_PATH

router = APIRouter()
HEADERS = {"X-API-Key": SLSKD_API_KEY}


class DownloadRequest(BaseModel):
    username: str
    filename: str
    size: int


class DownloadFolderRequest(BaseModel):
    username: str
    files: list[dict]


class DeleteFolderRequest(BaseModel):
    username: str
    file_ids: list[str]
    local_paths: list[str]   # slskd localFilename — may be empty for completed transfers
    folder_name: str = ""    # remote folder name, used to find files on disk as fallback
    filenames: list[str] = []  # display filenames inside the folder


def _group_state(files: list[dict]) -> str:
    """Compute a single summary state for a group of files."""
    states = [f["state"] for f in files]
    if any("InProgress" in s for s in states):
        return "InProgress"
    if any("Errored" in s for s in states):
        return "Errored"
    if any("Requested" in s or "Queued" in s for s in states):
        return "Queued"
    if all("Completed" in s for s in states):
        return "Completed"
    return states[0] if states else "Unknown"


def _group_progress(files: list[dict]) -> float:
    """Weighted average progress across all files in a group."""
    total_size = sum(f["size"] for f in files)
    if total_size == 0:
        percs = [f["percent"] for f in files]
        return sum(percs) / len(percs) if percs else 0
    weighted = sum(f["size"] * f["percent"] for f in files)
    return weighted / total_size


@router.post("/")
async def start_download(body: DownloadRequest):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SLSKD_URL}/api/v0/transfers/downloads/{body.username}",
            headers=HEADERS,
            json=[{"filename": body.filename, "size": body.size}]
        )
        if resp.status_code not in (200, 201):
            raise HTTPException(500, f"Error: {resp.text}")
    return {"ok": True, "filename": body.filename}


@router.post("/folder")
async def download_folder(body: DownloadFolderRequest):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SLSKD_URL}/api/v0/transfers/downloads/{body.username}",
            headers=HEADERS,
            json=[{"filename": f["filename"], "size": f["size"]} for f in body.files]
        )
        if resp.status_code not in (200, 201):
            raise HTTPException(500, f"Error: {resp.text}")
    return {"ok": True, "count": len(body.files)}


@router.get("/")
async def get_downloads():
    """Return downloads grouped by remote folder (one entry per album/folder)."""
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                f"{SLSKD_URL}/api/v0/transfers/downloads",
                headers=HEADERS
            )
            if resp.status_code not in (200, 201) or not resp.content:
                return []

            groups: dict[str, dict] = {}

            for user_group in resp.json():
                username = user_group["username"]
                for directory in user_group.get("directories", []):
                    raw_dir = directory.get("directory", "")
                    # Normalize path separators and extract folder name
                    norm_dir = raw_dir.replace("\\", "/")
                    folder_name = norm_dir.rstrip("/").split("/")[-1] or norm_dir

                    key = f"{username}::{raw_dir}"
                    if key not in groups:
                        groups[key] = {
                            "username": username,
                            "directory": raw_dir,
                            "folder_name": folder_name,
                            "files": [],
                        }

                    for file in directory.get("files", []):
                        norm_fname = file["filename"].replace("\\", "/")
                        display_name = norm_fname.split("/")[-1]
                        groups[key]["files"].append({
                            "filename": display_name,
                            "full_path": file["filename"],
                            "local_path": file.get("localFilename", ""),
                            "file_id": file.get("id", ""),
                            "state": file["state"],
                            "percent": file.get("percentComplete", 0),
                            "size": file.get("size", 0),
                            "speed": file.get("averageSpeed", 0),
                        })

            result = []
            for g in groups.values():
                g["state"] = _group_state(g["files"])
                g["progress"] = _group_progress(g["files"])
                g["total_size"] = sum(f["size"] for f in g["files"])
                g["speed"] = sum(f["speed"] for f in g["files"] if f["speed"])
                g["file_ids"] = [f["file_id"] for f in g["files"] if f["file_id"]]
                g["local_paths"] = [f["local_path"] for f in g["files"] if f["local_path"]]
                result.append(g)

            return result
    except Exception:
        return []


@router.delete("/folder")
async def delete_download_folder(body: DeleteFolderRequest):
    """Cancel all transfers in a folder and delete files from disk."""
    errors = []

    # 1. Cancel / remove transfers from slskd
    async with httpx.AsyncClient(timeout=10) as client:
        for file_id in body.file_ids:
            if not file_id:
                continue
            try:
                await client.delete(
                    f"{SLSKD_URL}/api/v0/transfers/downloads/{body.username}/{file_id}",
                    headers=HEADERS,
                    params={"remove": "true"},
                )
            except Exception as e:
                errors.append(str(e))

    # 2. Build the set of paths to delete
    #    Priority: explicit local_paths from slskd > reconstruct from music_path
    paths_to_delete: list[str] = [p for p in body.local_paths if p]

    # Fallback: search music_path for a folder matching folder_name
    if body.folder_name:
        # Try exact match first
        candidate = os.path.join(MUSIC_PATH, body.folder_name)
        if os.path.isdir(candidate):
            # Delete the entire directory tree directly
            try:
                shutil.rmtree(candidate)
                return {"ok": True, "errors": errors}
            except Exception as e:
                errors.append(str(e))
        else:
            # Search recursively (depth 1) for the folder
            try:
                for entry in os.scandir(MUSIC_PATH):
                    if entry.is_dir() and entry.name == body.folder_name:
                        shutil.rmtree(entry.path)
                        return {"ok": True, "errors": errors}
            except Exception:
                pass

        # If no folder found, reconstruct per-file paths from music_path + folder + filename
        if not paths_to_delete and body.filenames:
            for fname in body.filenames:
                p = os.path.join(MUSIC_PATH, body.folder_name, fname)
                if os.path.isfile(p):
                    paths_to_delete.append(p)

    # 3. Delete individual files
    deleted_dirs: set[str] = set()
    for path in paths_to_delete:
        try:
            if os.path.isfile(path):
                os.remove(path)
                deleted_dirs.add(os.path.dirname(path))
        except Exception as e:
            errors.append(str(e))

    # 4. Remove parent folder if now empty
    for folder in deleted_dirs:
        try:
            remaining = [
                f for f in os.listdir(folder)
                if f not in {".incomplete", ".DS_Store", "Thumbs.db"}
            ]
            if not remaining:
                shutil.rmtree(folder, ignore_errors=True)
        except Exception:
            pass

    return {"ok": True, "errors": errors}


@router.delete("/{username}/{file_id}")
async def cancel_download(username: str, file_id: str):
    async with httpx.AsyncClient() as client:
        await client.delete(
            f"{SLSKD_URL}/api/v0/transfers/downloads/{username}/{file_id}",
            headers=HEADERS
        )
    return {"ok": True}