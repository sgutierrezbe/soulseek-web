from fastapi import APIRouter
from fastapi.responses import FileResponse
from pathlib import Path
from config import MUSIC_PATH

router = APIRouter()

@router.get("/albums")
async def get_albums():
    base = Path(MUSIC_PATH)
    albums = []
    if not base.exists():
        return []
    for artist_dir in sorted(base.iterdir()):
        if not artist_dir.is_dir():
            continue
        for album_dir in sorted(artist_dir.iterdir()):
            if not album_dir.is_dir():
                continue
            files = list(album_dir.glob("**/*"))
            audio_files = [f for f in files if f.suffix.lower()
                          in {".mp3", ".flac", ".ogg", ".aac", ".opus", ".m4a"}]
            if not audio_files:
                continue
            cover = next((str(f) for f in files
                         if f.name.lower() in {"cover.jpg", "folder.jpg", "cover.png"}), None)
            albums.append({
                "artist": artist_dir.name,
                "album": album_dir.name,
                "track_count": len(audio_files),
                "has_cover": cover is not None,
                "cover_path": cover,
                "path": str(album_dir),
            })
    return albums
