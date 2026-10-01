"""Session-authorized AI station jobs, with polling that survives page reloads."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import DiscoveryStation, DiscoveryTrack, FetchQueue, User
from .sessions import require_session
from .station_worker import TERMINAL

router = APIRouter(prefix="/api/discovery", tags=["music discovery"])


class StationRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)
    count: int = Field(default=20, ge=5, le=50)

    @field_validator("prompt")
    @classmethod
    def nonblank(cls, value):
        if len(value.strip()) < 3:
            raise ValueError("Describe the station's vibe")
        return value.strip()


async def owned(db, station_id, user):
    job = await db.get(DiscoveryStation, station_id)
    if job is None or (job.owner_id != user.id and not user.is_admin):
        raise HTTPException(404, "Discovery job not found")
    return job


async def serialize(db, job):
    tracks = (
        await db.execute(
            select(DiscoveryTrack, FetchQueue)
            .outerjoin(FetchQueue, DiscoveryTrack.queue_id == FetchQueue.id)
            .where(DiscoveryTrack.station_id == job.id)
            .order_by(DiscoveryTrack.position)
        )
    ).all()
    items = []
    for track, queue in tracks:
        items.append(
            {
                "id": track.id,
                "title": track.title,
                "artist": track.artist,
                "reason": track.reason,
                "status": track.status,
                "match_source": track.match_source,
                "jellyfin_item_id": track.jellyfin_item_id,
                "queue_status": queue.status if queue else None,
                "progress": queue.progress if queue else 0,
                "attempts": queue.attempts if queue else 0,
                "error_message": track.error_message
                or (queue.error_message if queue else None),
                "warning_message": queue.warning_message if queue else None,
                "provider_errors": queue.provider_errors if queue else [],
                "next_attempt_at": queue.next_attempt_at.isoformat()
                if queue and queue.next_attempt_at
                else None,
            }
        )
    counts = {
        "existing": sum(t["status"] == "existing" for t in items),
        "imported": sum(t["status"] == "imported" for t in items),
        "failed": sum(
            t["status"] == "failed" or t["queue_status"] == "failed" for t in items
        ),
        "downloaded": sum(q is not None and q.status == "complete" for _, q in tracks),
        "pending": sum(
            t["status"] not in ("existing", "imported", "failed")
            and t["queue_status"] != "failed"
            for t in items
        ),
    }
    return {
        "id": job.id,
        "name": job.name,
        "prompt": job.prompt,
        "requested_count": job.requested_count,
        "suggested_count": len(items),
        "status": job.status,
        "error_message": job.error_message,
        "playlist_id": job.playlist_id,
        "generation_message": job.generation_message,
        "generation_calls": job.generation_calls,
        "counts": counts,
        "tracks": items,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "next_attempt_at": job.next_attempt_at.isoformat()
        if job.next_attempt_at
        else None,
    }


@router.get("/configuration")
async def configuration(user: User = Depends(require_session)):
    return {
        "ai_configured": bool(settings.ai_model),
        "can_fetch": user.can_fetch,
        "concurrency": settings.acquisition_concurrency,
        "max_attempts": settings.acquisition_max_attempts,
    }


@router.post("", status_code=202)
async def create_station(
    body: StationRequest,
    user: User = Depends(require_session),
    db: AsyncSession = Depends(get_db),
):
    if not user.can_fetch:
        raise HTTPException(403, "You don't have fetch permission")
    if not settings.ai_model:
        raise HTTPException(
            503,
            "Configure AI_MODEL, AI_BASE_URL and the provider's AI_API_KEY before generating stations",
        )
    # Serialize per-user submissions so concurrent requests cannot bypass the limit.
    await db.scalar(select(User).where(User.id == user.id).with_for_update())
    active = await db.scalar(
        select(func.count())
        .select_from(DiscoveryStation)
        .where(
            DiscoveryStation.owner_id == user.id,
            DiscoveryStation.status.not_in(TERMINAL),
        )
    )
    if active >= 3:
        raise HTTPException(
            429, "Three discovery jobs are already active; wait for one to finish"
        )
    job = DiscoveryStation(
        owner_id=user.id,
        prompt=body.prompt,
        name="Discovering songs…",
        requested_count=body.count,
        publish_radio=False,
    )
    db.add(job)
    await db.commit()
    return await serialize(db, job)


@router.get("")
async def list_stations(
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(require_session),
    db: AsyncSession = Depends(get_db),
):
    jobs = (
        await db.scalars(
            select(DiscoveryStation)
            .where(DiscoveryStation.owner_id == user.id)
            .order_by(DiscoveryStation.created_at.desc())
            .limit(limit)
        )
    ).all()
    return {"items": [await serialize(db, j) for j in jobs]}


class ScheduleRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    count: int = Field(default=20, ge=5, le=50)
    interval_hours: int = Field(default=24, ge=6, le=168)
    max_runs: int = Field(default=30, ge=1, le=365)
    enabled: bool = False


def schedule_out(s):
    return {
        k: getattr(s, k)
        for k in (
            "id",
            "query",
            "count",
            "interval_hours",
            "max_runs",
            "runs",
            "enabled",
            "next_run_at",
            "last_error",
        )
    }


@router.get("/providers")
async def providers(user: User = Depends(require_session)):
    from .providers import provider_readiness

    return {"items": await provider_readiness()}


@router.get("/schedule")
async def get_schedule(
    user: User = Depends(require_session), db: AsyncSession = Depends(get_db)
):
    from .models import DiscoverySchedule

    schedule = await db.scalar(
        select(DiscoverySchedule).where(DiscoverySchedule.owner_id == user.id)
    )
    return {
        "schedule": schedule_out(schedule) if schedule else None,
        "min_interval_hours": settings.discovery_min_interval_hours,
        "max_runs": settings.discovery_max_schedule_runs,
    }


@router.put("/schedule")
async def set_schedule(
    body: ScheduleRequest,
    user: User = Depends(require_session),
    db: AsyncSession = Depends(get_db),
):
    from .models import DiscoverySchedule

    if not user.can_fetch:
        raise HTTPException(403, "Fetch permission required")
    if (
        body.interval_hours < settings.discovery_min_interval_hours
        or body.max_runs > settings.discovery_max_schedule_runs
    ):
        raise HTTPException(400, "Schedule exceeds configured interval/run budget")
    if body.enabled and not (
        settings.spotify_client_id and settings.spotify_client_secret
    ):
        raise HTTPException(
            503, "Configure/reconnect Spotify discovery in Library first"
        )
    await db.scalar(select(User).where(User.id == user.id).with_for_update())
    schedule = await db.scalar(
        select(DiscoverySchedule).where(DiscoverySchedule.owner_id == user.id)
    )
    if not schedule:
        schedule = DiscoverySchedule(owner_id=user.id)
        db.add(schedule)
    for k, v in body.model_dump().items():
        setattr(schedule, k, v)
    schedule.runs = 0
    schedule.next_run_at = datetime.now(timezone.utc)
    schedule.last_error = None
    await db.commit()
    await db.refresh(schedule)
    return {"schedule": schedule_out(schedule)}


@router.get("/{station_id}")
async def get_station(
    station_id: str,
    user: User = Depends(require_session),
    db: AsyncSession = Depends(get_db),
):
    return await serialize(db, await owned(db, station_id, user))


@router.post("/{station_id}/retry", status_code=202)
async def retry_station(
    station_id: str,
    user: User = Depends(require_session),
    db: AsyncSession = Depends(get_db),
):
    if not user.can_fetch:
        raise HTTPException(403, "You don't have fetch permission")
    job = await owned(db, station_id, user)
    if job.status not in ("failed", "partial", "sync_failed"):
        raise HTTPException(409, "Discovery has no finished failure to retry")
    await db.refresh(job, with_for_update=True)
    if job.status not in ("failed", "partial", "sync_failed"):
        raise HTTPException(409, "Discovery was already resumed")
    await db.scalar(select(User).where(User.id == job.owner_id).with_for_update())
    active = await db.scalar(
        select(func.count())
        .select_from(DiscoveryStation)
        .where(
            DiscoveryStation.owner_id == job.owner_id,
            DiscoveryStation.status.not_in(TERMINAL),
        )
    )
    if active >= 3:
        raise HTTPException(
            429, "Three discovery jobs are already active; wait for one to finish"
        )
    tracks = (
        await db.scalars(
            select(DiscoveryTrack).where(DiscoveryTrack.station_id == job.id)
        )
    ).all()
    for track in tracks:
        if track.status == "failed":
            queue = await db.get(FetchQueue, track.queue_id) if track.queue_id else None
            if queue and queue.status == "failed":
                # A discovery retry uses the multi-provider acquisition path even when
                # its shared historical queue row came from a manual provider.
                queue.source = "auto"
                queue.status, queue.attempts, queue.progress = "queued", 0, 0
                queue.error_message = queue.completed_at = queue.next_attempt_at = None
            track.status = (
                "importing"
                if track.relative_path and (not queue or queue.status == "complete")
                else ("acquiring" if queue else "matching")
            )
            track.import_attempts = 0
            track.error_message = None
    job.status = (
        "planning"
        if not tracks
        or any(t.status == "matching" for t in tracks)
        or (
            len(tracks) < job.requested_count
            and not job.schedule_id
            and job.generation_calls < settings.ai_max_calls_per_job
        )
        else "acquiring"
    )
    job.attempts = job.sync_attempts = 0
    job.error_message = None
    job.next_attempt_at = datetime.now(timezone.utc)
    await db.commit()
    return await serialize(db, job)
