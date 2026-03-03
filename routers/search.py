from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx
import re
from config import SLSKD_URL, SLSKD_API_KEY
from collections import defaultdict, Counter


def normalize_folder(name: str) -> str:
    """Normaliza el nombre de carpeta para contar popularidad correctamente.
    Elimina años, tags de formato y calidad para agrupar variantes del mismo álbum."""
    name = re.sub(r'[\(\[]\s*(?:19|20)\d{2}\s*[\)\]]', '', name)   # (2025), [2021]
    name = re.sub(r'\[.*?\]', '', name)                              # [FLAC], [320kbps]
    name = re.sub(
        r'\b(FLAC|MP3|AAC|OGG|OPUS|WAV|WEB|CDRip|Vinyl|Lossless|'
        r'24bit|16bit|320|256|192|kbps|CBR|VBR|Hi[\-\s]?Res)\b',
        '', name, flags=re.IGNORECASE
    )
    # Quitar prefijo "Artista - " si el álbum lo tiene
    if ' - ' in name:
        name = name.split(' - ', 1)[-1]
    return re.sub(r'\s+', ' ', name).strip(' -_.').lower()


JUNK_NAMES = {"albumes", "albums", "música", "musica", "downloads", "descargas",
              "music", "mp3", "flac", "various", "various artists", "va", "mixed"}

async def get_deezer_album_ranks(query: str) -> dict[str, int]:
    """Consulta Deezer y devuelve {nombre_normalizado: posición} (0 = más popular)."""
    if not query:
        return {}
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=True) as deezer:
            resp = await deezer.get(
                "https://api.deezer.com/search/album",
                params={"q": query, "limit": 50}
            )
            data = resp.json().get("data", [])
            return {normalize_folder(a.get("title", "")): i for i, a in enumerate(data)}
    except Exception:
        return {}


router = APIRouter()
HEADERS = {"X-API-Key": SLSKD_API_KEY}

class SearchRequest(BaseModel):
    query: str

