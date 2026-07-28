"""Shared fixtures.

Environment is set before importing the app so `CONFIG_DIR` points at a
throwaway directory -- tests must never touch a real credentials.json.
"""

import math
import os
import struct
import sys
import tempfile
import wave
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

_CONFIG_DIR = Path(tempfile.mkdtemp(prefix="slskweb-config-"))
_MUSIC_DIR = Path(tempfile.mkdtemp(prefix="slskweb-music-"))

os.environ["CONFIG_DIR"] = str(_CONFIG_DIR)
os.environ["MUSIC_PATH"] = str(_MUSIC_DIR)
# A port with nothing listening: slskd-backed routes should fail cleanly.
os.environ["SLSKD_URL"] = "http://127.0.0.1:1"
os.environ["SLSKD_API_KEY"] = "test-key"
os.environ.pop("AUTH_PASSWORD", None)


def _write_wav(path: Path, seconds: float = 1.0, freq: int = 220) -> None:
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(
            b"".join(
                struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * t / 8000)))
                for t in range(int(8000 * seconds))
            )
        )


@pytest.fixture(scope="session")
def music_dir() -> Path:
    album = _MUSIC_DIR / "Aphex Twin" / "Selected Ambient Works"
    album.mkdir(parents=True, exist_ok=True)
    _write_wav(album / "01 Xtal.wav")
    _write_wav(album / "02 Tha.wav", freq=330)
    (album / "cover.jpg").write_bytes(b"\xff\xd8\xff" + b"\0" * 64)
    return _MUSIC_DIR


@pytest.fixture(scope="session")
def config_dir() -> Path:
    return _CONFIG_DIR


@pytest.fixture()
def client(music_dir):
    from fastapi.testclient import TestClient

    import main
    from config import settings

    settings.reload()
    with TestClient(main.app) as test_client:
        yield test_client
    # Leave auth disabled for the next test regardless of what a test did.
    settings.set_password("")
