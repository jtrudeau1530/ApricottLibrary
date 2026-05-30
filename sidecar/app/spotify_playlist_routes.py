import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import FetchQueue, SongMetadata, User
from .sessions import require_session
from .spotify import spotify
from .sse_hub import publish

log = logging.getLogger("spotify_playlists")
router = APIRouter(prefix="/api/spotify/playlists", tags=["spotify-playlists"])


@router.get("")
async def list_my_playlists(
    limit: int = Query(50, ge=1, le=50),
    offset: int = Query(0, ge=0),
    _user: User = Depends(require_session),
) -> dict:
    return await spotify.list_user_playlists(limit=limit, offset=offset)


@router.get("/debug/{playlist_id}")
async def debug_playlist(
    playlist_id: str,
    _user: User = Depends(require_session),
) -> dict:
    """Try several variations of the tracks call so we can see which Spotify rejects."""
    import httpx as _httpx
    from .auth import get_user_access_token

    token = await get_user_access_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    out: dict = {}
    async with _httpx.AsyncClient(timeout=10.0) as client:
        # 1) Playlist metadata
        meta = await client.get(
            f"https://api.spotify.com/v1/playlists/{playlist_id}", headers=headers
        )
        out["meta"] = {
            "status": meta.status_code,
            "body": meta.text[:400],
            "owner": (meta.json().get("owner") if meta.status_code == 200 else None),
        }
        # 2) Tracks with market=from_token (what we currently use)
        t1 = await client.get(
            f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
            params={"limit": "10", "market": "from_token"},
            headers=headers,
        )
        out["tracks_with_market_from_token"] = {"status": t1.status_code, "body": t1.text[:400]}
        # 3) Tracks with explicit market=US
        t2 = await client.get(
            f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
            params={"limit": "10", "market": "US"},
            headers=headers,
        )
        out["tracks_with_market_US"] = {"status": t2.status_code, "body": t2.text[:400]}
        # 4) Tracks with no market
        t3 = await client.get(
            f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
            params={"limit": "10"},
            headers=headers,
        )
        out["tracks_no_market"] = {"status": t3.status_code, "body": t3.text[:400]}
        # 5) Tracks with minimal fields requested
        t4 = await client.get(
            f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
            params={"limit": "10", "fields": "items(track(id,name))"},
            headers=headers,
        )
        out["tracks_with_fields"] = {"status": t4.status_code, "body": t4.text[:400]}
    out["token_prefix"] = token[:12] + "…"
    return out


@router.get("/{playlist_id}/tracks")
async def list_playlist_tracks(
    playlist_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    playlist = await spotify.get_playlist(playlist_id)
    if playlist is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist not found")
    tracks = await spotify.get_playlist_tracks(playlist_id)

    # Annotate each track with whether it's already queued or in the library.
    track_ids = [t["id"] for t in tracks if t.get("id")]
    queued_ids: set[str] = set()
    in_library_ids: set[str] = set()
    if track_ids:
        q_rows = (
            await db.execute(
                select(FetchQueue.spotify_track_id).where(
                    FetchQueue.spotify_track_id.in_(track_ids),
                    FetchQueue.status.in_(["queued", "running"]),
                )
            )
        ).all()
        queued_ids = {r[0] for r in q_rows}

        l_rows = (
            await db.execute(
                select(SongMetadata.spotify_track_id).where(
                    SongMetadata.spotify_track_id.in_(track_ids)
                )
            )
        ).all()
        in_library_ids = {r[0] for r in l_rows if r[0]}

    annotated = [
        {**t, "already_queued": t["id"] in queued_ids, "already_in_library": t["id"] in in_library_ids}
        for t in tracks
    ]
    return {
        "playlist": playlist,
        "count": len(annotated),
        "queued_count": sum(1 for t in annotated if t["already_queued"]),
        "library_count": sum(1 for t in annotated if t["already_in_library"]),
        "items": annotated,
    }


@router.post("/{playlist_id}/import", status_code=status.HTTP_202_ACCEPTED)
async def import_playlist(
    playlist_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    if not user.can_fetch:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have fetch permission")
    tracks = await spotify.get_playlist_tracks(playlist_id)
    if not tracks:
        return {"enqueued": 0, "skipped_queued": 0, "skipped_library": 0}

    track_ids = [t["id"] for t in tracks if t.get("id")]

    queued_set: set[str] = set()
    if track_ids:
        queued_set = {
            r[0]
            for r in (
                await db.execute(
                    select(FetchQueue.spotify_track_id).where(
                        FetchQueue.spotify_track_id.in_(track_ids),
                        FetchQueue.status.in_(["queued", "running"]),
                    )
                )
            ).all()
        }

    library_set: set[str] = set()
    if track_ids:
        library_set = {
            r[0]
            for r in (
                await db.execute(
                    select(SongMetadata.spotify_track_id).where(
                        SongMetadata.spotify_track_id.in_(track_ids)
                    )
                ).all()
            )
            if r[0]
        }

    enqueued = 0
    skipped_queued = 0
    skipped_library = 0
    new_rows: list[FetchQueue] = []
    for t in tracks:
        sid = t.get("id")
        if not sid:
            continue
        if sid in library_set:
            skipped_library += 1
            continue
        if sid in queued_set:
            skipped_queued += 1
            continue
        new_rows.append(
            FetchQueue(
                spotify_track_id=sid,
                track_name=t.get("name") or "",
                artist_name=(t.get("artists") or ["Unknown"])[0] if t.get("artists") else "Unknown",
                album_name=t.get("album") or "",
                cover_url=t.get("cover_url"),
                requester_id=user.id,
            )
        )
        queued_set.add(sid)  # avoid duplicates within the same playlist
        enqueued += 1

    if new_rows:
        db.add_all(new_rows)
        await db.commit()
        for r in new_rows:
            await publish(
                "queue:added",
                {
                    "id": r.id,
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
        "total_in_playlist": len(tracks),
    }
