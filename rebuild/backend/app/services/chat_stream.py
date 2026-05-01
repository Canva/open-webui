"""SSE streaming pipeline for ``POST /api/chats/{id}/messages``.

This is the only multi-step service in M2 — it owns the message-tree
mutation, the per-second persistence checkpoint, the cancellation
dance, and the SSE event taxonomy.

Reference (binding): ``rebuild/docs/plans/m2-conversations.md``
§ Streaming pipeline (lines 671-808 — the full pseudo-code), § SSE
streaming (the event-shape table on lines 660-668), § History-size
enforcement (lines 850-863), and § Acceptance criteria (the
``start → delta* → usage? → done`` happy path plus the four terminal
branches).

The pipeline is split across two functions so pre-yield validation
errors surface as proper HTTP responses instead of being lost behind
Starlette's already-sent ``http.response.start`` (the Phase 4a bug):

* :func:`prepare_stream` — ``async def``, **not** a generator. Does
  the chat lookup (404), agent membership check (400), user-message
  seeding, and initial history-cap enforcement (413). Commits the
  first persist, releasing the ``SELECT FOR UPDATE`` row lock BEFORE
  the response stream is opened. Errors raised here propagate cleanly
  through FastAPI's exception-handler chain (``app/core/errors.py``)
  because no bytes have hit the wire yet.
* :func:`stream_assistant_response` — the post-validation async
  generator. Owns the SSE event taxonomy, the persist throttle, the
  cancellation/timeout/cap-overflow/provider-error branches, and the
  terminal ``done`` frame.

The router (``app/routers/chats.py::post_message``) wires them up::

    prepared = await prepare_stream(...)             # 404 / 400 / 413 here
    return StreamingResponse(                         # response opens here
        stream_assistant_response(prepared, ...),
        media_type="text/event-stream",
    )

The generator structure is::

    yield sse("start", {...})
    try:
        try:
            async with asyncio.timeout(SSE_STREAM_TIMEOUT_SECONDS):
                while True:                              # provider loop
                    if cancel_event.is_set(): raise CancelledError
                    delta = wait_for(next, HEARTBEAT_S)  # heartbeat tick
                    yield "delta" / "usage"
                    persist_throttled(every=PERSIST_EVERY_S)
        except asyncio.TimeoutError:                       # SSE_STREAM_TIMEOUT
            persist + yield sse("timeout", ...); return
    except asyncio.CancelledError:                         # client / /cancel
        persist + yield sse("cancelled", ...); return
    except HistoryTooLargeError:                           # mid-stream cap hit
        truncate + persist + yield sse("error", code="history_too_large")
        return
    except ProviderError:                                  # upstream failure
        persist + yield sse("error", ...); return
    finally:
        cancel pending fetch task
        await registry.unregister(...)
    # normal completion
    persist + yield sse("done", ...)

Why this exact shape:

* The ``asyncio.timeout`` block sits **inside** the generator (not on
  the route handler) so the timeout branch owns the persist-partial
  cleanup. The M6 per-route HTTP timeout is a backstop set to the same
  ``SSE_STREAM_TIMEOUT_SECONDS`` value (locked in
  ``rebuild/docs/plans/m2-conversations.md`` § Settings additions) —
  diverging the two would let the route layer kill the request before
  the persist branch runs.
* The heartbeat is implemented with ``asyncio.wait_for`` +
  ``asyncio.shield`` around a per-iteration ``__anext__()`` task. The
  shield protects the upstream fetch from the heartbeat-timeout cancel
  so we don't drop a chunk mid-read. Per
  ``rebuild/docs/best-practises/FastAPI-best-practises.md`` § A.7 the
  heartbeat keeps proxies (LB, nginx) from idling-out the SSE
  connection at 60 s.
* User cancel via ``/cancel`` and client disconnect both surface as
  :class:`asyncio.CancelledError` — the persist + SSE shape is
  identical for both, so they share one ``except`` branch (per the
  plan's pseudo-code lines 773-781).
* ``_enforce_history_cap`` is called before EVERY ``chat.history``
  write (the first persist inside :func:`prepare_stream`, the
  per-second checkpoint, and every terminal-branch write) so the cap
  is enforced uniformly across every code path — no "fast path that
  skips the check".
* The generator never calls ``chat_writer.append_assistant_message``;
  that helper is reserved for non-streaming chat-target writes (M5).
  The streaming pipeline owns its own persistence path because the
  assistant message id has to be known **before** the stream opens (so
  we can register the cancel event), which the writer's "create-on-
  commit" shape can't accommodate.

Per ``rebuild/docs/best-practises/FastAPI-best-practises.md`` § A.8
the only background task in this module is the per-iteration
``pending_next`` task; it is held by a strong local reference and
cancelled in ``finally`` — never spawned and dropped on the floor.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import STREAM_HEARTBEAT_SECONDS
from app.core.ids import new_id
from app.core.time import now_ms
from app.models.chat import Chat
from app.models.user import User
from app.providers.openai import OpenAICompatibleProvider, ProviderError, StreamDelta
from app.schemas.chat import MessageSend
from app.schemas.history import History, HistoryMessage
from app.services.agents_cache import AgentsCache
from app.services.chat_writer import HistoryTooLargeError, _enforce_history_cap
from app.services.stream_registry import StreamRegistry

log = logging.getLogger(__name__)


# Persistence-checkpoint cadence inside the streaming loop. The plan
# locks 1.0 s (``rebuild/docs/plans/m2-conversations.md`` § Streaming
# pipeline, line 735) — fast enough that a server crash loses ≤ 1 s of
# tokens, slow enough that a 50-token-per-second stream issues only
# one UPDATE per second instead of one per token.
_PERSIST_EVERY_SECONDS: float = 1.0

# Defence-in-depth ceiling on the parent-id walk inside
# :func:`build_linear_thread`. A pathological history with a circular
# ``parentId`` chain (legacy bug; rebuild's strict schema makes it hard
# to construct, but not impossible if a future migration imports
# legacy data) would otherwise loop forever. 1000 hops is far beyond
# the 1 MiB history cap (each message is ~200 bytes minimum so the cap
# already bounds the legitimate depth at ~5000 — but the cycle guard
# fires before runaway memory, not after).
_MAX_THREAD_DEPTH: int = 1000


# Sentinel returned by :func:`_next_or_end` when the underlying provider
# iterator is exhausted. A class instance (not ``object()``) so mypy
# can narrow with :func:`isinstance` instead of an identity check.
class _EndOfStream:
    pass


_END_OF_STREAM = _EndOfStream()


def sse(event: str, data: dict[str, Any]) -> bytes:
    """Format an SSE frame.

    Per the spec on ``rebuild/docs/plans/m2-conversations.md`` line 818:
    ``f"event: {event}\\ndata: {json.dumps(data)}\\n\\n".encode()``.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


