"""Runtime configuration for soulseek-web.

Everything the app can be reconfigured with lives on the single ``settings``
object below. Routers read ``settings.slskd_url`` (etc.) at call time instead of
importing the value once, so saving new credentials in the Settings panel takes
effect on the very next request -- no restart, no patching of module globals.

Precedence, highest first:
  1. environment variables  (SLSKD_URL, SLSKD_API_KEY, MUSIC_PATH, ...)
  2. local_setup.json       (written by install.ps1; slskd URL/key only)
  3. credentials.json       (written by the setup wizard)
  4. built-in defaults
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Writable state lives under CONFIG_DIR. It defaults to the source tree (so a
# git-clone install keeps working exactly as before) but Docker points it at a
# mounted volume, which keeps settings and the cover cache out of the image.
CONFIG_DIR = Path(os.getenv("CONFIG_DIR") or BASE_DIR)
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
CACHE_DIR = Path(os.getenv("CACHE_DIR") or CONFIG_DIR / ".cache")

# Written by install.ps1 next to the code, never by the app.
LOCAL_SETUP_FILE = BASE_DIR / "local_setup.json"
VERSION_FILE = BASE_DIR / "VERSION"

DEFAULT_SLSKD_URL = "http://localhost:5030"
DEFAULT_MUSIC_PATH = "/mnt/music/downloads"

IS_WINDOWS = sys.platform == "win32"
PLATFORM = "Windows" if IS_WINDOWS else "Linux"

_PBKDF2_ROUNDS = 200_000


def _read_json(path: Path, encoding: str = "utf-8") -> dict:
    try:
        with open(path, encoding=encoding) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Return ``(hash_hex, salt_hex)`` for a password using PBKDF2-HMAC-SHA256."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ROUNDS
    )
    return digest.hex(), salt


def verify_password(password: str, hash_hex: str, salt: str) -> bool:
    if not hash_hex or not salt:
        return False
    try:
        candidate, _ = hash_password(password, salt)
    except ValueError:
        return False
    return hmac.compare_digest(candidate, hash_hex)


class Settings:
    """Mutable, thread-safe application settings backed by credentials.json."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.reload()

    # ── loading ──────────────────────────────────────────────────────────────

    def reload(self) -> None:
        with self._lock:
            self._saved = _read_json(CREDENTIALS_FILE)
            # install.ps1 writes this file with a BOM
            self._local = _read_json(LOCAL_SETUP_FILE, encoding="utf-8-sig")

    @property
    def local_setup(self) -> bool:
        """True on a Windows standalone install that manages its own slskd."""
        return bool(self._local)

    @property
    def local(self) -> dict:
        """Contents of local_setup.json (slskd paths for a standalone install)."""
        return dict(self._local)

    # ── slskd connection ─────────────────────────────────────────────────────

    @property
    def slskd_url(self) -> str:
        # On a standalone install the bundled slskd's address is fixed and must
        # win over credentials.json, which may hold a stale remote address.
        url = (
            _env("SLSKD_URL")
            or (self._local.get("slskd_url", "") if self._local else "")
            or self._saved.get("slskd_url", "")
            or DEFAULT_SLSKD_URL
        )
        return url.rstrip("/")

    @property
    def slskd_api_key(self) -> str:
        return (
            _env("SLSKD_API_KEY")
            or (self._local.get("slskd_api_key", "") if self._local else "")
            or self._saved.get("slskd_api_key", "")
        )

    @property
    def music_path(self) -> str:
        return (
            _env("MUSIC_PATH")
            or self._saved.get("music_path", "")
            or self._local.get("default_music_path", "")
            or DEFAULT_MUSIC_PATH
        )

    @property
    def configured(self) -> bool:
        return bool(self.slskd_url and self.slskd_api_key)

    # ── UI preferences ───────────────────────────────────────────────────────

    @property
    def lang(self) -> str:
        return self._saved.get("lang", "en")

    @property
    def advanced_search(self) -> bool:
        return bool(self._saved.get("advanced_search", False))

    # ── optional authentication ──────────────────────────────────────────────

    @property
    def auth_enabled(self) -> bool:
        return bool(_env("AUTH_PASSWORD") or self._saved.get("auth_hash"))

    @property
    def auth_from_env(self) -> bool:
        """True when the password comes from AUTH_PASSWORD and the UI can't change it."""
        return bool(_env("AUTH_PASSWORD"))

    def check_password(self, password: str) -> bool:
        env_password = _env("AUTH_PASSWORD")
        if env_password:
            return hmac.compare_digest(password, env_password)
        return verify_password(
            password, self._saved.get("auth_hash", ""), self._saved.get("auth_salt", "")
        )

    @property
    def session_secret(self) -> str:
        """Stable per-install secret used to sign session cookies."""
        with self._lock:
            secret = _env("SESSION_SECRET") or self._saved.get("session_secret")
            if not secret:
                secret = secrets.token_hex(32)
                self.update(session_secret=secret)
            return secret

    # ── persistence ──────────────────────────────────────────────────────────

    def update(self, **values) -> None:
        """Merge ``values`` into credentials.json and apply them immediately."""
        with self._lock:
            data = _read_json(CREDENTIALS_FILE)
            for key, value in values.items():
                if value is None:
                    data.pop(key, None)
                else:
                    data[key] = value
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            # Write-then-rename so a crash mid-save can't truncate the file.
            tmp = CREDENTIALS_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(CREDENTIALS_FILE)
            self._saved = data

    def set_password(self, password: str) -> None:
        if password:
            digest, salt = hash_password(password)
            self.update(auth_hash=digest, auth_salt=salt)
        else:
            self.update(auth_hash=None, auth_salt=None)

    # ── misc ─────────────────────────────────────────────────────────────────

    @property
    def version(self) -> str:
        try:
            return VERSION_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            return "unknown"


settings = Settings()
