"""Pydantic representation of the ``chat.history`` JSON column.

The column itself is stored as raw MySQL JSON (see ``app.models.chat.Chat``);
:class:`History` is the validation/round-trip shape we apply at every read
and write boundary, never the column type. The shape mirrors the legacy
fork's tree algebra and is locked in
``rebuild/docs/plans/m2-conversations.md`` § JSON shape of ``chat.history``.

Field semantics (locked):

* ``messages`` is a dict keyed by message id (O(1) updates during streaming).
* ``parentId`` / ``childrenIds`` form the message tree; an assistant
  message's parent is always the user message it answers; branching
  (regenerate, edit-and-resend) appends a sibling under the same parent.
* ``currentId`` points at the leaf of the active branch; the linear thread
  is rebuilt by walking ``parentId`` from ``currentId`` to the root.
* ``done`` is ``False`` only while a stream is in flight.
* ``cancelled`` is ``True`` if the user (or the M2 timeout / cancel path)
  aborted mid-stream; it is paired with ``done=True`` on persistence.
* ``error`` is set on provider failure; paired with ``done=True``.
* ``usage`` is the gateway's final ``usage`` chunk; ``None`` if the gateway
  didn't return one.

No ``files`` / ``sources`` / ``embeds`` / ``statusHistory`` / ``annotation``
/ ``mentions`` / ``tasks`` fields — those belong to scrapped legacy
features. :class:`StrictModel`'s ``extra="forbid"`` rejects them at
validation time so a stray legacy payload can't silently round-trip.
"""

from __future__ import annotations

from typing import Any, Literal

from app.schemas._base import StrictModel


class HistoryMessage(StrictModel):
    id: str
    parentId: str | None = None
    childrenIds: list[str] = []
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: int
    agent_id: str | None = None
    agentName: str | None = None
    done: bool = True
    error: dict[str, Any] | None = None
    cancelled: bool = False
    usage: dict[str, Any] | None = None


class History(StrictModel):
    messages: dict[str, HistoryMessage] = {}
    currentId: str | None = None