def build_linear_thread(history: History, *, parent_id: str) -> list[HistoryMessage]:
    """Walk the ``parentId`` chain from ``parent_id`` to the root and
    return the messages in chronological order.

    The chat-history JSON shape is a tree (each message has a ``parentId``
    and zero-or-more ``childrenIds``); the OpenAI Chat Completions API
    expects a flat ``[{"role", "content"}, ...]`` list. The reducer that
    flattens is "walk parentId from the leaf to the root, then reverse".

    Defensive guards:

    * Terminate on ``parentId is None`` (root reached).
    * Terminate on a missing id (corrupted history — legacy import
      could leave a dangling ``parentId``; we don't crash the stream).
    * Terminate after :data:`_MAX_THREAD_DEPTH` hops (cycle guard).
    """
    chain: list[HistoryMessage] = []
    current_id: str | None = parent_id
    seen: set[str] = set()
    for _ in range(_MAX_THREAD_DEPTH):
        if current_id is None:
            break
        if current_id in seen:
            log.warning("build_linear_thread: cycle detected at message %s; truncating", current_id)
            break
        msg = history.messages.get(current_id)
        if msg is None:
            log.warning("build_linear_thread: dangling parentId %s; truncating", current_id)
            break
        chain.append(msg)
        seen.add(current_id)
        current_id = msg.parentId
    chain.reverse()
    return chain


async def _next_or_end(
    aiter: AsyncIterator[StreamDelta],
) -> StreamDelta | _EndOfStream:
    """Wrap ``aiter.__anext__()`` so end-of-stream is a sentinel instead
    of a :class:`StopAsyncIteration` that ``asyncio.wait_for`` mishandles.
    """
    try:
        return await aiter.__anext__()
    except StopAsyncIteration:
        return _END_OF_STREAM


