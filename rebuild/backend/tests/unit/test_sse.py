"""Unit tests for :func:`app.services.chat_stream.sse`.

The SSE framing helper is a 3-liner but it's the wire format every
M2 streaming consumer (frontend ``parseSSE``, the cassette LLM mock,
the M5 automation executor's chat-target writer) expects. Any drift
in encoding / escaping / framing here surfaces as silent JSON parse
errors at the consumer.

Plan reference: ``rebuild/docs/plans/m2-conversations.md`` § Tests
("``tests/unit/test_sse.py`` — ``sse(event, data)`` formatting and JSON
edge cases (newlines, unicode)", line 1051) and § Streaming pipeline
(line 818 — the locked one-line implementation).
"""

from __future__ import annotations

import json

from app.services.chat_stream import sse


def test_sse_basic_shape() -> None:
    """Locked exact shape from plan line 818:
    ``f"event: {event}\\ndata: {json.dumps(data)}\\n\\n".encode()``."""
    frame = sse("delta", {"content": "hi"})
    assert frame == b'event: delta\ndata: {"content": "hi"}\n\n'


def test_sse_handles_unicode_content() -> None:
    """Emoji + non-ASCII content survives JSON encoding without ``\\u``
    escapes — Python's ``json.dumps`` defaults to ``ensure_ascii=True``,
    so the helper must NOT pass ``ensure_ascii=False`` (we want the
    safer ASCII-escaped form on the wire because some proxies strip
    high bytes).

    Asserting on the round-trip rather than the raw bytes keeps the
    test stable if Python's escape encoding ever changes its surface
    while preserving the same parsed value.
    """
    payload = {"content": "héllo 🎉 — bye"}
    frame = sse("delta", payload)
    body = frame.removeprefix(b"event: delta\ndata: ").removesuffix(b"\n\n")
    assert json.loads(body) == payload


def test_sse_handles_newlines_in_content() -> None:
    """Content containing literal ``\\n`` must be JSON-encoded as
    ``\\\\n`` (the JSON escape for newline) — NOT a literal newline,
    which would split the SSE record at the wrong boundary and corrupt
    the consumer's parse state.

    The frame must end with exactly one record terminator (``\\n\\n``)
    and contain no other unescaped newlines past the ``data:`` prefix.
    """
    frame = sse("delta", {"content": "line1\nline2"})
    body = frame.removeprefix(b"event: delta\ndata: ").removesuffix(b"\n\n")
    assert b"\n" not in body, "JSON body must not carry an unescaped newline"
    assert b"\\n" in body, "JSON body must encode the newline as \\n"
    assert json.loads(body) == {"content": "line1\nline2"}


def test_sse_event_name_appears_first() -> None:
    """The event name appears on the first line of the frame; the
    consumer's parser keys on this. Defensive — protects against a
    refactor that accidentally swaps the order to ``data: ... \\nevent:``.
    """
    frame = sse("done", {"assistant_message_id": "abc", "finish_reason": "stop"})
    assert frame.startswith(b"event: done\n")
    assert frame.endswith(b"\n\n")


def test_sse_terminates_with_double_newline() -> None:
    """SSE record terminator is ``\\n\\n``; consumers split on it.
    Asserted explicitly so the locked framing is impossible to drift."""
    frame = sse("usage", {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3})
    assert frame.endswith(b"\n\n")
    assert frame.count(b"\n\n") == 1
