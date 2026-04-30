"""``POST /v1/chat/completions`` with ``stream=True`` emits the OpenAI SSE shape.

The mock seam used here is ``pydantic_ai.models.test.TestModel``. We
build a fresh :class:`AgentEntry` whose underlying ``Agent`` runs
against ``TestModel(custom_output_text=...)`` instead of the production
``OpenAIModel`` pointed at Ollama. ``TestModel`` plugs in at the
model-driver layer that ``Agent`` already abstracts, so:

* The platform's ``_stream_response`` (and its ``agent.iter()`` loop)
  runs unchanged — including the pydantic-ai event taxonomy
  (``PartStartEvent`` + ``PartDeltaEvent``) and the chunk emitter.
* No ``respx`` HTTP mock is required. Mocking pydantic-ai's outbound
  OpenAI HTTP is fragile (request body matching, telemetry headers,
  SDK version drift) — ``TestModel`` collapses all of that into one
  in-process knob.

Plan reference: ``rebuild/docs/plans/feature-llm-models.md`` § API
surface (agent platform) → ``POST /v1/chat/completions`` (streaming
shape) and § Tests → Unit tests (``test_oai_router_chat.py``).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

from fastapi.testclient import TestClient
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.agents import AgentEntry
from app.config import Settings


def _build_test_agent_dict(
    settings: Settings, *, output_text: str = "hello there"
) -> dict[str, AgentEntry]:
    """Construct the agents map with a ``TestModel``-backed agent.

    Single ``ModelDef`` (the platform default), single agent — the
    minimum surface needed to exercise ``_stream_response``.
    """
    defn = settings.MODELS[0]
    agent: Agent[None, str] = Agent(
        model=TestModel(custom_output_text=output_text),
        output_type=str,
    )
    return {defn.id: AgentEntry(definition=defn, agent=agent)}


def _parse_sse_frames(body: str) -> list[str]:
    """Split an SSE response body into raw frame strings (excluding
    the trailing blank line). ``[DONE]`` is preserved as its own
    frame so callers can assert its presence by string compare.
    """
    return [frame for frame in body.split("\n\n") if frame]


def test_chat_completions_stream_emits_openai_chunks(
    make_client: Callable[[Mapping[str, AgentEntry]], TestClient],
    app_settings: Settings,
) -> None:
    agents = _build_test_agent_dict(app_settings, output_text="hello there from the test")
    client = make_client(agents)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "dev",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    frames = _parse_sse_frames(response.text)
    assert frames, "expected at least one SSE frame"

    assert frames[-1] == "data: [DONE]"

    chunks: list[dict] = []
    for frame in frames[:-1]:
        assert frame.startswith("data: "), f"unexpected frame: {frame!r}"
        payload = frame[len("data: ") :]
        parsed = json.loads(payload)
        chunks.append(parsed)

    assert len(chunks) >= 3, f"expected role + content + finish frames; got {len(chunks)}"

    for chunk in chunks:
        assert chunk["id"].startswith("chatcmpl-")
        assert chunk["object"] == "chat.completion.chunk"
        assert chunk["model"] == "dev"
        assert isinstance(chunk["created"], int)
        assert len(chunk["choices"]) == 1
        assert "delta" in chunk["choices"][0]

    assert chunks[0]["choices"][0]["delta"].get("role") == "assistant"

    content_pieces = [
        c["choices"][0]["delta"].get("content")
        for c in chunks
        if c["choices"][0]["delta"].get("content")
    ]
    assert content_pieces, "expected at least one delta.content frame"

    final_chunk = chunks[-1]
    assert final_chunk["choices"][0]["finish_reason"] == "stop"


def test_chat_completions_stream_unknown_model_returns_404(
    make_client: Callable[[Mapping[str, AgentEntry]], TestClient],
    app_settings: Settings,
) -> None:
    """Unknown model ids surface as 404 ``unknown model: <id>``.

    Locks the contract called out in
    ``feature-llm-models.md`` § API surface → Errors. The rebuild's
    cache normally prevents this from reaching the platform, but the
    platform still returns a clean 404 if it does.
    """
    agents = _build_test_agent_dict(app_settings)
    client = make_client(agents)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "no-such-alias",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )

    assert response.status_code == 404
    assert "unknown model" in response.json()["detail"]


def test_chat_completions_stream_no_user_message_returns_400(
    make_client: Callable[[Mapping[str, AgentEntry]], TestClient],
    app_settings: Settings,
) -> None:
    """An assistant-only history hits ``_seed_history``'s defensive
    ``HTTPException(400)`` branch on the streaming entrypoint.

    The 400 must surface as a synchronous JSON response — *not* an
    empty SSE body that quietly closes — because ``_seed_history``
    raises before ``StreamingResponse`` is constructed. Locks the
    symmetric contract with the non-stream test of the same name; a
    future refactor that defers history-seeding into the SSE generator
    (and thus past the response-headers boundary) breaks the test
    loudly.
    """
    agents = _build_test_agent_dict(app_settings)
    client = make_client(agents)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "dev",
            "messages": [{"role": "assistant", "content": "orphan"}],
            "stream": True,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "no user message in request"
