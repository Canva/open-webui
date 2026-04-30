"""Per-pod cancellation registry, fanned out across pods via Redis pub/sub.

The registry sits between the SSE streaming generator (`chat_stream.py`)
and the explicit cancel endpoint (`POST /api/chats/{id}/messages/{aid}/cancel`).
Two cancellation paths flow through it:

1. **Same-pod cancel** — the streaming generator polls the local
   :class:`asyncio.Event` returned by :meth:`register` between provider
   iterations and raises :class:`asyncio.CancelledError` when it is set.
2. **Cross-pod cancel** — the cancel endpoint may land on any pod via the
   load balancer; it calls :meth:`cancel`, which publishes a 1-byte
   payload to ``stream:cancel:{message_id}``. The pod actually running
   the stream has subscribed to that channel via :meth:`register` and
   sets the local event from its background ``_listen`` task.

The Redis connection is the same one M4's socket.io adapter and M6's
rate limiter use — no new infra (`rebuild.md` §9 — single managed Redis).

Subscriptions are short-lived (one per active stream) and torn down via
:meth:`unregister` from the streaming generator's ``finally`` block.

Per ``rebuild/docs/best-practises/FastAPI-best-practises.md`` § A.8, the
listen task is **always** held by a strong reference in
``_subscriptions`` so the GC can't reap it mid-flight; the bare
``asyncio.create_task(...)`` foot-gun never appears in this module.

The cancel publish is best-effort and idempotent. If the stream already
finished, ``unregister`` has dropped the local subscription, the publish
hits a dead channel server-side, and we no-op silently.

References:

* ``rebuild/docs/plans/m2-conversations.md`` § Streaming pipeline
  (lines 813-828 — the ``StreamRegistry`` block) and § Acceptance
  criteria (the cross-pod fakeredis test on line 1103).
* ``rebuild/docs/best-practises/FastAPI-best-practises.md`` § A.8
  (no unawaited tasks; strong refs only) and § B.6 (Redis pub/sub
  shape — connection pool from app.state, per-message channel,
  ``unsubscribe()`` always in ``finally``).
"""

from __future__ import annotations

import asyncio
import logging

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

log = logging.getLogger(__name__)

# Single source of truth for the channel name. Defined once so cancel and
# register can never drift out of sync. M4's socket.io fan-out uses a
# different prefix; do not collapse them.
_CANCEL_CHANNEL_PREFIX = "stream:cancel:"

# Timeout for waiting on the SUBSCRIBE confirmation. The round-trip is
# microseconds in practice; the generous cap is purely a safety net so a
# wedged Redis can't deadlock register() forever.
_SUBSCRIBE_CONFIRM_TIMEOUT_S = 5.0


