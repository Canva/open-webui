"""Unit tests for :class:`app.services.models_cache.ModelsCache`.

The cache is a thin TTL + single-flight wrapper around
:meth:`OpenAICompatibleProvider.list_models`. The behaviours we lock:

* First call after expiry hits the upstream and stores the items.
* Repeat calls within the TTL serve from cache (no upstream).
* TTL expiry triggers a fresh upstream call on the next ``get``.
* Concurrent ``get`` calls all complete with one upstream call total
  (single-flight under the lock).
* ``contains`` / ``label`` reflect the cached state (or fall back
  cleanly when the id is missing).

Plan reference: ``rebuild/docs/plans/m2-conversations.md`` § Models
("cached for 5 minutes in-process with background refresh", line 636)
and the dispatch-named ``test_models_cache.py`` target.
"""

from __future__ import annotations

import asyncio

from app.providers.openai import Model, ProviderError
from app.services.models_cache import ModelsCache


class _FakeProvider:
    """Counts ``list_models()`` invocations and returns a configurable
    list. Optionally awaits an event before returning so tests can
    pin a slow upstream and observe single-flight behaviour.
    """

    def __init__(
        self,
        *,
        items: list[Model] | None = None,
        delay_event: asyncio.Event | None = None,
        raise_with: Exception | None = None,
    ) -> None:
        self.items = items or [
            Model(id="gpt-4o", label="gpt-4o", owned_by="openai"),
            Model(id="gpt-4o-mini", label="gpt-4o-mini", owned_by="openai"),
        ]
        self.calls = 0
        self.delay_event = delay_event
        self.raise_with = raise_with

    async def list_models(self) -> list[Model]:
        self.calls += 1
        if self.delay_event is not None:
            await self.delay_event.wait()
        if self.raise_with is not None:
            raise self.raise_with
        return list(self.items)


# ---------------------------------------------------------------------------
# get / TTL behaviour
# ---------------------------------------------------------------------------


async def test_cache_first_get_calls_provider_and_stores_items() -> None:
    """First ``get`` after construction hits the upstream once and
    stores the items; the returned list matches what the provider
    served."""
    provider = _FakeProvider()
    cache = ModelsCache(provider, ttl_seconds=300)  # type: ignore[arg-type]

    items = await cache.get()
    assert provider.calls == 1
    assert [m.id for m in items] == ["gpt-4o", "gpt-4o-mini"]


async def test_cache_repeat_get_within_ttl_does_not_call_provider() -> None:
    """Repeat ``get`` calls within the TTL window serve from the cache."""
    provider = _FakeProvider()
    cache = ModelsCache(provider, ttl_seconds=300)  # type: ignore[arg-type]

    await cache.get()
    await cache.get()
    await cache.get()
    assert provider.calls == 1


async def test_cache_get_after_ttl_refreshes() -> None:
    """``ttl_seconds=0`` makes every call past the first refresh
    (``needs_refresh`` returns True as soon as ``monotonic()`` ticks).

    A full clock-mock would be overkill — the public surface this test
    asserts is "TTL-expiry triggers a refresh", and ttl=0 is the
    boundary case that exercises that branch deterministically.
    """
    provider = _FakeProvider()
    cache = ModelsCache(provider, ttl_seconds=0)  # type: ignore[arg-type]

    await cache.get()
    # Allow the monotonic clock to tick past 0.
    await asyncio.sleep(0.01)
    await cache.get()
    assert provider.calls >= 2


# ---------------------------------------------------------------------------
# single-flight under concurrent get
# ---------------------------------------------------------------------------


async def test_cache_single_flight_under_concurrent_get() -> None:
    """N concurrent ``get`` calls trigger exactly one
    ``provider.list_models()`` call. Without the single-flight lock the
    first request and N-1 racing duplicates would all see
    ``needs_refresh=True`` and each issue its own upstream fetch.

    We pin the provider on an event so all concurrent waiters queue on
    the lock; only when the event fires can the holder return and the
    rest skip the upstream (their inside-lock ``needs_refresh()`` re-
    check returns False).
    """
    release = asyncio.Event()
    provider = _FakeProvider(delay_event=release)
    cache = ModelsCache(provider, ttl_seconds=300)  # type: ignore[arg-type]

    tasks = [asyncio.create_task(cache.get()) for _ in range(8)]
    # Yield enough times for every task to reach the lock acquire +
    # the inner await on ``release``.
    for _ in range(20):
        await asyncio.sleep(0)
    # The lock holder is awaiting on ``release``; the other 7 are
    # awaiting on the lock. Releasing the upstream lets exactly the
    # one holder complete, then the rest skip the upstream call inside
    # ``refresh()``'s second ``needs_refresh()`` check.
    release.set()
    results = await asyncio.gather(*tasks)

    assert provider.calls == 1
    assert all(len(r) == 2 for r in results)


# ---------------------------------------------------------------------------
# contains / label
# ---------------------------------------------------------------------------


async def test_cache_contains_returns_true_for_cached_id() -> None:
    """The streaming generator's pre-flight model check uses
    ``contains(model_id)``; a cached id resolves to ``True``."""
    provider = _FakeProvider()
    cache = ModelsCache(provider, ttl_seconds=300)  # type: ignore[arg-type]
    await cache.refresh()
    assert cache.contains("gpt-4o") is True


async def test_cache_contains_returns_false_for_missing_id() -> None:
    """An id that didn't appear in the upstream's list resolves to
    ``False`` so the streaming generator can return a clean 400."""
    provider = _FakeProvider()
    cache = ModelsCache(provider, ttl_seconds=300)  # type: ignore[arg-type]
    await cache.refresh()
    assert cache.contains("never-heard-of-it") is False


async def test_cache_label_falls_back_to_id_for_missing() -> None:
    """``label`` is best-effort — a missing id returns the id verbatim
    so the placeholder assistant message's ``modelName`` is never
    blank, even for a model that disappeared from the upstream
    between when the user picked it and when the stream opened.
    """
    provider = _FakeProvider()
    cache = ModelsCache(provider, ttl_seconds=300)  # type: ignore[arg-type]
    await cache.refresh()
    assert cache.label("gpt-4o") == "gpt-4o"
    assert cache.label("never-heard-of-it") == "never-heard-of-it"


async def test_cache_get_propagates_provider_error() -> None:
    """Upstream :class:`ProviderError` propagates unchanged so the
    centralised handler maps it to 502/504/429 (plan line 635)."""
    import pytest

    provider = _FakeProvider(raise_with=ProviderError("upstream gone", status_code=502))
    cache = ModelsCache(provider, ttl_seconds=300)  # type: ignore[arg-type]
    with pytest.raises(ProviderError) as exc_info:
        await cache.get()
    assert exc_info.value.status_code == 502
