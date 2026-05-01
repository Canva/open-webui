"""Request / response schemas for the M2 chat surface.

The router handlers live in ``app/routers/chats.py`` (Phase 2b dispatch);
this module owns only the wire shapes. Every schema inherits from
:class:`StrictModel` so unknown fields produce a 422 (defence against
typo'd request bodies and against silent legacy payload leakage).

Locked references:

* ``rebuild/docs/plans/m2-conversations.md`` § API surface — Chat CRUD.
* ``rebuild/docs/plans/m2-conversations.md`` § JSON shape of
  ``chat.history`` (the :class:`History` model in
  ``app.schemas.history``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas._base import StrictModel
from app.schemas.history import History


class ChatSummary(StrictModel):
    """Sidebar-shaped chat row — no ``history`` payload."""

    id: str
    title: str
    pinned: bool
    archived: bool
    folder_id: str | None
    created_at: int
    updated_at: int


class ChatList(StrictModel):
    """Cursor-paginated sidebar list response."""

    items: list[ChatSummary]
    next_cursor: str | None = None


class ChatRead(ChatSummary):
    """Full chat including the ``history`` tree.

    ``share_id`` is reserved for M3 and is always ``None`` in M2 (the
    column exists on the ``chat`` table but no M2 code path writes it).
    """

    history: History
    share_id: str | None = None


class ChatCreate(StrictModel):
    """Body for ``POST /api/chats``. Empty title becomes ``"New Chat"`` in
    the router; we do not enforce ``min_length`` so the frontend can post
    a blank create from the empty-state landing screen."""

    title: str | None = None
    folder_id: str | None = None


class ChatPatch(StrictModel):
    """Body for ``PATCH /api/chats/{id}``. Every field optional; ``None``
    on ``folder_id`` explicitly detaches the chat from its current folder."""

    title: str | None = None
    folder_id: str | None = None
    pinned: bool | None = None
    archived: bool | None = None


class ChatParams(StrictModel):
    """Per-message provider knobs. Subset of the OpenAI param surface; we
    deliberately do not expose ``top_p`` / ``presence_penalty`` / etc until
    a real user need appears."""

    temperature: float | None = Field(default=None, ge=0, le=2)
    system: str | None = None


class MessageSend(StrictModel):
    """Body for ``POST /api/chats/{id}/messages`` — the streaming endpoint.

    ``content`` is required and must be non-empty (StrictModel strips
    whitespace before validation, so ``min_length=1`` rejects whitespace-only
    bodies as well as the literal empty string).

    ``agent_id`` is the rebuild-domain identifier for the agent the user
    picked. It is validated against the cached agent catalogue (sourced
    from the upstream's ``/v1/models`` list) inside the streaming
    generator; we accept any non-empty string here so the router can
    return a clean 400 with the upstream's vocabulary instead of a 422
    with a generic enum error.

    ``parent_id`` defaults to ``history.currentId`` server-side when
    ``None``; pass an explicit value to branch off an older message.
    """

    content: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    parent_id: str | None = None
    params: ChatParams = ChatParams()


class TitleMessage(StrictModel):
    """One row in :class:`TitleRequest.messages` — the OpenAI chat-completions
    shape we forward to the gateway when generating a sidebar title."""

    role: Literal["user", "assistant", "system"]
    content: str


class TitleRequest(StrictModel):
    """Body for ``POST /api/chats/{id}/title``.

    The frontend posts the linear conversation thread (already flattened
    via the ``currentId → parentId`` walk) and we ask the gateway for a
    ≤6-word title (plan line 543). The endpoint is a "nice to have" the
    auto-title task calls after the first assistant message lands; it is
    explicitly *not* on the streaming hot path.
    """

    messages: list[TitleMessage] = Field(min_length=1)


class TitleResponse(StrictModel):
    """Response for ``POST /api/chats/{id}/title``."""

    title: str
