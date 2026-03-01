from fastapi import APIRouter
from pydantic import BaseModel
import json
import os
import httpx

CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "credentials.json")

router = APIRouter()


def load_credentials() -> dict:
    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def get_active_credentials() -> dict:
    """Return credentials, preferring env vars over saved file."""
    creds = load_credentials()
    return {
        "slskd_url": os.getenv("SLSKD_URL") or creds.get("slskd_url", ""),
        "slskd_api_key": os.getenv("SLSKD_API_KEY") or creds.get("slskd_api_key", ""),
    }


@router.get("/status")
async def get_status():
    creds = get_active_credentials()
    configured = bool(creds["slskd_url"] and creds["slskd_api_key"])
    return {"configured": configured}


class CredentialsRequest(BaseModel):
    slskd_url: str
    slskd_api_key: str


@router.post("/credentials")
async def save_credentials(body: CredentialsRequest):
    url = body.slskd_url.rstrip("/")
    # Validate the credentials by hitting the slskd API
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{url}/api/v0/application",
                headers={"X-API-Key": body.slskd_api_key},
            )
            if resp.status_code not in (200, 204):
                return {"ok": False, "error": "Could not connect to slskd. Check the URL and API key."}
    except Exception as exc:
        return {"ok": False, "error": f"Could not reach slskd: {exc}"}

    with open(CREDENTIALS_FILE, "w") as f:
        json.dump({"slskd_url": url, "slskd_api_key": body.slskd_api_key}, f)

    # Update the config module so all routers see the new values immediately
    import config as cfg
    cfg.SLSKD_URL = url
    cfg.SLSKD_API_KEY = body.slskd_api_key

    return {"ok": True}
