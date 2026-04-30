"""Pure-function tests for the chat history reducers.

Covers :func:`app.services.chat_stream.build_linear_thread`, the
:class:`app.schemas.history.History` round-trip discipline, and the
:func:`app.services.chat_writer._enforce_history_cap` helper that enforces
``MAX_CHAT_HISTORY_BYTES`` on every chat-history write.

Plan reference: ``rebuild/docs/plans/m2-conversations.md`` § Tests
(lines 1048-1049: "the build_linear_thread, add_branch, derive_title
helpers; covers a multi-branch tree, a circular parentId (pathological —
must terminate), and an empty history") and § History-size enforcement
(lines 850-863).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from app.core.constants import MAX_CHAT_HISTORY_BYTES
from app.schemas.history import History, HistoryMessage
from app.services.chat_stream import _MAX_THREAD_DEPTH, build_linear_thread
from app.services.chat_writer import HistoryTooLargeError, _enforce_history_cap
from pydantic import ValidationError


def _msg(
    msg_id: str,
    *,
    parent_id: str | None,
    role: str = "user",
    content: str = "",
    children: list[str] | None = None,
) -> HistoryMessage:
    """Construct a :class:`HistoryMessage` with the M2-locked defaults.

    Centralised so the tree fixtures below stay readable; tests that
    need a non-default ``done`` / ``cancelled`` flag set them on the
    return value.
    """
    return HistoryMessage(
        id=msg_id,
        parentId=parent_id,
        childrenIds=children or [],
        role=role,
        content=content,
        timestamp=1700000000,
    )


# ---------------------------------------------------------------------------
# build_linear_thread
# ---------------------------------------------------------------------------


def test_build_linear_thread_walks_currentid_to_root() -> None:
    """A multi-branch tree flattens to the chronological chain that runs
    from the root through ``currentId``.

    Tree:
        u1 ── a2
         └─── c3 ── d4   (active branch)
    """
    history = History(
        messages={
            "u1": _msg("u1", parent_id=None, role="user", content="hi", children=["a2", "c3"]),
            "a2": _msg("a2", parent_id="u1", role="assistant", content="hello"),
            "c3": _msg(
                "c3", parent_id="u1", role="assistant", content="hi there!", children=["d4"]
            ),
            "d4": _msg("d4", parent_id="c3", role="user", content="follow up"),
        },
        currentId="d4",
    )

    chain = build_linear_thread(history, parent_id="d4")
    assert [m.id for m in chain] == ["u1", "c3", "d4"]
    # The OFF branch (a2) must not be in the linear thread.
    assert "a2" not in {m.id for m in chain}


def test_build_linear_thread_terminates_on_circular_parent_id() -> None:
    """A pathological cycle ``a -> b -> a`` must terminate, not loop.

    The depth guard is :data:`_MAX_THREAD_DEPTH` (1000); the cycle
    detector is the explicit ``seen`` set inside
    :func:`build_linear_thread`. Either guard alone is sufficient; we
    assert both fire at well below the depth cap so a future refactor
    that drops the cycle set still passes the depth bound.
    """
    history = History(
        messages={
            "a": _msg("a", parent_id="b", role="user", content="A"),
            "b": _msg("b", parent_id="a", role="user", content="B"),
        },
        currentId="a",
    )
    chain = build_linear_thread(history, parent_id="a")
    # Termination, not infinite loop. The cycle guard short-circuits as
    # soon as the second visit to ``a`` happens, so the chain is finite.
    assert len(chain) <= _MAX_THREAD_DEPTH
    # The first two distinct nodes are walked; subsequent revisits are
    # rejected. Order is reversed (root-first) at the end of the walk.
    assert {m.id for m in chain} == {"a", "b"}


def test_build_linear_thread_handles_empty_history() -> None:
    """``parent_id`` pointing at a missing message returns an empty
    chain — not an exception. The streaming pipeline only calls this
    helper after seeding the user message, so this branch is the
    "dangling parentId from a corrupted import" edge case rather than
    a happy-path code path.
    """
    history = History(messages={}, currentId=None)
    assert build_linear_thread(history, parent_id="never-existed") == []


def test_build_linear_thread_handles_missing_parent_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A message with a ``parentId`` that doesn't resolve in the
    history dict terminates the walk gracefully and returns the prefix
    that did resolve (with a warning log so the corruption is visible).
    """
    history = History(
        messages={
            "leaf": _msg("leaf", parent_id="missing-parent", role="assistant", content="hi"),
        },
        currentId="leaf",
    )
    import logging

    target_logger = logging.getLogger("app.services.chat_stream")
    prior_level = target_logger.level
    prior_disabled = target_logger.disabled
    prior_propagate = target_logger.propagate
    target_logger.setLevel(logging.WARNING)
    target_logger.disabled = False
    target_logger.propagate = True
    try:
        with caplog.at_level(logging.WARNING, logger="app.services.chat_stream"):
            chain = build_linear_thread(history, parent_id="leaf")
    finally:
        target_logger.setLevel(prior_level)
        target_logger.disabled = prior_disabled
        target_logger.propagate = prior_propagate
    assert [m.id for m in chain] == ["leaf"]
    messages = [record.getMessage() for record in caplog.records]
    assert any("dangling parentId" in m for m in messages), messages


