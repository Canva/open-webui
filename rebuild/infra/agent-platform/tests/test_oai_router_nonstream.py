"""Tests for ``POST /v1/chat/completions`` with ``stream=False``.

Same mock seam as the streaming tests (see
``test_oai_router_chat.py``'s module docstring): we swap the agent in
``app.state.agents`` for one whose backing ``Model`` is
:class:`pydantic_ai.models.function.FunctionModel` returning a fixed
``ModelResponse``. This bypasses the OpenAI HTTP layer entirely while
exercising the full router → ``_seed_history`` → ``agent.run`` →
``ChatCompletionResponse`` envelope construction.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agents import AgentEntry
from app.config import AgentDef
from app.oai_router import router as oai_router

REPLY_TEXT = "Hi back!"


async def _fake_request(
    messages: list[ModelMessage],
    info: AgentInfo,
) -> ModelResponse:
    """Non-streaming ``FunctionDef``: returns a single ``TextPart``
    with the reply.

    The router's non-stream branch reads ``result.output`` (the joined
    text) and ``result.usage()`` and projects both into
    ``ChatCompletionResponse``. ``ModelResponse``'s default
    ``RequestUsage`` is empty, which gives us the documented
    "values can be 0 if mock doesn't surface them" envelope.
    """
    return ModelResponse(parts=[TextPart(content=REPLY_TEXT)])


@pytest.fixture
def nonstreaming_client() -> Iterator[TestClient]:
    """Bare app + ``app.state.agents`` populated with a single
    ``FunctionModel``-backed non-streaming agent. No Ollama, no lifespan."""
    app = FastAPI(title="agent-platform-nonstream-tests", version="0.0.0")
    app.include_router(oai_router)
    fake_model = FunctionModel(function=_fake_request, model_name="dev")
    agent = Agent(model=fake_model, output_type=str)
    app.state.agents = {
        "dev": AgentEntry(
            definition=AgentDef(
                id="dev",
                label="Dev (Qwen 2.5, 0.5B)",
                ollama_tag="qwen2.5:0.5b",
            ),
            agent=agent,
        )
    }
    with TestClient(app) as c:
        yield c


def test_nonstream_returns_chat_completion_envelope(
    nonstreaming_client: TestClient,
) -> None:
    """The non-stream branch builds a single ``ChatCompletionResponse``
    JSON envelope. Every field the rebuild's provider would read on a
    non-stream path must be populated: ``object``, ``id`` (with the
    ``chatcmpl-`` prefix), ``model``, the assistant message, the finish
    reason, and the (potentially-zero) usage triple."""
    response = nonstreaming_client.post(
        "/v1/chat/completions",
        json={
            "model": "dev",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["object"] == "chat.completion"
    assert body["id"].startswith("chatcmpl-")
    assert body["model"] == "dev"

    choice = body["choices"][0]
    assert choice["message"]["role"] == "assistant"
    assert choice["message"]["content"] == REPLY_TEXT
    assert choice["finish_reason"] == "stop"

    usage = body["usage"]
    # FunctionModel auto-estimates usage from the message log; we don't
    # pin specific values, just the int contract — the rebuild's pipeline
    # treats missing/zero usage as a no-op.
    assert isinstance(usage["prompt_tokens"], int)
    assert isinstance(usage["completion_tokens"], int)
    assert isinstance(usage["total_tokens"], int)


def test_nonstream_unknown_model_returns_404(
    nonstreaming_client: TestClient,
) -> None:
    """Same 404 contract as the streaming branch — ``unknown model: <id>``
    is the locked detail string the rebuild reads to surface a clean
    error in the dropdown."""
    response = nonstreaming_client.post(
        "/v1/chat/completions",
        json={
            "model": "nope",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "unknown model: nope"


def test_nonstream_no_user_message_returns_400(
    nonstreaming_client: TestClient,
) -> None:
    """``_seed_history``'s 400 surfaces synchronously on the non-stream
    path (no ``StreamingResponse`` wrapping the generator), so the body
    is JSON not SSE. Locks the symmetric contract with the streaming
    test of the same name."""
    response = nonstreaming_client.post(
        "/v1/chat/completions",
        json={
            "model": "dev",
            "messages": [{"role": "assistant", "content": "orphan"}],
            "stream": False,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "no user message in request"
