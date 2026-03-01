from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import config

router = APIRouter()


class SetupRequest(BaseModel):
    slskd_url: str
    slskd_api_key: str
    music_path: str


@router.get("/status")
async def get_setup_status():
    return {"setup_required": config.setup_required()}


@router.post("/")
async def do_setup(body: SetupRequest):
    if not body.slskd_api_key.strip():
        raise HTTPException(400, "API key is required")
    try:
        config.save_config(
            body.slskd_url.strip() or "http://localhost:5030",
            body.slskd_api_key.strip(),
            body.music_path.strip() or "/mnt/music/downloads",
        )
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc
    return {"ok": True}
