import asyncio
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import FetchQueue, SongMetadata, User
from .sessions import require_session
from .spotify import spotify
from .sse_hub import publish

log = logging.getLogger("spotify_playlists")
router = APIRouter(prefix="/api/spotify/playlists", tags=["spotify-playlists"])

paste_router = APIRouter(prefix="/api/spotify/paste", tags=["spotify-paste"])

# Matches "track:abc123…" "track/abc123…" "tracks/abc123…" forms anywhere.
# Spotify IDs are base62, always 22 chars.
_TRACK_ID_RE = re.compile(r"track[s/:]([A-Za-z0-9]{22})")
# Standalone bare 22-char IDs on their own line.
_BARE_ID_RE = re.compile(r"(?:^|[^A-Za-z0-9])([A-Za-z0-9]{22})(?=[^A-Za-z0-9]|$)")


def _extract_track_ids(text: str) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for m in _TRACK_ID_RE.finditer(text):
        tid = m.group(1)
        if tid not in seen:
            seen.add(tid)
            ids.append(tid)
    # Only consider bare-22-char matches if we found nothing via track/ pattern,
    # to avoid false positives from album IDs, playlist IDs, etc.
    if not ids:
        for m in _BARE_ID_RE.finditer(text):
            tid = m.group(1)
            if tid not in seen:
                seen.add(tid)
                ids.append(tid)
    return ids


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
        # 1) Playlist metadata — full body so we can inspect tracks.items
        meta = await client.get(
            f"https://api.spotify.com/v1/playlists/{playlist_id}",
            params={"market": "from_token"},
            headers=headers,
        )
        meta_json = meta.json() if meta.status_code == 200 else None
        tracks_block = (meta_json or {}).get("tracks") or {}
        items = tracks_block.get("items") or []
        out["meta"] = {
            "status": meta.status_code,
            "owner": (meta_json or {}).get("owner"),
            "track_total": tracks_block.get("total"),
            "items_in_response": len(items),
            "first_item_keys": list(items[0].keys()) if items else None,
            "first_item_track_id": ((items[0] or {}).get("track") or {}).get("id") if items else None,
            "first_item_track_name": ((items[0] or {}).get("track") or {}).get("name") if items else None,
            "tracks_next": tracks_block.get("next"),
            "body_preview": meta.text[:600],
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


class PasteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)


class ResolvedTrack(BaseModel):
    id: str
    name: str
    artists: list[str] = Field(default_factory=list)
    album: str | None = None
    cover_url: str | None = None


class EnqueueResolvedRequest(BaseModel):
    tracks: list[ResolvedTrack] = Field(min_length=1, max_length=1000)


async def _resolve_tracks(
    track_ids: list[str],
) -> tuple[list[dict], list[str], dict[str, int]]:
    """Resolve track metadata for each ID via Spotify's singular /v1/tracks/{id}.

    Spotify's batch /v1/tracks?ids=... endpoint is gated behind Extended Quota
    (returns 403 for Development-mode apps), but the singular endpoint is still
    open. We trade RPS for actually getting data.

    Returns (tracks, missing_ids, error_counts). error_counts maps the upstream
    Spotify status (or a short label like ``"exception"``) to how many ids hit
    it, so the UI can tell rate-limit (429) apart from quota (403) apart from
    genuinely-unknown (404).
    """
    results: list[dict] = []
    missing: list[str] = []
    error_counts: dict[str, int] = {}

    def _bump(label: str) -> None:
        error_counts[label] = error_counts.get(label, 0) + 1

    async def _one(tid: str) -> None:
        try:
            tr = await spotify.get_track(tid)
            if tr is None:
                missing.append(tid)
                _bump("404")
            else:
                results.append(tr)
        except HTTPException as exc:
            log.warning("Failed to resolve %s: %s %s", tid, exc.status_code, exc.detail)
            missing.append(tid)
            _bump(str(exc.status_code))
        except Exception as exc:  # pragma: no cover
            log.warning("Failed to resolve %s: %s", tid, exc)
            missing.append(tid)
            _bump("exception")

    # Concurrency=2 + per-call spacing keeps us well under Spotify's burst limit.
    sem = asyncio.Semaphore(2)

    async def _bound(tid: str) -> None:
        async with sem:
            await _one(tid)
            await asyncio.sleep(0.15)

    await asyncio.gather(*(_bound(t) for t in track_ids))
    by_id = {t["id"]: t for t in results}
    ordered = [by_id[t] for t in track_ids if t in by_id]
    return ordered, missing, error_counts


