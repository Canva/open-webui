"""The single model-gateway transport.

A thin wrapper around the OpenAI Python SDK pointed at
``settings.MODEL_GATEWAY_BASE_URL``. M2 ships exactly one provider class —
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
the rebuild's ``Settings`` (``MODEL_GATEWAY_API_KEY``) so the value never
appears in logs or repr output. The constructor below calls
``.get_secret_value()`` immediately before handing the key to
``AsyncOpenAI`` — the plan's code block predates the SecretStr decision,
so this is the documented divergence.
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
class Model:
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
    """The only provider. Reads ``MODEL_GATEWAY_BASE_URL`` /
    ``MODEL_GATEWAY_API_KEY`` from the central :class:`app.core.config.Settings`.

    Exactly one instance per worker; constructed in ``lifespan`` and stored
    on ``app.state.provider``. Routes / services receive it via the
    :data:`app.core.deps.Provider` dependency alias. Never instantiated
    at module import.
    """

    def __init__(self) -> None:
        api_key = (
            settings.MODEL_GATEWAY_API_KEY.get_secret_value()
            if settings.MODEL_GATEWAY_API_KEY is not None
            else "unused"
        )
        self._client = AsyncOpenAI(
            base_url=settings.MODEL_GATEWAY_BASE_URL,
            api_key=api_key,
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0),
            max_retries=0,
        )

    async def aclose(self) -> None:
        """Release the underlying httpx pool. Called from ``lifespan`` shutdown."""
        await self._client.close()

    async def list_models(self) -> list[Model]:
        try:
            page = await self._client.models.list()
        except (APIStatusError, APIError) as e:
            raise ProviderError(f"gateway list_models failed: {e}", status_code=502) from e

        out: list[Model] = []
        for m in page.data:
            out.append(Model(id=m.id, label=m.id, owned_by=getattr(m, "owned_by", None)))
        out.sort(key=lambda m: m.id)
        return out

    async def stream(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        params: dict[str, Any],
    ) -> AsyncIterator[StreamDelta]:
        msgs = list(messages)
        if params.get("system"):
            msgs.insert(0, {"role": "system", "content": params["system"]})

        kwargs: dict[str, Any] = {
            "model": model,
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
