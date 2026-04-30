"""Table-driven test for ``_seed_history``.

The plan calls out four happy-path scenarios (a-d) plus the locked
defensive ``HTTPException(400)`` for the no-user-message case. Each
scenario locks one structural invariant of the OpenAI → Pydantic-AI
translation:

* **(a) single user**           — empty history, prompt verbatim.
* **(b) [system, user]**        — system inlined as a prefix on the
  prompt, no system role in history (the rebuild's provider already
  prepends ``params.system`` into ``messages[0]`` but we still handle
  raw OpenAI ``system`` for callers that send it directly).
* **(c) [user, assistant, user]** — multi-turn history of one
  ``ModelRequest`` + one ``ModelResponse``; the **trailing user is
  dropped** so ``agent.iter()`` doesn't double-stack the turn.
* **(d) [system, user, assistant, system, user]** — both ``system``
  messages concatenated (newline-joined) into the prefix; the
  ``[user, assistant]`` history element pair survives unchanged.

Plus (e), the only error case the helper raises:

* **(e) [assistant("orphan")]** — no user message → ``HTTPException(400,
  "no user message in request")``.

Plan reference: ``rebuild/docs/plans/feature-llm-models.md`` §
Tests → Unit tests (``test_seed_history.py``) and ``app/oai_router.py``
docstring on ``_seed_history``.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
)

from app.oai_models import ChatMessage
from app.oai_router import _seed_history


@pytest.mark.parametrize(
    ("messages", "expected_history_len", "expected_history_types", "expected_prompt"),
    [
        pytest.param(
            [ChatMessage(role="user", content="hi")],
            0,
            [],
            "hi",
            id="a-single-user-message",
        ),
        pytest.param(
            [
                ChatMessage(role="system", content="be terse"),
                ChatMessage(role="user", content="hi"),
            ],
            0,
            [],
            "be terse\n\nhi",
            id="b-system-then-user",
        ),
        pytest.param(
            [
                ChatMessage(role="user", content="a"),
                ChatMessage(role="assistant", content="b"),
                ChatMessage(role="user", content="c"),
            ],
            2,
            [ModelRequest, ModelResponse],
            "c",
            id="c-multi-turn-trailing-user-dropped",
        ),
        pytest.param(
            [
                ChatMessage(role="system", content="s1"),
                ChatMessage(role="user", content="a"),
                ChatMessage(role="assistant", content="b"),
                ChatMessage(role="system", content="s2"),
                ChatMessage(role="user", content="c"),
            ],
            2,
            [ModelRequest, ModelResponse],
            "s1\n\ns2\n\nc",
            id="d-multi-system-concatenated-prefix",
        ),
    ],
)
def test_seed_history_translates_openai_messages(
    messages: list[ChatMessage],
    expected_history_len: int,
    expected_history_types: list[type],
    expected_prompt: str,
) -> None:
    history, user_prompt = _seed_history(messages)

    assert len(history) == expected_history_len
    assert [type(h) for h in history] == expected_history_types
    assert user_prompt == expected_prompt


def test_seed_history_raises_when_no_user_message() -> None:
    """Defensive contract: an assistant-only message list is rejected.

    The rebuild always sends a user message; this guard exists so a
    future caller (or a regression in the rebuild) gets a clean 400
    instead of a confusing pydantic-ai stack trace from running an
    agent against an empty prompt.
    """
    with pytest.raises(HTTPException) as excinfo:
        _seed_history([ChatMessage(role="assistant", content="orphan")])

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "no user message in request"
