"""First-run wizard, settings panel, and the in-app updater.

Two install shapes are supported. A *remote* install points at an slskd that
someone else is running, so the user supplies a URL and API key. A *local*
install (Windows, via install.ps1) ships its own slskd, so soulseek-web owns its
config file and only needs the user's Soulseek account.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import threading
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import slskd
from cache import metadata
from config import BASE_DIR, IS_WINDOWS, PLATFORM, settings

router = APIRouter()


# ── status & settings ────────────────────────────────────────────────────────


@router.get("/status")
async def get_status():
    return {
        "configured": settings.configured,
        "local_setup": settings.local_setup,
        "slskd_url": settings.slskd_url,
        "music_path": settings.music_path,
        "platform": PLATFORM,
        "lang": settings.lang,
        "advanced_search": settings.advanced_search,
        "auth_enabled": settings.auth_enabled,
        "version": settings.version,
    }


def _read_local_slskd_account() -> tuple[str, str]:
    """Read the Soulseek username/password out of the bundled slskd.yml."""
    config_path = settings.local.get("slskd_config_path", "")
    if not config_path or not os.path.exists(config_path):
        return "", ""
    try:
        with open(config_path, encoding="utf-8") as handle:
            content = handle.read()
    except OSError:
        return "", ""
    username = re.search(r'username:\s*"([^"]*)"', content)
    password = re.search(r'password:\s*"([^"]*)"', content)
    return (username.group(1) if username else "", password.group(1) if password else "")


@router.get("/settings")
async def get_settings():
    soulseek_username = ""
    soulseek_password = ""

    if settings.local_setup:
        soulseek_username, soulseek_password = await run_in_threadpool(
            _read_local_slskd_account
        )
    elif settings.configured:
        try:
            application = await slskd.ping()
            soulseek_username = application.get("server", {}).get("username", "")
        except slskd.SlskdError:
            pass

    return {
        "platform": PLATFORM,
        "local_setup": settings.local_setup,
        "slskd_url": settings.slskd_url,
        "slskd_api_key": settings.slskd_api_key,
        "music_path": settings.music_path,
        "soulseek_username": soulseek_username,
        "soulseek_password": soulseek_password,
        "advanced_search": settings.advanced_search,
        "lang": settings.lang,
        "auth_enabled": settings.auth_enabled,
    }


class PreferencesRequest(BaseModel):
    advanced_search: bool = False
    lang: str = "en"


@router.post("/preferences")
async def save_preferences(body: PreferencesRequest):
    lang = body.lang if body.lang in ("es", "en") else "en"
    settings.update(advanced_search=body.advanced_search, lang=lang)
    return {"ok": True}


# ── remote mode ──────────────────────────────────────────────────────────────


class CredentialsRequest(BaseModel):
    slskd_url: str
    slskd_api_key: str
    music_path: str = ""
    soulseek_username: str = ""
    soulseek_password: str = ""


class TestRequest(BaseModel):
    slskd_url: str
    slskd_api_key: str


@router.post("/test")
async def test_connection(body: TestRequest):
    """Check a slskd instance without saving anything."""
    try:
        application = await slskd.ping(body.slskd_url.rstrip("/"), body.slskd_api_key)
    except slskd.SlskdError as exc:
        return {"ok": False, "error": exc.message}
    server = application.get("server", {}) if isinstance(application, dict) else {}
    return {
        "ok": True,
        "version": application.get("version", "") if isinstance(application, dict) else "",
        "soulseek_username": server.get("username", ""),
        "connected": server.get("state", "") in ("Connected, LoggedIn", "Connected"),
    }


@router.post("/credentials")
async def save_credentials(body: CredentialsRequest):
    url = body.slskd_url.strip().rstrip("/")
    if not url:
        return {"ok": False, "error": "Enter the address of your slskd instance."}

    try:
        await slskd.ping(url, body.slskd_api_key)
    except slskd.SlskdError as exc:
        return {"ok": False, "error": exc.message}

    if body.soulseek_username and body.soulseek_password:
        try:
            await slskd.client().put(
                f"{url}/api/v0/application/user",
                headers={"X-API-Key": body.slskd_api_key},
                json={
                    "username": body.soulseek_username,
                    "password": body.soulseek_password,
                },
                timeout=10,
            )
        except Exception:
            # Not fatal: the connection itself works, only the account update failed.
            pass

    settings.update(
        slskd_url=url,
        slskd_api_key=body.slskd_api_key,
        music_path=body.music_path.strip() or settings.music_path,
    )
    metadata.clear()
    return {"ok": True}


# ── local (Windows standalone) mode ──────────────────────────────────────────


class SoulseekRequest(BaseModel):
    soulseek_username: str
    soulseek_password: str
    music_path: str = ""


# NOTE: `api_keys` is a mapping keyed by name, not a list. slskd silently
# ignores a list here, which leaves the API unauthenticated-but-unreachable.
_SLSKD_YML = """# Generated by soulseek-web -- edits here are overwritten on save.
soulseek:
  username: "{username}"
  password: "{password}"

