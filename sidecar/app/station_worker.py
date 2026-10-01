"""Durable Library discovery -> matching -> acquisition -> verified import."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, text

from . import jellyfin
from .config import settings
from .db import SessionLocal, engine
from .models import (
    DiscoveryStation,
    DiscoveryTrack,
    FetchQueue,
    SongMetadata,
    User,
)
from .spotify import spotify
from .station_ai import generate_station
from .queue_identity import get_or_enqueue
from .sse_hub import publish
from .track_matching import (
    choose_match,
    identity_key,
    matches,
    media_file,
    probe,
    scan_media,
)

log = logging.getLogger("station_worker")
TERMINAL = {"ready", "partial", "failed", "sync_failed"}


def now():
    return datetime.now(timezone.utc)


async def catalog_snapshot() -> list[dict]:
    catalog, offset = [], 0
    while True:
        page = await jellyfin.list_tracks(limit=500, offset=offset, strict=True)
        catalog.extend(page["items"])
        offset += len(page["items"])
        if offset >= page["total"]:
            break
        if not page["items"]:
            raise RuntimeError(
                "Jellyfin returned an incomplete catalog; acquisition paused"
            )
    async with SessionLocal() as db:
        overrides = {
            m.jellyfin_item_id: m
            for m in (await db.scalars(select(SongMetadata))).all()
        }
    for item in catalog:
        meta = overrides.get(item["id"])
        if meta:
            item["spotify_track_id"] = meta.spotify_track_id
            for field in ("title", "artist", "album"):
                if getattr(meta, field):
                    item[field] = getattr(meta, field)
            if meta.artist:
                item["artists"] = [meta.artist]
    return catalog


def relative(path: str) -> str | None:
    safe = media_file(path, settings.media_path)
    return (
        safe.relative_to(Path(settings.media_path).resolve()).as_posix()
        if safe
        else None
    )


async def plan_station(station: DiscoveryStation):
    async with SessionLocal() as db:
        tracks = (
            await db.scalars(
                select(DiscoveryTrack).where(DiscoveryTrack.station_id == station.id)
            )
        ).all()
    while len(tracks) < station.requested_count and not station.schedule_id:
        async with SessionLocal() as db:
            job = await db.get(DiscoveryStation, station.id)
            if job.generation_calls >= settings.ai_max_calls_per_job:
                break
            job.generation_calls += 1  # Charge the durable budget before network I/O.
            await db.commit()
        try:
            suggestion = await generate_station(
                station.prompt,
                min(settings.ai_batch_size, station.requested_count - len(tracks)),
                [f"{t.artist[:80]} - {t.title[:120]}" for t in tracks],
            )
        except Exception as exc:
            if not tracks:
                raise
            async with SessionLocal() as db:
                job = await db.get(DiscoveryStation, station.id)
                job.generation_message = (
                    "Generation/top-up stopped: "
                    + (
                        str(exc)
                        if isinstance(exc, RuntimeError)
                        else "provider connection failed"
                    )
                    + ". Retained suggestions will still be acquired."
                )
                await db.commit()
            break
        async with SessionLocal() as db:
            job = await db.get(DiscoveryStation, station.id)
            if not tracks:
                job.name = suggestion.name.strip() or "Music discovery"
            seen = {t.identity_key for t in tracks}
            for song in suggestion.tracks:
                key = identity_key(song.artist, song.title)
                if key in seen or len(seen) >= station.requested_count:
                    continue
                seen.add(key)
                db.add(
                    DiscoveryTrack(
                        station_id=job.id,
                        position=len(seen) - 1,
                        title=song.title,
                        artist=song.artist,
                        album=song.album,
                        reason=song.reason,
                        identity_key=key,
                    )
                )
            await db.commit()
            tracks = (
                await db.scalars(
                    select(DiscoveryTrack)
                    .where(DiscoveryTrack.station_id == station.id)
                    .order_by(DiscoveryTrack.position)
                )
            ).all()
    async with SessionLocal() as db:
        job = await db.get(DiscoveryStation, station.id)
        if len(tracks) < job.requested_count:
            reason = (
                job.generation_message
                if job.generation_message
                and job.generation_message.startswith("Generation/top-up stopped:")
                else (
                    f"Model did not supply enough unique recordings within the durable {settings.ai_max_calls_per_job}-call budget."
                    if not job.schedule_id
                    else "The bounded Spotify search had insufficient new unique recordings."
                )
            )
            job.generation_message = f"Only {len(tracks)} of {job.requested_count} unique suggestions. {reason} Missing suggestions were not acquired."
        if not tracks:
            raise RuntimeError(job.generation_message or "Discovery returned no songs")
        await db.commit()

    # A failed catalog request is a failure, never evidence that music is missing.
    catalog = await catalog_snapshot()
    local = await asyncio.to_thread(scan_media, settings.media_path)
    async with SessionLocal() as db:
        tracks = (
            await db.scalars(
                select(DiscoveryTrack)
                .where(
                    DiscoveryTrack.station_id == station.id,
                    DiscoveryTrack.status == "matching",
                )
                .order_by(DiscoveryTrack.position)
            )
        ).all()
    for track in tracks:
        queued, created = None, False
        wanted = {"artist": track.artist, "title": track.title, "album": track.album}
        existing, ambiguous_catalog = choose_match(wanted, catalog)
        local_match, ambiguous_local = choose_match(wanted, local)
        async with SessionLocal() as db:
            current = await db.get(DiscoveryTrack, track.id)
            if ambiguous_catalog or (not existing and ambiguous_local):
                current.status = "failed"
                current.error_message = "Multiple different recordings share these tags; no recording was selected or acquired"
            elif existing:
                item = existing
                current.jellyfin_item_id = item["id"]
                current.relative_path = (
                    relative(item["path"]) if item.get("path") else None
                )
                current.match_source = "jellyfin"
                # Reconfirm that the catalog row points to valid audio when mounted.
                current.status = "existing"
                if not item.get("duration_seconds"):
                    current.status = "importing" if current.relative_path else "failed"
                    current.error_message = (
                        "Jellyfin has not confirmed a playable audio duration"
                    )
                if (
                    item.get("path")
                    and Path(item["path"])
                    .resolve()
                    .is_relative_to(Path(settings.media_path).resolve())
                    and not current.relative_path
                ):
                    current.status = "failed"
                    current.error_message = (
                        "Jellyfin catalog entry points to missing Library audio"
                    )
                if current.relative_path and not await asyncio.to_thread(
                    probe, Path(settings.media_path) / current.relative_path
                ):
                    current.status = "failed"
                    current.error_message = (
                        "Existing catalog audio could not be validated"
                    )
            elif local_match:
                current.relative_path = relative(local_match["path"])
                current.match_source = "library"
                current.status = "importing"
            else:
                metadata = None
                metadata_error = None
                if settings.spotify_client_id and settings.spotify_client_secret:
                    try:
                        results = await spotify.search_tracks(
                            f"{track.artist} {track.title}", limit=10
                        )
                        metadata, _ = choose_match(
                            wanted,
                            [
                                {
                                    **m,
                                    "duration_seconds": (m.get("duration_ms") or 0)
                                    / 1000,
                                }
                                for m in results
                            ],
                        )
                    except Exception as exc:
                        from .providers import safe_error

                        metadata_error = safe_error("spotify_metadata", exc)
                        log.info(
                            "Optional Spotify metadata unavailable for station %s",
                            station.id,
                        )
                queued, created = await get_or_enqueue(
                    db,
                    FetchQueue(
                        source="auto",
                        identity_key=track.identity_key,
                        track_name=track.title,
                        artist_name=track.artist,
                        album_name=(metadata or {}).get("album") or track.album,
                        spotify_track_id=(metadata or {}).get("id"),
                        cover_url=(metadata or {}).get("cover_url"),
                        provider_errors=[metadata_error] if metadata_error else [],
                        duration_seconds=round(metadata["duration_ms"] / 1000)
                        if metadata and metadata.get("duration_ms")
                        else None,
                        requester_id=station.owner_id,
                    ),
                )
                current.queue_id = queued.id
                current.status = "acquiring"
            await db.commit()
            if queued and created:
                await publish(
                    "queue:added",
                    {
                        "id": queued.id,
                        "source": queued.source,
                        "source_id": queued.source_id,
                        "spotify_track_id": queued.spotify_track_id,
                        "track_name": queued.track_name,
                        "artist_name": queued.artist_name,
                        "album_name": queued.album_name,
                        "cover_url": queued.cover_url,
                        "status": queued.status,
                        "progress": 0,
                        "error_message": None,
                        "requester_username": None,
                        "created_at": queued.created_at.isoformat(),
                    },
                )
    await jellyfin.trigger_refresh(strict=True)
    async with SessionLocal() as db:
        job = await db.get(DiscoveryStation, station.id)
        job.status = "acquiring"
        job.error_message = None
        job.next_attempt_at = now() + timedelta(seconds=10)
        await db.commit()


async def follow_acquisition(station: DiscoveryStation):
    catalog = await catalog_snapshot()
    by_path = {
        relative(c["path"]): c for c in catalog if c.get("path") and relative(c["path"])
    }
    async with SessionLocal() as db:
        job = await db.get(DiscoveryStation, station.id)
        tracks = (
            await db.scalars(
                select(DiscoveryTrack)
                .where(DiscoveryTrack.station_id == job.id)
                .order_by(DiscoveryTrack.position)
            )
        ).all()
        pending = False
        imported = False
        for track in tracks:
            if track.status in ("existing", "imported", "failed"):
                continue
            queue = await db.get(FetchQueue, track.queue_id) if track.queue_id else None
            if queue:
                if queue.status == "failed":
                    track.status, track.error_message = "failed", queue.error_message
                    continue
                if queue.status != "complete":
                    pending = True
                    continue
                track.relative_path = (
                    relative(queue.output_path) if queue.output_path else None
                )
                if not track.relative_path:
                    track.status, track.error_message = (
                        "failed",
                        "Downloaded audio is missing from Library",
                    )
                    continue
                track.match_source = "download"
                track.status = "importing"
            if track.status == "acquiring" and not queue:
                track.status, track.error_message = (
                    "failed",
                    "Acquisition queue entry is missing",
                )
                continue
            item = by_path.get(track.relative_path)
            if (
                item
                and item.get("duration_seconds")
                and matches({"artist": track.artist, "title": track.title}, item)
            ):
                track.jellyfin_item_id = item["id"]
                track.status = "imported"
                track.error_message = None
                imported = True
                if queue and queue.spotify_track_id:
                    meta = await db.get(SongMetadata, item["id"])
                    if meta is None:
                        db.add(
                            SongMetadata(
                                jellyfin_item_id=item["id"],
                                spotify_track_id=queue.spotify_track_id,
                            )
                        )
                    else:
                        meta.spotify_track_id = queue.spotify_track_id
            else:
                track.import_attempts += 1
                if track.import_attempts >= settings.station_import_attempts:
                    track.status = "failed"
                    track.error_message = "File exists in Library, but Jellyfin did not index a matching recording within the retry limit"
                else:
                    pending = True
        if pending:
            job.next_attempt_at = now() + timedelta(seconds=15)
        else:
            playable = [
                t
                for t in tracks
                if t.status in ("existing", "imported") and t.jellyfin_item_id
            ]
            if playable:
                # Library manages music only. Existing legacy playlists are preserved.
                job.status = (
                    "ready" if len(playable) == job.requested_count else "partial"
                )
                job.next_attempt_at = None
            else:
                job.status = "failed"
                job.error_message = (
                    "No playable recordings were imported; see track failures"
                )
        await db.commit()
    if imported:
        await publish("catalog:updated", {"station_id": station.id})
    if pending:
        await jellyfin.trigger_refresh(strict=True)


async def tick():
    async with SessionLocal() as db:
        station = await db.scalar(
            select(DiscoveryStation)
            .where(
                DiscoveryStation.status.not_in(TERMINAL),
                (DiscoveryStation.next_attempt_at.is_(None))
                | (DiscoveryStation.next_attempt_at <= now()),
            )
            .order_by(DiscoveryStation.updated_at)
            .limit(1)
        )
        if not station:
            return
        owner = await db.get(User, station.owner_id)
        if not owner or owner.disabled or not owner.can_fetch:
            station.status = "failed"
            station.error_message = "Station owner no longer has fetch permission"
            await db.commit()
            return
        if station.status in ("queued", "planning"):
            station.status = "planning"
            station.attempts += 1
        elif station.status in ("syncing", "sync_failed"):
            station.status = "acquiring"
        await db.commit()
    try:
        if station.status == "planning":
            await plan_station(station)
        elif station.status == "acquiring":
            await follow_acquisition(station)
        async with SessionLocal() as db:
            job = await db.get(DiscoveryStation, station.id)
            if job and job.status not in ("failed", "sync_failed"):
                job.error_message = None
                job.attempts = 0
                await db.commit()
    except Exception as exc:
        log.warning("Station %s: %s", station.id, exc)
        async with SessionLocal() as db:
            job = await db.get(DiscoveryStation, station.id)
            if not job:
                return
            job.error_message = str(exc) or type(exc).__name__
            if job.status == "acquiring":
                job.attempts += 1
            if job.attempts >= settings.acquisition_max_attempts:
                job.status = "failed"
            delay = 15 * 2 ** max(0, job.attempts - 1)
            job.next_attempt_at = now() + timedelta(seconds=delay)
            await db.commit()


async def start_station_worker():
    while True:
        try:
            # Only one coordinator across replicas. The queue remains independently
            # concurrent. Session lock is released on disconnect or in finally.
            async with engine.connect() as connection:
                locked = await connection.scalar(
                    text("SELECT pg_try_advisory_lock(1647210921)")
                )
                await connection.commit()
                if locked:
                    try:
                        from .discovery_schedule import schedule_tick

                        await schedule_tick()
                        await tick()
                    finally:
                        await connection.execute(
                            text("SELECT pg_advisory_unlock(1647210921)")
                        )
                        await connection.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Station coordinator error")
        await asyncio.sleep(2)
