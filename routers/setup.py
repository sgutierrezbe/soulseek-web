from fastapi import APIRouter
from pydantic import BaseModel
import json
import os
import time
import httpx
import subprocess

CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "credentials.json")
LOCAL_SETUP_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "local_setup.json")

router = APIRouter()


# ── helpers ───────────────────────────────────────────────────────────────────

def load_credentials() -> dict:
    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_local_setup() -> dict:
    """Config generada por install.ps1 en instalaciones Windows autónomas."""
    if os.path.exists(LOCAL_SETUP_FILE):
        try:
            with open(LOCAL_SETUP_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def get_active_credentials() -> dict:
    creds = load_credentials()
    local = load_local_setup()
    return {
        "slskd_url":     os.getenv("SLSKD_URL")     or creds.get("slskd_url")     or local.get("slskd_url", ""),
        "slskd_api_key": os.getenv("SLSKD_API_KEY") or creds.get("slskd_api_key") or local.get("slskd_api_key", ""),
        "music_path":    os.getenv("MUSIC_PATH")    or creds.get("music_path")    or local.get("default_music_path", ""),
    }


def _apply_to_modules(url: str, api_key: str, music_path: str):
    import config as cfg
    cfg.SLSKD_URL     = url
    cfg.SLSKD_API_KEY = api_key
    cfg.MUSIC_PATH    = music_path
    import routers.search as sr
    import routers.downloads as dr
    sr.HEADERS = {"X-API-Key": api_key}
    dr.HEADERS = {"X-API-Key": api_key}


# ── GET /api/setup/status ─────────────────────────────────────────────────────

@router.get("/status")
async def get_status():
    creds      = get_active_credentials()
    local      = load_local_setup()
    configured = bool(creds["slskd_url"] and creds["slskd_api_key"])
    return {
        "configured":  configured,
        "local_setup": bool(local),
        "slskd_url":   creds["slskd_url"],
        "music_path":  creds["music_path"] or local.get("default_music_path", ""),
    }


# ── POST /api/setup/credentials  (modo remoto) ────────────────────────────────

class CredentialsRequest(BaseModel):
    slskd_url:    str
    slskd_api_key: str
    music_path:   str = ""


@router.post("/credentials")
async def save_credentials(body: CredentialsRequest):
    url = body.slskd_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{url}/api/v0/application",
                headers={"X-API-Key": body.slskd_api_key},
            )
            if resp.status_code not in (200, 204):
                return {"ok": False, "error": "No se pudo conectar a slskd. Verificá la URL y el API key."}
    except Exception as exc:
        return {"ok": False, "error": f"No se pudo alcanzar slskd: {exc}"}

    saved = {
        "slskd_url":    url,
        "slskd_api_key": body.slskd_api_key,
        "music_path":   body.music_path.strip() or "/mnt/music/downloads",
    }
    with open(CREDENTIALS_FILE, "w") as f:
        json.dump(saved, f, indent=2)

    _apply_to_modules(saved["slskd_url"], saved["slskd_api_key"], saved["music_path"])
    return {"ok": True}


# ── POST /api/setup/soulseek  (modo local Windows) ───────────────────────────

class SoulseekRequest(BaseModel):
    soulseek_username: str
    soulseek_password: str
    music_path:        str = ""


@router.post("/soulseek")
async def save_soulseek(body: SoulseekRequest):
    local = load_local_setup()
    if not local:
        return {"ok": False, "error": "Este endpoint solo está disponible en instalación local."}

    slskd_config_path = local.get("slskd_config_path", "")
    slskd_url         = local.get("slskd_url", "http://localhost:5030")
    slskd_api_key     = local.get("slskd_api_key", "")
    music_path        = body.music_path.strip() or local.get("default_music_path", "")

    config_dir = os.path.dirname(slskd_config_path)
    if not slskd_config_path or not os.path.exists(config_dir):
        return {"ok": False, "error": f"No se encontró la carpeta de slskd: {config_dir}"}

    # Escribir slskd.yml con las credenciales de Soulseek del usuario
    music_path_fwd  = music_path.replace("\\", "/")
    incomplete_path = music_path_fwd.rstrip("/") + "/.incomplete"

    yml = f"""# Configuración generada por soulseek-web
soulseek:
  username: "{body.soulseek_username}"
  password: "{body.soulseek_password}"

web:
  port: 5030
  authentication:
    disabled: false
    api_keys:
      - name: soulseek-web
        key: "{slskd_api_key}"

directories:
  downloads: "{music_path_fwd}"
  incomplete: "{incomplete_path}"

shares:
  directories: []
"""
    try:
        with open(slskd_config_path, "w", encoding="utf-8") as f:
            f.write(yml)
    except Exception as exc:
        return {"ok": False, "error": f"No se pudo escribir la config de slskd: {exc}"}

    # Reiniciar slskd para que tome las nuevas credenciales
    slskd_exe_path = local.get("slskd_exe_path", "")
    try:
        # Matar proceso slskd existente
        subprocess.run(["taskkill", "/F", "/IM", "slskd.exe"], capture_output=True)
        time.sleep(1)
        # Relanzar en segundo plano si tenemos la ruta del ejecutable
        if slskd_exe_path and os.path.exists(slskd_exe_path):
            DETACHED = 0x00000008
            CREATE_NEW = 0x00000200
            subprocess.Popen(
                [slskd_exe_path, "--config", slskd_config_path],
                creationflags=DETACHED | CREATE_NEW,
                close_fds=True,
            )
    except Exception:
        pass  # En Linux falla silenciosamente, no es un problema

    # Esperar que slskd responda (hasta ~18 s)
    for attempt in range(6):
        await __import__("asyncio").sleep(3)
        try:
            async with httpx.AsyncClient(timeout=4) as client:
                r = await client.get(f"{slskd_url}/api/v0/application",
                                     headers={"X-API-Key": slskd_api_key})
                if r.status_code in (200, 204):
                    break
        except Exception:
            pass
    else:
        return {"ok": False, "error": "slskd no respondió tras reiniciar. Verificá que el programa esté instalado correctamente."}

    saved = {
        "slskd_url":    slskd_url,
        "slskd_api_key": slskd_api_key,
        "music_path":   music_path,
    }
    with open(CREDENTIALS_FILE, "w") as f:
        json.dump(saved, f, indent=2)

    _apply_to_modules(slskd_url, slskd_api_key, music_path)
    return {"ok": True}
