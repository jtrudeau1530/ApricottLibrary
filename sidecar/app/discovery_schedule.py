"""Persisted, finite Spotify discovery campaigns. Never an unlimited download loop."""

from datetime import timedelta
from sqlalchemy import select, func
from .db import SessionLocal
from .models import (
    DiscoverySchedule,
    DiscoveryStation,
    DiscoveryTrack,
    FetchQueue,
    User,
)
from .queue_identity import get_or_enqueue
from .spotify import spotify
from .station_worker import now, TERMINAL, catalog_snapshot
from .track_matching import identity_key, choose_match
from .providers import safe_error


async def schedule_tick():
    async with SessionLocal() as db:
        schedule = await db.scalar(
            select(DiscoverySchedule)
            .where(
                DiscoverySchedule.enabled.is_(True),
                DiscoverySchedule.next_run_at <= now(),
            )
            .order_by(DiscoverySchedule.next_run_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not schedule:
            return
        owner = await db.get(User, schedule.owner_id)
        if (
            not owner
            or owner.disabled
            or not owner.can_fetch
            or schedule.runs >= schedule.max_runs
        ):
            schedule.enabled = False
            await db.commit()
            return
        await db.scalar(select(User).where(User.id == owner.id).with_for_update())
        active = await db.scalar(
            select(func.count())
            .select_from(DiscoveryStation)
            .where(
                DiscoveryStation.owner_id == owner.id,
                DiscoveryStation.status.not_in(TERMINAL),
            )
        )
        schedule.next_run_at = now() + timedelta(hours=schedule.interval_hours)
        schedule.runs += 1
        schedule.enabled = schedule.runs < schedule.max_runs
        if active >= 3:
            schedule.last_error = (
                "Skipped this interval: three acquisition jobs are already active."
            )
            await db.commit()
            return
        # Persist the campaign budget before provider calls; crashes never replay a run.
        await db.commit()
        spent_run = schedule.runs
        schedule_id = schedule.id
        campaign_query = schedule.query
        phase = "jellyfin_catalog"
        try:
            catalog = await catalog_snapshot()
            phase = "spotify_discovery"
            candidates = []
            for offset in range(0, 50, 10):
                batch = await spotify.search_tracks(
                    schedule.query, limit=10, offset=offset
                )
                candidates.extend(batch)
                if len(batch) < 10:
                    break
            seen = set(
                (
                    await db.scalars(
                        select(DiscoveryTrack.identity_key)
                        .join(
                            DiscoveryStation,
                            DiscoveryTrack.station_id == DiscoveryStation.id,
                        )
                        .where(DiscoveryStation.schedule_id == schedule.id)
                    )
                ).all()
            )
            selected = []
            for item in candidates:
                artists = item.get("artists") or []
                if not artists or not item.get("name") or not item.get("id"):
                    continue
                key = identity_key(artists[0], item["name"])
                wanted = {
                    "artist": artists[0],
                    "title": item["name"],
                    "album": item.get("album") or "",
                    "duration_seconds": (item.get("duration_ms") or 0) / 1000,
                }
                match, ambiguous = choose_match(wanted, catalog)
                if key in seen or match or ambiguous:
                    continue
                seen.add(key)
                selected.append((item, key))
                if len(selected) >= schedule.count:
                    break
            await db.refresh(schedule, with_for_update=True)
            if schedule.runs != spent_run or schedule.query != campaign_query:
                # An explicit edit/stop replaced this campaign while the query ran.
                return
            if not schedule.enabled and schedule.runs < schedule.max_runs:
                return
            job = DiscoveryStation(
                owner_id=owner.id,
                name="Spotify discovery",
                prompt=schedule.query,
                requested_count=schedule.count,
                publish_radio=False,
                schedule_id=schedule.id,
                status="queued" if selected else "partial",
                generation_message=(
                    f"Spotify returned {len(selected)} new unique songs of {schedule.count} requested after at most 50 results; existing, previously suggested and ambiguous recordings were excluded."
                    if len(selected) < schedule.count
                    else None
                ),
            )
            db.add(job)
            await db.flush()
            queues = {}
            # Keep authoritative Spotify IDs/duration/art instead of searching
            # the same title again (which can miss the original recording).
            # Match the batch helper's lock order for overlapping imports.
            for item, key in sorted(selected, key=lambda pair: pair[1]):
                queue, _ = await get_or_enqueue(
                    db,
                    FetchQueue(
                        source="auto",
                        identity_key=key,
                        track_name=item["name"],
                        artist_name=item["artists"][0],
                        album_name=item.get("album") or "",
                        spotify_track_id=item["id"],
                        duration_seconds=round(item["duration_ms"] / 1000)
                        if item.get("duration_ms")
                        else None,
                        cover_url=item.get("cover_url"),
                        requester_id=owner.id,
                    ),
                )
                queues[key] = queue.id
            for position, (item, key) in enumerate(selected):
                db.add(
                    DiscoveryTrack(
                        station_id=job.id,
                        position=position,
                        title=item["name"],
                        artist=item["artists"][0],
                        album=item.get("album") or "",
                        identity_key=key,
                        reason="Spotify recurring discovery",
                        queue_id=queues[key],
                        status="acquiring",
                    )
                )
            schedule.last_error = None
            await db.commit()
        except Exception as exc:
            error = safe_error(phase, exc)
            # Preserve the already charged run, but never commit a partial batch
            # after an enqueue/database failure.
            await db.rollback()
            schedule = await db.get(DiscoverySchedule, schedule_id)
            schedule.last_error = error["message"] + " (" + error["code"] + ")"
            await db.commit()