@dataclass(slots=True)
class _StreamState:
    """Mutable state carried across the streaming loop.

    Exists purely so :func:`_run_provider_loop` can mutate the same
    fields :func:`stream_assistant_response`'s outer try/except
    branches read on teardown — Python closures over locals don't
    survive a generator handoff cleanly. A dataclass is the cheapest
    pattern that keeps both functions on the same set of names.
    """

    accumulated: list[str] = field(default_factory=list)
    finish_reason: str | None = None
    pending_next: asyncio.Task[StreamDelta | _EndOfStream] | None = None


@dataclass(slots=True)
class PreparedStream:
    """The pre-validated state handed from :func:`prepare_stream` to
    :func:`stream_assistant_response`.

    Holds the loaded chat row (with its now-released ``SELECT FOR
    UPDATE`` lock), the validated :class:`History` tree (already
    mutated to include the user message and the placeholder assistant
    message), and the original :class:`MessageSend` body the generator
    needs for the provider call (agent id + params).
    """

    chat: Chat
    history: History
    user_msg: HistoryMessage
    assistant_msg: HistoryMessage
    body: MessageSend


async def prepare_stream(
    *,
    chat_id: str,
    user: User,
    body: MessageSend,
    db: AsyncSession,
    agents_cache: AgentsCache,
) -> PreparedStream:
    """Pre-yield validation + first persist for the streaming endpoint.

    Runs the synchronous-from-the-route's-perspective pre-stream work:
    chat lookup (404 if missing), agent membership check (400 if
    unknown), user-message + placeholder-assistant seeding, history-cap
    enforcement (413 if oversized), and the initial commit that
    releases the ``SELECT FOR UPDATE`` row lock BEFORE
    :class:`StreamingResponse` opens the response stream.

    Errors raised here surface as proper HTTP responses through the
    centralised exception handlers in ``app/core/errors.py``:

    * :class:`HTTPException(404)` — chat not found / not owned.
    * :class:`HTTPException(400)` — unknown agent id.
    * :class:`HistoryTooLargeError` → 413 — initial user message
      pushes ``chat.history`` over :data:`MAX_CHAT_HISTORY_BYTES`.

    Because nothing has been written to the response wire yet, all
    three reach the client as JSON error responses with the right
    status code (the Phase 4a bug was that these used to raise from
    inside the generator, AFTER Starlette had sent
    ``http.response.start`` with status 200).

    The returned :class:`PreparedStream` is consumed exactly once by
    :func:`stream_assistant_response`; the chat row and history tree
    held inside it are the same objects the generator will commit to
    on every persist checkpoint. Note that the
    ``Depends(get_session)`` ``async with`` exits when the route
    handler returns the :class:`StreamingResponse`, BEFORE Starlette
    iterates the generator body — see the re-attach comment at the
    top of :func:`stream_assistant_response` for the consequence and
    the one-line workaround.
    """
    # Step 1: load + authorise. ``with_for_update()`` serialises
    # concurrent writes against the same chat row (e.g. an in-flight
    # stream colliding with a future M5 automation chat-target write).
    # The lock is released by the ``await db.commit()`` at the end of
    # step 3 — well before the provider iteration starts and before
    # :class:`StreamingResponse` opens the response.
    result = await db.execute(
        select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id).with_for_update()
    )
    chat = result.scalar_one_or_none()
    if chat is None:
        # The session's open transaction (the SELECT FOR UPDATE itself,
        # even when it returned nothing, opened one) is rolled back by
        # the ``get_session`` dependency teardown when the request
        # completes. No row was locked because the WHERE predicate
        # matched no rows, so there is nothing to leak here either way.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="chat not found")
    history = History.model_validate(chat.history)

    # Step 2: agent validation.
    if not agents_cache.contains(body.agent_id):
        await agents_cache.refresh()
        if not agents_cache.contains(body.agent_id):
            # The chat row IS locked at this point (SELECT FOR UPDATE
            # succeeded above). The HTTPException propagates up to the
            # exception handler; the ``get_session`` dependency teardown
            # then closes the session, which rolls back the open
            # transaction and releases the row lock — so subsequent
            # test-cleanup ``DELETE FROM chat`` does not deadlock.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unknown agent: {body.agent_id}",
            )

    # Step 3: seed history + first persist.
    user_msg, assistant_msg = _seed_history(
        history=history, body=body, agent_label=agents_cache.label(body.agent_id)
    )
    if not chat.title or chat.title == "New Chat":
        chat.title = _derive_title_from(body.content)
    # Enforce the cap up-front so a too-large initial user message is
    # rejected with a clean 413 (via the M0 centralised handler)
    # BEFORE we open the stream. Once the response stream opens,
    # status is locked at 200 and overflow surfaces as a terminal
    # SSE ``error`` instead (see :func:`_close_with_history_overflow`).
    payload = history.model_dump()
    _enforce_history_cap(payload)
    chat.history = payload
    chat.updated_at = now_ms()
    # Releases the SELECT FOR UPDATE row lock.
    await db.commit()

    return PreparedStream(
        chat=chat,
        history=history,
        user_msg=user_msg,
        assistant_msg=assistant_msg,
        body=body,
    )


