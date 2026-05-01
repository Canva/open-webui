"""Integration-test fixtures for the M2 chat / folder / streaming surface.

Layered on top of the parent ``backend/tests/conftest.py`` (see the
``mysql_container`` / ``engine`` / ``client`` / ``db_session`` fixtures
there). This module adds the M2-specific wiring:

* :func:`alice_headers` / :func:`alice` — convenience identities used by
  every chat / folder / streaming integration test. ``alice`` is the
  upserted :class:`app.models.user.User` row (so tests can build chats
  via the ORM); ``alice_headers`` is the dict of trusted-proxy headers
  the same identity flows through ``httpx`` with.
* :func:`bob_headers` — second identity used by the cross-user-isolation
  cases (``test_get_chat_returns_404_for_foreign_owner`` and friends).
* :func:`cassette_provider` — :class:`app.providers.openai.OpenAICompatibleProvider`
  whose underlying SDK ``http_client`` is bound by ``ASGITransport`` to
  the in-process :mod:`tests.llm_mock` cassette server. No real
  upstream is reachable.
* :func:`cassette_agents_cache` — :class:`app.services.agents_cache.AgentsCache`
  pre-loaded from the cassette provider so tests don't have to ``await``
  a refresh before issuing requests.
* :func:`fake_redis_server` / :func:`fake_redis` — a single
  ``fakeredis.aioredis.FakeServer`` shared between two ``FakeRedis``
  clients (used by the cross-pod cancellation registry test).
* :func:`stream_registry` — :class:`app.services.stream_registry.StreamRegistry`
  around the fake redis. Torn down via ``aclose()`` so listen tasks are
  reaped between tests.
* :func:`m2_client` — :class:`httpx.AsyncClient` wired against the
  global FastAPI app with every M2 dependency (``get_provider``,
  ``get_agents_cache``, ``get_stream_registry``, ``get_redis``,
  ``get_session``) overridden. The in-flight test never touches a real
  upstream or redis.

All these fixtures rely on ``app.dependency_overrides`` rather than
monkey-patching module-level state — see
``rebuild/docs/best-practises/FastAPI-best-practises.md`` § A.11.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport


@pytest_asyncio.fixture
async def _truncate_m2_tables(engine: Any) -> AsyncIterator[None]:
    """Wipe every M2 + M3 table around each integration test.

    ``DELETE FROM user`` cascades to ``chat`` and ``folder`` via the
    ``ON DELETE CASCADE`` policies declared on both, but the explicit
    deletes below are belt-and-braces — a future revision that drops a
    cascade by accident would otherwise surface only as cross-test
    bleed (the worst test-failure class to debug).

    ``shared_chat`` is wiped *before* ``chat`` even though
    ``shared_chat.chat_id → chat.id ON DELETE CASCADE`` makes the
    explicit delete redundant in practice — the explicit ordering keeps
    the test-cleanup contract honest if a future M3 revision ever
    weakens that cascade, and matches the rest of this fixture's belt-
    and-braces style.
    """
    async with engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM shared_chat"))
        await conn.execute(sa.text("DELETE FROM chat"))
        await conn.execute(sa.text("DELETE FROM folder"))
        await conn.execute(sa.text("DELETE FROM user"))
    yield
    async with engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM shared_chat"))
        await conn.execute(sa.text("DELETE FROM chat"))
        await conn.execute(sa.text("DELETE FROM folder"))
        await conn.execute(sa.text("DELETE FROM user"))


@pytest.fixture
def alice_headers() -> dict[str, str]:
    """Trusted-proxy headers for the canonical "current user" identity."""
    return {
        "X-Forwarded-Email": "alice@canva.com",
        "X-Forwarded-Name": "Alice",
    }


@pytest.fixture
def bob_headers() -> dict[str, str]:
    """A second identity for cross-user-isolation tests."""
    return {
        "X-Forwarded-Email": "bob@canva.com",
        "X-Forwarded-Name": "Bob",
    }


@pytest_asyncio.fixture
async def alice(_truncate_m2_tables: None, engine: Any) -> Any:
    """The :class:`app.models.user.User` row matching :func:`alice_headers`.

    Useful when a test needs to seed a chat / folder directly via the
    ORM before exercising the HTTP surface. Uses a dedicated session
    (rather than ``db_session``) so it composes with tests that also
    request ``db_session`` without sharing identity-map state.
    """
    from app.core.auth import upsert_user_from_headers
    from app.core.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        user = await upsert_user_from_headers(
            session,
            email="alice@canva.com",
            name="Alice",
        )
        # Detach so callers can cross transaction boundaries without
        # ``MissingGreenlet``. Pull the fields we care about up-front
        # because lazy loads after expunge would re-issue SELECTs.
        _ = user.id, user.email, user.name
        session.expunge(user)
        return user


@pytest_asyncio.fixture
async def bob(_truncate_m2_tables: None, engine: Any) -> Any:
    """Second identity, mirrors :func:`alice` for cross-user tests."""
    from app.core.auth import upsert_user_from_headers
    from app.core.db import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        user = await upsert_user_from_headers(
            session,
            email="bob@canva.com",
            name="Bob",
        )
        _ = user.id, user.email, user.name
        session.expunge(user)
        return user


@pytest.fixture
def cassette_mock_app() -> Any:
    """A fresh :mod:`tests.llm_mock` instance per test.

    Tests that need a custom agent list mutate ``app.state.models``
    (the upstream OpenAI-compat wire field) after construction; the
    default ships the three ids the rebuild's frontend dropdown is
    expected to render.
    """
    from tests.llm_mock import create_mock_app

    return create_mock_app()


@pytest_asyncio.fixture
async def cassette_provider(cassette_mock_app: Any) -> AsyncIterator[Any]:
    """An :class:`OpenAICompatibleProvider` bound to the cassette mock.

    We replace ``provider._client`` with a fresh :class:`AsyncOpenAI`
    pointed at an :class:`httpx.AsyncClient` whose transport is the
    cassette mock app. The original ``_client`` (which would have
    pointed at a non-existent gateway in tests) is closed before the
    swap so we don't leak the underlying httpx pool.
    """
    from app.providers.openai import OpenAICompatibleProvider
    from openai import AsyncOpenAI

    provider = OpenAICompatibleProvider()
    await provider._client.close()  # noqa: SLF001 — test-only swap
    mock_client = httpx.AsyncClient(
        transport=ASGITransport(app=cassette_mock_app),
        base_url="http://mock",
    )
    provider._client = AsyncOpenAI(  # noqa: SLF001
        api_key="cassette",
        base_url="http://mock/v1",
        http_client=mock_client,
    )
    try:
        yield provider
    finally:
        await provider.aclose()


@pytest_asyncio.fixture
async def cassette_agents_cache(cassette_provider: Any) -> Any:
    """An :class:`AgentsCache` pre-warmed against the cassette provider.

    Pre-warming means the first integration request doesn't have to
    pay the round-trip to ``/v1/models`` (the upstream wire path)
    before validating ``body.agent_id``; it also means the test can
    assert on the cached ids directly.
    """
    from app.services.agents_cache import AgentsCache

    cache = AgentsCache(cassette_provider)
    await cache.refresh()
    return cache


@pytest.fixture
def fake_redis_server() -> Any:
    """A shared :class:`fakeredis.aioredis.FakeServer`.

    Two :class:`FakeRedis` clients connected to the same server simulate
    "two pods talking to one redis" — exactly the shape the cross-pod
    stream-registry test relies on. Returned as a server (not a client)
    so callers can construct any number of clients against it.
    """
    from fakeredis.aioredis import FakeServer  # type: ignore[attr-defined]

    return FakeServer()


@pytest_asyncio.fixture
async def fake_redis(fake_redis_server: Any) -> AsyncIterator[Any]:
    """Single fakeredis client per test, torn down with ``aclose``."""
    from fakeredis.aioredis import FakeRedis

    client = FakeRedis(server=fake_redis_server)
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def stream_registry(fake_redis: Any) -> AsyncIterator[Any]:
    """A :class:`StreamRegistry` against the fakeredis client.

    Torn down via ``aclose()`` so the per-stream listen tasks are
    cancelled between tests. Without the teardown a leaked listen task
    would keep a reference to the (now-closed) FakeRedis client and
    the next test's pytest-asyncio loop would warn on shutdown.
    """
    from app.services.stream_registry import StreamRegistry

    registry = StreamRegistry(redis=fake_redis)
    try:
        yield registry
    finally:
        await registry.aclose()


@pytest_asyncio.fixture
async def m2_client(
    engine: Any,
    _truncate_m2_tables: None,
    cassette_provider: Any,
    cassette_agents_cache: Any,
    fake_redis: Any,
    stream_registry: Any,
) -> AsyncIterator[Any]:
    """The async HTTP client for the M2 integration surface.

    Every singleton the M2 routes resolve via :mod:`app.core.deps` is
    overridden so the request lifecycle never touches the real
    upstream gateway, the real redis, or the lifespan-bound app.state
    the test client doesn't actually run. ``get_session`` is the
    parent ``client`` fixture's pattern, copied verbatim so the same
    sessionmaker that backs the conftest engine answers session
    requests.
    """
    from app.core.db import AsyncSessionLocal, get_session
    from app.core.deps import (
        get_agents_cache,
        get_provider,
        get_redis,
        get_stream_registry,
    )
    from app.main import app

    async def _session_override() -> AsyncIterator[Any]:
        async with AsyncSessionLocal() as session:
            yield session

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_provider] = lambda: cassette_provider
    app.dependency_overrides[get_agents_cache] = lambda: cassette_agents_cache
    app.dependency_overrides[get_redis] = lambda: fake_redis
    app.dependency_overrides[get_stream_registry] = lambda: stream_registry

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
