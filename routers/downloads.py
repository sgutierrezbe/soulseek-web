from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx
from config import SLSKD_URL, SLSKD_API_KEY

router = APIRouter()
HEADERS = {"X-API-Key": SLSKD_API_KEY}


class DownloadRequest(BaseModel):
    username: str
    filename: str
    size: int


class DownloadFolderRequest(BaseModel):
    username: str
    files: list[dict]


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
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SLSKD_URL}/api/v0/transfers/downloads",
            headers=HEADERS
        )
        downloads = []
        for user_group in resp.json():
            for directory in user_group.get("directories", []):
                for file in directory.get("files", []):
                    downloads.append({
                        "username": user_group["username"],
                        "filename": file["filename"].split("\\")[-1],
                        "full_path": file["filename"],
                        "state": file["state"],
                        "percent": file.get("percentComplete", 0),
                        "size": file.get("size", 0),
                        "speed": file.get("averageSpeed", 0),
                    })
        return downloads


@router.delete("/{username}/{file_id}")
async def cancel_download(username: str, file_id: str):
    async with httpx.AsyncClient() as client:
        await client.delete(
            f"{SLSKD_URL}/api/v0/transfers/downloads/{username}/{file_id}",
            headers=HEADERS
        )
    return {"ok": True}