async def stream_assistant_response(
    *,
    db: AsyncSession,
    provider: OpenAICompatibleProvider,
    registry: StreamRegistry,
    prepared: PreparedStream,
) -> AsyncIterator[bytes]:
    """The post-validation SSE generator.

    Yields raw ``bytes`` SSE frames (``event: ...\\ndata: ...\\n\\n``)
    plus occasional ``: keep-alive\\n\\n`` heartbeats. All pre-yield
    validation (chat lookup, agent membership, initial cap
    enforcement) ran in :func:`prepare_stream` BEFORE this generator
    was constructed, so every branch here either yields an SSE frame
    or persists+yields a terminal frame — never raises an
    :class:`HTTPException` after Starlette has sent
    ``http.response.start``.

    The provider loop is factored into :func:`_run_provider_loop` so
    the outer terminal-branch try/except chain stays readable; the
    two functions share state via :class:`_StreamState`.
    """
    chat = prepared.chat
    history = prepared.history
    user_msg = prepared.user_msg
    assistant_msg = prepared.assistant_msg
    body = prepared.body

    # Re-attach the chat to the session before any subsequent commit.
    #
    # FastAPI's dependency teardown for ``Depends(get_session)`` runs as
    # soon as the route handler returns the ``StreamingResponse``,
    # i.e. BEFORE Starlette starts iterating this generator (the
    # ``AsyncExitStack`` that owns the dep yield-cleanup unwinds at
    # the boundary of the route function, not after the response body
    # is sent). The session's ``async with`` exit calls
    # ``session.close()``, which clears the identity map and detaches
    # every persistent object — including the ``chat`` row that
    # :func:`prepare_stream` loaded.
    #
    # The :class:`AsyncSession` itself is reusable after ``close()``
    # (a fresh transaction auto-begins on the next operation), but a
    # detached object's attribute mutations are NOT tracked by the
    # session's unit-of-work, so subsequent ``await db.commit()``
    # calls in the persist throttle and the terminal branches would
    # silently no-op (no UPDATE issued, the assistant content + done
    # flag never reach the DB).
    #
    # ``db.add(chat)`` re-attaches the persistent object so the
    # session resumes tracking attribute changes; the row is not
    # re-INSERTed because its primary key matches an existing row.
    db.add(chat)

    # Step 4: open the stream.
    yield sse(
        "start",
        {
            "user_message_id": user_msg.id,
            "assistant_message_id": assistant_msg.id,
        },
    )

    linear = build_linear_thread(history, parent_id=user_msg.id)
    openai_messages: list[dict[str, Any]] = [{"role": m.role, "content": m.content} for m in linear]
    cancel_event = await registry.register(assistant_msg.id)
    state = _StreamState()

    try:
        try:
            async with asyncio.timeout(settings.sse_stream_timeout_seconds):
                async for frame in _run_provider_loop(
                    provider=provider,
                    db=db,
                    chat=chat,
                    history=history,
                    assistant_msg=assistant_msg,
                    body=body,
                    openai_messages=openai_messages,
                    cancel_event=cancel_event,
                    state=state,
                ):
                    yield frame
        except TimeoutError:
            yield await _close_with_timeout(
                db, chat=chat, history=history, assistant_msg=assistant_msg, state=state
            )
            return
    except asyncio.CancelledError:
        yield await _close_with_cancel(
            db, chat=chat, history=history, assistant_msg=assistant_msg, state=state
        )
        return
    except HistoryTooLargeError as exc:
        yield await _close_with_history_overflow(
            db,
            chat=chat,
            history=history,
            assistant_msg=assistant_msg,
            state=state,
            exc=exc,
        )
        return
    except ProviderError as exc:
        yield await _close_with_provider_error(
            db,
            chat=chat,
            history=history,
            assistant_msg=assistant_msg,
            state=state,
            exc=exc,
        )
        return
    finally:
        # Cancel any in-flight provider __anext__() task so we don't leak
        # a coroutine when the loop exits via cancel/timeout/error. Per
        # § A.8 of FastAPI-best-practises.md we hold a strong reference
        # (``state.pending_next``) and cancel deliberately here.
        await _drain_pending(state.pending_next)
        await registry.unregister(assistant_msg.id)

    # Step 5: normal completion.
    assistant_msg.content = "".join(state.accumulated)
    assistant_msg.done = True
    chat.history = history.model_dump()
    chat.updated_at = now_ms()
    await db.commit()
    yield sse(
        "done",
        {
            "assistant_message_id": assistant_msg.id,
            "finish_reason": state.finish_reason or "stop",
        },
    )