web:
  port: {port}
  authentication:
    api_keys:
      soulseek-web:
        key: "{api_key}"
        role: administrator
        cidr: 0.0.0.0/0,::/0

directories:
  downloads: "{downloads}"
  incomplete: "{incomplete}"

shares:
  directories: []
"""


def _write_slskd_config(username: str, password: str, music_path: str) -> str | None:
    """Write slskd.yml and create the download folders. Returns an error string."""
    local = settings.local
    config_path = local.get("slskd_config_path", "")
    if not config_path or not os.path.isdir(os.path.dirname(config_path)):
        return f"slskd's config folder was not found: {os.path.dirname(config_path)}"

    downloads = music_path.replace("\\", "/").rstrip("/")
    port = str(local.get("slskd_url", "http://localhost:5030")).rsplit(":", 1)[-1] or "5030"
    try:
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write(
                _SLSKD_YML.format(
                    username=username,
                    password=password,
                    port=port,
                    api_key=local.get("slskd_api_key", ""),
                    downloads=downloads,
                    incomplete=f"{downloads}/.incomplete",
                )
            )
        os.makedirs(music_path, exist_ok=True)
        os.makedirs(os.path.join(music_path, ".incomplete"), exist_ok=True)
    except OSError as exc:
        return f"Could not write slskd's config: {exc}"
    return None


def _restart_slskd() -> None:
    exe = settings.local.get("slskd_exe_path", "")
    config_path = settings.local.get("slskd_config_path", "")
    try:
        subprocess.run(["taskkill", "/F", "/IM", "slskd.exe"], capture_output=True)
        time.sleep(1)
        if exe and os.path.exists(exe):
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            subprocess.Popen(
                [exe, "--config", config_path],
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
    except Exception:
        pass  # Non-Windows or no bundled slskd -- nothing to restart.


@router.post("/soulseek")
async def save_soulseek(body: SoulseekRequest):
    if not settings.local_setup:
        return {"ok": False, "error": "This endpoint is only available on a local install."}

    music_path = body.music_path.strip() or settings.music_path
    error = await run_in_threadpool(
        _write_slskd_config, body.soulseek_username, body.soulseek_password, music_path
    )
    if error:
        return {"ok": False, "error": error}

    settings.update(music_path=music_path)
    await run_in_threadpool(_restart_slskd)

    # slskd takes a while to come back up and log in to the Soulseek server.
    for _ in range(8):
        await asyncio.sleep(2.5)
        try:
            await slskd.ping()
            metadata.clear()
            return {"ok": True}
        except slskd.SlskdError:
            continue

    return {
        "ok": False,
        "error": "slskd did not respond after restarting. Check that it is installed correctly.",
    }


# ── version & update ─────────────────────────────────────────────────────────


def _git(*args: str, timeout: int = 60) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", *args], cwd=BASE_DIR, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except Exception as exc:
        return 1, str(exc)


@router.get("/version")
async def get_version():
    _, commit = await run_in_threadpool(_git, "rev-parse", "--short", "HEAD")
    return {
        "version": settings.version,
        "commit": commit if len(commit) <= 12 else "",
        "platform": PLATFORM,
    }


def _run_update() -> dict:
    code, pull_output = _git("pull", "--ff-only")
    if code != 0:
        return {"ok": False, "error": f"git pull failed: {pull_output[:400]}"}

    venv_pip = BASE_DIR / "venv" / ("Scripts" if IS_WINDOWS else "bin") / "pip"
    pip_command = (
        [str(venv_pip)] if venv_pip.exists() else [sys.executable, "-m", "pip"]
    )
    try:
        subprocess.run(
            [*pip_command, "install", "-q", "-r", str(BASE_DIR / "requirements.txt")],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except Exception as exc:
        return {"ok": False, "error": f"pip install failed: {exc}"}

    already_latest = "Already up to date" in pull_output or "Ya está actualizado" in pull_output
    return {
        "ok": True,
        "already_latest": already_latest,
        "pull_output": pull_output[:400],
    }


@router.post("/update")
async def do_update():
    """Pull the latest code and reinstall dependencies."""
    result = await run_in_threadpool(_run_update)
    if not result["ok"]:
        raise HTTPException(500, result["error"])

    settings.reload()
    already_latest = result["already_latest"]

    if not IS_WINDOWS and not already_latest:
        # Restart shortly after responding so the client sees the result first.
        def restart_service() -> None:
            time.sleep(1.5)
            try:
                subprocess.run(
                    ["systemctl", "restart", "soulseek-web"], capture_output=True, timeout=15
                )
            except Exception:
                pass

        threading.Thread(target=restart_service, daemon=True).start()

    return {
        "ok": True,
        "already_latest": already_latest,
        "version": settings.version,
        "pull_output": result["pull_output"],
        "needs_restart": IS_WINDOWS and not already_latest,
    }
