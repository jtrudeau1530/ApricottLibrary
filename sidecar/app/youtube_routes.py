"""YouTube playlist import — enumerate via yt-dlp, match against Spotify search
for clean metadata, queue with source='youtube' so the worker dispatches to
yt-dlp instead of librespot.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import youtube
from .db import get_db
from .models import FetchQueue, SongMetadata, User
from .sessions import require_session
from .spotify import spotify
from .sse_hub import publish

log = logging.getLogger("youtube_routes")

router = APIRouter(prefix="/api/youtube", tags=["youtube"])


class PlaylistRequest(BaseModel):
    url: str = Field(min_length=10, max_length=500)


class YoutubeResolvedTrack(BaseModel):
    video_id: str
    track_name: str
    artist_name: str
    album_name: str = ""
    cover_url: str | None = None
    spotify_track_id: str | None = None
    youtube_title: str
    matched: bool = False


class YoutubeEnqueueRequest(BaseModel):
    tracks: list[YoutubeResolvedTrack] = Field(min_length=1, max_length=1000)


async def _resolve_one(entry: dict) -> YoutubeResolvedTrack:
    """For one YouTube entry, search Spotify for the best metadata match.

    On a clean hit we use Spotify's name/artist/album/cover (so Jellyfin
    treats the file identically to a librespot download). On no match we
    fall back to the parsed YouTube title.
    """
    raw_title = entry.get("title") or ""
    channel = entry.get("channel") or ""
    artist_guess, track_guess = youtube.parse_title(raw_title, channel)

    matched = False
    spotify_id: str | None = None
    name = track_guess
    artist = artist_guess
    album = ""
    cover = entry.get("thumbnail")

    if track_guess:
        try:
            query = f"{track_guess} {artist_guess}".strip()
            tracks = await spotify.search_tracks(query, limit=1)
            if tracks:
                top = tracks[0]
                spotify_id = top.get("id")
                name = top.get("name") or name
                if top.get("artists"):
                    artist = top["artists"][0]
                album = top.get("album") or ""
                cover = top.get("cover_url") or cover
                matched = True
        except Exception as exc:  # pragma: no cover
            log.debug("Spotify match failed for %s: %s", raw_title, exc)

    return YoutubeResolvedTrack(
        video_id=entry["video_id"],
        track_name=name,
        artist_name=artist,
        album_name=album,
        cover_url=cover,
        spotify_track_id=spotify_id,
        youtube_title=raw_title,
        matched=matched,
    )


@router.post("/preview")
async def preview_playlist(
    body: PlaylistRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_session),
) -> dict:
    try:
        entries = await asyncio.to_thread(youtube.enumerate_playlist, body.url)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Could not read playlist: {exc}",
        )
    if not entries:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Playlist has no videos (or is private / unavailable).",
        )

    # Modest concurrency on Spotify search — /v1/search is a different bucket
    # than /v1/tracks so we have plenty of headroom, but still play nice.
    sem = asyncio.Semaphore(4)

    async def _bound(e: dict) -> YoutubeResolvedTrack:
        async with sem:
            return await _resolve_one(e)

    resolved = await asyncio.gather(*(_bound(e) for e in entries))

    video_ids = [t.video_id for t in resolved]
    q_rows = (
        await db.execute(
            select(FetchQueue.source_id).where(
                FetchQueue.source == "youtube",
                FetchQueue.source_id.in_(video_ids),
                FetchQueue.status.in_(["queued", "running"]),
            )
        )
    ).all()
    queued_set = {r[0] for r in q_rows}

    spotify_ids = [t.spotify_track_id for t in resolved if t.spotify_track_id]
    library_set: set[str] = set()
    if spotify_ids:
        l_rows = (
            await db.execute(
                select(SongMetadata.spotify_track_id).where(
                    SongMetadata.spotify_track_id.in_(spotify_ids)
                )
            )
        ).all()
        library_set = {r[0] for r in l_rows if r[0]}

    items = []
    for t in resolved:
        items.append(
            {
                **t.model_dump(),
                "already_queued": t.video_id in queued_set,
                "already_in_library": bool(
                    t.spotify_track_id and t.spotify_track_id in library_set
                ),
            }
        )

    return {
        "found": len(entries),
        "matched": sum(1 for t in resolved if t.matched),
        "queued_count": sum(1 for it in items if it["already_queued"]),
        "library_count": sum(1 for it in items if it["already_in_library"]),
        "tracks": items,
    }


@router.post("/import", status_code=status.HTTP_202_ACCEPTED)
async def import_resolved(
    body: YoutubeEnqueueRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    if not user.can_fetch:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have fetch permission")

    video_ids = [t.video_id for t in body.tracks]
    q_rows = (
        await db.execute(
            select(FetchQueue.source_id).where(
                FetchQueue.source == "youtube",
                FetchQueue.source_id.in_(video_ids),
                FetchQueue.status.in_(["queued", "running"]),
            )
        )
    ).all()
    queued_set = {r[0] for r in q_rows}

    spotify_ids = [t.spotify_track_id for t in body.tracks if t.spotify_track_id]
    library_set: set[str] = set()
    if spotify_ids:
        l_rows = (
            await db.execute(
                select(SongMetadata.spotify_track_id).where(
                    SongMetadata.spotify_track_id.in_(spotify_ids)
                )
            )
        ).all()
        library_set = {r[0] for r in l_rows if r[0]}

    enqueued = 0
    skipped_queued = 0
    skipped_library = 0
    new_rows: list[FetchQueue] = []
    for t in body.tracks:
        if t.spotify_track_id and t.spotify_track_id in library_set:
            skipped_library += 1
            continue
        if t.video_id in queued_set:
            skipped_queued += 1
            continue
        new_rows.append(
            FetchQueue(
                source="youtube",
                source_id=t.video_id,
                spotify_track_id=t.spotify_track_id,
                track_name=t.track_name or t.youtube_title or "Unknown",
                artist_name=t.artist_name or "Unknown",
                album_name=t.album_name or "",
                cover_url=t.cover_url,
                requester_id=user.id,
            )
        )
        queued_set.add(t.video_id)
        enqueued += 1

    if new_rows:
        db.add_all(new_rows)
        await db.commit()
        for r in new_rows:
            await publish(
                "queue:added",
                {
                    "id": r.id,
                    "source": r.source,
                    "source_id": r.source_id,
                    "spotify_track_id": r.spotify_track_id,
                    "track_name": r.track_name,
                    "artist_name": r.artist_name,
                    "album_name": r.album_name,
                    "cover_url": r.cover_url,
                    "requester_id": r.requester_id,
                    "requester_username": user.username,
                    "status": r.status,
                    "progress": 0,
                    "error_message": None,
                    "attempts": 0,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "started_at": None,
                    "completed_at": None,
                },
            )

    return {
        "enqueued": enqueued,
        "skipped_queued": skipped_queued,
        "skipped_library": skipped_library,
    }
