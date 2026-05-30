import asyncio
import logging
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query

from . import librespot_session
from .admin_provision import ensure_master_admin
from .auth import librespot_router
from .auth import router as spotify_auth_router
from .auth_routes import router as session_auth_router
from .config import settings
from .models import User
from .audio_routes import router as audio_router
from .catalog_routes import router as catalog_router
from .playlist_routes import router as playlist_router
from .queue_routes import router as queue_router
from .sessions import require_admin, require_session
from .spotify import spotify
from .sse_routes import router as sse_router

log = logging.getLogger("sidecar")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Running database migrations...")
    cfg = AlembicConfig(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "migrations"))
    await asyncio.to_thread(command.upgrade, cfg, "head")
    log.info("Migrations complete.")

    await ensure_master_admin()

    # Phase 2: start queue worker (added in Phase 2 — placeholder import guarded)
    try:
        from .queue_worker import start_worker  # noqa: WPS433

        app.state.queue_worker_task = asyncio.create_task(start_worker())
    except Exception as exc:  # pragma: no cover
        log.info("Queue worker not started: %s", exc)

    yield

    task = getattr(app.state, "queue_worker_task", None)
    if task is not None:
        task.cancel()


app = FastAPI(title="Apricot Library Sidecar", lifespan=lifespan)

# Public health (no auth)
public_router = APIRouter(prefix="/api", tags=["public"])


@public_router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


app.include_router(public_router)
app.include_router(session_auth_router)
app.include_router(queue_router)
app.include_router(sse_router)
app.include_router(catalog_router)
app.include_router(audio_router)
app.include_router(playlist_router)


# Authenticated wrappers around the existing Spotify + librespot routers.
# We mount them under /api so the frontend talks to a single base path,
# and gate every route with require_session.
api_router = APIRouter(prefix="/api", dependencies=[Depends(require_session)])
api_router.include_router(spotify_auth_router)
# librespot credential upload is admin-only — protect explicitly.
librespot_admin_router = APIRouter(dependencies=[Depends(require_admin)])
librespot_admin_router.include_router(librespot_router)
api_router.include_router(librespot_admin_router)


_SAFE_NAME = re.compile(r"[^A-Za-z0-9 _\-().,'&!]")


def _safe(name: str) -> str:
    return _SAFE_NAME.sub("_", name).strip() or "Unknown"


@api_router.get("/search")
async def search(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=50),
    _user: User = Depends(require_session),
) -> dict:
    tracks = await spotify.search_tracks(q, limit=limit)
    return {"query": q, "count": len(tracks), "tracks": tracks}


@api_router.post("/download/{track_id}")
async def download(track_id: str, _user: User = Depends(require_session)) -> dict:
    meta = await spotify.get_track(track_id)
    if meta is None:
        raise HTTPException(404, f"Track {track_id} not found on Spotify")

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


@api_router.get("/storage")
async def storage(_user: User = Depends(require_session)) -> dict:
    """Disk usage for the media volume — backs the home page storage widget."""
    total, used, free = shutil.disk_usage(settings.media_path)
    return {
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "percent_used": round(used * 100 / total, 2) if total else 0.0,
    }


app.include_router(api_router)