async def _run_provider_loop(
    *,
    provider: OpenAICompatibleProvider,
    db: AsyncSession,
    chat: Chat,
    history: History,
    assistant_msg: HistoryMessage,
    body: MessageSend,
    openai_messages: list[dict[str, Any]],
    cancel_event: asyncio.Event,
    state: _StreamState,
) -> AsyncIterator[bytes]:
    """Inner provider iteration: yields ``delta`` / ``usage`` / heartbeat
    frames while persisting throttled checkpoints.

    Raises (caught by :func:`stream_assistant_response`'s outer chain):

    * :class:`asyncio.CancelledError` — user cancel via the registry's
      local event, or client disconnect propagated by Starlette.
    * :class:`asyncio.TimeoutError` — outer ``asyncio.timeout`` deadline
      exceeded (raised at the ``async with`` boundary in the caller).
    * :class:`HistoryTooLargeError` — mid-stream persist would overflow
      the 1 MiB cap.
    * :class:`ProviderError` — upstream gateway failure mapped by the
      provider's ``except`` chain.
    """
    provider_aiter = provider.stream(
        messages=openai_messages,
        agent_id=body.agent_id,
        params=body.params.model_dump(exclude_none=True),
    ).__aiter__()
    last_persist = monotonic()

    while True:
        # Cancel-event poll between iterations. The /cancel endpoint's
        # Redis publish reaches this pod's registry, which sets the
        # local event; we observe it on the next iteration boundary and
        # raise so the outer ``except asyncio.CancelledError`` runs.
        if cancel_event.is_set():
            raise asyncio.CancelledError

        if state.pending_next is None:
            state.pending_next = asyncio.create_task(_next_or_end(provider_aiter))

        # Heartbeat tick. ``asyncio.shield`` keeps the upstream fetch
        # alive across the heartbeat-timeout cancel so we don't drop a
        # chunk mid-read; the same task is awaited again on the next
        # iteration when the heartbeat fires.
        try:
            item = await asyncio.wait_for(
                asyncio.shield(state.pending_next),
                timeout=STREAM_HEARTBEAT_SECONDS,
            )
        except TimeoutError:
            # Provider silent for ≥ STREAM_HEARTBEAT_SECONDS; emit an
            # SSE comment frame so the LB doesn't idle-cut the
            # connection at 60 s. The outer ``asyncio.timeout`` block
            # remains the only request-deadline enforcer.
            yield b": keep-alive\n\n"
            continue

        state.pending_next = None
        if isinstance(item, _EndOfStream):
            return
        # mypy narrows ``item`` to ``StreamDelta`` after the isinstance
        # guard above; bind a local for readability.
        delta = item

        if delta.content:
            state.accumulated.append(delta.content)
            yield sse("delta", {"content": delta.content})
        if delta.usage:
            assistant_msg.usage = delta.usage
            yield sse("usage", delta.usage)
        if delta.finish_reason:
            state.finish_reason = delta.finish_reason

        # Persist throttle. The cap check sits inside the throttle
        # branch (not on every iteration) so the hot path stays cheap;
        # an oversized history surfaces within at most
        # ``_PERSIST_EVERY_SECONDS`` of the offending append.
        if monotonic() - last_persist > _PERSIST_EVERY_SECONDS:
            assistant_msg.content = "".join(state.accumulated)
            snapshot = history.model_dump()
            # Raises HistoryTooLargeError → propagates to the outer
            # except in :func:`stream_assistant_response` → terminal SSE error frame.
            _enforce_history_cap(snapshot)
            chat.history = snapshot
            await db.commit()
            last_persist = monotonic()


