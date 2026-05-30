import asyncio
import logging
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import select, update

from . import librespot_session
from .config import settings
from .db import SessionLocal
from .models import FetchQueue
from .sse_hub import publish

log = logging.getLogger("queue_worker")

_SAFE_NAME = re.compile(r"[^A-Za-z0-9 _\-().,'&!]")
_POLL_INTERVAL_SECONDS = 2.0
_HEARTBEAT_INTERVAL_SECONDS = 5.0
_STALE_RUNNING_AGE_SECONDS = 60


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe(name: str) -> str:
    return _SAFE_NAME.sub("_", name).strip() or "Unknown"


async def _reset_stale_running() -> None:
    """On startup or periodically: rows stuck in 'running' with no recent heartbeat go back to queued."""
    cutoff = _utc_now() - timedelta(seconds=_STALE_RUNNING_AGE_SECONDS)
    async with SessionLocal() as db:
        await db.execute(
            update(FetchQueue)
            .where(FetchQueue.status == "running", FetchQueue.heartbeat_at < cutoff)
            .values(status="queued", started_at=None, heartbeat_at=None)
        )
        await db.execute(
            update(FetchQueue)
            .where(FetchQueue.status == "running", FetchQueue.heartbeat_at.is_(None))
            .values(status="queued", started_at=None)
        )
        await db.commit()


async def _claim_next() -> FetchQueue | None:
    async with SessionLocal() as db:
        result = await db.execute(
            select(FetchQueue)
            .where(FetchQueue.status == "queued")
            .order_by(FetchQueue.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        row.status = "running"
        row.started_at = _utc_now()
        row.heartbeat_at = _utc_now()
        row.attempts = (row.attempts or 0) + 1
        await db.commit()
        await db.refresh(row)
        return row


async def _mark_complete(item_id: str, output_path: Path) -> None:
    async with SessionLocal() as db:
        await db.execute(
            update(FetchQueue)
            .where(FetchQueue.id == item_id)
            .values(
                status="complete",
                progress=100,
                completed_at=_utc_now(),
                output_path=str(output_path),
                error_message=None,
            )
        )
        await db.commit()


async def _mark_failed(item_id: str, error: str) -> None:
    async with SessionLocal() as db:
        await db.execute(
            update(FetchQueue)
            .where(FetchQueue.id == item_id)
            .values(status="failed", error_message=error, completed_at=_utc_now())
        )
        await db.commit()


async def _heartbeat(item_id: str, progress: int) -> None:
    async with SessionLocal() as db:
        await db.execute(
            update(FetchQueue)
            .where(FetchQueue.id == item_id)
            .values(heartbeat_at=_utc_now(), progress=progress)
        )
        await db.commit()


async def _trigger_jellyfin_refresh() -> None:
    """Async refresh — fire-and-forget; we don't block on Jellyfin scan completion."""
    url = f"{settings.jellyfin_internal_url.rstrip('/')}/Library/Refresh"
    headers = {"X-Emby-Token": settings.jellyfin_api_key}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, headers=headers)
    except Exception as exc:  # pragma: no cover
        log.warning("Jellyfin refresh failed: %s", exc)


async def _emit_storage_update() -> None:
    try:
        total, used, _ = shutil.disk_usage(settings.media_path)
        await publish(
            "storage:update",
            {
                "total_bytes": total,
                "used_bytes": used,
                "percent_used": round(used * 100 / total, 2) if total else 0.0,
            },
        )
    except Exception as exc:  # pragma: no cover
        log.debug("Storage update emit failed: %s", exc)


async def _download_one(row: FetchQueue) -> None:
    log.info("Worker picked up %s — %s", row.id, row.track_name)
    await publish(
        "queue:running",
        {
            "id": row.id,
            "spotify_track_id": row.spotify_track_id,
            "track_name": row.track_name,
            "artist_name": row.artist_name,
        },
    )

    artist = _safe(row.artist_name)
    album = _safe(row.album_name or "Unknown")
    name = _safe(row.track_name or row.spotify_track_id)
    output_path = Path(settings.media_path) / artist / album / f"{name}.ogg"

    heartbeat_task: asyncio.Task | None = None

    async def _beat() -> None:
        progress = 0
        while True:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
            progress = min(progress + 10, 95)
            await _heartbeat(row.id, progress)
            await publish("queue:progress", {"id": row.id, "percent": progress})

    try:
        heartbeat_task = asyncio.create_task(_beat())
        await asyncio.to_thread(librespot_session.download_track, row.spotify_track_id, output_path)
        if heartbeat_task:
            heartbeat_task.cancel()
        await _mark_complete(row.id, output_path)
        await publish(
            "queue:complete",
            {"id": row.id, "output_path": str(output_path.relative_to(settings.media_path))},
        )
        # Best-effort Jellyfin notify + storage refresh.
        asyncio.create_task(_trigger_jellyfin_refresh())
        await _emit_storage_update()
    except Exception as exc:
        if heartbeat_task:
            heartbeat_task.cancel()
        log.exception("Download failed for %s", row.id)
        await _mark_failed(row.id, str(exc))
        await publish("queue:error", {"id": row.id, "error_message": str(exc)})


async def start_worker() -> None:
    log.info("Queue worker starting")
    await _reset_stale_running()
    while True:
        try:
            row = await _claim_next()
            if row is None:
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)
                continue
            await _download_one(row)
        except asyncio.CancelledError:
            log.info("Queue worker stopping")
            raise
        except Exception:  # pragma: no cover
            log.exception("Worker loop error — sleeping and continuing")
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
