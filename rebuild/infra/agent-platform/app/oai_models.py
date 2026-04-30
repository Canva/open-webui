from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    # The OpenAI SDK adds telemetry headers and the occasional
    # ``stream_options`` field that we don't model explicitly. Allow
    # extras so the request validates cleanly.
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: Usage = Usage()


class DeltaContent(BaseModel):
    role: str | None = None
    content: str | None = None


class ChunkChoice(BaseModel):
    index: int = 0
    delta: DeltaContent
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChunkChoice]


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str
    # Non-OpenAI extension. The rebuild's OpenAICompatibleProvider reads
    # this via ``getattr(m, "label", None)`` so absent labels fall back
    # to ``m.id``; emitting it here is what surfaces friendly names like
    # "Dev (Qwen 2.5, 0.5B)" in the rebuild's model dropdown.
    label: str


class ModelListResponse(BaseModel):
    object: str = "list"
    data: list[ModelInfo]
