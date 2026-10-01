"""One acquisition row per recording across station and manual import entry points."""

import asyncio
from sqlalchemy import select, text

from .config import settings
from .models import FetchQueue
from .track_matching import identity_key, media_file, probe


async def get_or_enqueue(db, row: FetchQueue) -> tuple[FetchQueue, bool]:
    key = row.identity_key or identity_key(row.artist_name, row.track_name)
    # Unidentified manual videos must not all collapse to Unknown/Unknown.
    if row.artist_name == "Unknown" or not row.track_name:
        key = identity_key(
            row.source or "spotify",
            row.source_id or row.spotify_track_id or row.track_name,
        )
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
    )
    existing = await db.scalar(select(FetchQueue).where(FetchQueue.identity_key == key))
    if existing is None:
        legacy = (
            await db.scalars(
                select(FetchQueue)
                .where(
                    FetchQueue.identity_key.is_(None),
                    FetchQueue.status.in_(["queued", "running", "complete"]),
                )
                .order_by(FetchQueue.created_at)
            )
        ).all()
        existing = next(
            (q for q in legacy if identity_key(q.artist_name, q.track_name) == key),
            None,
        )
        if existing:
            existing.identity_key = key
    if existing:
        safe = (
            media_file(existing.output_path, settings.media_path)
            if existing.output_path
            else None
        )
        if (
            existing.status == "complete"
            and safe
            and not await asyncio.to_thread(probe, safe)
        ):
            existing.status = "failed"
            existing.error_message = "Historical acquisition file failed audio validation; existing file was preserved"
        elif existing.status == "complete" and not safe:
            existing.status = "queued"
            existing.attempts = existing.progress = 0
            for field in (
                "output_path",
                "error_message",
                "completed_at",
                "next_attempt_at",
            ):
                setattr(existing, field, None)
            existing.source, existing.source_id = row.source or "spotify", row.source_id
            return existing, True
        return existing, False
    row.identity_key = key
    db.add(row)
    await db.flush()
    return row, True


async def enqueue_batch(
    db, rows: list[FetchQueue]
) -> tuple[list[FetchQueue], int, int]:
    added, queued, library = [], 0, 0
    # A consistent lock order prevents two overlapping batches from deadlocking.
    rows = sorted(rows, key=lambda r: identity_key(r.artist_name, r.track_name))
    for row in rows:
        shared, created = await get_or_enqueue(db, row)
        if created:
            added.append(shared)
        elif shared.status == "complete":
            library += 1
        else:
            queued += 1
    return added, queued, library
