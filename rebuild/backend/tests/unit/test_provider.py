"""Unit tests for :class:`app.providers.openai.OpenAICompatibleProvider`.

The provider is the rebuild's only model-gateway transport — every
upstream failure mode has to map cleanly onto :class:`ProviderError`
with the right HTTP status code, otherwise the streaming pipeline's
SSE error frames and the non-streaming routes' 502 / 504 / 429
responses will diverge.

We test against an in-process mock whose ``http_client`` is bound by
:class:`httpx.ASGITransport` to a tiny FastAPI app — no network, no
``respx`` lifetime gymnastics around the openai SDK's own httpx pool.

Plan reference: ``rebuild/docs/plans/m2-conversations.md`` § Tests
(``tests/unit/test_provider.py`` bullet, line 1050) and § Provider
abstraction (the exception-mapping contract on lines 401-410, 426-430).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from app.providers.openai import (
    Model,
    OpenAICompatibleProvider,
    ProviderError,
    StreamDelta,
)
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response, StreamingResponse
from httpx import ASGITransport
from openai import AsyncOpenAI


def _chunk(
    *,
    content: str | None = None,
    finish_reason: str | None = None,
    role: str | None = None,
    usage: dict[str, int] | None = None,
) -> str:
    """Build one SSE record matching the OpenAI chat-completion chunk
    shape the SDK deserialises into ``ChatCompletionChunk``."""
    delta: dict[str, Any] = {}
    if role is not None:
        delta["role"] = role
    if content is not None:
        delta["content"] = content
    if usage is not None:
        body = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": "gpt-4o",
            "choices": [],
            "usage": usage,
        }
    else:
        body = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": "gpt-4o",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
    return f"data: {json.dumps(body, separators=(',', ':'))}\n\n"


def _make_provider(
    handler: Any, *, raise_on_request: Exception | None = None
) -> tuple[OpenAICompatibleProvider, httpx.AsyncClient]:
    """Construct an :class:`OpenAICompatibleProvider` whose underlying
    SDK client is bound to a one-route in-process FastAPI app via
    :class:`ASGITransport`. The route's body is whatever ``handler``
    yields. Tests get a real OpenAI SDK roundtrip for free without
    needing a real network or ``respx``.

    ``raise_on_request`` is the escape hatch for tests that need the
    transport itself to raise (e.g. a forced timeout) before any
    response bytes are emitted.
    """
    app = FastAPI()

    if raise_on_request is not None:

        @app.post("/v1/chat/completions")
        async def _raise() -> Response:
            raise raise_on_request

        @app.get("/v1/models")
        async def _models() -> Response:
            raise raise_on_request

    else:

        @app.post("/v1/chat/completions")
        async def _completions() -> Response:
            result: Response = await handler()
            return result

        @app.get("/v1/models")
        async def _models() -> Response:
            result: Response = await handler()
            return result

    provider = OpenAICompatibleProvider()
    asyncio.get_event_loop()  # noqa: F841 — sanity for pytest-asyncio loop
    mock_client = httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://provider-test",
    )
    sdk = AsyncOpenAI(
        api_key="test",
        base_url="http://provider-test/v1",
        http_client=mock_client,
    )
    provider._client = sdk  # noqa: SLF001 — test-only swap
    return provider, mock_client


# ---------------------------------------------------------------------------
# stream
# ---------------------------------------------------------------------------


async def test_stream_yields_token_chunks_then_usage_then_finish() -> None:
    """Happy path: the SDK stream is mapped to a sequence of
    :class:`StreamDelta` instances with content, finish reason, and a
    final usage chunk.

    The provider's own ``_chunk = chunk.choices[0]`` branch is what we
    care about here — empty content chunks must not be filtered (the
    streaming generator is what filters), and usage chunks come through
    as standalone deltas with content="".
    """
    body = (
        _chunk(role="assistant")
        + _chunk(content="Hi")
        + _chunk(content=" there", finish_reason="stop")
        + _chunk(usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8})
    )

    async def _handler() -> Response:
        async def _emit() -> AsyncIterator[bytes]:
            yield body.encode()

        return StreamingResponse(_emit(), media_type="text/event-stream")

    provider, mock_client = _make_provider(_handler)
    try:
        deltas: list[StreamDelta] = []
        async for delta in provider.stream(
            messages=[{"role": "user", "content": "hi"}],
            model="gpt-4o",
            params={},
        ):
            deltas.append(delta)
    finally:
        await mock_client.aclose()

    assert len(deltas) == 4
    assert deltas[0].content == ""  # role-only chunk has no content
    assert deltas[1].content == "Hi"
    assert deltas[2].content == " there"
    assert deltas[2].finish_reason == "stop"
    assert deltas[3].usage == {
        "prompt_tokens": 5,
        "completion_tokens": 3,
        "total_tokens": 8,
        "completion_tokens_details": None,
        "prompt_tokens_details": None,
    }


async def _drain_stream(provider: OpenAICompatibleProvider) -> None:
    """Run the provider's stream to completion (or to its first error).

    Extracted so the ``pytest.raises`` blocks below stay single-statement
    (ruff PT012) — each error-shape test asserts on the wrapped
    :class:`ProviderError` raised here, not on iteration mechanics.
    """
    async for _ in provider.stream(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-4o",
        params={},
    ):
        pass


async def test_stream_wraps_apitimeouterror_as_provider_error_504() -> None:
    """A read timeout from the upstream SDK call surfaces as
    :class:`ProviderError(504)` so the centralised handler maps it to
    HTTP 504 (and the streaming generator emits an ``error`` SSE frame
    with the same status_code).
    """
    provider, mock_client = _make_provider(
        handler=None,
        raise_on_request=httpx.ReadTimeout("upstream slow"),
    )
    try:
        with pytest.raises(ProviderError) as exc_info:
            await _drain_stream(provider)
    finally:
        await mock_client.aclose()
    assert exc_info.value.status_code == 504
    assert "upstream timeout" in str(exc_info.value)


async def test_stream_wraps_ratelimiterror_as_provider_error_429() -> None:
    """An HTTP 429 from the upstream maps to :class:`ProviderError(429)`."""

    async def _handler() -> Response:
        return JSONResponse(
            {"error": {"message": "rate limited", "type": "rate_limit"}},
            status_code=429,
        )

    provider, mock_client = _make_provider(_handler)
    try:
        with pytest.raises(ProviderError) as exc_info:
            await _drain_stream(provider)
    finally:
        await mock_client.aclose()
    assert exc_info.value.status_code == 429
    assert "rate-limited" in str(exc_info.value)


async def test_stream_wraps_apistatuserror_as_provider_error_502() -> None:
    """An HTTP 5xx from the upstream maps to :class:`ProviderError(502)`."""

    async def _handler() -> Response:
        return JSONResponse(
            {"error": {"message": "internal", "type": "server_error"}},
            status_code=503,
        )

    provider, mock_client = _make_provider(_handler)
    try:
        with pytest.raises(ProviderError) as exc_info:
            await _drain_stream(provider)
    finally:
        await mock_client.aclose()
    assert exc_info.value.status_code == 502
    assert "503" in str(exc_info.value)


async def test_stream_propagates_cancellation_after_closing_underlying_stream() -> None:
    """Per plan § Provider abstraction line 426-428: when a task running
    the provider iteration is cancelled (Starlette's client-disconnect
    path), the :class:`asyncio.CancelledError` raised at the inner
    ``await`` point must be caught long enough to call ``stream.close()``
    on the SDK's :class:`AsyncStream` — releasing the upstream
    connection — and then re-raised so the framework knows the
    iteration ended on a cancel.

    We assert the contract by replacing the SDK call site with a fake
    ``AsyncStream``-shaped object whose ``__aiter__`` blocks on a
    never-firing event after the first chunk and whose ``close()`` sets
    a sentinel. (Going through the real SDK + httpx ``ASGITransport``
    would not work here because ``ASGITransport`` buffers the entire
    response body before delivering it to the SDK, so a cancel before
    the upstream completes would never reach the provider's inner
    await.)
    """
    closed = asyncio.Event()
    suspended = asyncio.Event()

    role_chunk_obj: Any = type(
        "_FakeChunk",
        (),
        {
            "usage": None,
            "choices": [
                type(
                    "_Choice",
                    (),
                    {
                        "delta": type(
                            "_Delta",
                            (),
                            {"content": "Hi", "role": "assistant"},
                        )(),
                        "finish_reason": None,
                    },
                )()
            ],
        },
    )()

    class _FakeAsyncStream:
        async def close(self) -> None:
            closed.set()

        def __aiter__(self) -> Any:
            return self

        async def __anext__(self) -> Any:
            if not suspended.is_set():
                # First call: emit one chunk so the provider yields a
                # delta to the consumer. Subsequent calls block forever
                # so the consumer-task cancel below surfaces as
                # CancelledError at the provider's inner await — exactly
                # the Starlette client-disconnect shape.
                suspended.set()
                return role_chunk_obj
            never_fires = asyncio.Event()
            await never_fires.wait()
            return role_chunk_obj  # pragma: no cover

    fake_stream = _FakeAsyncStream()

    provider = OpenAICompatibleProvider()
    await provider._client.close()  # noqa: SLF001 — test-only swap

    async def _fake_create(**_kwargs: Any) -> Any:
        return fake_stream

    # Replace the SDK call site directly. ``provider.stream`` only
    # touches ``self._client.chat.completions.create`` and the returned
    # object's iterator + close protocol — fake_stream satisfies both.
    provider._client.chat.completions.create = _fake_create  # type: ignore[method-assign]

    async def _consume() -> None:
        async for _ in provider.stream(
            messages=[{"role": "user", "content": "hi"}],
            model="gpt-4o",
            params={},
        ):
            pass

    consumer = asyncio.create_task(_consume())
    # Wait until the provider has yielded the first delta and is
    # awaiting the next chunk — that's when its inner await is the
    # one that will receive the cancellation.
    for _ in range(20):
        await asyncio.sleep(0)
        if suspended.is_set():
            break
    assert suspended.is_set(), "provider should have iterated past the first chunk"

    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer

    assert closed.is_set(), "provider must call stream.close() on cancel"


# ---------------------------------------------------------------------------
# list_models
# ---------------------------------------------------------------------------


async def test_list_models_returns_sorted_by_id() -> None:
    """Provider sorts the upstream list by ``id`` so the dropdown is
    stable across upstream-side reorderings."""

    async def _handler() -> Response:
        return JSONResponse(
            {
                "object": "list",
                "data": [
                    {"id": "zeta", "object": "model", "owned_by": "x"},
                    {"id": "alpha", "object": "model", "owned_by": "x"},
                    {"id": "mu", "object": "model", "owned_by": "y"},
                ],
            }
        )

    provider, mock_client = _make_provider(_handler)
    try:
        models = await provider.list_models()
    finally:
        await mock_client.aclose()

    assert [m.id for m in models] == ["alpha", "mu", "zeta"]
    assert all(isinstance(m, Model) for m in models)
    assert models[0].label == "alpha"  # label falls back to id
    assert models[2].owned_by == "x"


async def test_list_models_wraps_errors_as_provider_error_502() -> None:
    """Any 5xx from the upstream maps to :class:`ProviderError(502)`."""

    async def _handler() -> Response:
        return JSONResponse(
            {"error": {"message": "boom", "type": "server_error"}},
            status_code=500,
        )

    provider, mock_client = _make_provider(_handler)
    try:
        with pytest.raises(ProviderError) as exc_info:
            await provider.list_models()
    finally:
        await mock_client.aclose()
    assert exc_info.value.status_code == 502
    assert "list_models" in str(exc_info.value)
