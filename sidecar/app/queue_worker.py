import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from mutagen.oggvorbis import OggVorbis
from sqlalchemy import select, update  # noqa: F401

from . import jellyfin, librespot_session
from .config import settings
from .db import SessionLocal
from .models import FetchQueue, SongMetadata
from .sse_hub import publish
from .storage import compute_storage_snapshot

log = logging.getLogger("queue_worker")

_SAFE_NAME = re.compile(r"[^A-Za-z0-9 _\-().,'&!]")
_POLL_INTERVAL_SECONDS = 2.0
_HEARTBEAT_INTERVAL_SECONDS = 5.0
_STALE_RUNNING_AGE_SECONDS = 60
# Brief pause between successful downloads — empirically the librespot session
# degrades ("Failed fetching audio key") after many rapid back-to-back fetches.
_INTER_TRACK_PAUSE_SECONDS = 1.5


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
        snap = await asyncio.to_thread(compute_storage_snapshot, settings.media_path)
        await publish("storage:update", snap)
    except Exception as exc:  # pragma: no cover
        log.debug("Storage update emit failed: %s", exc)


def _write_ogg_tags(path: Path, title: str, artist: str, album: str) -> None:
    """librespot writes raw OGG with no Vorbis comments. Fill in so Jellyfin can read them."""
    try:
        audio = OggVorbis(path)
        audio["title"] = title
        audio["artist"] = artist
        if album:
            audio["album"] = album
        audio.save()
    except Exception as exc:
        log.warning("Failed to write OGG tags on %s: %s", path, exc)


async def _record_spotify_mapping(row: FetchQueue, output_path: Path) -> None:
    """After Jellyfin scans the new file, find the matching item by Path and
    persist the spotify_track_id ↔ jellyfin_item_id mapping in song_metadata."""
    # Give Jellyfin a moment to scan (best-effort; we don't block the worker forever).
    await asyncio.sleep(3)
    for _ in range(6):  # ~24s total with the trailing sleep below
        try:
            result = await jellyfin.list_tracks(sort="added", limit=50)
            for item in result.get("items", []):
                # Match by track id won't work since we don't have it yet;
                # use the filename. Jellyfin doesn't expose the file path on list,
                # so we fetch each item's full metadata only if title matches.
                if item.get("title", "").lower() == row.track_name.lower():
                    full = await jellyfin.get_track(item["id"])
                    if full and full.get("path", "").endswith(output_path.name):
                        async with SessionLocal() as db:
                            existing = (
                                await db.execute(
                                    select(SongMetadata).where(
                                        SongMetadata.jellyfin_item_id == item["id"]
                                    )
                                )
                            ).scalar_one_or_none()
                            if existing is None:
                                db.add(
                                    SongMetadata(
                                        jellyfin_item_id=item["id"],
                                        spotify_track_id=row.spotify_track_id,
                                    )
                                )
                            else:
                                existing.spotify_track_id = row.spotify_track_id
                            await db.commit()
                        return
        except Exception as exc:  # pragma: no cover
            log.debug("Mapping resolve attempt failed: %s", exc)
        await asyncio.sleep(4)


async def _save_album_cover(album_dir: Path, cover_url: str | None) -> None:
    """Save cover.jpg next to the audio file. Jellyfin auto-picks these up on scan."""
    if not cover_url:
        return
    target = album_dir / "cover.jpg"
    if target.exists():
        return
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(cover_url)
            if resp.status_code != 200:
                log.warning("Cover fetch %s returned %s", cover_url, resp.status_code)
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(resp.content)
    except Exception as exc:
        log.warning("Cover save failed for %s: %s", album_dir, exc)


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
        # librespot output has no Vorbis comments — write title/artist/album so Jellyfin tags correctly.
        await asyncio.to_thread(
            _write_ogg_tags, output_path, row.track_name, row.artist_name, row.album_name or ""
        )
        # Save album cover next to the file so Jellyfin picks it up as album art.
        await _save_album_cover(output_path.parent, row.cover_url)
        await _mark_complete(row.id, output_path)
        # Best-effort: record spotify_track_id → jellyfin_item_id once Jellyfin sees it.
        asyncio.create_task(_record_spotify_mapping(row, output_path))
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
            await asyncio.sleep(_INTER_TRACK_PAUSE_SECONDS)
        except asyncio.CancelledError:
            log.info("Queue worker stopping")
            raise
        except Exception:  # pragma: no cover
            log.exception("Worker loop error — sleeping and continuing")
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
