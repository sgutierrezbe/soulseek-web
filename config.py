import os
import json

_CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")

def _load_file_creds() -> dict:
    if os.path.exists(_CREDENTIALS_FILE):
        try:
            with open(_CREDENTIALS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

_file_creds = _load_file_creds()

SLSKD_URL = os.getenv("SLSKD_URL") or _file_creds.get("slskd_url", "http://localhost:5030")
SLSKD_API_KEY = os.getenv("SLSKD_API_KEY") or _file_creds.get("slskd_api_key", "")
MUSIC_PATH = os.getenv("MUSIC_PATH", "/mnt/music/downloads")