async def _close_with_timeout(
    db: AsyncSession,
    *,
    chat: Chat,
    history: History,
    assistant_msg: HistoryMessage,
    state: _StreamState,
) -> bytes:
    """``SSE_STREAM_TIMEOUT_SECONDS`` exceeded.

    Persist shape mirrors cancellation (``cancelled=True, done=True``);
    the distinct SSE frame lets the UI render an "exceeded time limit"
    affordance instead of a generic cancellation.
    """
    assistant_msg.content = "".join(state.accumulated)
    assistant_msg.cancelled = True
    assistant_msg.done = True
    await _persist_terminal(db, chat=chat, history=history)
    return sse(
        "timeout",
        {
            "assistant_message_id": assistant_msg.id,
            "limit_seconds": settings.sse_stream_timeout_seconds,
        },
    )


async def _close_with_cancel(
    db: AsyncSession,
    *,
    chat: Chat,
    history: History,
    assistant_msg: HistoryMessage,
    state: _StreamState,
) -> bytes:
    """Client disconnect (Starlette raises ``CancelledError`` inside the
    generator) or explicit ``/cancel`` (the registry's local event was
    set, the provider loop raised ``CancelledError`` itself).

    Same persist shape for both — the user sees the partial content
    they already received plus a ``cancelled`` badge on reload.
    """
    assistant_msg.content = "".join(state.accumulated)
    assistant_msg.cancelled = True
    assistant_msg.done = True
    await _persist_terminal(db, chat=chat, history=history)
    return sse("cancelled", {"assistant_message_id": assistant_msg.id})


async def _close_with_history_overflow(
    db: AsyncSession,
    *,
    chat: Chat,
    history: History,
    assistant_msg: HistoryMessage,
    state: _StreamState,
    exc: HistoryTooLargeError,
) -> bytes:
    """Mid-stream ``_enforce_history_cap`` raised — truncate the
    assistant content until the serialised history fits, then persist
    with ``done=True, error={"code": "history_too_large"}`` (per plan
    § History-size enforcement, line 863).
    """
    assistant_msg.content = "".join(state.accumulated)
    await _persist_after_truncate(db, chat=chat, history=history, assistant_msg=assistant_msg)
    return sse(
        "error",
        {
            "assistant_message_id": assistant_msg.id,
            "code": "history_too_large",
            "message": str(exc),
            "status_code": status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        },
    )


async def _close_with_provider_error(
    db: AsyncSession,
    *,
    chat: Chat,
    history: History,
    assistant_msg: HistoryMessage,
    state: _StreamState,
    exc: ProviderError,
) -> bytes:
    """Upstream gateway failed mid-stream. Persist the partial content
    with ``done=True, error={...}`` so a reload shows what the user
    already saw plus the error tag.
    """
    assistant_msg.content = "".join(state.accumulated)
    assistant_msg.done = True
    assistant_msg.error = {"message": str(exc)}
    await _persist_terminal(db, chat=chat, history=history)
    return sse(
        "error",
        {
            "assistant_message_id": assistant_msg.id,
            "message": str(exc),
            "status_code": exc.status_code,
        },
    )


def _seed_history(
    *,
    history: History,
    body: MessageSend,
    agent_label: str,
) -> tuple[HistoryMessage, HistoryMessage]:
    """Build the user message + placeholder assistant message and stitch
    them into the history tree. Returns ``(user_msg, assistant_msg)``.

    The mutation is in-place on ``history`` (it's a Pydantic model with
    a mutable ``messages`` dict) so the caller can ``history.model_dump()``
    after for the first persist.
    """
    parent_id = body.parent_id or history.currentId
    user_msg = HistoryMessage(
        id=new_id(),
        parentId=parent_id,
        childrenIds=[],
        role="user",
        content=body.content,
        timestamp=now_ms(),
    )
    assistant_msg = HistoryMessage(
        id=new_id(),
        parentId=user_msg.id,
        childrenIds=[],
        role="assistant",
        content="",
        timestamp=now_ms(),
        agent_id=body.agent_id,
        agentName=agent_label,
        done=False,
    )
    history.messages[user_msg.id] = user_msg
    history.messages[assistant_msg.id] = assistant_msg
    if parent_id is not None and parent_id in history.messages:
        history.messages[parent_id].childrenIds.append(user_msg.id)
    user_msg.childrenIds.append(assistant_msg.id)
    history.currentId = assistant_msg.id
    return user_msg, assistant_msg


