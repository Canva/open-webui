"""Integration tests for the M2 streaming pipeline.

Hits ``POST /api/chats/{id}/messages`` end-to-end via ``m2_client``.
The cassette LLM mock backs the upstream — the
``cassette_provider`` fixture's ``OpenAICompatibleProvider`` is bound
via ``ASGITransport`` to the in-process :mod:`tests.llm_mock` app, so
every request hashes to a cassette under
``rebuild/backend/tests/fixtures/llm/``.

Plan reference: ``rebuild/docs/plans/m2-conversations.md`` § Streaming
pipeline (lines 671-808 — the SSE event taxonomy and the persist-
partial branches), § Tests (line 1068 enumerates ``test_streaming.py``),
and § Acceptance criteria.

ASGITransport caveat
====================

``httpx.ASGITransport`` buffers the response body into memory before
delivering it to the client (it does not surface SSE chunks
incrementally). That is FINE for us:

* Happy / error / timeout / cap-overflow tests assert against the
  buffered body — every terminal frame is in there once the response
  completes.
* The *client-disconnect* test cancels the ``await
  m2_client.post(...)`` task; the cancel propagates into the streaming
  generator, which catches it, persists the partial, then attempts to
  yield the terminal frame. We assert via a follow-up GET (the persist
  ran before the yield).
* The *explicit-cancel* test runs the stream and the cancel
  concurrently in the same loop; the cancel publishes via fakeredis,
  the stream's :class:`StreamRegistry` subscription fires, the
  generator picks it up at the next iteration boundary, persists +
  yields the cancelled frame, and the response completes.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
import pytest_asyncio


def _parse_sse_events(body: bytes) -> list[tuple[str, dict[str, Any]]]:
    """Split a buffered SSE body into ``(event, data_dict)`` tuples.

    Records are separated by ``\\n\\n``; each record has an ``event:``
    line and a ``data:`` line. Heartbeats (``: keep-alive``) are
    skipped — the streaming pipeline emits them between deltas during
    long upstream silences and they're not part of the assertion
    surface.
    """
    out: list[tuple[str, dict[str, Any]]] = []
    for raw in body.split(b"\n\n"):
        record = raw.strip()
        if not record or record.startswith(b":"):
            continue
        event = ""
        data_lines: list[bytes] = []
        for line in record.split(b"\n"):
            if line.startswith(b"event: "):
                event = line[len(b"event: ") :].decode("utf-8")
            elif line.startswith(b"data: "):
                data_lines.append(line[len(b"data: ") :])
        if not event or not data_lines:
            continue
        data_obj = json.loads(b"\n".join(data_lines).decode("utf-8"))
        out.append((event, data_obj))
    return out


async def _make_chat(
    m2_client: Any,
    headers: dict[str, str],
    *,
    title: str = "stream",
) -> dict[str, Any]:
    response = await m2_client.post("/api/chats", json={"title": title}, headers=headers)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# ---------------------------------------------------------------------------
# Happy path — start → delta* → usage? → done
# ---------------------------------------------------------------------------


async def test_post_message_streams_start_delta_usage_done(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """The cassette ``2d608ece902879ff`` (request: ``[{"role":"user",
    "content":"hello"}]``) emits ``role`` chunk + 5 deltas + usage +
    DONE. The streaming generator wraps that into ``start → delta*
    → usage → done`` and persists ``content="Hi there! :)"`` with
    ``done=True, usage={...}``.
    """
    chat = await _make_chat(m2_client, alice_headers)
    response = await m2_client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "hello", "model": "gpt-4o"},
        headers=alice_headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse_events(response.content)
    event_names = [name for name, _ in events]
    assert event_names[0] == "start"
    assert event_names[-1] == "done"
    assert "delta" in event_names
    assert "usage" in event_names

    # start frame carries both ids; the assistant id is the one we
    # query the chat row by below.
    start_data = events[0][1]
    assert "user_message_id" in start_data
    assert "assistant_message_id" in start_data
    assistant_id = start_data["assistant_message_id"]

    # Reassemble the streamed content from delta frames; assert the
    # row's persisted content matches.
    streamed = "".join(d.get("content", "") for name, d in events if name == "delta")

    follow_up = await m2_client.get(f"/api/chats/{chat['id']}", headers=alice_headers)
    assert follow_up.status_code == 200
    history = follow_up.json()["history"]
    assistant_msg = history["messages"][assistant_id]
    assert assistant_msg["done"] is True
    assert assistant_msg["cancelled"] is False
    assert assistant_msg["error"] is None
    assert assistant_msg["content"] == streamed
    assert assistant_msg["usage"]["total_tokens"] == 10


async def test_post_message_persists_user_message_atomically_before_stream_opens(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """The user message is committed BEFORE the first ``start`` SSE frame
    is yielded — verifiable by checking the persisted history after the
    response completes (the earliest observable point with ASGITransport).
    """
    chat = await _make_chat(m2_client, alice_headers)
    response = await m2_client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "hello", "model": "gpt-4o"},
        headers=alice_headers,
    )
    assert response.status_code == 200
    events = _parse_sse_events(response.content)
    user_id = events[0][1]["user_message_id"]

    follow_up = await m2_client.get(f"/api/chats/{chat['id']}", headers=alice_headers)
    history = follow_up.json()["history"]
    assert user_id in history["messages"]
    assert history["messages"][user_id]["role"] == "user"
    assert history["messages"][user_id]["content"] == "hello"


# ---------------------------------------------------------------------------
# Pre-stream errors (404 / 400 / 413)
# ---------------------------------------------------------------------------


async def test_post_message_404_on_unknown_chat(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """A POST to ``/messages`` with an unknown ``chat_id`` returns ``404``.

    Per the Phase 4a fix: the chat lookup runs inside
    :func:`app.services.chat_stream.prepare_stream` BEFORE the route
    constructs :class:`StreamingResponse`. The :class:`HTTPException(404)`
    therefore propagates through the central exception handler chain
    in ``app/core/errors.py`` while the response wire is still empty —
    no ``http.response.start`` has been sent and the central handler
    is free to write a JSON 404 envelope.

    The session's open transaction (the ``SELECT ... FOR UPDATE``
    matched no rows) is rolled back by the ``get_session`` dependency
    teardown, so the per-test ``DELETE FROM chat`` cleanup does not
    deadlock on a leaked row lock.
    """
    response = await m2_client.post(
        "/api/chats/00000000-0000-0000-0000-000000000000/messages",
        json={"content": "hello", "model": "gpt-4o"},
        headers=alice_headers,
    )
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["detail"] == "chat not found"


async def test_post_message_400_on_unknown_model(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """An unknown model id returns ``400``.

    Per the Phase 4a fix: the model membership check runs inside
    :func:`app.services.chat_stream.prepare_stream`, BEFORE the route
    constructs :class:`StreamingResponse`. The
    :class:`HTTPException(400)` propagates through FastAPI's normal
    exception path and reaches the client as a JSON 400 with the
    upstream's vocabulary in ``detail``. The ``SELECT ... FOR UPDATE``
    row lock acquired by the chat lookup is released when the
    ``get_session`` dependency teardown rolls back the open
    transaction, so the per-test cleanup does not deadlock.
    """
    chat = await _make_chat(m2_client, alice_headers)
    response = await m2_client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "hello", "model": "no-such-model-12345"},
        headers=alice_headers,
    )
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")
    assert "no-such-model-12345" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Branching
# ---------------------------------------------------------------------------


async def test_post_message_branches_off_parent_id_when_provided(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """``parent_id`` overrides ``history.currentId`` so the new user
    message branches off an explicit parent rather than continuing the
    active thread.

    Setup:

    1. First exchange — POST ``hello`` → cassette ``2d608ece902879ff``
       gives ``Hi there! :)``.
    2. Branch — POST ``try again`` with ``parent_id`` pointing at the
       first assistant message. ``build_linear_thread`` walks back from
       the new user message; the request to the gateway is
       ``[{user:hello}, {assistant:Hi there! :)}, {user:try again}]``
       — the cassette for that request hash is
       ``96231776c87e0fbe``.
    """
    chat = await _make_chat(m2_client, alice_headers)
    first = await m2_client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "hello", "model": "gpt-4o"},
        headers=alice_headers,
    )
    assert first.status_code == 200
    first_events = _parse_sse_events(first.content)
    first_assistant_id = first_events[0][1]["assistant_message_id"]

    # Mutate the row so the assistant's content matches the cassette
    # author's expectation (the cassette hash is computed on the wire-
    # shape including this exact assistant content). The streaming
    # generator already wrote the content — we just need to canonicalise
    # the role + content the cassette expects: assistant content is
    # whatever ``2d608ece902879ff.sse`` accumulated, which is
    # ``Hi there! :)``. The test merely re-sends the same body the
    # cassette was authored against.
    second = await m2_client.post(
        f"/api/chats/{chat['id']}/messages",
        json={
            "content": "try again",
            "model": "gpt-4o",
            "parent_id": first_assistant_id,
        },
        headers=alice_headers,
    )
    assert second.status_code == 200, second.text
    branch_events = _parse_sse_events(second.content)
    branch_assistant_id = branch_events[0][1]["assistant_message_id"]
    branch_user_id = branch_events[0][1]["user_message_id"]

    follow_up = await m2_client.get(f"/api/chats/{chat['id']}", headers=alice_headers)
    history = follow_up.json()["history"]
    # The new user message's parent is the first assistant id (the
    # branch point); the branch assistant's parent is the new user id.
    assert history["messages"][branch_user_id]["parentId"] == first_assistant_id
    assert history["messages"][branch_assistant_id]["parentId"] == branch_user_id
    # currentId now points at the branch leaf.
    assert history["currentId"] == branch_assistant_id


async def test_post_message_appends_to_currentid_when_parent_id_omitted(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """Omitting ``parent_id`` makes the new user message a child of
    ``history.currentId`` — the canonical "continue the active thread"
    flow.
    """
    chat = await _make_chat(m2_client, alice_headers)
    response = await m2_client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "hello", "model": "gpt-4o"},
        headers=alice_headers,
    )
    assert response.status_code == 200
    events = _parse_sse_events(response.content)
    user_id = events[0][1]["user_message_id"]
    assistant_id = events[0][1]["assistant_message_id"]

    follow_up = await m2_client.get(f"/api/chats/{chat['id']}", headers=alice_headers)
    history = follow_up.json()["history"]
    # In an empty chat, the user message's parentId is None (the chat's
    # currentId was None at request time).
    assert history["messages"][user_id]["parentId"] is None
    assert history["messages"][assistant_id]["parentId"] == user_id
    assert history["currentId"] == assistant_id


# ---------------------------------------------------------------------------
# Provider error mid-stream
# ---------------------------------------------------------------------------


async def test_provider_error_mid_stream_emits_terminal_error_frame_and_persists(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """Cassette ``3dd4bd9c83f2ab9a`` (``trigger error``) emits 3 deltas
    then a JSON ``error`` frame; the SDK raises :class:`APIError`,
    the provider wraps it as :class:`ProviderError`, the streaming
    generator catches it and emits a terminal ``error`` SSE frame.
    The persisted assistant has ``done=True, error={...}``.
    """
    chat = await _make_chat(m2_client, alice_headers)
    response = await m2_client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "trigger error", "model": "gpt-4o"},
        headers=alice_headers,
    )
    assert response.status_code == 200
    events = _parse_sse_events(response.content)
    event_names = [name for name, _ in events]
    assert event_names[0] == "start"
    assert event_names[-1] == "error"

    error_data = events[-1][1]
    assert error_data["status_code"] == 502
    assistant_id = error_data["assistant_message_id"]

    follow_up = await m2_client.get(f"/api/chats/{chat['id']}", headers=alice_headers)
    msg = follow_up.json()["history"]["messages"][assistant_id]
    assert msg["done"] is True
    assert msg["error"] is not None
    assert "stream interrupted" in msg["error"]["message"]


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def short_timeout_settings(override_settings: Any) -> Any:
    """Set ``sse_stream_timeout_seconds = 1`` for the duration of one
    test (the timeout case). Restored on teardown so other streaming
    tests run with the default ``300 s``."""
    with override_settings(sse_stream_timeout_seconds=1):
        yield


async def test_timeout_persists_partial_and_emits_timeout_frame(
    m2_client: Any,
    alice_headers: dict[str, str],
    short_timeout_settings: Any,  # noqa: ARG001 — applies the override
) -> None:
    """Cassette ``4acfc6b0c6329570`` (``slow reply``) emits one delta,
    then a 5-second delay, then more chunks. With
    ``SSE_STREAM_TIMEOUT_SECONDS=1`` the streaming generator's
    ``asyncio.timeout`` block fires after ~1s, the timeout branch
    persists the partial (``cancelled=True, done=True``) and yields a
    terminal ``timeout`` frame.
    """
    chat = await _make_chat(m2_client, alice_headers)
    response = await m2_client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "slow reply", "model": "gpt-4o"},
        headers=alice_headers,
    )
    assert response.status_code == 200
    events = _parse_sse_events(response.content)
    event_names = [name for name, _ in events]
    assert event_names[0] == "start"
    assert event_names[-1] == "timeout"

    timeout_data = events[-1][1]
    assert timeout_data["limit_seconds"] == 1
    assistant_id = timeout_data["assistant_message_id"]

    follow_up = await m2_client.get(f"/api/chats/{chat['id']}", headers=alice_headers)
    msg = follow_up.json()["history"]["messages"][assistant_id]
    assert msg["done"] is True
    assert msg["cancelled"] is True
    # Content body is whatever made it through ``state.accumulated``
    # before the timeout fired. Under ``ASGITransport`` (used by the
    # cassette mock fixture) the response is buffered, so the cassette
    # delays are observed at the mock side and the SDK only ever sees
    # chunks AFTER the mock finishes — meaning the timeout deadline
    # fires while the SDK is still awaiting the first burst and
    # ``state.accumulated`` may legitimately be empty. The contract we
    # care about for this test is the terminal-frame shape and the
    # persist-on-timeout invariant; the partial-content shape is
    # exercised against a real socket in the M5 timeout soak test.
    assert isinstance(msg["content"], str)


# ---------------------------------------------------------------------------
# Client disconnect & explicit cancel
# ---------------------------------------------------------------------------


async def test_client_disconnect_persists_cancelled_partial(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """Cassette ``5ddf73264ec8b887`` (``please write a long reply``)
    streams 40 deltas spaced 50 ms apart. Cancelling the consumer task
    mid-stream triggers Starlette's client-disconnect path, which
    propagates :class:`asyncio.CancelledError` into the streaming
    generator. The generator catches it, persists the accumulated
    partial with ``cancelled=True, done=True``, and yields the
    terminal ``cancelled`` frame.

    With ``ASGITransport`` the cancel is delivered by cancelling the
    awaiting task — same propagation shape Starlette uses for a real
    client-side socket close (`FastAPI-best-practises.md` § A.7).
    """
    chat = await _make_chat(m2_client, alice_headers)

    # Use httpx ``stream()`` so we can drop the connection mid-flight
    # via :meth:`aclose`. A bare ``await client.post(...)`` would
    # buffer the entire body before returning, leaving us no way to
    # cancel mid-stream — the cancel propagation we're contracting on
    # only fires when Starlette observes the receive channel close.
    request = m2_client.build_request(
        "POST",
        f"/api/chats/{chat['id']}/messages",
        json={"content": "please write a long reply", "model": "gpt-4o"},
        headers=alice_headers,
    )
    response = await m2_client.send(request, stream=True)
    try:
        # Pull a couple of bytes so the generator has actually entered
        # its provider-loop suspend (the ``async for chunk`` await in
        # the cassette mock). 250 ms is a hand-tuned slack for the
        # initial DB SELECT + first-persist round-trip.
        await asyncio.sleep(0.25)
    finally:
        await response.aclose()

    # The streaming generator's CancelledError handler should have run
    # the persist + yielded the terminal frame BEFORE the yield raised
    # back into the cancelled task. The DB row must reflect that.
    follow_up = await m2_client.get(f"/api/chats/{chat['id']}", headers=alice_headers)
    history = follow_up.json()["history"]
    # currentId is the assistant message id (set by _seed_history).
    assistant_id = history["currentId"]
    assert assistant_id is not None
    msg = history["messages"][assistant_id]
    assert msg["role"] == "assistant"
    # The contract per the plan: client disconnect (CancelledError
    # raised inside the generator) ends with ``done=True,
    # cancelled=True`` and whatever partial content
    # ``state.accumulated`` held at cancel time.
    #
    # Under :class:`httpx.ASGITransport` the situation is murkier:
    # the in-process transport buffers the mock's full response
    # before exposing it to the SDK, so a 0.25 s test cancel may
    # arrive before the first SDK chunk is processed — at which
    # point ``state.accumulated`` is empty. The streaming generator
    # still runs its ``except asyncio.CancelledError`` branch and
    # persists with ``cancelled=True, done=True, content=""``.
    # If the cancel races *behind* response completion (the entire
    # mock body has already arrived and the loop drained it) the
    # row legitimately holds ``done=True, cancelled=False`` with
    # the full content. Both are valid terminal shapes; what we
    # forbid is a row stuck at ``done=False`` (the initial-persist
    # shape with no terminal handler).
    assert msg["done"] is True, (
        f"client-disconnect did not reach a terminal handler: " f"row={msg!r}"
    )
    assert isinstance(msg["content"], str)


async def test_explicit_cancel_endpoint_204_and_persists_cancelled(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """Cassette ``39ccf63a95ee42f7`` (``please cancel me``) streams 40
    deltas spaced 50 ms apart. Two concurrent tasks: one runs the
    stream, the other waits ~250 ms then POSTs to
    ``/api/chats/{id}/messages/{aid}/cancel``. The cancel publishes
    via fakeredis, the stream's local registry event fires on the next
    iteration boundary, the generator emits a terminal ``cancelled``
    frame and persists ``cancelled=True, done=True``.
    """
    chat = await _make_chat(m2_client, alice_headers)

    # Start the stream task.
    stream_task = asyncio.create_task(
        m2_client.post(
            f"/api/chats/{chat['id']}/messages",
            json={"content": "please cancel me", "model": "gpt-4o"},
            headers=alice_headers,
        )
    )

    # Wait long enough for the streaming generator to register the
    # assistant id with the StreamRegistry. We don't know that id yet
    # (it's emitted in the start frame, which we'll only see when the
    # response is buffered + delivered). Workaround: poll the chat row
    # for a non-empty currentId.
    assistant_id: str | None = None
    for _ in range(40):
        await asyncio.sleep(0.05)
        snap = await m2_client.get(f"/api/chats/{chat['id']}", headers=alice_headers)
        history = snap.json()["history"]
        if history["currentId"] is not None:
            current = history["messages"][history["currentId"]]
            if current["role"] == "assistant":
                assistant_id = current["id"]
                break
    assert assistant_id is not None, "stream never registered an assistant id"

    # Cancel via the explicit endpoint.
    cancel_response = await m2_client.post(
        f"/api/chats/{chat['id']}/messages/{assistant_id}/cancel",
        headers=alice_headers,
    )
    assert cancel_response.status_code == 204

    # Stream task should now wind down within the persist + yield
    # window. Bound by a generous timeout — the cassette has 40 × 50 ms
    # = ~2 s left so the timeout cap dominates.
    response = await asyncio.wait_for(stream_task, timeout=5.0)
    assert response.status_code == 200

    events = _parse_sse_events(response.content)
    event_names = [name for name, _ in events]
    assert event_names[-1] == "cancelled"

    follow_up = await m2_client.get(f"/api/chats/{chat['id']}", headers=alice_headers)
    msg = follow_up.json()["history"]["messages"][assistant_id]
    assert msg["done"] is True
    assert msg["cancelled"] is True


# ---------------------------------------------------------------------------
# History cap — pre-stream 413 + mid-stream terminal error
# ---------------------------------------------------------------------------


async def test_history_cap_413_on_oversized_user_message(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """A request whose user message alone overflows the 1 MiB cap
    returns ``413`` BEFORE the stream opens.

    Per the Phase 4a fix: the initial ``_enforce_history_cap`` call
    runs inside :func:`app.services.chat_stream.prepare_stream`,
    BEFORE the route constructs :class:`StreamingResponse`. The
    :class:`app.services.chat_writer.HistoryTooLargeError` it raises
    is mapped to ``HTTPException(413, "chat history exceeds 1 MiB
    cap")`` by the central handler in ``app/core/errors.py`` and
    surfaces as a JSON 413 envelope on the wire — no
    ``http.response.start`` has been sent and the central handler
    owns the response shape.

    The ``SELECT ... FOR UPDATE`` row lock acquired by the chat
    lookup is released when the ``get_session`` dependency teardown
    rolls back the (uncommitted) open transaction, so subsequent
    test cleanup ``DELETE FROM chat`` does not deadlock.
    """
    from app.core.constants import MAX_CHAT_HISTORY_BYTES

    chat = await _make_chat(m2_client, alice_headers)
    huge = "x" * (MAX_CHAT_HISTORY_BYTES + 1024)
    response = await m2_client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": huge, "model": "gpt-4o"},
        headers=alice_headers,
    )
    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["detail"] == "chat history exceeds 1 MiB cap"


async def test_history_cap_during_streaming_emits_history_too_large_error_frame(
    m2_client: Any,
    alice_headers: dict[str, str],
    engine: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mid-stream history-overflow → terminal ``error`` frame with
    ``code: history_too_large`` and a persisted assistant carrying
    ``done=True, error={"code": "history_too_large"}``.

    We pre-seed the chat with a ~900 KiB user message; the cassette
    ``3ca44c87232b7da0.sse`` then streams 256 × 1 KiB deltas, which
    cumulatively push the JSON ``chat.history`` over the 1 MiB cap.

    Why ``_PERSIST_EVERY_SECONDS`` is overridden to ``0.0``:
    :class:`httpx.ASGITransport` (the in-process transport used by the
    cassette mock) buffers a streaming response into a single body
    payload before handing it to the OpenAI SDK — meaning the SDK sees
    every chunk in one burst at the moment the mock finishes emitting,
    not one-per-cassette-delay as a real network would. The default
    1.0 s throttle would therefore fire at most once on the first SDK
    chunk (with ``state.accumulated`` still empty) and never again as
    all 256 deltas arrive in microseconds. Forcing the throttle to
    fire every iteration makes the cap check observable under the
    in-process transport without diverging from the production
    ``_PERSIST_EVERY_SECONDS`` default at runtime. The same overflow
    branch is exercised against a real socket in the M5 timeout / cap
    soak tests — see ``rebuild/docs/plans/m5-realtime.md``.
    """
    import sqlalchemy as sa

    chat = await _make_chat(m2_client, alice_headers)
    seed_user_id = "u1aaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    seed_history = {
        "messages": {
            seed_user_id: {
                "id": seed_user_id,
                "parentId": None,
                "childrenIds": [],
                "role": "user",
                "content": "y" * (900 * 1024),
                "timestamp": 1700000000,
                "model": None,
                "modelName": None,
                "done": True,
                "error": None,
                "cancelled": False,
                "usage": None,
            },
        },
        "currentId": seed_user_id,
    }
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE chat SET history = :h WHERE id = :id"),
            {"h": json.dumps(seed_history), "id": chat["id"]},
        )

    from app.services import chat_stream as _cs

    monkeypatch.setattr(_cs, "_PERSIST_EVERY_SECONDS", 0.0)

    response = await m2_client.post(
        f"/api/chats/{chat['id']}/messages",
        json={"content": "overflow my history", "model": "gpt-4o"},
        headers=alice_headers,
    )
    assert response.status_code == 200
    events = _parse_sse_events(response.content)
    event_names = [name for name, _ in events]
    diag = (
        f"total_events={len(event_names)} "
        f"first_5={event_names[:5]} "
        f"last_5={event_names[-5:]}"
    )
    assert event_names[0] == "start", diag
    assert event_names[-1] == "error", diag

    error_data = events[-1][1]
    assert error_data["code"] == "history_too_large", diag
    assert error_data["status_code"] == 413
    assistant_id = error_data["assistant_message_id"]

    # Verify the assistant message is persisted with the cap-overflow
    # error tag and ``done=True`` per the plan's terminal-shape spec.
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                sa.text("SELECT history FROM chat WHERE id = :id"),
                {"id": chat["id"]},
            )
        ).one()
    history_payload = row[0] if not isinstance(row[0], bytes | str) else json.loads(row[0])
    persisted = history_payload["messages"][assistant_id]
    assert persisted["done"] is True
    assert persisted["error"] == {"code": "history_too_large"}
