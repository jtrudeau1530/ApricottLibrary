import asyncio
import logging
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from mutagen.oggvorbis import OggVorbis
from sqlalchemy import or_, select, update

from . import jellyfin, librespot_session, musicbrainz, youtube
from .config import settings
from .db import SessionLocal
from .models import FetchQueue, SongMetadata
from .sse_hub import publish
from .storage import compute_storage_snapshot
from .track_matching import media_file, probe

log = logging.getLogger("queue_worker")

_SAFE_NAME = re.compile(r"[^A-Za-z0-9 _\-().,'&!]")
_POLL_INTERVAL_SECONDS = 2.0
_HEARTBEAT_INTERVAL_SECONDS = 5.0
_STALE_RUNNING_AGE_SECONDS = 60
# Brief pause between successful downloads — empirically the librespot session
# degrades ("Failed fetching audio key") after many rapid back-to-back fetches.
_INTER_TRACK_PAUSE_SECONDS = 1.5
_spotify_download_lock = asyncio.Lock()


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
        await db.execute(update(FetchQueue).where(
            FetchQueue.source == "auto", FetchQueue.status == "queued",
            FetchQueue.attempts >= settings.acquisition_max_attempts,
        ).values(status="failed", error_message="Acquisition retry limit reached after interruption", completed_at=_utc_now()))
        await db.commit()


async def _claim_next() -> FetchQueue | None:
    async with SessionLocal() as db:
        result = await db.execute(
            select(FetchQueue)
            .where(FetchQueue.status == "queued")
            .where(or_(FetchQueue.next_attempt_at.is_(None), FetchQueue.next_attempt_at <= _utc_now()))
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
                next_attempt_at=None,
                heartbeat_at=None,
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
    await publish("queue:progress", {"id": item_id, "percent": progress})


async def _trigger_jellyfin_refresh() -> None:
    """Reuse the shared idle-scan guard across downloads and discovery jobs."""
    await jellyfin.trigger_refresh()


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
                    if full and full.get("path") and Path(full["path"]).resolve() == output_path.resolve():
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


async def _save_album_cover(album_dir: Path, cover_url: str | None) -> bool:
    """Save cover.jpg next to the audio file. Jellyfin auto-picks these up on scan."""
    if not cover_url:
        return (album_dir / "cover.jpg").is_file()
    target = album_dir / "cover.jpg"
    if target.exists():
        return True
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(cover_url)
            if resp.status_code != 200:
                log.warning("Cover fetch %s returned %s", cover_url, resp.status_code)
                return False
            if resp.headers.get("content-type", "").split(";")[0] not in ("image/jpeg", "image/png") or not 0 < len(resp.content) <= 5_000_000:
                return False
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=target.parent, suffix=".part")
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(resp.content)
                # Shared consumers must be able to read artwork as well as audio.
                os.chmod(temporary, 0o644)
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    pass
            finally:
                Path(temporary).unlink(missing_ok=True)
            return True
    except Exception as exc:
        log.warning("Cover save failed for %s: %s", album_dir, exc)
        return False


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

    try:
        heartbeat_task = asyncio.create_task(_beat())
        source = (row.source or "spotify").lower()
        if source == "auto":
            # Keep the heartbeat alive during network/tagging work, but don't
            # invent a percent based on elapsed time for automatic acquisition.
            heartbeat_task.cancel()
            async def _auto_beat():
                while True:
                    await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
                    async with SessionLocal() as db:
                        await db.execute(update(FetchQueue).where(FetchQueue.id == row.id).values(heartbeat_at=_utc_now()))
                        await db.commit()
            heartbeat_task = asyncio.create_task(_auto_beat())
            from .acquisition import acquire
            output_path = await acquire(row)
        elif source == "youtube":
            if not row.source_id:
                raise RuntimeError("YouTube queue row missing source_id (video id)")
            await asyncio.to_thread(youtube.download_audio, row.source_id, output_path)
        else:
            if not row.spotify_track_id:
                raise RuntimeError("Spotify queue row missing spotify_track_id")
            async with _spotify_download_lock:
                await asyncio.to_thread(librespot_session.download_track, row.spotify_track_id, output_path)
                await asyncio.sleep(_INTER_TRACK_PAUSE_SECONDS)
        if heartbeat_task:
            heartbeat_task.cancel()

        # For YouTube downloads only, enrich via MusicBrainz + Cover Art Archive
        # after the file lands. Spotify-source rows already have clean metadata.
        final_title = row.track_name
        final_artist = row.artist_name
        final_album = row.album_name or ""
        final_cover = row.cover_url
        if source == "youtube":
            try:
                enriched = await musicbrainz.enrich(row.artist_name, row.track_name)
            except Exception as exc:  # pragma: no cover
                log.warning("MusicBrainz enrich failed for %s: %s", row.id, exc)
                enriched = None
            if enriched:
                final_artist = enriched.get("artist") or final_artist
                final_album = enriched.get("album") or final_album
                final_cover = enriched.get("cover_url") or final_cover
                log.info(
                    "Enriched %s: artist=%r album=%r cover=%s",
                    row.id, final_artist, final_album, bool(enriched.get("cover_url")),
                )
            # Relocate the file under the enriched folder structure if it
            # actually changed — Jellyfin's library scan keys off the path.
            new_path = (
                Path(settings.media_path)
                / _safe(final_artist)
                / _safe(final_album or "Unknown")
                / f"{_safe(final_title)}.ogg"
            )
            if new_path != output_path:
                new_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.replace(new_path)
                # Drop the now-empty old album/artist dirs if we left them empty.
                for parent in (output_path.parent, output_path.parent.parent):
                    try:
                        parent.rmdir()
                    except OSError:
                        break
                output_path = new_path
        if source != "auto":
            await asyncio.to_thread(
                _write_ogg_tags, output_path, final_title, final_artist, final_album
            )
            await _save_album_cover(output_path.parent, final_cover)
        if not media_file(output_path, settings.media_path) or not await asyncio.to_thread(probe, output_path):
            raise RuntimeError("Download produced no valid audio; acquisition was not completed")
        await _mark_complete(row.id, output_path)
        # Best-effort: record spotify_track_id → jellyfin_item_id once Jellyfin sees it.
        if row.spotify_track_id and source != "auto":
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
        from .acquisition import TrackUnavailable
        error = str(exc) or type(exc).__name__
        if row.source == "auto" and row.attempts < settings.acquisition_max_attempts and not isinstance(exc, TrackUnavailable):
            async with SessionLocal() as db:
                await db.execute(update(FetchQueue).where(FetchQueue.id == row.id).values(
                    status="queued", progress=0, error_message=error, heartbeat_at=None,
                    next_attempt_at=_utc_now() + timedelta(seconds=10 * 2 ** (row.attempts - 1)),
                ))
                await db.commit()
            await publish("queue:retry", {"id": row.id, "error_message": error})
        else:
            await _mark_failed(row.id, error)
            await publish("queue:error", {"id": row.id, "error_message": error})
    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)


async def _worker_loop() -> None:
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


async def start_worker() -> None:
    log.info("Queue worker starting with concurrency %d", settings.acquisition_concurrency)
    await _reset_stale_running()
    async def recover():
        while True:
            await asyncio.sleep(30)
            try:
                await _reset_stale_running()
            except Exception:
                log.exception("Queue recovery check failed; retrying on the next interval")
    tasks = [asyncio.create_task(_worker_loop()) for _ in range(settings.acquisition_concurrency)]
    tasks.append(asyncio.create_task(recover()))
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
