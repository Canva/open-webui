"""Reusable assistant-message writer.

Two callers in the rebuild:

* ``app/services/chat_stream.py`` (Phase 2c, realtime-engineer) — final
  persistence on normal completion / cancellation / error.
* ``app/services/automation_executor.py`` (M5) — chat-target writes from
  the automation pipeline.

The public surface is deliberately narrow (one function +
``HistoryTooLargeError``) so we can keep both call sites consistent
without a deeper service layer (`rebuild/docs/best-practises/FastAPI-best-practises.md`
§ B.5).

Locked references:

* ``rebuild/docs/plans/m2-conversations.md`` § Deliverables
  (``append_assistant_message`` signature on line 17).
* ``rebuild/docs/plans/m2-conversations.md`` § History-size enforcement
  (the ``_enforce_history_cap`` helper + 413 mapping).
"""

from __future__ import annotations

import json
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import MAX_CHAT_HISTORY_BYTES
from app.core.ids import new_id
from app.core.time import now_ms
from app.models.chat import Chat
from app.schemas.history import History, HistoryMessage


class HistoryTooLargeError(Exception):
    """Raised when a ``chat.history`` JSON payload would exceed
    :data:`app.core.constants.MAX_CHAT_HISTORY_BYTES` after a write.

    Mapped centrally to ``HTTPException(413, ...)`` for request-side paths
    by :func:`app.core.errors.register_exception_handlers`. The streaming
    generator (Phase 2c) catches it inside its persist loop and emits a
    terminal SSE ``error`` frame instead.
    """

    def __init__(self, *, size: int, cap: int) -> None:
        super().__init__(f"chat.history is {size} bytes, cap is {cap}")
        self.size = size
        self.cap = cap


def _enforce_history_cap(history: dict[str, Any]) -> None:
    encoded = json.dumps(history, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_CHAT_HISTORY_BYTES:
        raise HistoryTooLargeError(size=len(encoded), cap=MAX_CHAT_HISTORY_BYTES)


def _status_flags(
    status: Literal["complete", "cancelled", "error"],
) -> tuple[bool, bool, dict[str, Any] | None]:
    """Translate a writer-level ``status`` into the
    ``(done, cancelled, error)`` triple stored on the
    :class:`HistoryMessage`.

    The plan locks ``done=True`` for every terminal status (the M6 zombie
    sweeper distinguishes "interrupted mid-stream" from "interrupted post-
    persist" via ``done`` alone). ``status="error"`` carries the literal
    ``{"message": "execution error"}`` payload — the M2 plan does not
    pin a specific schema for the error dict; we choose the legacy fork's
    short-form so the M5 automation executor's ``error`` envelope reads
    consistently with chat-stream-side error frames.
    """
    if status == "complete":
        return True, False, None
    if status == "cancelled":
        return True, True, None
    return True, False, {"message": "execution error"}


async def append_assistant_message(
    session: AsyncSession,
    *,
    chat_id: str,
    parent_message_id: str | None,
    agent_id: str,
    content: str,
    status: Literal["complete", "cancelled", "error"] = "complete",
) -> str:
    """Append a new assistant :class:`HistoryMessage` to ``chat.history``,
    update ``currentId`` and ``updated_at``, enforce the history-size cap,
    and commit.

    Returns the new message id.

    The chat row is loaded with ``SELECT ... FOR UPDATE`` so concurrent
    appends (e.g. an in-flight stream colliding with an M5 automation
    chat-target write) serialise on the row lock instead of racing on the
    JSON merge. The lock is released at commit.
    """
    result = await session.execute(select(Chat).where(Chat.id == chat_id).with_for_update())
    chat = result.scalar_one_or_none()
    if chat is None:
        raise LookupError(f"chat {chat_id} not found")

    history = History.model_validate(chat.history)
    new_message_id = new_id()
    done, cancelled, error = _status_flags(status)

    message = HistoryMessage(
        id=new_message_id,
        parentId=parent_message_id,
        childrenIds=[],
        role="assistant",
        content=content,
        timestamp=now_ms(),
        agent_id=agent_id,
        agentName=agent_id,
        done=done,
        cancelled=cancelled,
        error=error,
    )
    history.messages[new_message_id] = message
    if parent_message_id is not None and parent_message_id in history.messages:
        history.messages[parent_message_id].childrenIds.append(new_message_id)
    history.currentId = new_message_id

    payload = history.model_dump()
    _enforce_history_cap(payload)

    chat.history = payload
    chat.updated_at = now_ms()
    await session.commit()

    return new_message_id
