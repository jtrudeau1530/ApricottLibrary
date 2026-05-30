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


@router.get("/cover/{item_id}")
async def cover(
    item_id: str,
    max_width: int = Query(300, ge=64, le=1200),
    _user: User = Depends(require_session),
) -> Response:
    url = jellyfin.cover_url(item_id, max_width=max_width)
    headers = {"X-Emby-Token": settings.jellyfin_api_key}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code != 200:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cover not available")
    media_type = resp.headers.get("content-type") or "image/jpeg"
    return Response(content=resp.content, media_type=media_type, headers={"Cache-Control": "public, max-age=3600"})
