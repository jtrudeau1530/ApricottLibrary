from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import User
from .security import hash_password
from .sessions import destroy_user_sessions, require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])


class UserOut(BaseModel):
    id: str
    username: str
    disabled: bool
    is_admin: bool
    permissions: dict
    created_at: datetime


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=255)
    is_admin: bool = False
    can_fetch: bool = True
    can_edit_metadata: bool = False


class UserPatch(BaseModel):
    password: str | None = Field(default=None, min_length=6, max_length=255)
    disabled: bool | None = None
    is_admin: bool | None = None
    can_fetch: bool | None = None
    can_edit_metadata: bool | None = None


def _user_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        username=u.username,
        disabled=u.disabled,
        is_admin=u.is_admin,
        permissions=u.permissions or {},
        created_at=u.created_at,
    )


@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    rows = (await db.execute(select(User).order_by(User.created_at.asc()))).scalars().all()
    return {"count": len(rows), "items": [_user_out(u).model_dump() for u in rows]}


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    existing = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        permissions={
            "is_admin": body.is_admin,
            "can_fetch": body.can_fetch,
            "can_edit_metadata": body.can_edit_metadata,
        },
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _user_out(user).model_dump()


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UserPatch,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == admin.id and body.disabled is True:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't disable yourself")
    if body.password is not None:
        user.password_hash = hash_password(body.password)
        await destroy_user_sessions(db, user.id)
    if body.disabled is not None:
        user.disabled = body.disabled
        if body.disabled:
            await destroy_user_sessions(db, user.id)
    perms = dict(user.permissions or {})
    if body.is_admin is not None:
        perms["is_admin"] = body.is_admin
    if body.can_fetch is not None:
        perms["can_fetch"] = body.can_fetch
    if body.can_edit_metadata is not None:
        perms["can_edit_metadata"] = body.can_edit_metadata
    user.permissions = perms
    await db.commit()
    await db.refresh(user)
    return _user_out(user).model_dump()


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> None:
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't delete yourself")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    await db.delete(user)
    await db.commit()
