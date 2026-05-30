from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import FetchQueue, User
from .sessions import require_session
from .sse_hub import publish

router = APIRouter(prefix="/api/queue", tags=["queue"])


class EnqueueRequest(BaseModel):
    spotify_track_id: str = Field(min_length=22, max_length=32)
    track_name: str = Field(min_length=1, max_length=512)
    artist_name: str = Field(min_length=1, max_length=512)
    album_name: str = ""
    cover_url: str | None = None


class QueueRowOut(BaseModel):
    id: str
    source: str
    source_id: str | None
    spotify_track_id: str | None
    track_name: str
    artist_name: str
    album_name: str
    cover_url: str | None
    requester_id: str | None
    requester_username: str | None
    status: str
    progress: int
    error_message: str | None
    attempts: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


async def _to_out(row: FetchQueue, requester_username: str | None) -> QueueRowOut:
    return QueueRowOut(
        id=row.id,
        source=row.source or "spotify",
        source_id=row.source_id,
        spotify_track_id=row.spotify_track_id,
        track_name=row.track_name,
        artist_name=row.artist_name,
        album_name=row.album_name,
        cover_url=row.cover_url,
        requester_id=row.requester_id,
        requester_username=requester_username,
        status=row.status,
        progress=row.progress or 0,
        error_message=row.error_message,
        attempts=row.attempts or 0,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def enqueue(
    body: EnqueueRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    if not user.can_fetch:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have fetch permission")

    existing = await db.execute(
        select(FetchQueue).where(
            FetchQueue.spotify_track_id == body.spotify_track_id,
            FetchQueue.status.in_(["queued", "running"]),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already in queue")

    row = FetchQueue(
        spotify_track_id=body.spotify_track_id,
        track_name=body.track_name,
        artist_name=body.artist_name,
        album_name=body.album_name,
        cover_url=body.cover_url,
        requester_id=user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    out = await _to_out(row, user.username)
    await publish("queue:added", out.model_dump())
    return out.model_dump()


@router.get("")
async def list_queue(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_session),
) -> dict:
    result = await db.execute(
        select(FetchQueue, User.username)
        .outerjoin(User, FetchQueue.requester_id == User.id)
        .where(FetchQueue.status.in_(["queued", "running"]))
        .order_by(FetchQueue.created_at.asc())
    )
    rows = result.all()
    items = [await _to_out(r, username) for (r, username) in rows]
    return {"count": len(items), "items": [i.model_dump() for i in items]}


@router.get("/history")
async def queue_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_session),
) -> dict:
    result = await db.execute(
        select(FetchQueue, User.username)
        .outerjoin(User, FetchQueue.requester_id == User.id)
        .where(FetchQueue.status.in_(["complete", "failed"]))
        .order_by(desc(FetchQueue.completed_at))
        .limit(limit)
        .offset(offset)
    )
    rows = result.all()
    items = [await _to_out(r, username) for (r, username) in rows]
    return {"count": len(items), "items": [i.model_dump() for i in items]}


@router.post("/retry-failed")
async def retry_all_failed(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    if not user.can_fetch:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have fetch permission")
    result = await db.execute(select(FetchQueue).where(FetchQueue.status == "failed"))
    rows = result.scalars().all()
    if not rows:
        return {"requeued": 0}
    for row in rows:
        row.status = "queued"
        row.error_message = None
        row.started_at = None
        row.completed_at = None
        row.heartbeat_at = None
        row.progress = 0
    await db.commit()
    for row in rows:
        await publish("queue:retry", {"id": row.id})
    return {"requeued": len(rows)}


@router.post("/{item_id}/retry")
async def retry_queue_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    if not user.can_fetch:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have fetch permission")
    result = await db.execute(select(FetchQueue).where(FetchQueue.id == item_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if row.status not in ("failed", "complete"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed or complete items can be retried")
    await db.execute(
        update(FetchQueue)
        .where(FetchQueue.id == item_id)
        .values(
            status="queued",
            error_message=None,
            started_at=None,
            completed_at=None,
            heartbeat_at=None,
            progress=0,
        )
    )
    await db.commit()
    await publish("queue:retry", {"id": item_id})
    return {"status": "requeued", "id": item_id}
