"""Pydantic-shape tests for ``ChatCompletionRequest`` and friends.

The rebuild's :class:`OpenAICompatibleProvider.stream` posts a body
shaped like::

    {
        "model": "...",
        "messages": [...],
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": ...,
    }

The platform's :class:`ChatCompletionRequest` doesn't model
``stream_options`` explicitly — it carries ``ConfigDict(extra="allow")``
so the OpenAI SDK's extra fields survive ``model_validate`` cleanly.
This test locks both halves of the contract: extra fields are
accepted *and* preserved (so a future change that flips ``extra`` to
``"ignore"`` or ``"forbid"`` breaks the test loudly).

Plan reference: ``rebuild/docs/plans/feature-llm-models.md`` § Tests
→ Unit tests (``test_oai_models.py``).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.oai_models import ChatCompletionRequest


PAYLOAD: dict = {
    "model": "gpt-4o",
    "messages": [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "hi"},
    ],
    "stream": True,
    "stream_options": {"include_usage": True},
    "temperature": 0.7,
}


def test_request_accepts_real_provider_payload() -> None:
    parsed = ChatCompletionRequest.model_validate(PAYLOAD)

    assert parsed.model == "gpt-4o"
    assert parsed.stream is True
    assert parsed.temperature == 0.7
    assert len(parsed.messages) == 2
    assert parsed.messages[0].role == "system"
    assert parsed.messages[0].content == "You are helpful."
    assert parsed.messages[1].role == "user"
    assert parsed.messages[1].content == "hi"


def test_request_preserves_extra_fields() -> None:
    """``extra="allow"`` keeps ``stream_options`` reachable.

    The platform doesn't pass ``stream_options`` through to Pydantic-AI
    (the agent runs the OpenAI loop itself), so this is purely about
    "the request validates" — but locking that the field survives
    means a future "let's just look at body.stream_options" patch
    won't silently see ``None``.
    """
    parsed = ChatCompletionRequest.model_validate(PAYLOAD)

    extras = parsed.model_extra or {}
    assert "stream_options" in extras
    assert extras["stream_options"] == {"include_usage": True}


def test_request_allows_arbitrary_extras() -> None:
    """Arbitrary extras (telemetry, request metadata, ...) round-trip."""
    payload = dict(PAYLOAD, metadata={"trace_id": "abc-123"})
    parsed = ChatCompletionRequest.model_validate(payload)
    extras = parsed.model_extra or {}
    assert extras.get("metadata") == {"trace_id": "abc-123"}


def test_request_missing_model_field_raises() -> None:
    """``model`` is required; the OpenAI spec mandates it.

    Without this the platform would have nothing to look up in the
    agents registry and would fall through to the 404 branch — but
    the right shape is a 422 at parse time, not a 404 at dispatch.
    """
    payload = {k: v for k, v in PAYLOAD.items() if k != "model"}
    with pytest.raises(ValidationError):
        ChatCompletionRequest.model_validate(payload)
