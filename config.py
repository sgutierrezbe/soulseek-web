import os
from pathlib import Path

_env_path = Path(__file__).parent / ".env"


def _read_env_file() -> dict:
    """Parse key=value pairs from the .env file, if it exists."""
    values: dict = {}
    if _env_path.exists():
        for line in _env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def _get(key: str, default: str = "") -> str:
    result = _read_env_file().get(key)
    if result is not None:
        return result
    return os.getenv(key, default)


SLSKD_URL = _get("SLSKD_URL", "http://localhost:5030")
SLSKD_API_KEY = _get("SLSKD_API_KEY", "")
MUSIC_PATH = _get("MUSIC_PATH", "/mnt/music/downloads")


def setup_required() -> bool:
    """Return True when the API key has not been configured yet."""
    return not _get("SLSKD_API_KEY")


def save_config(url: str, api_key: str, music_path: str) -> None:
    """Persist config values to .env and update the in-memory globals."""
    try:
        lines = _env_path.read_text().splitlines() if _env_path.exists() else []
        updates = {"SLSKD_URL": url, "SLSKD_API_KEY": api_key, "MUSIC_PATH": music_path}
        result = []
        updated: set = set()
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k = stripped.partition("=")[0].strip()
                if k in updates:
                    result.append(f"{k}={updates[k]}")
                    updated.add(k)
                    continue
            result.append(line)
        for k, v in updates.items():
            if k not in updated:
                result.append(f"{k}={v}")
        _env_path.write_text("\n".join(result) + "\n")
    except OSError as exc:
        raise RuntimeError(f"Could not write configuration to {_env_path}: {exc}") from exc

    global SLSKD_URL, SLSKD_API_KEY, MUSIC_PATH
    SLSKD_URL = url
    SLSKD_API_KEY = api_key
    MUSIC_PATH = music_path
