"""Async Alembic environment for the rebuild backend.

The metadata that Alembic compares against is ``app.db.base.Base.metadata``;
the ORM modules under ``app.models`` register their tables on it at import
time. The database URL is read from
``app.core.config.settings.DATABASE_URL``.

Both ``app.core.config`` and ``app.models.*`` imports are deferred to call
time so this module can be parsed and imported even before the
fastapi-engineer dispatch lands ``app/core/config.py``, ``app/core/ids.py``,
and ``app/core/time.py`` (those resolve at the moment `alembic upgrade head`
is invoked, which is after every dispatch in M0 has run).
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from app.db.base import Base
from sqlalchemy import MetaData, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, async_engine_from_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _settings_url() -> str:
    """Resolve the SQLAlchemy URL from the project Settings at call time.

    Deferred import: depends on app.core.config from fastapi-engineer dispatch.
    """
    from app.core.config import settings

    return settings.DATABASE_URL


def _target_metadata() -> MetaData:
    """Import every ORM module so its tables register on ``Base.metadata``.

    The import lives inside the function (rather than at module load) so the
    env file remains importable in isolation — the user model imports
    ``app.core.ids`` / ``app.core.time``, which are landed by a later
    dispatch in M0.
    """
    import app.models  # noqa: F401  # registers User et al. on Base.metadata

    return Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (URL only, no DB connection)."""
    context.configure(
        url=_settings_url(),
        target_metadata=_target_metadata(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=_target_metadata())
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations against a live async asyncmy engine.

    When ``DATABASE_IAM_AUTH=True`` (Aurora MySQL behind IRSA in
    staging/prod), the same ``do_connect`` hook used by the runtime
    engine is registered on this Alembic engine's sync side — see
    :mod:`app.core.iam_auth`. The migration Job authenticates as
    ``settings.DATABASE_IAM_AUTH_MIGRATE_USER`` (a separate setting from
    ``DATABASE_IAM_AUTH_USER`` so the future least-privilege split lands
    as a values-file change, not a code change — see
    ``database-best-practises.md`` § B.9). Today both env vars hold the
    same single IAM user with ``ALL PRIVILEGES``; the helper picks AWS
    credentials up from the standard boto3 chain so no Job-side
    branching is needed.
    """
    from app.core.config import settings
    from app.core.iam_auth import attach_iam_auth_to_engine, is_iam_auth_enabled

    section = dict(config.get_section(config.config_ini_section, {}) or {})
    section["sqlalchemy.url"] = _settings_url()
    engine: AsyncEngine = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    if is_iam_auth_enabled():
        attach_iam_auth_to_engine(
            engine,
            dialect="mysql",
            user=settings.DATABASE_IAM_AUTH_MIGRATE_USER,
        )
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
