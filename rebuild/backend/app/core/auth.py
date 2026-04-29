"""Trusted-header auth — the only auth surface in the rebuild.

Two symbols, by design (see ``rebuild/docs/plans/m0-foundations.md`` § Trusted-
header dependency):

* :func:`upsert_user_from_headers` — pure async helper that owns the entire
  "trusted header → ``User`` row" contract. Called from the FastAPI
  dependency below and (in M4) from the socket.io ``connect`` handler, which
  is outside the FastAPI request lifecycle.
* :func:`get_user` — FastAPI ``Depends`` dependency. Reads the headers and
  delegates to the helper.

Both lowercase + URL-decode the email, optionally enforce
``settings.TRUSTED_EMAIL_DOMAIN_ALLOWLIST``, and use MySQL's
``INSERT ... ON DUPLICATE KEY UPDATE id = id`` for race-free idempotent
first-login on the unique-email constraint.
"""

from __future__ import annotations

from typing import Annotated, cast
from urllib.parse import unquote

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.models.user import User


async def upsert_user_from_headers(
    db: AsyncSession,
    *,
    email: str,
    name: str | None,
) -> User:
    """Look up or create a ``User`` from a trusted-proxy email + optional name.

    Steps:
      1. Lowercase + URL-decode the email.
      2. Enforce ``settings.TRUSTED_EMAIL_DOMAIN_ALLOWLIST`` if non-empty.
      3. Look up the row by ``email`` (the unique constraint).
      4. If absent, ``INSERT ... ON DUPLICATE KEY UPDATE id = id`` so the
         path is race-free under concurrent first-time logins.
      5. Re-select by email (MySQL doesn't reliably return the inserted row
         from an upsert) and commit.
    """
    email = unquote(email).strip().lower()
    if settings.TRUSTED_EMAIL_DOMAIN_ALLOWLIST:
        domain = email.split("@", 1)[1] if "@" in email else ""
        if domain not in settings.TRUSTED_EMAIL_DOMAIN_ALLOWLIST:
            raise HTTPException(status_code=401, detail="email domain not allowed")

    user = await db.scalar(select(User).where(User.email == email))
    if user is not None:
        return user

    display_name = unquote(name) if name else email
    stmt = (
        mysql_insert(User)
        .values(email=email, name=display_name)
        .on_duplicate_key_update(id=User.id)
    )
    await db.execute(stmt)
    await db.commit()

    user = await db.scalar(select(User).where(User.email == email))
    if user is None:  # pragma: no cover — would require a constraint violation
        raise HTTPException(status_code=500, detail="user upsert failed")
    # db.scalar(select(User)...) is typed Optional[Any] in SQLAlchemy 2's
    # generated stubs; cast to satisfy our strict no-Any-return rule.
    return cast(User, user)


# Cannot use DbSession alias here — app.core.deps imports get_user, so this
# would be a circular import. Inline Annotated[AsyncSession, Depends(get_session)]
# is the sanctioned exception. The grep gate in tests/test_no_bare_depends.py
# scopes to app/routers/ only, so this file is intentionally exempt.
async def get_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """FastAPI dependency: resolve the current ``User`` from trusted headers."""
    email = request.headers.get(settings.TRUSTED_EMAIL_HEADER)
    if not email:
        raise HTTPException(status_code=401, detail="missing trusted header")
    name = request.headers.get(settings.TRUSTED_NAME_HEADER)
    return await upsert_user_from_headers(db, email=email, name=name)
