from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_db
from .models import Session, User


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_session(db: AsyncSession, user: User) -> Session:
    token = token_urlsafe(32)
    sess = Session(
        id=token,
        user_id=user.id,
        expires_at=_now() + timedelta(days=settings.session_ttl_days),
    )
    db.add(sess)
    await db.commit()
    return sess


async def destroy_session(db: AsyncSession, token: str) -> None:
    await db.execute(delete(Session).where(Session.id == token))
    await db.commit()


async def destroy_user_sessions(db: AsyncSession, user_id: str) -> None:
    await db.execute(delete(Session).where(Session.user_id == user_id))
    await db.commit()


def set_session_cookie(response: Response, token: str) -> None:
    # Library's SvelteKit frontend takes the token out of this Set-Cookie
    # via regex and re-issues the browser cookie itself (host-only on
    # library.zektek.us) - the browser never sees this header directly,
    # only the sidecar's server-to-server response does. So the Domain
    # attribute here is effectively dead weight, but kept for clarity
    # and in case a future client talks straight to api.library.zektek.us.
    # Do NOT emit a second Set-Cookie alongside this one (e.g. a
    # host-only delete to evict a legacy cookie): Node's
    # Headers.get('set-cookie') in the SvelteKit action only returns the
    # first Set-Cookie value, so any extra header before this one wins
    # the regex and login silently breaks.
    domain = settings.session_cookie_domain or None
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
        domain=domain,
        max_age=settings.session_ttl_days * 86400,
    )


def clear_session_cookie(response: Response) -> None:
    # Mirrors set_session_cookie - one Set-Cookie header only, matching
    # the Domain attribute used on the way in.
    domain = settings.session_cookie_domain or None
    response.delete_cookie(
        settings.session_cookie_name, path="/", domain=domain
    )


async def _load_user_from_cookie(request: Request, db: AsyncSession) -> User | None:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    row = await db.execute(
        select(Session, User).join(User, Session.user_id == User.id).where(Session.id == token)
    )
    pair = row.first()
    if pair is None:
        return None
    sess, user = pair
    if sess.expires_at < _now() or user.disabled:
        return None
    return user


async def require_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await _load_user_from_cookie(request, db)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


async def require_admin(user: User = Depends(require_session)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user


async def optional_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    return await _load_user_from_cookie(request, db)
