import logging

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import User
from .security import hash_password

log = logging.getLogger("admin_provision")


async def ensure_master_admin() -> None:
    """Create the master admin from env vars if no admin exists yet.

    Fail-safe: if env vars look like placeholders or missing entirely on a
    fresh DB, raise — refusing to start an insecure stack.
    """
    if not settings.apricot_admin_username or not settings.apricot_admin_password:
        raise RuntimeError(
            "APRICOT_ADMIN_USERNAME and APRICOT_ADMIN_PASSWORD must be set on first boot."
        )

    async with SessionLocal() as db:
        rows = (await db.execute(select(User))).scalars().all()
        if any(u.is_admin for u in rows):
            log.info("Master admin already present; skipping provisioning.")
            return

        # Refuse the default placeholder in production-shaped deploys.
        if settings.apricot_admin_password == "change-me-on-first-boot" and settings.session_cookie_secure:
            raise RuntimeError(
                "APRICOT_ADMIN_PASSWORD is still the placeholder. "
                "Set a real password before first boot in a secure environment."
            )

        admin = User(
            username=settings.apricot_admin_username,
            password_hash=hash_password(settings.apricot_admin_password),
            permissions={"is_admin": True, "can_fetch": True, "can_edit_metadata": True},
        )
        db.add(admin)
        await db.commit()
        log.warning(
            "Master admin '%s' provisioned. Change the password via the admin UI ASAP.",
            settings.apricot_admin_username,
        )
