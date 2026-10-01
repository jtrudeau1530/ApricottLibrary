"""Read-only catalog contract for any consumer; Library never creates stations."""

import asyncio
import hmac
from pathlib import Path
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from .config import settings
from . import jellyfin
from .db import SessionLocal
from .models import SongMetadata
from .track_matching import media_file, probe

router = APIRouter(prefix="/api/consumer/catalog", tags=["consumer catalog"])


async def require_consumer(authorization: str | None = Header(default=None)):
    if not settings.library_catalog_token:
        raise HTTPException(503, "Consumer catalog token is not configured")
    if (
        not authorization
        or not authorization.startswith("Bearer ")
        or not hmac.compare_digest(
            authorization.removeprefix("Bearer "), settings.library_catalog_token
        )
    ):
        raise HTTPException(401, "Invalid consumer catalog token")


@router.get("", dependencies=[Depends(require_consumer)])
async def catalog(
    limit: int = Query(500, ge=1, le=500), offset: int = Query(0, ge=0, le=100000)
):
    page = await jellyfin.list_tracks(
        limit=limit, offset=offset, sort="title", descending=False, strict=True
    )
    async with SessionLocal() as db:
        overrides = {
            m.jellyfin_item_id: m
            for m in (
                await db.scalars(
                    select(SongMetadata).where(
                        SongMetadata.jellyfin_item_id.in_(
                            [i["id"] for i in page["items"]]
                        )
                    )
                )
            ).all()
        }
    items = []
    for item in page["items"]:
        safe = media_file(item.get("path") or "", settings.media_path)
        if not safe or not item.get("duration_seconds"):
            continue
        meta = await asyncio.to_thread(probe, safe)
        if not meta:
            continue
        if not item.get("genre"):
            item["genre"] = "; ".join(meta.get("genres") or [])
        override = overrides.get(item["id"])
        for field in ("title", "artist", "album"):
            if override and getattr(override, field):
                item[field] = getattr(override, field)
        items.append(
            {
                k: item.get(k)
                for k in ("id", "title", "artist", "album", "genre", "duration_seconds")
            }
            | {
                "relative_path": safe.relative_to(
                    Path(settings.media_path).resolve()
                ).as_posix()
            }
        )
    return {
        "items": items,
        "total": page["total"],
        "next_offset": offset + len(page["items"]),
    }
