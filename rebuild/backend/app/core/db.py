"""Async engine + session factory + FastAPI dependency.

The engine is process-scoped and constructed at import time. Routers reach
the session via the :data:`app.core.deps.DbSession` Annotated alias, which
wraps :func:`get_session`. ``/readyz`` opens a session directly via
:data:`AsyncSessionLocal` to avoid pulling auth into an unauthenticated infra
endpoint.

When ``settings.database_iam_auth`` is on (production Aurora MySQL), a
``do_connect`` listener on the engine's sync core mints a fresh RDS IAM
auth token per physical connection — see :mod:`app.core.iam_auth` and
``rebuild/docs/plans/m0-foundations.md`` § IAM database authentication.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.iam_auth import attach_iam_auth_to_engine, is_iam_auth_enabled

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_pool_max_overflow,
    pool_recycle=settings.db_pool_recycle_seconds,
    pool_pre_ping=True,
    future=True,
)

if is_iam_auth_enabled():
    # MySQL is the rebuild's only target (rebuild.md §2); the dialect
    # arg is named for symmetry with the legacy fork's helper signature.
    # The runtime engine authenticates as database_iam_auth_user (a
    # separate setting from database_iam_auth_migrate_user so the
    # migration Job can later move to a higher-privilege IAM user
    # without touching code — see rebuild/docs/best-practises/database-best-practises.md § B.9).
    attach_iam_auth_to_engine(engine, dialect="mysql", user=settings.database_iam_auth_user)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped ``AsyncSession``; closes on response send."""
    async with AsyncSessionLocal() as session:
        yield session