async def _drain_pending(
    pending_next: asyncio.Task[StreamDelta | _EndOfStream] | None,
) -> None:
    """Cancel and await an outstanding provider-fetch task.

    Called from :func:`stream_assistant_response`'s ``finally`` block
    so a partial fetch in flight at cancel/timeout/error time is reaped
    instead of leaked. Idempotent: a missing or already-done task is a
    no-op.
    """
    if pending_next is None or pending_next.done():
        return
    pending_next.cancel()
    # Any exception (CancelledError, ProviderError, transport error)
    # is uninteresting at teardown — we only care that the task is
    # finished so the underlying connection can be released.
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await pending_next


# ---------------------------------------------------------------------------
# Internal helpers — kept module-private so the public surface of the
# streaming pipeline is exactly ``prepare_stream`` +
# ``stream_assistant_response`` + ``PreparedStream`` + ``sse`` +
# ``build_linear_thread``.
# ---------------------------------------------------------------------------


def _derive_title_from(content: str) -> str:
    """Lazy import of :func:`app.services.chat_title.derive_title`.

    Module-level import would create a tiny but real circular hazard
    once M5's automation executor (which imports ``chat_writer``, which
    is imported from this module) lands. Lazy-import keeps the import
    graph one-way at module load.
    """
    from app.services.chat_title import derive_title

    return derive_title(content)


async def _persist_terminal(db: AsyncSession, *, chat: Chat, history: History) -> None:
    """Final ``chat.history`` write for the cancelled / timeout /
    provider-error branches.

    All three branches share the same persistence shape (the assistant
    message has already been mutated in-memory by the caller; we just
    serialise + cap-check + commit). The cap check here protects against
    the corner case where the assistant message accumulated enough
    content to push the history over the 1 MiB cap on its very last
    chunk — we'd rather emit a terminal error in the rare overlap than
    silently fail the commit on the way out.
    """
    payload = history.model_dump()
    try:
        _enforce_history_cap(payload)
    except HistoryTooLargeError:
        # Defensive: if the terminal-branch persist itself overflows,
        # leave the previous successfully-persisted history in place
        # rather than blow up the SSE response. The user already saw
        # the partial content on the wire; the next reload will show
        # whatever the last successful checkpoint contained.
        log.warning(
            "stream_assistant_response: terminal persist would overflow cap; "
            "keeping last checkpoint",
        )
        return
    chat.history = payload
    chat.updated_at = now_ms()
    await db.commit()


async def _persist_after_truncate(
    db: AsyncSession,
    *,
    chat: Chat,
    history: History,
    assistant_msg: HistoryMessage,
) -> None:
    """Persist after a :class:`HistoryTooLargeError` mid-stream.

    Trims ``assistant_msg.content`` (halving each iteration) until the
    serialised history fits the cap, then commits with
    ``done=True, error={"code": "history_too_large"}``.

    Halving converges in ≤ ⌈log₂(content_len)⌉ iterations — at most ~24
    for a 16 MiB content blob. For typical 5-50 KiB streamed content
    this is < 14 iterations of constant-time JSON serialisation, which
    is cheap enough to do inline at the error path.
    """
    assistant_msg.done = True
    assistant_msg.error = {"code": "history_too_large"}
    while True:
        payload = history.model_dump()
        try:
            _enforce_history_cap(payload)
            break
        except HistoryTooLargeError:
            if not assistant_msg.content:
                # Even an empty assistant message overflows — the user
                # message itself is the offender. Bail out without
                # touching ``chat.history``; the previous checkpoint
                # holds what the user saw on the wire.
                log.warning(
                    "stream_assistant_response: history overflows even with empty "
                    "assistant content; preserving previous checkpoint",
                )
                return
            assistant_msg.content = assistant_msg.content[: len(assistant_msg.content) // 2]
    chat.history = payload
    chat.updated_at = now_ms()
    await db.commit()
