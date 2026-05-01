"""The single agent-gateway transport.

A thin wrapper around the OpenAI Python SDK pointed at
``settings.agent_gateway_base_url``. M2 ships exactly one provider class —
no provider matrix, no LiteLLM, no second class — per
``rebuild/docs/best-practises/FastAPI-best-practises.md`` § B.4.

Lifecycle (locked):

* Constructed exactly once per worker, inside the FastAPI ``lifespan``,
  and stored on ``app.state.provider``.
* Routes/services receive it via the
  :data:`app.core.deps.Provider` dependency alias
  (``provider: Provider``).
* Tests fake it via
  ``app.dependency_overrides[get_provider] = lambda: FakeProvider()`` —
  no monkey-patching of module-level names, no special test-only imports.

There is **no** module-level singleton. A module-level instance would (a)
run before ``Settings`` is fully resolved on some test paths, (b) be
impossible to override via ``app.dependency_overrides`` in unit tests,
and (c) confuse uvicorn worker-fork semantics if we ever moved off the
lifespan-per-process model. Rationale lives in
``rebuild/docs/plans/m2-conversations.md`` § Provider abstraction
(the block following the class definition).

The OpenAI SDK's secret/token surface uses :class:`pydantic.SecretStr` on
the rebuild's ``Settings`` (``AGENT_GATEWAY_API_KEY``) so the value never
appears in logs or repr output. The constructor below calls
``.get_secret_value()`` immediately before handing the key to
``AsyncOpenAI`` — the plan's code block predates the SecretStr decision,
so this is the documented divergence.

Wire-format note: the OpenAI-compatible upstream still calls its
catalogue ``/v1/models`` and uses ``model:`` on chat completion bodies.
The rebuild's domain calls each entry an **agent** (each agent has a
preselected underlying model on the agent platform). This module is the
translation layer: it accepts ``agent_id`` from the rebuild and emits
``model=`` to the OpenAI SDK.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
from openai import APIError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError

from app.core.config import settings

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Agent:
    id: str
    label: str
    owned_by: str | None


@dataclass(slots=True)
class StreamDelta:
    content: str = ""
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


class ProviderError(Exception):
    """Wrapper for upstream gateway failures. Always carries an HTTP-friendly
    status code so the streaming generator and the non-streaming routes can
    map it to the right SSE/HTTP shape without re-classifying."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class OpenAICompatibleProvider:
    """The only provider. Reads ``AGENT_GATEWAY_BASE_URL`` /
    ``AGENT_GATEWAY_API_KEY`` from the central :class:`app.core.config.Settings`.

    Exactly one instance per worker; constructed in ``lifespan`` and stored
    on ``app.state.provider``. Routes / services receive it via the
    :data:`app.core.deps.Provider` dependency alias. Never instantiated
    at module import.
    """

    def __init__(self) -> None:
        api_key = (
            settings.agent_gateway_api_key.get_secret_value()
            if settings.agent_gateway_api_key is not None
            else "unused"
        )
        self._client = AsyncOpenAI(
            base_url=settings.agent_gateway_base_url,
            api_key=api_key,
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0),
            max_retries=0,
        )

    async def aclose(self) -> None:
        """Release the underlying httpx pool. Called from ``lifespan`` shutdown."""
        await self._client.close()

    async def list_agents(self) -> list[Agent]:
        """Fetch the agent catalogue.

        The OpenAI-compatible upstream still serves this at ``/v1/models``;
        we translate each entry into the rebuild's :class:`Agent` shape
        (the rebuild's UI never exposes the underlying model id).
        """
        try:
            page = await self._client.models.list()
        except (APIStatusError, APIError) as e:
            raise ProviderError(f"gateway list_agents failed: {e}", status_code=502) from e

        out: list[Agent] = []
        for m in page.data:
            out.append(
                Agent(
                    id=m.id,
                    label=getattr(m, "label", None) or m.id,
                    owned_by=getattr(m, "owned_by", None),
                )
            )
        out.sort(key=lambda a: a.id)
        return out

    async def stream(
        self,
        *,
        messages: list[dict[str, Any]],
        agent_id: str,
        params: dict[str, Any],
    ) -> AsyncIterator[StreamDelta]:
        """Open a streaming chat completion against the upstream gateway.

        ``agent_id`` is the rebuild-domain identifier the user picked; the
        OpenAI SDK still wants it in the ``model=`` slot on the wire, so
        we forward it there verbatim. The agent platform on the other end
        owns the agent → underlying model mapping.
        """
        msgs = list(messages)
        if params.get("system"):
            msgs.insert(0, {"role": "system", "content": params["system"]})

        kwargs: dict[str, Any] = {
            "model": agent_id,
            "messages": msgs,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if "temperature" in params:
            kwargs["temperature"] = params["temperature"]

        try:
            stream = await self._client.chat.completions.create(**kwargs)
        except APITimeoutError as e:
            raise ProviderError("upstream timeout", status_code=504) from e
        except RateLimitError as e:
            raise ProviderError("upstream rate-limited", status_code=429) from e
        except APIStatusError as e:
            raise ProviderError(f"upstream {e.status_code}: {e.message}", status_code=502) from e

        try:
            async for chunk in stream:
                if chunk.usage is not None:
                    yield StreamDelta(usage=chunk.usage.model_dump())
                    continue
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                yield StreamDelta(
                    content=(choice.delta.content or ""),
                    finish_reason=choice.finish_reason,
                )
        except asyncio.CancelledError:
            await stream.close()
            raise
        except APIError as e:
            raise ProviderError(f"stream interrupted: {e}", status_code=502) from e
