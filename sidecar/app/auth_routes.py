from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .models import User
from .security import verify_password
from .sessions import (
    clear_session_cookie,
    create_session,
    destroy_session,
    require_session,
    set_session_cookie,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=255)


class UserOut(BaseModel):
    id: str
    username: str
    is_admin: bool
    permissions: dict


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        permissions=user.permissions or {},
    )


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if user is None or user.disabled or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    existing = request.cookies.get("apricot_session")
    if existing:
        await destroy_session(db, existing)

    sess = await create_session(db, user)
    set_session_cookie(response, sess.id)
    return {"user": _user_out(user).model_dump()}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_session),
) -> dict:
    token = request.cookies.get("apricot_session")
    if token:
        await destroy_session(db, token)
    clear_session_cookie(response)
    return {"status": "logged_out"}


@router.get("/me")
async def me(user: User = Depends(require_session)) -> dict:
    return {"user": _user_out(user).model_dump()}
