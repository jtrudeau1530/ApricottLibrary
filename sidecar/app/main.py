from fastapi import FastAPI, HTTPException, Query

from .auth import router as auth_router
from .spotify import spotify

app = FastAPI(title="Apricot Library Sidecar")
app.include_router(auth_router)


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


@app.post("/download/{track_id}", status_code=501)
async def download(track_id: str) -> dict:
    raise HTTPException(
        status_code=501,
        detail="Download not yet implemented (Phase 4: OnTheSpot integration)",
    )
