"""Cassette-replay LLM mock — the OpenAI-compatible upstream stand-in for
the M2 integration suite.

This module mocks the **upstream agent gateway** which speaks the
OpenAI wire format, so the wire field names (``model``) and HTTP path
(``/v1/models``) deliberately retain the OpenAI nomenclature. The
rebuild's *internal* domain talks about *agents*; the translation
happens in :class:`app.providers.openai.OpenAICompatibleProvider`.

A tiny FastAPI app exposing the two endpoints the rebuild's
:class:`app.providers.openai.OpenAICompatibleProvider` ever hits:

* ``GET /v1/models`` — fixed agent list (overridable per-test by mounting
  ``app.state.models``; the attribute keeps the OpenAI wire field name).
  No hashing; the rebuild's
  ``OpenAICompatibleProvider.list_agents`` calls this once on cache fill.
* ``POST /v1/chat/completions`` — request hashed via
  :func:`compute_cassette_hash` to a filename under
  ``rebuild/backend/tests/fixtures/llm/``:
    * Streaming requests look up ``<hash>.sse`` and replay the file
      byte-for-byte with ``Content-Type: text/event-stream``.
    * Non-streaming (title helper) requests look up ``<hash>.json`` and
      return it as ``application/json``; on miss we synthesise a
      ``{"choices":[{"message":{"content":"Cassette miss"}}]}`` envelope
      so the title-helper integration test surfaces the cassette gap
      without crashing the route.

The hash is short (16 hex chars) for filename ergonomics and long enough
that a collision in our ~dozen test scenarios is implausible. The hash
is computed on the canonical JSON form ``{"messages","model","temperature"}``
of the **request body the wire sees** — the rebuild's provider has
already prepended any ``params.system`` into ``messages[0]`` before the
HTTP call, so ``system`` does not need to appear separately in the hash.

``LLM_RECORD=1`` proxy mode (record cassettes from a real upstream on
first run, replay thereafter) is **deferred** per the M2 dispatch.
Cassettes are hand-crafted today; the proxy path lives in this docstring
as future work and not in code so the file replay surface stays the only
test path that can possibly fire.

Plan reference: ``rebuild/docs/plans/m2-conversations.md`` § Tests
("Cassette strategy for the agent gateway mock", lines 1075-1080).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response, StreamingResponse

# Where cassette files live relative to this module. Resolving via
# ``__file__`` keeps the suite cwd-independent — the same module works
# whether pytest is invoked from ``rebuild/`` or ``rebuild/backend/``.
HERE = Path(__file__).resolve().parent
FIXTURES_DIR = HERE / "fixtures" / "llm"

DEFAULT_MODELS: list[dict[str, Any]] = [
    {"id": "gpt-4o", "object": "model", "owned_by": "openai"},
    {"id": "gpt-4o-mini", "object": "model", "owned_by": "openai"},
    {"id": "claude-3-5-sonnet-20241022", "object": "model", "owned_by": "anthropic"},
]


def compute_cassette_hash(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float | None = None,
) -> str:
    """Hash the canonical request shape to a 16-char filename stem.

    The dispatch's spec is ``hashlib.sha256(json.dumps(request_dict,
    sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16]``;
    this is the implementation cassette authors use to derive the
    cassette filename their test will hit.
    """
    canonical_body = {"model": model, "messages": messages, "temperature": temperature}
    canonical = json.dumps(canonical_body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _hash_request_body(body: dict[str, Any]) -> str:
    """Server-side mirror of :func:`compute_cassette_hash`.

    The rebuild's provider posts ``{"model","messages","stream",
    "stream_options","temperature?"}``; we strip ``stream`` /
    ``stream_options`` so streaming and non-streaming requests with
    otherwise identical payloads collide on the same hash (and disambiguate
    via the ``.sse`` vs ``.json`` extension on the cassette file).
    """
    return compute_cassette_hash(
        model=body["model"],
        messages=body["messages"],
        temperature=body.get("temperature"),
    )


def create_mock_app(*, fixtures_dir: Path = FIXTURES_DIR) -> FastAPI:
    """Build a fresh mock app instance.

    Tests that need a custom agent list can mutate ``app.state.models``
    after construction; the attribute name keeps the OpenAI wire field
    so the route handler stays a faithful upstream stand-in. The
    default list ships with the three ids the rebuild's frontend
    dropdown is expected to render.
    """
    app = FastAPI(title="llm-mock", version="0.0.0")
    app.state.models = list(DEFAULT_MODELS)
    app.state.fixtures_dir = fixtures_dir

    @app.get("/v1/models")
    async def list_models() -> dict[str, Any]:
        return {"object": "list", "data": list(app.state.models)}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        body = await request.json()
        if "model" not in body or "messages" not in body:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="missing required fields: model, messages",
            )
        cassette_hash = _hash_request_body(body)
        is_streaming = bool(body.get("stream"))
        if is_streaming:
            return _replay_sse(app.state.fixtures_dir, cassette_hash)
        return _replay_json(app.state.fixtures_dir, cassette_hash)

    return app


def _replay_sse(fixtures_dir: Path, cassette_hash: str) -> Response:
    cassette = fixtures_dir / f"{cassette_hash}.sse"
    if not cassette.exists():
        # 404 with the hash in the body so the test author knows exactly
        # which cassette filename to author. Returning the hash inside
        # the response (not just the URL) keeps it visible even when the
        # SDK swallows the URL on its way to the exception.
        return JSONResponse(
            {
                "error": {
                    "message": (
                        f"cassette not found: {cassette_hash}.sse " f"(expected at {cassette})"
                    ),
                    "type": "cassette_miss",
                    "hash": cassette_hash,
                }
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )
    payload = cassette.read_bytes()

    async def _emit() -> Any:
        # Cassette frames are split on the SSE record terminator (``\n\n``)
        # so each ``data: ...`` chunk leaves the mock as a separate HTTP
        # body chunk and the OpenAI SDK observes them as discrete events
        # over time. Comment-only frames of the literal shape
        # ``: delay <seconds>`` are interpreted by the mock as a sleep
        # directive (NOT forwarded), so cassettes can encode the delays
        # the timeout / cancel-mid-stream tests need without the mock
        # needing per-test configuration. The delay marker is the only
        # divergence from a strict OpenAI SSE replay.
        import asyncio

        for raw_record in payload.split(b"\n\n"):
            record = raw_record.strip()
            if not record:
                continue
            if record.startswith(b": delay "):
                try:
                    seconds = float(record[len(b": delay ") :].decode("ascii"))
                except ValueError:  # pragma: no cover — bad cassette
                    seconds = 0.0
                if seconds > 0:
                    await asyncio.sleep(seconds)
                continue
            yield record + b"\n\n"

    return StreamingResponse(_emit(), media_type="text/event-stream")


def _replay_json(fixtures_dir: Path, cassette_hash: str) -> Response:
    cassette = fixtures_dir / f"{cassette_hash}.json"
    if cassette.exists():
        return Response(content=cassette.read_bytes(), media_type="application/json")
    # Missing cassette → synthesise a minimal-but-valid completion so the
    # title-helper integration test surfaces the cassette gap as a
    # readable title rather than a 502.
    fallback = {
        "id": f"chatcmpl-miss-{cassette_hash}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "cassette-miss",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Cassette miss"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 2, "total_tokens": 2},
    }
    return JSONResponse(fallback)


# Module-level app instance for tests that don't need per-test isolation.
# Test fixtures requiring a custom agent list construct a fresh instance
# via :func:`create_mock_app` and mutate its ``app.state.models`` (the
# OpenAI wire field name).
app = create_mock_app()
