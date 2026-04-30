from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

import uuid7
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    UserPromptPart,
)

from app.agents import AgentEntry
from app.oai_models import (
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    ChunkChoice,
    DeltaContent,
    ModelInfo,
    ModelListResponse,
    Usage,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["openai-compat"])


def _now() -> int:
    return int(time.time())


def _completion_id() -> str:
    # UUIDv7 (not uuid4) per the project-wide rule — see the plan's
    # § Project-wide conventions and rebuild.md §9. The ruff banned-api
    # rule in pyproject.toml enforces this against drift.
    return f"chatcmpl-{uuid7.create()}"


def _seed_history(messages: list[ChatMessage]) -> tuple[list[ModelMessage], str]:
    """Translate OpenAI-style ``messages`` into a Pydantic-AI
    ``message_history`` plus the trailing user prompt.

    Pydantic-AI's ``Agent.iter()`` takes the latest user message via the
    ``user_prompt`` argument separately from ``message_history``; passing
    the same turn through both would double-stack it. This helper:

    1. Inlines any ``system`` messages into a prefix on the user prompt
       (the rebuild's provider already prepends ``params.system`` into
       ``messages[0]``, but we still handle the raw OpenAI ``system``
       role for callers that send it directly).
    2. Builds a ``ModelRequest`` / ``ModelResponse`` history mirroring
       the OpenAI conversation.
    3. **Drops the trailing ``ModelRequest`` from the history** so
       ``agent.iter()`` doesn't replay it on top of ``user_prompt``.
    4. Raises ``HTTPException(400)`` if there is no user message.
    """
    history: list[ModelMessage] = []
    system_prefix = ""
    user_prompt = ""
    for msg in messages:
        if msg.role == "system":
            system_prefix = (system_prefix + "\n\n" + msg.content).strip()
        elif msg.role == "user":
            user_prompt = msg.content
            history.append(ModelRequest(parts=[UserPromptPart(content=msg.content)]))
        elif msg.role == "assistant":
            history.append(ModelResponse(parts=[TextPart(content=msg.content)]))
    if not user_prompt:
        raise HTTPException(status_code=400, detail="no user message in request")
    # Drop the last user message from history — Pydantic-AI's iter() takes
    # it via the user_prompt arg; sending it twice double-stacks the turn.
    if history and isinstance(history[-1], ModelRequest):
        history.pop()
    if system_prefix:
        user_prompt = f"{system_prefix}\n\n{user_prompt}"
    return history, user_prompt


@router.get("/models")
async def list_models(request: Request) -> ModelListResponse:
    agents: dict[str, AgentEntry] = request.app.state.agents
    now = _now()
    return ModelListResponse(
        data=[
            ModelInfo(
                id=entry.definition.id,
                created=now,
                owned_by=entry.definition.owned_by,
                label=entry.definition.label,
            )
            for entry in agents.values()
        ]
    )


@router.post("/chat/completions")
async def chat_completions(body: ChatCompletionRequest, request: Request):
    agents: dict[str, AgentEntry] = request.app.state.agents
    entry = agents.get(body.model)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown model: {body.model}")

    history, user_prompt = _seed_history(body.messages)

    if body.stream:
        return StreamingResponse(
            _stream_response(entry, body.model, user_prompt, history),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    result = await entry.agent.run(user_prompt=user_prompt, message_history=history)
    text: str = result.output
    usage = result.usage()
    return ChatCompletionResponse(
        id=_completion_id(),
        created=_now(),
        model=body.model,
        choices=[ChatCompletionChoice(message=ChatMessage(role="assistant", content=text))],
        usage=Usage(
            prompt_tokens=usage.request_tokens or 0,
            completion_tokens=usage.response_tokens or 0,
            total_tokens=usage.total_tokens or 0,
        ),
    )


async def _stream_response(
    entry: AgentEntry,
    model_id: str,
    user_prompt: str,
    history: list[ModelMessage],
) -> AsyncIterator[str]:
    """Yield SSE-formatted ``ChatCompletionChunk`` frames terminated by
    ``data: [DONE]\\n\\n``.

    We use ``agent.iter()`` (not ``agent.run_stream()``) so a future
    tool-using agent plugs in here without rewriting the streaming path.

    Divergence from OpenAI: **no terminal usage chunk.** OpenAI emits a
    final usage delta when ``stream_options.include_usage=true`` (which
    the rebuild's provider sets). Pydantic-AI's ``agent.iter()`` does
    not surface per-chunk usage cleanly through node-stream events
    today; the rebuild's streaming pipeline already gates on
    ``if delta.usage:``, so a missing usage chunk is a no-op there.
    """
    cid = _completion_id()
    created = _now()

    yield (
        "data: "
        + ChatCompletionChunk(
            id=cid,
            created=created,
            model=model_id,
            choices=[ChunkChoice(delta=DeltaContent(role="assistant"))],
        ).model_dump_json()
        + "\n\n"
    )

    try:
        async with entry.agent.iter(user_prompt=user_prompt, message_history=history) as run:
            async for node in run:
                # Local import — pydantic-ai's Agent classmethod is only
                # used on the streaming path, no need to pin it at module
                # import time.
                from pydantic_ai import Agent

                if not Agent.is_model_request_node(node):
                    continue
                async with node.stream(run.ctx) as request_stream:
                    async for event in request_stream:
                        text_delta = ""
                        if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                            text_delta = event.part.content or ""
                        elif isinstance(event, PartDeltaEvent) and isinstance(
                            event.delta, TextPartDelta
                        ):
                            text_delta = event.delta.content_delta or ""
                        if not text_delta:
                            continue
                        yield (
                            "data: "
                            + ChatCompletionChunk(
                                id=cid,
                                created=created,
                                model=model_id,
                                choices=[ChunkChoice(delta=DeltaContent(content=text_delta))],
                            ).model_dump_json()
                            + "\n\n"
                        )
    except asyncio.CancelledError:
        # Re-raise so Starlette can tear down the upstream connection
        # cleanly. We log it for dev-loop visibility; cancellation is
        # routine on user-driven stop, not an error.
        log.info("client disconnected mid-stream for model %s", model_id)
        raise

    yield (
        "data: "
        + ChatCompletionChunk(
            id=cid,
            created=created,
            model=model_id,
            choices=[ChunkChoice(delta=DeltaContent(), finish_reason="stop")],
        ).model_dump_json()
        + "\n\n"
    )
    yield "data: [DONE]\n\n"