@paste_router.post("/preview")
async def paste_preview(
    body: PasteRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_session),
) -> dict:
    ids = _extract_track_ids(body.text)
    if not ids:
        return {
            "found_ids": 0,
            "tracks": [],
            "missing_ids": [],
            "queued_count": 0,
            "library_count": 0,
            "error_counts": {},
        }

    tracks, missing, error_counts = await _resolve_tracks(ids)
    resolved_ids = [t["id"] for t in tracks]

    queued_set: set[str] = set()
    library_set: set[str] = set()
    if resolved_ids:
        q_rows = (
            await db.execute(
                select(FetchQueue.spotify_track_id).where(
                    FetchQueue.spotify_track_id.in_(resolved_ids),
                    FetchQueue.status.in_(["queued", "running"]),
                )
            )
        ).all()
        queued_set = {r[0] for r in q_rows}

        l_rows = (
            await db.execute(
                select(SongMetadata.spotify_track_id).where(
                    SongMetadata.spotify_track_id.in_(resolved_ids)
                )
            )
        ).all()
        library_set = {r[0] for r in l_rows if r[0]}

    annotated = [
        {
            **t,
            "already_queued": t["id"] in queued_set,
            "already_in_library": t["id"] in library_set,
        }
        for t in tracks
    ]
    return {
        "found_ids": len(ids),
        "resolved_count": len(annotated),
        "missing_ids": missing,
        "queued_count": sum(1 for t in annotated if t["already_queued"]),
        "library_count": sum(1 for t in annotated if t["already_in_library"]),
        "tracks": annotated,
        "error_counts": error_counts,
    }


@paste_router.post("/enqueue", status_code=status.HTTP_202_ACCEPTED)
async def paste_enqueue_resolved(
    body: EnqueueResolvedRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    """Enqueue tracks already resolved by /preview. Skips Spotify entirely — avoids
    rate-limiting when bulk-adding large lists."""
    if not user.can_fetch:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have fetch permission")

    track_ids = [t.id for t in body.tracks]
    q_rows = (
        await db.execute(
            select(FetchQueue.spotify_track_id).where(
                FetchQueue.spotify_track_id.in_(track_ids),
                FetchQueue.status.in_(["queued", "running"]),
            )
        )
    ).all()
    queued_set = {r[0] for r in q_rows}
    l_rows = (
        await db.execute(
            select(SongMetadata.spotify_track_id).where(
                SongMetadata.spotify_track_id.in_(track_ids)
            )
        )
    ).all()
    library_set = {r[0] for r in l_rows if r[0]}

    enqueued = 0
    skipped_queued = 0
    skipped_library = 0
    new_rows: list[FetchQueue] = []
    for t in body.tracks:
        if t.id in library_set:
            skipped_library += 1
            continue
        if t.id in queued_set:
            skipped_queued += 1
            continue
        new_rows.append(
            FetchQueue(
                spotify_track_id=t.id,
                track_name=t.name or "",
                artist_name=(t.artists[0] if t.artists else "Unknown"),
                album_name=t.album or "",
                cover_url=t.cover_url,
                requester_id=user.id,
            )
        )
        queued_set.add(t.id)
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
    }


@paste_router.post("/import", status_code=status.HTTP_202_ACCEPTED)
async def paste_import(
    body: PasteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    if not user.can_fetch:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have fetch permission")
    ids = _extract_track_ids(body.text)
    if not ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No Spotify track IDs found. Paste track URLs, URIs, or CSV from Exportify.",
        )

    tracks, missing, _error_counts = await _resolve_tracks(ids)
    track_ids = [t["id"] for t in tracks]
    if not track_ids:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Spotify failed to resolve any of {len(ids)} ids.",
        )

    q_rows = (
        await db.execute(
            select(FetchQueue.spotify_track_id).where(
                FetchQueue.spotify_track_id.in_(track_ids),
                FetchQueue.status.in_(["queued", "running"]),
            )
        )
    ).all()
    queued_set = {r[0] for r in q_rows}
    l_rows = (
        await db.execute(
            select(SongMetadata.spotify_track_id).where(
                SongMetadata.spotify_track_id.in_(track_ids)
            )
        )
    ).all()
    library_set = {r[0] for r in l_rows if r[0]}

    enqueued = 0
    skipped_queued = 0
    skipped_library = 0
    new_rows: list[FetchQueue] = []
    for t in tracks:
        sid = t["id"]
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
        queued_set.add(sid)
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
        "missing_ids": missing,
        "total_found": len(ids),
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
    library_set: set[str] = set()
    if track_ids:
        q_rows = (
            await db.execute(
                select(FetchQueue.spotify_track_id).where(
                    FetchQueue.spotify_track_id.in_(track_ids),
                    FetchQueue.status.in_(["queued", "running"]),
                )
            )
        ).all()
        queued_set = {r[0] for r in q_rows}

        l_rows = (
            await db.execute(
                select(SongMetadata.spotify_track_id).where(
                    SongMetadata.spotify_track_id.in_(track_ids)
                )
            )
        ).all()
        library_set = {r[0] for r in l_rows if r[0]}

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
