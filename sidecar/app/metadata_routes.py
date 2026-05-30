import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from mutagen import File as MutagenFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import jellyfin
from .db import get_db
from .models import SongMetadata, User
from .sessions import require_session

log = logging.getLogger("metadata")
router = APIRouter(prefix="/api/catalog/tracks", tags=["metadata"])


class MetadataPatch(BaseModel):
    title: str | None = Field(default=None, max_length=512)
    artist: str | None = Field(default=None, max_length=512)
    album: str | None = Field(default=None, max_length=512)
    description: str | None = Field(default=None, max_length=4000)


def _write_tags(file_path: Path, patch: MetadataPatch) -> bool:
    if not file_path.exists():
        log.warning("File %s does not exist; skipping mutagen write.", file_path)
        return False
    try:
        audio = MutagenFile(file_path, easy=True)
        if audio is None:
            log.warning("Mutagen can't parse %s", file_path)
            return False
        if patch.title is not None:
            audio["title"] = patch.title
        if patch.artist is not None:
            audio["artist"] = patch.artist
        if patch.album is not None:
            audio["album"] = patch.album
        audio.save()
        return True
    except Exception as exc:
        log.exception("mutagen write failed for %s: %s", file_path, exc)
        return False


@router.patch("/{item_id}")
async def update_track_metadata(
    item_id: str,
    patch: MetadataPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    if not user.can_edit_metadata:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have edit-metadata permission")

    current = await jellyfin.get_track(item_id)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Track not found")

    # 1. Persist to Postgres — source of truth that survives Jellyfin rescans.
    existing = (
        await db.execute(select(SongMetadata).where(SongMetadata.jellyfin_item_id == item_id))
    ).scalar_one_or_none()
    if existing is None:
        existing = SongMetadata(jellyfin_item_id=item_id)
        db.add(existing)
    if patch.title is not None:
        existing.title = patch.title
    if patch.artist is not None:
        existing.artist = patch.artist
    if patch.album is not None:
        existing.album = patch.album
    if patch.description is not None:
        existing.description = patch.description
    existing.updated_by = user.id
    await db.commit()

    # 2. Write file tags via mutagen — survives Jellyfin rescans that ignore item-level locks.
    file_path_str = current.get("path")
    tags_written = False
    if file_path_str:
        tags_written = _write_tags(Path(file_path_str), patch)

    # 3. Update Jellyfin with LockData=true.
    raw = current.get("_raw") or {}
    if patch.title is not None:
        raw["Name"] = patch.title
    if patch.artist is not None:
        raw["Artists"] = [patch.artist]
    if patch.album is not None:
        raw["Album"] = patch.album
    if patch.description is not None:
        raw["Overview"] = patch.description
    raw["LockData"] = True
    jellyfin_ok = await jellyfin.update_metadata(item_id, raw)

    return {
        "status": "ok",
        "postgres_persisted": True,
        "tags_written": tags_written,
        "jellyfin_updated": jellyfin_ok,
    }
