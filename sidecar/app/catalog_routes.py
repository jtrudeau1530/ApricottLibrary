import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response

from . import jellyfin
from .config import settings
from .models import User
from .sessions import require_session

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("/tracks")
async def list_tracks(
    sort: str = Query("added", pattern="^(title|artist|album|added|duration)$"),
    descending: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, max_length=200),
    _user: User = Depends(require_session),
) -> dict:
    return await jellyfin.list_tracks(
        sort=sort, descending=descending, limit=limit, offset=offset, search=search
    )


@router.get("/tracks/{item_id}")
async def get_track(item_id: str, _user: User = Depends(require_session)) -> dict:
    item = await jellyfin.get_track(item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Track not found")
    return item


async def _proxy_image(url: str) -> Response:
    headers = {"X-Emby-Token": settings.jellyfin_api_key}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code != 200:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not available")
    media_type = resp.headers.get("content-type") or "image/jpeg"
    return Response(
        content=resp.content, media_type=media_type, headers={"Cache-Control": "public, max-age=3600"}
    )


@router.get("/cover/{item_id}")
async def cover(
    item_id: str,
    max_width: int = Query(300, ge=64, le=1600),
    _user: User = Depends(require_session),
) -> Response:
    return await _proxy_image(jellyfin.cover_url(item_id, max_width=max_width))


@router.get("/backdrop/{item_id}")
async def backdrop(
    item_id: str,
    max_width: int = Query(1600, ge=320, le=2400),
    _user: User = Depends(require_session),
) -> Response:
    return await _proxy_image(jellyfin.backdrop_url(item_id, max_width=max_width))


@router.get("/logo/{item_id}")
async def logo(
    item_id: str,
    max_width: int = Query(800, ge=120, le=1200),
    _user: User = Depends(require_session),
) -> Response:
    return await _proxy_image(jellyfin.logo_url(item_id, max_width=max_width))


@router.get("/song/{item_id}")
async def song_view(item_id: str, _user: User = Depends(require_session)) -> dict:
    view = await jellyfin.get_song_view(item_id)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Track not found")
    return view