@router.post("/")
async def search(body: SearchRequest):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{SLSKD_URL}/api/v0/searches",
                headers=HEADERS,
                json={"searchText": body.query, "fileLimit": 500}
            )
            if resp.status_code != 200 or not resp.content:
                raise HTTPException(500, "Error iniciando búsqueda")
            return {"search_id": resp.json()["id"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"No se pudo conectar a slskd: {e}")

@router.get("/{search_id}")
async def get_results(search_id: str, raw: bool = False):
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{SLSKD_URL}/api/v0/searches/{search_id}/responses",
                headers=HEADERS
            )
            if resp.status_code != 200 or not resp.content:
                return {"state": "Searching", "albums": [], "total": 0}

            responses = resp.json()

            state_resp = await client.get(
                f"{SLSKD_URL}/api/v0/searches/{search_id}",
                headers=HEADERS
            )
            state = state_resp.json().get("state", "") if state_resp.content else ""

        albums = []

        for response in responses:
            username = response["username"]
            upload_speed = response.get("uploadSpeed", 0)
            queue_length = response.get("queueLength", 0)
            free_slots = response.get("hasFreeUploadSlot", False)

            folders = defaultdict(list)
            for file in response.get("files", []):
                fname = file["filename"]
                if "\\" in fname:
                    folder = fname.rsplit("\\", 1)[0]
                else:
                    folder = fname.rsplit("/", 1)[0]
                folders[folder].append(file)

            for folder_path, files in folders.items():
                audio_files = [f for f in files if f["filename"].split(".")[-1].lower()
                               in {"mp3", "flac", "ogg", "aac", "opus", "m4a", "wav"}]

                if raw:
                    # Raw mode: include every folder, use all files for display
                    display_files = files if files else []
                    if not display_files:
                        continue
                    # Use audio_files if any, otherwise all files
                    count_files = audio_files if audio_files else files
                else:
                    if not audio_files:
                        continue
                    if len(audio_files) < 2:
                        continue
                    display_files = audio_files
                    count_files = audio_files

                exts = [f["filename"].split(".")[-1].upper() for f in count_files]
                ext_counts = defaultdict(int)
                for e in exts:
                    ext_counts[e] += 1
                dominant_ext = max(ext_counts, key=ext_counts.get) if ext_counts else "?"

                bitrate = next((f.get("bitRate") for f in count_files if f.get("bitRate")), None)
                sample_rate = next((f.get("sampleRate") for f in count_files if f.get("sampleRate")), None)
                bit_depth = next((f.get("bitDepth") for f in count_files if f.get("bitDepth")), None)

                total_size = sum(f.get("size", 0) for f in display_files)

                folder_name = folder_path.split("\\")[-1] if "\\" in folder_path else folder_path.split("/")[-1]
                if not raw:
                    folder_name = re.sub(r'^(\s*\[[^\]]*\]\s*)+', '', folder_name).strip()

                parts = folder_path.replace("\\", "/").split("/")
                artist_guess = parts[-2] if len(parts) >= 2 else ""

                albums.append({
                    "username": username,
                    "upload_speed": upload_speed,
                    "queue_length": queue_length,
                    "free_slots": free_slots,
                    "folder_path": folder_path,
                    "folder_name": folder_name,
                    "artist_guess": artist_guess,
                    "track_count": len(count_files),
                    "total_size": total_size,
                    "extension": dominant_ext,
                    "bitrate": bitrate,
                    "sample_rate": sample_rate,
                    "bit_depth": bit_depth,
                    "files": [{"filename": f["filename"], "size": f.get("size", 0)} for f in display_files],
                })

        # ── Raw mode: no dedup, no Deezer, just sort by speed ────────────────
        if raw:
            albums.sort(key=lambda x: (-x["upload_speed"], not x["free_slots"]))
            return {"state": state, "albums": albums, "total": len(albums)}

        # ── Smart mode: dedup + Deezer ranking ───────────────────────────────
        popularity = Counter(normalize_folder(a["folder_name"]) + "::" + a["extension"] for a in albums)

        artist_counts = Counter(
            a["artist_guess"] for a in albums
            if a["artist_guess"] and a["artist_guess"].lower() not in JUNK_NAMES
        )
        top_artist = artist_counts.most_common(1)[0][0] if artist_counts else ""
        deezer_ranks = await get_deezer_album_ranks(top_artist)

        seen = {}
        for album in albums:
            key = normalize_folder(album["folder_name"]) + "::" + album["extension"]
            if key not in seen:
                seen[key] = album
            else:
                current = seen[key]
                better_quality = (
                    (album["bitrate"] or 0) > (current["bitrate"] or 0) or
                    (album["free_slots"] and not current["free_slots"])
                )
                if better_quality:
                    seen[key] = album
                else:
                    if " - " not in album["folder_name"] and " - " in current["folder_name"]:
                        seen[key]["folder_name"] = album["folder_name"]
                if not current["artist_guess"] or current["artist_guess"].lower() in JUNK_NAMES:
                    if album["artist_guess"] and album["artist_guess"].lower() not in JUNK_NAMES:
                        seen[key]["artist_guess"] = album["artist_guess"]

        albums = list(seen.values())

        albums.sort(key=lambda x: (
            x["extension"] != "FLAC",
            deezer_ranks.get(normalize_folder(x["folder_name"]), 999),
            -popularity[normalize_folder(x["folder_name"]) + "::" + x["extension"]],
            -(x["bitrate"] or 0),
            not x["free_slots"],
            -x["upload_speed"]
        ))

        return {
            "state": state,
            "albums": albums,
            "total": len(albums)
        }
    except Exception:
        return {"state": "Searching", "albums": [], "total": 0}

@router.delete("/{search_id}")
async def stop_search(search_id: str):
    async with httpx.AsyncClient() as client:
        await client.delete(
            f"{SLSKD_URL}/api/v0/searches/{search_id}",
            headers=HEADERS
        )
    return {"ok": True}