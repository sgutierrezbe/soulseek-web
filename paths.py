"""Filesystem helpers for the downloads folder.

Every path the API touches is resolved and then checked to be inside the
configured music folder. Without this a crafted `folder_name` or `path` query
could read -- or delete -- files anywhere the server process can reach.
"""

from __future__ import annotations

from pathlib import Path

from config import settings

AUDIO_EXTS = {".mp3", ".flac", ".ogg", ".aac", ".opus", ".m4a", ".wav", ".aiff", ".ape", ".wv"}

COVER_NAMES = ("cover", "folder", "front", "album", "albumart")
COVER_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# Entries that don't count as "real" content when deciding if a folder is empty.
IGNORED_ENTRIES = {".incomplete", ".ds_store", "thumbs.db", "desktop.ini"}

MIME_BY_EXT = {
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".wav": "audio/wav",
    ".aiff": "audio/aiff",
    ".ape": "audio/x-ape",
    ".wv": "audio/x-wavpack",
}


def music_root() -> Path:
    """The configured downloads folder, resolved. May not exist yet."""
    return Path(settings.music_path).expanduser().resolve()


def is_within(candidate: Path, base: Path) -> bool:
    try:
        candidate.relative_to(base)
        return True
    except ValueError:
        return False


def resolve_within(*parts: str, base: Path | None = None) -> Path | None:
    """Join `parts` onto the music root, or None if the result escapes it.

    Symlinks are resolved before the check, so a symlink inside the music folder
    cannot be used to reach outside it.
    """
    root = base or music_root()
    cleaned = [str(p).replace("\\", "/").strip("/") for p in parts if p]
    if not cleaned:
        return root
    try:
        candidate = root.joinpath(*cleaned).resolve()
    except (OSError, ValueError):
        return None
    return candidate if is_within(candidate, root) else None


def find_album_folder(folder_name: str) -> Path | None:
    """Locate a downloaded album folder by name inside the music root.

    slskd stores downloads either directly under the downloads directory or one
    level deeper (artist/album), so both layouts are checked.
    """
    if not folder_name:
        return None
    leaf = folder_name.replace("\\", "/").rstrip("/").split("/")[-1]

    direct = resolve_within(leaf)
    if direct is not None and direct.is_dir():
        return direct

    root = music_root()
    if not root.is_dir():
        return None
    try:
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            if entry.name == leaf:
                return entry
            try:
                for child in entry.iterdir():
                    if child.is_dir() and child.name == leaf:
                        return child
            except OSError:
                continue
    except OSError:
        return None
    return None


def audio_files(folder: Path) -> list[Path]:
    try:
        return sorted(
            p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTS
        )
    except OSError:
        return []


def find_cover_file(folder: Path) -> Path | None:
    """Look for a cover image sitting alongside the audio files."""
    try:
        entries = [p for p in folder.iterdir() if p.is_file()]
    except OSError:
        return None
    by_name = {p.name.lower(): p for p in entries}
    for stem in COVER_NAMES:
        for ext in COVER_EXTS:
            hit = by_name.get(stem + ext)
            if hit is not None:
                return hit
    # Fall back to any image in the folder.
    for entry in entries:
        if entry.suffix.lower() in COVER_EXTS:
            return entry
    return None


def is_effectively_empty(folder: Path) -> bool:
    try:
        return not [p for p in folder.iterdir() if p.name.lower() not in IGNORED_ENTRIES]
    except OSError:
        return False