class StreamRegistry:
    """Per-pod cancellation registry with a Redis pub/sub fan-out.

    One instance per worker, constructed in the FastAPI ``lifespan`` and
    stored on ``app.state.stream_registry``. Routes / services receive it
    via the :data:`app.core.deps.StreamRegistryDep` alias.
    """

    def __init__(self, *, redis: Redis) -> None:
        self._redis = redis
        # Local cancellation events, keyed by ``assistant_message_id``.
        # The streaming generator on this pod awaits-then-checks the
        # event between provider iterations.
        self._locals: dict[str, asyncio.Event] = {}
        # Strong references to the per-stream listen tasks. Required by
        # § A.8 of FastAPI-best-practises.md — bare ``asyncio.create_task``
        # without a strong reference is the canonical foot-gun
        # (the GC eats the task mid-flight).
        self._subscriptions: dict[str, asyncio.Task[None]] = {}
        self._closed = False

    async def register(self, message_id: str) -> asyncio.Event:
        """Register a local cancellation event for ``message_id`` and
        subscribe to the corresponding Redis channel.

        Returns the :class:`asyncio.Event` the streaming generator should
        poll between provider iterations.

        Idempotent: a duplicate ``message_id`` returns the existing event
        instead of leaking a second subscription. UUIDv7 ids make a
        collision implausible in practice; the guard is defensive.
        """
        if self._closed:
            raise RuntimeError("StreamRegistry is closed")
        existing = self._locals.get(message_id)
        if existing is not None:
            return existing

        channel = f"{_CANCEL_CHANNEL_PREFIX}{message_id}"
        event = asyncio.Event()
        pubsub: PubSub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        # Drain the SUBSCRIBE confirmation so the server-side subscription
        # is guaranteed established before ``register`` returns. Without
        # this drain a ``publish`` racing in from another pod between the
        # SUBSCRIBE command and the first ``listen()`` read could be
        # delivered before the listen loop starts iterating, surfacing
        # only later as a "subscribe" message that we filter out — i.e.
        # the cancel would be silently lost.
        await pubsub.get_message(
            ignore_subscribe_messages=False,
            timeout=_SUBSCRIBE_CONFIRM_TIMEOUT_S,
        )

        self._locals[message_id] = event
        self._subscriptions[message_id] = asyncio.create_task(
            self._listen(message_id=message_id, pubsub=pubsub, event=event, channel=channel),
            name=f"stream-cancel-listen:{message_id}",
        )
        return event

    async def cancel(self, message_id: str) -> bool:
        """Publish a cancel signal for ``message_id`` to every pod.

        Best-effort: the pod actually running the stream receives the
        message via its subscription and sets the local event; pods
        without a local subscription receive nothing (the channel has
        no subscribers from their perspective) and that's fine.

        Returns ``True`` if the publish succeeded (regardless of how
        many subscribers picked it up — zero is a valid outcome when
        the stream has already finished and unsubscribed).
        Returns ``False`` only if the publish itself raised.
        """
        channel = f"{_CANCEL_CHANNEL_PREFIX}{message_id}"
        try:
            await self._redis.publish(channel, b"1")
        except Exception:
            log.exception("StreamRegistry.cancel publish failed for %s", message_id)
            return False
        return True

    async def unregister(self, message_id: str) -> None:
        """Cancel the listen task and drop the local entry.

        Always called from the streaming generator's ``finally`` block.
        Idempotent: a missing entry is a no-op.
        """
        self._locals.pop(message_id, None)
        task = self._subscriptions.pop(message_id, None)
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("StreamRegistry listen task raised on unregister: %s", message_id)

    async def aclose(self) -> None:
        """Cancel every outstanding subscription. Called from
        ``lifespan`` shutdown so a graceful stop reclaims pubsub
        connections instead of letting them dangle until socket close.
        """
        if self._closed:
            return
        self._closed = True
        tasks = list(self._subscriptions.values())
        self._subscriptions.clear()
        self._locals.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            # ``return_exceptions=True`` swallows the CancelledErrors we
            # just induced — they are expected, not failures.
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _listen(
        self,
        *,
        message_id: str,
        pubsub: PubSub,
        event: asyncio.Event,
        channel: str,
    ) -> None:
        """Background task: listen for the first ``message`` frame on
        ``channel`` and set the local cancellation event.

        One cancel per stream is enough — the streaming generator only
        needs to be told *once* to stop. We exit after the first hit so
        the pubsub connection is released promptly.

        :class:`asyncio.CancelledError` raised by :meth:`unregister` /
        :meth:`aclose` propagates out (the ``try/finally`` only owns
        cleanup). The task therefore ends in the cancelled state, which
        is exactly what ``await task`` in ``unregister`` expects.
        """
        try:
            async for msg in pubsub.listen():
                # ``listen()`` yields all message types — subscribe
                # confirmations, unsubscribe acks, and actual messages.
                # We drained the SUBSCRIBE confirmation in ``register``
                # already; here we filter on type to be defensive.
                if msg.get("type") == "message":
                    event.set()
                    return
        finally:
            # Pubsub teardown must happen even on cancellation, hence the
            # ``finally`` block (per § B.6 of FastAPI-best-practises.md —
            # "``unsubscribe()`` always in finally").
            try:
                await pubsub.unsubscribe(channel)
            except Exception:
                log.debug(
                    "StreamRegistry pubsub.unsubscribe(%s) failed",
                    channel,
                    exc_info=True,
                )
            try:
                # ``PubSub.aclose`` is typed as untyped in redis-py 5.x's
                # stubs (the method is async but the annotation lacks a
                # return type). The call is correct; the ignore is
                # narrow.
                await pubsub.aclose()  # type: ignore[no-untyped-call]
            except Exception:
                log.debug(
                    "StreamRegistry pubsub.aclose(%s) failed",
                    channel,
                    exc_info=True,
                )
