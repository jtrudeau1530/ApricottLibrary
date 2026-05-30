from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import Playlist, PlaylistItem, User
from .sessions import require_admin, require_session

router = APIRouter(prefix="/api/playlists", tags=["playlists"])


class PlaylistOut(BaseModel):
    id: str
    name: str
    owner_id: str | None
    owner_username: str | None
    song_count: int
    cover_url: str | None
    created_at: datetime
    updated_at: datetime


class PlaylistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    is_global: bool = False


class PlaylistItemAdd(BaseModel):
    jellyfin_item_id: str = Field(min_length=1, max_length=64)


def _can_edit(playlist: Playlist, user: User) -> bool:
    if playlist.owner_id is None:  # global
        return user.is_admin
    return playlist.owner_id == user.id or user.is_admin


@router.get("")
async def list_playlists(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    """Visible playlists: globals + the viewer's own."""
    q = (
        select(
            Playlist,
            User.username.label("owner_username"),
            func.count(PlaylistItem.id).label("song_count"),
        )
        .outerjoin(User, Playlist.owner_id == User.id)
        .outerjoin(PlaylistItem, PlaylistItem.playlist_id == Playlist.id)
        .where(or_(Playlist.owner_id.is_(None), Playlist.owner_id == user.id))
        .group_by(Playlist.id, User.username)
        .order_by(Playlist.updated_at.desc())
    )
    rows = (await db.execute(q)).all()
    items = [
        PlaylistOut(
            id=p.id,
            name=p.name,
            owner_id=p.owner_id,
            owner_username=owner_username,
            song_count=song_count,
            cover_url=None,
            created_at=p.created_at,
            updated_at=p.updated_at,
        ).model_dump()
        for (p, owner_username, song_count) in rows
    ]
    return {"count": len(items), "items": items}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_playlist(
    body: PlaylistCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    if body.is_global and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can create global playlists")
    playlist = Playlist(name=body.name, owner_id=None if body.is_global else user.id)
    db.add(playlist)
    await db.commit()
    await db.refresh(playlist)
    return {
        "id": playlist.id,
        "name": playlist.name,
        "owner_id": playlist.owner_id,
        "is_global": playlist.owner_id is None,
    }


@router.get("/{playlist_id}")
async def get_playlist(
    playlist_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    p = (await db.execute(select(Playlist).where(Playlist.id == playlist_id))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist not found")
    if p.owner_id is not None and p.owner_id != user.id and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your playlist")
    items_rows = (
        await db.execute(
            select(PlaylistItem)
            .where(PlaylistItem.playlist_id == playlist_id)
            .order_by(PlaylistItem.position.asc(), PlaylistItem.added_at.asc())
        )
    ).scalars().all()
    return {
        "id": p.id,
        "name": p.name,
        "owner_id": p.owner_id,
        "is_global": p.owner_id is None,
        "items": [
            {"id": it.id, "jellyfin_item_id": it.jellyfin_item_id, "position": it.position}
            for it in items_rows
        ],
    }


@router.post("/{playlist_id}/items", status_code=status.HTTP_201_CREATED)
async def add_item(
    playlist_id: str,
    body: PlaylistItemAdd,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    p = (await db.execute(select(Playlist).where(Playlist.id == playlist_id))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist not found")
    if not _can_edit(p, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't edit this playlist")
    pos = (
        await db.execute(
            select(func.coalesce(func.max(PlaylistItem.position), -1) + 1).where(
                PlaylistItem.playlist_id == playlist_id
            )
        )
    ).scalar_one()
    item = PlaylistItem(playlist_id=playlist_id, jellyfin_item_id=body.jellyfin_item_id, position=pos)
    db.add(item)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Already in playlist")
    return {"id": item.id, "position": item.position}


@router.delete("/{playlist_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_item(
    playlist_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_session),
) -> None:
    p = (await db.execute(select(Playlist).where(Playlist.id == playlist_id))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist not found")
    if not _can_edit(p, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't edit this playlist")
    await db.execute(
        delete(PlaylistItem).where(
            PlaylistItem.playlist_id == playlist_id, PlaylistItem.id == item_id
        )
    )
    await db.commit()


@router.delete("/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_playlist(
    playlist_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_session),
) -> None:
    p = (await db.execute(select(Playlist).where(Playlist.id == playlist_id))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist not found")
    if not _can_edit(p, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't edit this playlist")
    await db.execute(delete(Playlist).where(Playlist.id == playlist_id))
    await db.commit()
