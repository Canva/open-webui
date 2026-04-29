"""Shared fixtures for the backend test suite.

Anchors:

* ``mysql_container`` (session-scoped) — boots a real MySQL 8.0.39 via
  testcontainers with the project's pinned ``utf8mb4_0900_ai_ci`` collation.
  Heavy: ~one-time image pull, then ~5s spin-up. Subsequent fixtures
  (``database_url``, ``engine``) attach to it.
* ``engine`` (session-scoped) — async SQLAlchemy engine bound to the live
  container. Mutates ``app.core.config.settings.DATABASE_URL`` and rebinds
  the production singletons in ``app.core.db`` (and ``app.routers.health``,
  which copies ``AsyncSessionLocal`` at module load) so the FastAPI app +
  ``/readyz`` handler hit the testcontainer instead of the prod URL. Runs
  ``alembic upgrade head`` against the container before yielding.
* ``client`` (function-scoped) — ``httpx.AsyncClient`` bound via
  ``ASGITransport`` to the live FastAPI app. Overrides ``get_session`` to
  yield a session against the test engine.
* ``db_session`` (function-scoped) — direct ``AsyncSession`` for tests that
  need to read/write the DB outside the HTTP path.
* ``fake_redis`` (function-scoped) — ``fakeredis.aioredis.FakeRedis``
  monkey-patched onto ``redis.asyncio.Redis.from_url`` so ``/readyz``'s
  Redis check resolves without a real Redis container.
* ``override_settings`` (function-scoped) — context-manager + helper that
  patches fields on the ``settings`` singleton and restores them on exit.

Working directory: pytest is invoked from ``rebuild/`` (see ``Makefile``
``test-unit`` target). All file paths inside this conftest derive their
location from ``__file__`` so the suite works from any cwd a verifier may
choose.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

# Resolve filesystem anchors at import time so the suite works from any cwd.
HERE = Path(__file__).resolve().parent  # rebuild/backend/tests
BACKEND_DIR = HERE.parent  # rebuild/backend
REBUILD_ROOT = BACKEND_DIR.parent  # rebuild/
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
ALEMBIC_DIR = BACKEND_DIR / "alembic"


# Pre-set sane defaults BEFORE any `app.*` import so the import-time
# `settings = Settings()` call sees a stable env. Tests that need different
# values use `monkeypatch.setenv` and re-instantiate `Settings()`.
os.environ.setdefault("ENV", "test")


@pytest.fixture(scope="session")
def mysql_container() -> Iterator[Any]:
    """Boot mysql:8.0.39 with the project's utf8mb4_0900_ai_ci collation."""
    from testcontainers.mysql import MySqlContainer

    container = MySqlContainer("mysql:8.0.39").with_command(
        "--character-set-server=utf8mb4 "
        "--collation-server=utf8mb4_0900_ai_ci "
        "--default-authentication-plugin=caching_sha2_password"
    )
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def database_url(mysql_container: Any) -> str:
    """Async SQLAlchemy URL pointing at the testcontainer.

    testcontainers-mysql renders a sync ``mysql+pymysql://...`` URL by
    default; we swap the driver token so the rebuild's asyncmy engine can
    consume it.
    """
    raw = mysql_container.get_connection_url()
    if raw.startswith("mysql+pymysql"):
        return raw.replace("mysql+pymysql", "mysql+asyncmy", 1)
    if raw.startswith("mysql://"):
        return raw.replace("mysql://", "mysql+asyncmy://", 1)
    return raw


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Any]:
    """Async engine bound to the testcontainer + alembic upgrade head.

    Side-effects:

    1. ``app.core.config.settings.DATABASE_URL`` is overwritten so any
       lazy reads (notably ``alembic/env.py``'s ``_settings_url``) see the
       container URL.
    2. ``app.core.db.engine`` and ``app.core.db.AsyncSessionLocal`` are
       rebound to the test engine + sessionmaker.
    3. ``app.routers.health.AsyncSessionLocal`` (a module-level reference
       to the original sessionmaker captured at import time) is rebound to
       the same test sessionmaker; otherwise ``/readyz`` would still try
       the prod DSN.
    4. ``alembic upgrade head`` runs against the container.
    """
    from alembic import command
    from alembic.config import Config
    from app.core import config as config_module
    from app.core import db as db_module
    from app.routers import health as health_module

    config_module.settings.DATABASE_URL = database_url

    # NullPool: each connection is opened fresh on the calling loop and fully
    # closed on context exit, so connections are never retained across the
    # per-function event loops pytest-asyncio creates for each test. With a
    # pooled engine, an asyncmy connection opened on loop A and returned to
    # the pool would be checked out by a later test on loop B and the
    # ``pool_pre_ping`` ping would fire on loop A's reader → "different loop"
    # RuntimeError. Tests are I/O-light so the per-test connect cost is
    # negligible.
    test_engine = create_async_engine(
        database_url,
        poolclass=NullPool,
        future=True,
    )
    test_session_local = async_sessionmaker(
        test_engine, expire_on_commit=False, class_=AsyncSession
    )

    db_module.engine = test_engine
    db_module.AsyncSessionLocal = test_session_local
    health_module.AsyncSessionLocal = test_session_local

    cfg = Config(str(ALEMBIC_INI))
    # `script_location` in the ini is relative to the cwd of the alembic
    # invocation. Pin it to an absolute path so the suite is cwd-independent.
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    command.upgrade(cfg, "head")

    try:
        yield test_engine
    finally:
        asyncio.run(test_engine.dispose())


