import asyncio
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

from . import librespot_session
from .auth import librespot_router
from .auth import router as auth_router
from .config import settings
from .spotify import spotify

app = FastAPI(title="Apricot Library Sidecar")
app.include_router(auth_router)
app.include_router(librespot_router)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9 _\-().,'&!]")


def _safe(name: str) -> str:
    return _SAFE_NAME.sub("_", name).strip() or "Unknown"


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/search")
async def search(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=50),
) -> dict:
    tracks = await spotify.search_tracks(q, limit=limit)
    return {"query": q, "count": len(tracks), "tracks": tracks}


@app.post("/download/{track_id}")
async def download(track_id: str) -> dict:
    tracks = await spotify.search_tracks(f"track:{track_id}", limit=1)
    meta = next((t for t in tracks if t["id"] == track_id), None)
    if meta is None:
        full = await spotify.search_tracks(track_id, limit=5)
        meta = next((t for t in full if t["id"] == track_id), None)
    if meta is None:
        raise HTTPException(404, f"Track {track_id} not found via Spotify search")

    artist = _safe(meta["artists"][0] if meta["artists"] else "Unknown")
    album = _safe(meta["album"] or "Unknown")
    name = _safe(meta["name"] or track_id)
    output_path = Path(settings.media_path) / artist / album / f"{name}.ogg"

    await asyncio.to_thread(librespot_session.download_track, track_id, output_path)

    return {
        "status": "downloaded",
        "track_id": track_id,
        "path": str(output_path.relative_to(settings.media_path)),
        "metadata": meta,
    }