# ---------------------------------------------------------------------------
# History round-trip + StrictModel discipline
# ---------------------------------------------------------------------------


def test_history_round_trip() -> None:
    """``History.model_validate(History(...).model_dump())`` is identity
    over a fixture covering branching, regenerate, and ``usage`` blocks.

    Mirrors the example in plan § JSON shape of chat.history.
    """
    fixture = History(
        messages={
            "u1": _msg("u1", parent_id=None, role="user", content="hi", children=["a2", "c3"]),
            "a2": HistoryMessage(
                id="a2",
                parentId="u1",
                childrenIds=[],
                role="assistant",
                content="hello",
                timestamp=1700000001,
                model="gpt-4o",
                modelName="GPT-4o",
                done=True,
                usage={"prompt_tokens": 8, "completion_tokens": 1, "total_tokens": 9},
            ),
            "c3": HistoryMessage(
                id="c3",
                parentId="u1",
                childrenIds=[],
                role="assistant",
                content="hi there!",
                timestamp=1700000060,
                model="gpt-4o-mini",
                modelName="GPT-4o mini",
                done=True,
                usage={"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
            ),
        },
        currentId="c3",
    )
    dumped = fixture.model_dump()
    rehydrated = History.model_validate(dumped)
    assert rehydrated == fixture


def test_history_rejects_unknown_fields() -> None:
    """``StrictModel.extra="forbid"`` discipline: a stray field on the
    history JSON (e.g. legacy ``files`` / ``sources`` / ``annotation``)
    must surface as a 422 at the validation boundary, not silently
    round-trip.
    """
    payload: dict[str, Any] = {
        "messages": {},
        "currentId": None,
        "extra_field": "should be rejected",
    }
    with pytest.raises(ValidationError):
        History.model_validate(payload)


def test_history_rejects_unknown_message_fields() -> None:
    """Same StrictModel discipline at the per-message level —
    legacy ``mentions`` / ``statusHistory`` / ``tool_calls`` must not
    sneak in via the inner dict.
    """
    payload = {
        "messages": {
            "u1": {
                "id": "u1",
                "parentId": None,
                "childrenIds": [],
                "role": "user",
                "content": "hi",
                "timestamp": 1700000000,
                "files": ["legacy.png"],  # rejected
            }
        },
        "currentId": "u1",
    }
    with pytest.raises(ValidationError):
        History.model_validate(payload)


# ---------------------------------------------------------------------------
# _enforce_history_cap
# ---------------------------------------------------------------------------


def _serialised_size(history: dict[str, Any]) -> int:
    """Mirror the cap helper's exact serialisation so test fixtures can
    target a precise byte size."""
    return len(json.dumps(history, separators=(",", ":")).encode("utf-8"))


def test_enforce_cap_rejects_oversized_payload() -> None:
    """A payload just over :data:`MAX_CHAT_HISTORY_BYTES` raises
    :class:`HistoryTooLargeError` and the exception carries both the
    actual size and the cap so the M0 handler can render a clean 413.
    """
    blob = "x" * (MAX_CHAT_HISTORY_BYTES + 1)
    history = {
        "messages": {
            "u1": {
                "id": "u1",
                "parentId": None,
                "childrenIds": [],
                "role": "user",
                "content": blob,
                "timestamp": 1700000000,
                "model": None,
                "modelName": None,
                "done": True,
                "error": None,
                "cancelled": False,
                "usage": None,
            }
        },
        "currentId": "u1",
    }
    actual_size = _serialised_size(history)
    assert actual_size > MAX_CHAT_HISTORY_BYTES, "fixture must be over the cap"

    with pytest.raises(HistoryTooLargeError) as exc_info:
        _enforce_history_cap(history)
    assert exc_info.value.size == actual_size
    assert exc_info.value.cap == MAX_CHAT_HISTORY_BYTES
    assert str(actual_size) in str(exc_info.value)


def test_enforce_cap_accepts_payload_under_cap() -> None:
    """Under-cap payloads return ``None`` silently — the helper is a
    raise-or-noop contract, not a returns-bool one."""
    history = History(
        messages={"u1": _msg("u1", parent_id=None, role="user", content="hi")},
        currentId="u1",
    ).model_dump()
    assert _serialised_size(history) < MAX_CHAT_HISTORY_BYTES
    # ``_enforce_history_cap`` raises on overflow and returns ``None``
    # otherwise; its contract is "no exception" rather than a return value.
    _enforce_history_cap(history)
