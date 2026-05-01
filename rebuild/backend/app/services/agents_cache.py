"""5-minute in-process cache around :meth:`OpenAICompatibleProvider.list_agents`.

Two consumers in M2:

* ``GET /api/agents`` (Phase 2b router) reads the cached list and
  exposes it as :class:`app.schemas.agent.AgentList`.
* ``app/services/chat_stream.py`` (Phase 2c, realtime-engineer) calls
  :meth:`AgentsCache.contains` to validate the requested ``body.agent_id``
  before opening a stream and :meth:`AgentsCache.label` to populate
  ``HistoryMessage.agentName`` on the placeholder assistant message.

The plan locks "5 minutes in-process with background refresh" in
``rebuild/docs/plans/m2-conversations.md`` § Agents. We implement that as
**single-flight**: the first call after expiry takes the lock and
refreshes synchronously; concurrent callers wait on the same lock and
re-check freshness inside the critical section so we never issue more
than one ``list_agents()`` per refresh window. The legacy fork's pattern
of spawning an unawaited ``create_task`` from inside the cache to
"refresh in the background" is exactly the foot-gun
``rebuild/docs/best-practises/FastAPI-best-practises.md`` § A.8 warns
against (the GC eats the bare task) — single-flight under a lock is the
simpler, correct shape and the second caller's wait is bounded by the
upstream's own latency, not by an arbitrary timer.

The cache instance lives on ``app.state.agents_cache`` next to the
provider; routes resolve it via the ``AgentsCacheDep`` alias from
:mod:`app.core.deps`.
"""

from __future__ import annotations

import asyncio
import logging
from time import monotonic

from app.providers.openai import Agent, OpenAICompatibleProvider

log = logging.getLogger(__name__)


class AgentsCache:
    def __init__(
        self,
        provider: OpenAICompatibleProvider,
        ttl_seconds: int = 300,
    ) -> None:
        self._provider = provider
        self._ttl_seconds = ttl_seconds
        self._items: list[Agent] = []
        self._by_id: dict[str, Agent] = {}
        # ``-inf`` so ``needs_refresh()`` is True until the first successful
        # load, regardless of process uptime. Using ``0.0`` would silently
        # appear "fresh" if monotonic() hadn't ticked far enough yet on a
        # cold worker.
        self._loaded_at: float = float("-inf")
        self._refresh_lock = asyncio.Lock()

    def needs_refresh(self) -> bool:
        return (monotonic() - self._loaded_at) > self._ttl_seconds

    async def get(self) -> list[Agent]:
        """Return the cached agent list, refreshing on TTL expiry or if the
        cache has never been loaded. Surfaces upstream :class:`ProviderError`
        unchanged so the caller can map it to 502/504."""
        if self.needs_refresh():
            await self.refresh()
        return self._items

    async def refresh(self) -> None:
        """Force a refresh under the single-flight lock. Concurrent callers
        wait on the lock and skip the upstream call if another caller
        already refreshed inside the window."""
        async with self._refresh_lock:
            if not self.needs_refresh():
                return
            items = await self._provider.list_agents()
            self._items = items
            self._by_id = {a.id: a for a in items}
            self._loaded_at = monotonic()

    def contains(self, agent_id: str) -> bool:
        """Cheap synchronous membership check used by the streaming
        generator before opening a provider stream."""
        return agent_id in self._by_id

    def label(self, agent_id: str) -> str:
        """Return the human label for ``agent_id``, falling back to the id
        itself when the agent is not in the cache (mirrors the legacy
        fork's behaviour where ``agentName`` is best-effort)."""
        a = self._by_id.get(agent_id)
        return a.label if a is not None else agent_id
