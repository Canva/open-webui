"""Request / response schemas for the M3 sharing surface.

The router handlers live in ``app/routers/shares.py``; this module owns
only the wire shapes. All three response models inherit from
:class:`StrictModel`, so the ``extra="forbid"`` rule applies — any
unknown field on a future request body becomes a 422 instead of being
silently ignored. There are no request bodies on the M3 share surface
(``POST`` / ``DELETE`` take no body, ``GET`` reads the token from the
path) but the ``StrictModel`` base is still the project-wide contract
for response shapes too.

Locked references:

* ``rebuild/docs/plans/m3-sharing.md`` § API surface — the three
  endpoint shapes (``ShareCreateResponse`` for POST, no body for DELETE,
  ``SharedChatResponse`` for GET).
* ``rebuild/docs/plans/m3-sharing.md`` § Pydantic schemas — the exact
  field set, including ``shared_by: SharedBy`` rather than two flat
  ``shared_by_name`` / ``shared_by_email`` strings (groups the columns
  the FE renders together; mirrors the resolver join shape).
* ``rebuild.md`` §4 — every timestamp is a BIGINT epoch-millisecond
  integer; ``created_at`` here is ``shared_chat.created_at`` straight
  off the row, with **no** ``datetime.fromtimestamp`` conversion. The
  router returns the integer untouched and the FE formats with the
  same ``new Date(ms)`` helper used everywhere else.
* ``rebuild/docs/plans/m3-sharing.md`` § Frontend route — ``url`` is a
  *relative* path (``/s/{token}``); the SvelteKit app constructs the
  absolute URL from ``window.location.origin`` so the same response
  works in dev / staging / prod without a base-URL config knob.
"""

from __future__ import annotations

from pydantic import EmailStr

from app.schemas._base import StrictModel
from app.schemas.history import History


class ShareCreateResponse(StrictModel):
    """Response for ``POST /api/chats/{chat_id}/share``.

    ``token`` is the 43-char unpadded URL-safe base64 string returned by
    ``secrets.token_urlsafe(32)`` and is also the new ``chat.share_id``.
    ``url`` is a relative path (``/s/{token}``) — the FE owns absolute
    URL construction. ``created_at`` is a BIGINT epoch-ms integer
    matching ``shared_chat.created_at`` on the row (no ``datetime``
    conversion; project-wide convention per ``rebuild.md`` §4).
    """

    token: str
    url: str
    created_at: int


class SharedBy(StrictModel):
    """The original sharer's identity, projected from ``user``.

    Surfaced on ``GET /api/shared/{token}`` so the read-only view can
    render "Shared by {name}". Email is included because the proxy has
    already authenticated the caller (any valid ``X-Forwarded-Email``)
    so there is no information-leak concern beyond what the proxy
    itself permits — see ``m3-sharing.md`` § API surface for the locked
    rationale.
    """

    name: str
    email: EmailStr


class SharedChatResponse(StrictModel):
    """Response for ``GET /api/shared/{token}``.

    ``history`` is validated through M2's :class:`History` model — the
    plan locks "the share view validates against the same schema as the
    source chat" so a malformed snapshot is caught at the boundary
    rather than silently rendering garbage. ``created_at`` is the
    snapshot capture time (epoch ms).
    """

    token: str
    title: str
    history: History
    shared_by: SharedBy
    created_at: int
