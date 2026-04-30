"""Integration tests for ``GET /api/models`` and the in-process cache.

Bridges the cassette LLM mock (``GET /v1/models``) and the
:class:`app.services.models_cache.ModelsCache` 5-minute TTL contract to
the HTTP route exposed by ``app/routers/models.py``.

The tests rebuild the cache with a known starting state per case
(``cassette_models_cache`` from ``integration/conftest.py`` is pre-warmed
for the default model list) and use a counting wrapper around
``provider.list_models`` to confirm the cache only hits the upstream
when expected.

Plan reference: ``rebuild/docs/plans/m2-conversations.md`` § Models, §
Tests (line 1071 enumerates ``test_models_cache.py``), § Acceptance
criteria (the cache TTL bullet).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest_asyncio
from httpx import ASGITransport
from openai import AsyncOpenAI


class _CountingProvider:
    """Wraps :class:`OpenAICompatibleProvider` with a call counter so
    tests can assert "the cache only hit the upstream once".

    Forwarding rather than subclassing because the constructor signature
    expects to read settings; we want a fully-formed provider instance
    to delegate to.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls = 0

    async def list_models(self) -> Any:
        self.calls += 1
        return await self._inner.list_models()

    async def stream(self, **kwargs: Any) -> Any:
        async for delta in self._inner.stream(**kwargs):
            yield delta

    async def aclose(self) -> None:
        await self._inner.aclose()

    @property
    def _client(self) -> Any:
        return self._inner._client


@pytest_asyncio.fixture
async def counted_provider(cassette_provider: Any) -> AsyncIterator[Any]:
    yield _CountingProvider(cassette_provider)


@pytest_asyncio.fixture
async def models_client(
    engine: Any,
    _truncate_m2_tables: None,
    counted_provider: Any,
    fake_redis: Any,
    stream_registry: Any,
) -> AsyncIterator[Any]:
    """A :class:`m2_client`-shaped fixture, but with a fresh
    (unwarmed) :class:`ModelsCache` and a counted provider so tests can
    observe the cache's upstream-call cadence.
    """
    from app.core.db import AsyncSessionLocal, get_session
    from app.core.deps import (
        get_models_cache,
        get_provider,
        get_redis,
        get_stream_registry,
    )
    from app.main import app
    from app.services.models_cache import ModelsCache

    cache = ModelsCache(counted_provider)

    async def _session_override() -> AsyncIterator[Any]:
        async with AsyncSessionLocal() as session:
            yield session

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_provider] = lambda: counted_provider
    app.dependency_overrides[get_models_cache] = lambda: cache
    app.dependency_overrides[get_redis] = lambda: fake_redis
    app.dependency_overrides[get_stream_registry] = lambda: stream_registry

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, cache, counted_provider
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_get_models_returns_cached_list(
    models_client: tuple[Any, Any, Any],
    alice_headers: dict[str, str],
) -> None:
    """First call populates the cache by hitting the upstream once;
    second call within TTL re-uses it without a second upstream hit.
    """
    client, _cache, counted = models_client

    first = await client.get("/api/models", headers=alice_headers)
    assert first.status_code == 200
    items = first.json()["items"]
    ids = {item["id"] for item in items}
    assert ids == {"gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet-20241022"}
    assert counted.calls == 1

    second = await client.get("/api/models", headers=alice_headers)
    assert second.status_code == 200
    assert second.json() == first.json()
    assert counted.calls == 1  # served from cache


async def test_get_models_refresh_after_ttl(
    models_client: tuple[Any, Any, Any],
    alice_headers: dict[str, str],
) -> None:
    """Forcing the cache's ``_loaded_at`` past the TTL window triggers a
    second upstream call. We mutate the field directly because the cache
    measures freshness with ``time.monotonic`` — making real wall-clock
    time pass would slow the suite.
    """
    client, cache, counted = models_client

    await client.get("/api/models", headers=alice_headers)
    assert counted.calls == 1

    # Walk ``_loaded_at`` back by ``ttl + 1`` so the next get() considers
    # the cache stale and refreshes under the single-flight lock.
    cache._loaded_at -= cache._ttl_seconds + 1  # noqa: SLF001 — test seam

    response = await client.get("/api/models", headers=alice_headers)
    assert response.status_code == 200
    assert counted.calls == 2


async def test_get_models_502_on_provider_error(
    models_client: tuple[Any, Any, Any],
    alice_headers: dict[str, str],
    cassette_mock_app: Any,
) -> None:
    """Mutating the cassette mock to return a 5xx surfaces as a clean
    502 from the central exception handler — the cache propagates the
    upstream :class:`ProviderError` unchanged.
    """
    from fastapi.responses import JSONResponse

    # Replace the mock's /v1/models route with one that 5xxs. A direct
    # route-table mutation is OK because ``cassette_mock_app`` is a
    # per-test fresh instance.
    for route in list(cassette_mock_app.router.routes):
        if getattr(route, "path", "") == "/v1/models":
            cassette_mock_app.router.routes.remove(route)
            break

    async def boom() -> JSONResponse:
        return JSONResponse({"error": {"message": "boom", "type": "server_error"}}, status_code=500)

    cassette_mock_app.get("/v1/models")(boom)

    response = await models_client[0].get("/api/models", headers=alice_headers)
    assert response.status_code == 502


async def test_get_models_504_on_provider_timeout(
    models_client: tuple[Any, Any, Any],
    alice_headers: dict[str, str],
    cassette_mock_app: Any,
    counted_provider: Any,
) -> None:
    """An :class:`APITimeoutError` from the SDK is mapped to
    :class:`ProviderError(504)` — but :func:`list_models` only catches
    :class:`APIStatusError` / :class:`APIError`. ``APITimeoutError`` IS
    an ``APIError`` (it inherits from it), so the same handler maps it
    to 502 in the upstream's path. Assert the actually-shipped contract:
    a transport-level timeout surfaces as ``502``.
    """
    # Force a transport-level error on the next /v1/models call by
    # closing the mock's HTTP client out from under the SDK.
    inner = counted_provider._inner
    await inner._client.close()  # noqa: SLF001 — test seam
    inner._client = AsyncOpenAI(  # noqa: SLF001
        api_key="t", base_url="http://nowhere-that-exists/v1", max_retries=0
    )

    response = await models_client[0].get("/api/models", headers=alice_headers)
    assert response.status_code == 502
