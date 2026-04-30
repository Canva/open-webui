"""Integration tests for :class:`app.services.stream_registry.StreamRegistry`.

The registry's load-bearing property is "a cancel published from any
pod is delivered to the pod actually running the stream within ~ms".
We assert that with two ``FakeRedis`` clients connected to the same
in-memory ``FakeServer`` — exactly the shape ``rebuild/docs/best-
practises/FastAPI-best-practises.md`` § B.6 calls out for testing
Redis pub/sub.

Plan reference: ``rebuild/docs/plans/m2-conversations.md`` § Tests
("Stream registry cross-pod" line 1093) and § Acceptance criteria
(the cross-pod cancel bullet — must fire within 100 ms).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest_asyncio
from app.services.stream_registry import StreamRegistry
from fakeredis.aioredis import FakeRedis, FakeServer  # type: ignore[attr-defined]


@pytest_asyncio.fixture
async def two_pod_registries() -> AsyncIterator[tuple[StreamRegistry, StreamRegistry]]:
    """Two registries sharing one fakeredis server — pod A and pod B.

    Both registries are :meth:`aclose`d on teardown so any per-stream
    listen tasks they spawned are reaped between tests; otherwise the
    next test's pytest-asyncio loop would warn on shutdown.
    """
    server = FakeServer()
    redis_a = FakeRedis(server=server)
    redis_b = FakeRedis(server=server)
    registry_a = StreamRegistry(redis=redis_a)
    registry_b = StreamRegistry(redis=redis_b)
    try:
        yield registry_a, registry_b
    finally:
        await registry_a.aclose()
        await registry_b.aclose()
        await redis_a.aclose()
        await redis_b.aclose()


# ---------------------------------------------------------------------------
# Cross-pod cancellation — the headline acceptance bullet
# ---------------------------------------------------------------------------


async def test_cancel_crosses_pod_boundary_via_redis(
    two_pod_registries: tuple[StreamRegistry, StreamRegistry],
) -> None:
    """Per ``rebuild/docs/plans/m2-conversations.md`` line 1093: register
    on registry-A, cancel from registry-B, the local event on A is set
    within 100 ms.

    The 100 ms cap is the load-bearing latency budget; if this widens
    the cancel UX degrades from "instant" to "perceptible delay".
    """
    registry_a, registry_b = two_pod_registries
    event = await registry_a.register("msg-1")
    assert not event.is_set()

    await registry_b.cancel("msg-1")

    # 100 ms cap per the acceptance criterion. With fakeredis in-process
    # this is wildly generous — observed latency is microseconds — but
    # the budget is what the plan locks.
    await asyncio.wait_for(event.wait(), timeout=0.1)
    assert event.is_set()

    await registry_a.unregister("msg-1")


async def test_cancel_is_idempotent(
    two_pod_registries: tuple[StreamRegistry, StreamRegistry],
) -> None:
    """A repeated cancel is a no-op (publishes to a channel with no
    subscriber after the first cancel completed and unregistered)."""
    registry_a, registry_b = two_pod_registries
    event = await registry_a.register("msg-2")
    await registry_b.cancel("msg-2")
    await asyncio.wait_for(event.wait(), timeout=0.1)
    await registry_a.unregister("msg-2")
    # Second cancel after the listen task has already exited — must
    # NOT raise.
    await registry_b.cancel("msg-2")


async def test_register_returns_existing_event_on_duplicate_id(
    two_pod_registries: tuple[StreamRegistry, StreamRegistry],
) -> None:
    """Defensive: a second :meth:`register` call with the same id
    returns the same :class:`asyncio.Event` instance. UUIDv7 ids make a
    real collision implausible, but the guard prevents the second call
    from leaking a duplicate subscription task."""
    registry_a, _ = two_pod_registries
    e1 = await registry_a.register("msg-3")
    e2 = await registry_a.register("msg-3")
    assert e1 is e2
    await registry_a.unregister("msg-3")


async def test_unregister_drops_local_subscription_and_cancels_listener_task(
    two_pod_registries: tuple[StreamRegistry, StreamRegistry],
) -> None:
    """After :meth:`unregister`, the background ``_listen`` task is
    cancelled — no resource leak, no zombie subscription."""
    registry_a, _ = two_pod_registries
    await registry_a.register("msg-4")
    listen_task = registry_a._subscriptions["msg-4"]  # noqa: SLF001 — test seam
    assert not listen_task.done()

    await registry_a.unregister("msg-4")

    assert listen_task.done()
    assert "msg-4" not in registry_a._subscriptions  # noqa: SLF001
    assert "msg-4" not in registry_a._locals  # noqa: SLF001


async def test_aclose_cancels_all_outstanding_subscriptions() -> None:
    """``aclose`` is the lifespan-shutdown hook; it must reap every
    outstanding listen task in one shot.
    """
    server = FakeServer()
    redis = FakeRedis(server=server)
    registry = StreamRegistry(redis=redis)
    try:
        await registry.register("a")
        await registry.register("b")
        await registry.register("c")
        tasks = list(registry._subscriptions.values())  # noqa: SLF001
        assert all(not t.done() for t in tasks)

        await registry.aclose()

        assert all(t.done() for t in tasks)
        assert not registry._subscriptions  # noqa: SLF001
        assert not registry._locals  # noqa: SLF001
    finally:
        await redis.aclose()
