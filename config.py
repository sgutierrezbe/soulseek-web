import os
import json

_CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")


def _load_saved() -> dict:
    if os.path.exists(_CREDENTIALS_FILE):
        try:
            with open(_CREDENTIALS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


_saved = _load_saved()

SLSKD_URL = os.getenv("SLSKD_URL") or _saved.get("slskd_url", "http://localhost:5030")
SLSKD_API_KEY = os.getenv("SLSKD_API_KEY") or _saved.get("slskd_api_key", "")
MUSIC_PATH = os.getenv("MUSIC_PATH") or _saved.get("music_path", "/mnt/music/downloads")
