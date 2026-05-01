"""Chat CRUD + the optional title-helper endpoint.

The streaming endpoint (``POST /api/chats/{id}/messages``) and its
companion explicit-cancel surface (``POST /api/chats/{id}/messages/{message_id}/cancel``)
are added to **this same file** by Phase 2c (realtime-engineer). The
file is structured so that follow-up edit lands cleanly:

* ``router`` is a single ``APIRouter`` instance with prefix ``/api`` and
  tag ``["chats"]`` — Phase 2c reuses it.
* No module-level mutable state, no global registries, no streaming
  generators here — Phase 2c brings the SSE generator + the
  :class:`StreamRegistry` import.
* The CRUD helpers (``_load_owned_chat``, ``_to_summary``, ``_to_read``,
  ``_validate_folder``, the cursor codec) are kept generic enough that
  the streaming handler can call ``_load_owned_chat`` directly.

References:

* ``rebuild/docs/plans/m2-conversations.md`` § Chat CRUD (full surface).
* ``rebuild/docs/plans/m2-conversations.md`` § Out of scope (sidebar
  ``?q=`` is ``LIKE %q%`` on ``title`` plus ``JSON_SEARCH(LOWER(history),
  ...)`` on content; OR'd together).
* ``rebuild/docs/best-practises/database-best-practises.md`` § A.3
  (cursor pagination on ``(sort_column, id)`` — never ``OFFSET``).
* ``rebuild/docs/best-practises/FastAPI-best-practises.md`` § A.6
  (errors via ``HTTPException`` directly; no per-router try/except for
  app-level errors — the centralised handler in ``app/core/errors.py``
  maps :class:`app.providers.openai.ProviderError` to 502 / 504 / 429).
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from openai import APIError, APIStatusError, APITimeoutError, RateLimitError
from openai.types.chat import ChatCompletionMessageParam
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    AgentsCacheDep,
    CurrentUser,
    DbSession,
    Provider,
    StreamRegistryDep,
)
from app.core.ids import new_id
from app.core.time import now_ms
from app.models.chat import Chat
from app.models.folder import Folder
from app.providers.openai import ProviderError
from app.schemas.chat import (
    ChatCreate,
    ChatList,
    ChatPatch,
    ChatRead,
    ChatSummary,
    MessageSend,
    TitleRequest,
    TitleResponse,
)
from app.schemas.history import History
from app.services.chat_stream import prepare_stream, stream_assistant_response
from app.services.chat_title import derive_title

router = APIRouter(prefix="/api", tags=["chats"])

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200
_NO_FOLDER_SENTINEL = "none"
_CURSOR_TUPLE_LEN = 2  # (updated_at, id)
_TITLE_SYSTEM_PROMPT = (
    "Generate a concise, descriptive title (no more than 6 words) for the "
    "conversation. Reply with only the title — no quotes, no markdown, no "
    "trailing punctuation."
)
_TITLE_MAX_TOKENS = 20


# ---------------------------------------------------------------------------
# Helpers — kept generic so Phase 2c's streaming handler can reuse them.
# ---------------------------------------------------------------------------


async def _load_owned_chat(db: AsyncSession, *, chat_id: str, user_id: str) -> Chat:
    """Load a chat by id + user, or raise ``404``.

    ``Chat.user_id == user.id`` is the project-wide invariant on every
    chat read or write — defence in depth even with the FK
    (``database-best-practises.md`` § A.5). A foreign or missing chat
    returns 404 (not 403) to leak nothing about other users' rows
    (``FastAPI-best-practises.md`` § A.9).
    """
    chat = await db.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id))
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="chat not found")
    return chat


async def _validate_folder(db: AsyncSession, *, folder_id: str, user_id: str) -> None:
    """Confirm a folder belongs to ``user_id`` or raise ``404``.

    Used by ``POST /api/chats`` (initial assignment) and ``PATCH
    /api/chats/{id}`` (move). Returns ``None`` on success — the caller
    only needs to know the folder is theirs to point at.
    """
    exists = await db.scalar(
        select(Folder.id).where(Folder.id == folder_id, Folder.user_id == user_id)
    )
    if exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="folder not found")


def _to_summary(chat: Chat) -> ChatSummary:
    return ChatSummary(
        id=chat.id,
        title=chat.title,
        pinned=chat.pinned,
        archived=chat.archived,
        folder_id=chat.folder_id,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


def _to_read(chat: Chat) -> ChatRead:
    return ChatRead(
        id=chat.id,
        title=chat.title,
        pinned=chat.pinned,
        archived=chat.archived,
        folder_id=chat.folder_id,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        history=History.model_validate(chat.history),
        share_id=chat.share_id,
    )


def _encode_cursor(updated_at: int, chat_id: str) -> str:
    """Encode ``(updated_at, id)`` as a URL-safe base64 JSON tuple.

    Padding is stripped on encode and re-added on decode so the cursor
    is safe to drop into a query string verbatim.
    """
    raw = json.dumps([updated_at, chat_id], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[int, str]:
    """Decode the cursor back to ``(updated_at, id)``.

    Any malformed cursor (bad base64, bad JSON, wrong arity, wrong types)
    surfaces as a clean 422 — the client is supposed to round-trip the
    server-issued opaque string verbatim.
    """
    try:
        pad = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode((cursor + pad).encode("ascii"))
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, list) or len(parsed) != _CURSOR_TUPLE_LEN:
            raise ValueError("expected [updated_at, id]")
        return int(parsed[0]), str(parsed[1])
    except (ValueError, TypeError, json.JSONDecodeError, binascii.Error) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid cursor: {e}",
        ) from e


# ---------------------------------------------------------------------------
# CRUD routes
# ---------------------------------------------------------------------------


@router.get("/chats", response_model=ChatList)
async def list_chats(
    user: CurrentUser,
    db: DbSession,
    folder_id: str | None = None,
    archived: bool = False,
    pinned: bool | None = None,
    q: str | None = None,
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = None,
) -> ChatList:
    """Sidebar list. Cursor-paginated on ``(updated_at DESC, id DESC)``.

    Query parameters:

    * ``folder_id`` — ``None`` for "no folder filter"; the literal
      sentinel ``"none"`` for "no folder" (``Chat.folder_id IS NULL``);
      any other value filters by that folder UUID. Foreign / non-existent
      folders simply return an empty page (no 404 — leaks nothing).
    * ``archived`` — defaults to ``False`` so the sidebar shows live
      chats by default; pass ``true`` for the archive view.
    * ``pinned`` — when omitted, no pinned filter; when provided, filters
      to that exact value.
    * ``q`` — substring search; case-insensitive ``LIKE %q%`` on
      ``title`` OR'd with ``JSON_SEARCH(LOWER(history), 'one', LOWER(:q))``
      on the chat body (plan § Out of scope, line 1064).
    * ``cursor`` — opaque, encodes ``(updated_at, id)`` as base64 of a
      JSON tuple. Clients pass back exactly what the server returned.
    """
    stmt = select(Chat).where(Chat.user_id == user.id)

    if folder_id == _NO_FOLDER_SENTINEL:
        stmt = stmt.where(Chat.folder_id.is_(None))
    elif folder_id is not None:
        stmt = stmt.where(Chat.folder_id == folder_id)

    stmt = stmt.where(Chat.archived.is_(archived))

    if pinned is not None:
        stmt = stmt.where(Chat.pinned.is_(pinned))

    if q:
        # Case-insensitive substring on title OR'd with content search via
        # MySQL's JSON_SEARCH (returns a path on hit, NULL on miss). The
        # plan locks this exact two-pronged shape (§ Out of scope, line 1064).
        pattern = f"%{q}%"
        content_match = func.json_search(
            func.lower(Chat.history), "one", func.lower(pattern)
        ).is_not(None)
        stmt = stmt.where(or_(Chat.title.ilike(pattern), content_match))

    if cursor is not None:
        cursor_updated_at, cursor_id = _decode_cursor(cursor)
        # Stable tie-break on (updated_at, id) — equal updated_at rows
        # page consistently across requests instead of skipping or
        # repeating themselves.
        stmt = stmt.where(
            or_(
                Chat.updated_at < cursor_updated_at,
                (Chat.updated_at == cursor_updated_at) & (Chat.id < cursor_id),
            )
        )

    stmt = stmt.order_by(Chat.updated_at.desc(), Chat.id.desc()).limit(limit + 1)

    rows = (await db.scalars(stmt)).all()

    next_cursor: str | None = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = _encode_cursor(last.updated_at, last.id)
        rows = list(rows[:limit])

    return ChatList(items=[_to_summary(c) for c in rows], next_cursor=next_cursor)


@router.post("/chats", response_model=ChatRead, status_code=status.HTTP_201_CREATED)
async def create_chat(body: ChatCreate, user: CurrentUser, db: DbSession) -> ChatRead:
    """Create an empty chat.

    The plan literal default for ``title`` is ``"New Chat"`` (matches
    ``Chat.title.default``); we deliberately do **not** call
    :func:`derive_title` here because the chat has no first user message
    yet — the title-helper endpoint is the surface that exercises the
    derive-from-prompt path. ``history`` starts as the empty tree
    ``{"messages": {}, "currentId": None}`` so subsequent ``GET`` round-
    trips through :class:`History` cleanly.
    """
    if body.folder_id is not None:
        await _validate_folder(db, folder_id=body.folder_id, user_id=user.id)

    now = now_ms()
    chat = Chat(
        id=new_id(),
        user_id=user.id,
        title=body.title or "New Chat",
        history={"messages": {}, "currentId": None},
        folder_id=body.folder_id,
        archived=False,
        pinned=False,
        created_at=now,
        updated_at=now,
    )
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    return _to_read(chat)


@router.get("/chats/{chat_id}", response_model=ChatRead)
async def get_chat(chat_id: str, user: CurrentUser, db: DbSession) -> ChatRead:
    """Full chat including the validated ``history`` tree."""
    chat = await _load_owned_chat(db, chat_id=chat_id, user_id=user.id)
    return _to_read(chat)


@router.patch("/chats/{chat_id}", response_model=ChatRead)
async def patch_chat(chat_id: str, body: ChatPatch, user: CurrentUser, db: DbSession) -> ChatRead:
    """Partial metadata update.

    ``model_dump(exclude_unset=True)`` is the only correct shape here —
    ``folder_id=None`` in the body must be distinguishable from "field
    omitted" (the former detaches; the latter leaves it alone). When
    ``folder_id`` is moving to a non-``None`` value, the new folder is
    validated to belong to the user. ``updated_at`` is bumped on every
    PATCH (even title-only) so the sidebar reflects "last touched".
    """
    chat = await _load_owned_chat(db, chat_id=chat_id, user_id=user.id)
    patch = body.model_dump(exclude_unset=True)

    if "folder_id" in patch and patch["folder_id"] is not None:
        await _validate_folder(db, folder_id=patch["folder_id"], user_id=user.id)

    for field, value in patch.items():
        setattr(chat, field, value)
    chat.updated_at = now_ms()

    await db.commit()
    await db.refresh(chat)
    return _to_read(chat)


@router.delete("/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(chat_id: str, user: CurrentUser, db: DbSession) -> Response:
    """Hard delete. ``204 No Content`` on success, ``404`` if not owned.

    Implemented as load-then-``session.delete`` rather than a bare
    ``delete()`` statement so the ownership check (``_load_owned_chat``
    raises 404) and the actual deletion are both expressed at the ORM
    level — no rowcount-from-Result inspection needed.
    """
    chat = await _load_owned_chat(db, chat_id=chat_id, user_id=user.id)
    await db.delete(chat)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Title helper (non-streaming)
# ---------------------------------------------------------------------------


async def _generate_title(
    *,
    provider: Provider,
    agent_id: str,
    messages: list[dict[str, Any]],
) -> str:
    """One-shot non-streaming completion for the title-helper endpoint.

    Phase 2a's ``OpenAICompatibleProvider`` only exposes ``stream`` and
    ``list_agents``; the title helper is the one M2 surface that needs a
    blocking completion. We poke through to ``provider._client`` here
    deliberately (per the dispatch instructions) and mirror
    ``provider.stream``'s exception mapping so :class:`ProviderError`
    bubbles into the centralised handler with the right status code.

    ``agent_id`` is the rebuild-domain id; the OpenAI SDK still wants it
    in the ``model=`` slot on the wire.
    """
    # The OpenAI SDK's ``messages`` argument expects a union of
    # ``ChatCompletion*MessageParam`` TypedDicts; plain ``dict[str, Any]``
    # is what hits the wire either way, but mypy strict needs the cast to
    # accept the call. ``stream=False`` is a literal so the SDK overload
    # picks the non-streaming ``ChatCompletion`` return type unambiguously.
    typed_messages = cast(
        list[ChatCompletionMessageParam],
        [
            {"role": "system", "content": _TITLE_SYSTEM_PROMPT},
            *messages,
        ],
    )
    try:
        response = await provider._client.chat.completions.create(  # noqa: SLF001
            model=agent_id,
            messages=typed_messages,
            stream=False,
            max_tokens=_TITLE_MAX_TOKENS,
        )
    except APITimeoutError as e:
        raise ProviderError("upstream timeout", status_code=504) from e
    except RateLimitError as e:
        raise ProviderError("upstream rate-limited", status_code=429) from e
    except APIStatusError as e:
        raise ProviderError(f"upstream {e.status_code}: {e.message}", status_code=502) from e
    except APIError as e:
        raise ProviderError(f"upstream error: {e}", status_code=502) from e

    if not response.choices:
        raise ProviderError("upstream returned no choices", status_code=502)
    raw = (response.choices[0].message.content or "").strip()
    if not raw:
        raise ProviderError("upstream returned empty title", status_code=502)
    return raw


@router.post("/chats/{chat_id}/title", response_model=TitleResponse)
async def title_chat(
    chat_id: str,
    body: TitleRequest,
    user: CurrentUser,
    db: DbSession,
    provider: Provider,
    cache: AgentsCacheDep,
) -> TitleResponse:
    """Ask the gateway for a ≤6-word title; persist + return it.

    Implementation notes:

    * The default agent is the first id from the cached agent catalogue
      (alphabetical from Phase 2a's :class:`AgentsCache`). If the cache
      is empty the cache call itself raises :class:`ProviderError` →
      502/504/429 via the centralised handler.
    * The gateway's response is run through :func:`derive_title` to
      enforce the 60-char / single-line invariant — defence against an
      unusually verbose agent that ignored "≤6 words". ``derive_title``
      also catches the empty / whitespace-only case and returns the
      project default ``"New Chat"``.
    * ``updated_at`` is bumped so the sidebar surfaces the new title.
    """
    chat = await _load_owned_chat(db, chat_id=chat_id, user_id=user.id)

    items = await cache.get()
    if not items:
        raise ProviderError("no agents available from upstream", status_code=502)
    default_agent_id = items[0].id

    raw_title = await _generate_title(
        provider=provider,
        agent_id=default_agent_id,
        messages=[m.model_dump() for m in body.messages],
    )
    new_title = derive_title(raw_title)

    chat.title = new_title
    chat.updated_at = now_ms()
    await db.commit()

    return TitleResponse(title=new_title)


# ---------------------------------------------------------------------------
# Streaming surface (Phase 2c — realtime-engineer)
# ---------------------------------------------------------------------------
#
# The streaming and cancel endpoints share this router (single ``/api``
# prefix per FastAPI-best-practises.md § A.1). The generator and
# StreamRegistry live in ``app/services/chat_stream.py`` and
# ``app/services/stream_registry.py`` respectively — this file is the
# thin HTTP-shape adapter that wires them up.
#
# The streaming endpoint deliberately does NOT declare a
# ``response_model`` because the response body is ``text/event-stream``
# (not JSON); the SSE event taxonomy is documented in
# ``rebuild/docs/plans/m2-conversations.md`` § SSE streaming
# (lines 654-668). Headers ``Cache-Control: no-cache`` and
# ``X-Accel-Buffering: no`` are mandatory — the latter defeats nginx's
# response buffering so tokens reach the client as they're produced
# (FastAPI-best-practises.md § A.7).


@router.post("/chats/{chat_id}/messages", response_class=StreamingResponse)
async def post_message(
    chat_id: str,
    body: MessageSend,
    user: CurrentUser,
    db: DbSession,
    provider: Provider,
    registry: StreamRegistryDep,
    agents_cache: AgentsCacheDep,
) -> StreamingResponse:
    """Append a user message and stream the assistant reply via SSE.

    The handler is split in two so pre-stream errors (404 / 400 / 413)
    surface as proper JSON HTTP responses instead of being lost behind
    Starlette's already-sent ``http.response.start`` (Phase 4a bug —
    see ``app/services/chat_stream.py`` module docstring):

    1. :func:`app.services.chat_stream.prepare_stream` runs the chat
       lookup, agent membership check, user-message seeding, initial
       history-cap enforcement, and the first persist that releases
       the ``SELECT FOR UPDATE`` row lock. Any
       :class:`fastapi.HTTPException` (404 / 400) or
       :class:`app.services.chat_writer.HistoryTooLargeError` (413)
       raised here propagates out through the central exception
       handlers in ``app/core/errors.py`` — nothing has been written
       to the response wire yet.

    2. :func:`app.services.chat_stream.stream_assistant_response` is
       the post-validation async generator. It owns the SSE event
       taxonomy (``start → delta* → usage? → done``), the persist
       throttle, and the four terminal branches (cancel / timeout /
       mid-stream history-cap / provider error). Every error raised
       inside the generator becomes a terminal SSE frame because the
       response status is already locked at 200 by the time the
       generator's first ``yield`` runs.
    """
    prepared = await prepare_stream(
        chat_id=chat_id,
        user=user,
        body=body,
        db=db,
        agents_cache=agents_cache,
    )
    return StreamingResponse(
        stream_assistant_response(
            db=db,
            provider=provider,
            registry=registry,
            prepared=prepared,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/chats/{chat_id}/messages/{assistant_message_id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_message(
    chat_id: str,
    assistant_message_id: str,
    user: CurrentUser,
    db: DbSession,
    registry: StreamRegistryDep,
) -> Response:
    """Best-effort cancel of an in-flight stream.

    Looks up the chat by id + user (404 if not owned) and publishes a
    cancel signal to ``stream:cancel:{assistant_message_id}`` via
    :class:`app.services.stream_registry.StreamRegistry`. The pod
    actually running the stream receives the signal via its Redis
    subscription, sets the local cancellation event, and the streaming
    generator catches it on its next iteration and emits a terminal
    ``cancelled`` SSE frame.

    Returns 204 even when the stream has already finished (idempotent;
    the publish hits an empty channel and is a no-op). The
    ``assistant_message_id`` itself is not validated against the chat
    history because the chat-ownership check is sufficient — and a
    spurious cancel is harmless (it's a Redis no-op).

    Plan reference: ``rebuild/docs/plans/m2-conversations.md`` line 672
    ("Best-effort; if the stream already finished, returns 204 anyway.")
    and § Acceptance criteria.
    """
    await _load_owned_chat(db, chat_id=chat_id, user_id=user.id)
    await registry.cancel(assistant_message_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router", "_load_owned_chat"]