@pytest_asyncio.fixture
async def _truncate_user(engine: Any) -> AsyncIterator[None]:
    """Wipe the ``user`` table around each test that touches DB state.

    Implemented as a direct ``DELETE`` (not TRUNCATE) so it composes with
    the engine's pool without needing a separate connection privilege.
    """
    async with engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM user"))
    yield
    async with engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM user"))


@pytest_asyncio.fixture
async def db_session(
    engine: Any,
    _truncate_user: None,
) -> AsyncIterator[AsyncSession]:
    """A direct AsyncSession against the test engine (pre-cleaned)."""
    from app.core.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(
    engine: Any,
    _truncate_user: None,
) -> AsyncIterator[Any]:
    """Async HTTPX client bound to the FastAPI app via ASGITransport.

    Overrides ``get_session`` to yield from the rebound testcontainer
    sessionmaker. The override is cleared on teardown so other tests that
    construct their own app instance are unaffected.
    """
    import httpx
    from app.core.db import AsyncSessionLocal, get_session
    from app.main import app

    async def _override() -> AsyncIterator[AsyncSession]:
        async with AsyncSessionLocal() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patch ``Redis.from_url`` to return a ``fakeredis`` client.

    ``app.routers.health._check_redis`` calls ``Redis.from_url(...)`` and
    awaits ``client.ping()``. fakeredis's async client supports ``ping``
    and ``aclose``, so the readyz path resolves without a Redis container.
    """
    from fakeredis.aioredis import FakeRedis

    fake = FakeRedis()

    def _from_url(*_args: Any, **_kwargs: Any) -> FakeRedis:
        return fake

    monkeypatch.setattr("redis.asyncio.Redis.from_url", _from_url)
    return fake


@contextmanager
def _override_settings_cm(**overrides: Any) -> Iterator[Any]:
    """Mutate fields on the global ``settings`` singleton for the duration
    of the with-block. Restores prior values on exit (incl. raised
    exceptions) so test order is irrelevant.
    """
    from app.core.config import settings

    sentinel = object()
    originals: dict[str, Any] = {k: getattr(settings, k, sentinel) for k in overrides}
    for k, v in overrides.items():
        setattr(settings, k, v)
    try:
        yield settings
    finally:
        for k, v in originals.items():
            if v is sentinel:
                delattr(settings, k)
            else:
                setattr(settings, k, v)


@pytest.fixture
def override_settings() -> Any:
    """Yield the context-manager helper as a fixture for test ergonomics.

    Usage::

        def test_thing(override_settings):
            with override_settings(TRUSTED_EMAIL_DOMAIN_ALLOWLIST=["canva.com"]):
                ...
    """
    return _override_settings_cm
