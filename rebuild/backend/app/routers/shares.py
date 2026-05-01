"""M3 sharing surface — anyone-with-the-link snapshot reads.

Three endpoints, all on a single ``/api`` ``APIRouter`` (one prefix per
domain per FastAPI-best-practises.md § A.1):

* ``POST   /api/chats/{chat_id}/share`` — owner-only. Mints (or
  rotates) the share token, snapshots ``chat.title`` + ``chat.history``
  into a fresh ``shared_chat`` row, and returns the new token plus the
  relative ``/s/{token}`` URL.
* ``DELETE /api/chats/{chat_id}/share`` — owner-only. Revokes the
  active share by deleting the ``shared_chat`` row and clearing
  ``chat.share_id``. Idempotent: a second DELETE on the same chat
  returns 204 too (the plan is explicit on this — see § API surface).
* ``GET    /api/shared/{token}`` — any authenticated proxy user (the
  ``CurrentUser`` dep is the auth gate; an unauthenticated request
  returns 401 *before* the handler runs, which the auth E2E test
  asserts). A valid ``X-Forwarded-Email`` may belong to any user;
  ownership is irrelevant once the token is known.

Locked semantics worth restating at the router level:

* **Token rotation on re-share.** ``POST`` on a chat that already has
  a ``share_id`` deletes the existing ``shared_chat`` row first and
  inserts a new one with a fresh token (``m3-sharing.md`` § Snapshot
  semantics). Every existing URL stops working immediately. The plan
  bans update-in-place so the token is the unit of disclosure: revoke
  is one DELETE, no "update that silently keeps an old URL alive"
  trap. The rotate-delete, the new insert, and the back-pointer write
  all land in **one transaction** — without that atomicity a crash
  mid-sequence could leave ``chat.share_id`` pointing at a deleted
  ``shared_chat.id`` (which the M3-owned ``fk_chat_share_id ON DELETE
  SET NULL`` would resolve on next read, but is a messier recovery
  than just keeping the three writes inside one ``commit``).

* **404, never 403, on the owner-only paths.** ``_load_owned_chat``
  already enforces this — a chat that does not exist and a chat the
  caller doesn't own both surface as 404, so we never leak existence
  to a non-owner (FastAPI-best-practises.md § A.9; mirrors M2's
  pattern in ``app/routers/chats.py``).

* **404, never 410, on the read path.** ``GET /api/shared/{token}``
  returns 404 for both "this token never existed" and "this token was
  revoked" — the plan locks 404 over 410 so the response is identical
  in both cases and an attacker can't distinguish "wrong token" from
  "revoked token" by status code (``m3-sharing.md`` § API surface).

* **Token shape.** ``secrets.token_urlsafe(32)`` returns a 43-char
  unpadded URL-safe base64 string — that is the share-token shape
  M3 uses, and it is **deliberately not** ``app.core.ids.new_id()``
  (which is UUIDv7, ``VARCHAR(36)``, the wrong width for
  ``shared_chat.id`` and the wrong shape for an unguessable URL
  segment). The ruff-gated ban on ``uuid.uuid4`` does not apply to
  ``secrets.token_urlsafe``; this comment is here so a future agent
  doesn't accidentally "fix" it the wrong way.

References:

* ``rebuild/docs/plans/m3-sharing.md`` — full plan, with § API surface
  and § Snapshot semantics being the binding sections for this file.
* ``rebuild/docs/best-practises/FastAPI-best-practises.md`` § A.1
  (single ``/api`` prefix per domain), § A.5 / § B.4 (``Annotated``
  dependency aliases from ``app.core.deps``), § A.6 (errors via
  ``HTTPException``; central handler in ``app/core/errors.py`` does
  the mapping), § A.9 (404 over 403 for non-owner paths).
* ``app/routers/chats.py`` — the canonical style guide for this
  codebase's routers; this module mirrors its shape (no bare
  ``Depends``; ``_load_owned_chat`` is imported, not re-implemented;
  explicit ``Response(status_code=204)`` for DELETE).
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.core.time import now_ms
from app.models.shared_chat import SharedChat
from app.models.user import User
from app.routers.chats import _load_owned_chat
from app.schemas.history import History
from app.schemas.share import ShareCreateResponse, SharedBy, SharedChatResponse

router = APIRouter(prefix="/api", tags=["shares"])

# ``secrets.token_urlsafe(32)`` → 43-char string; matches ``shared_chat.id`` width.
_TOKEN_BYTES = 32


@router.post("/chats/{chat_id}/share", response_model=ShareCreateResponse)
async def create_share(
    chat_id: str,
    user: CurrentUser,
    db: DbSession,
) -> ShareCreateResponse:
    """Create or rotate the share for an owned chat.

    Behaviour, exactly as locked in ``m3-sharing.md`` § API surface:

    1. Load the chat by ``(chat_id, user_id)``; 404 if missing or not
       owned (no existence leak — same shape M2 establishes via
       ``_load_owned_chat``).
    2. If ``chat.share_id`` is already set, delete the existing
       ``shared_chat`` row by primary key and clear the back-pointer
       *first*. Token rotation: every URL pointing at the old token
       stops working immediately. Delete-then-insert is locked by the
       plan; do not rewrite as an in-place update.
    3. Generate a new 43-char URL-safe base64 token via
       ``secrets.token_urlsafe(32)``.
    4. Insert a fresh ``shared_chat`` row with the snapshot copy of
       ``chat.title`` and ``chat.history`` and the new token as PK.
    5. Set ``chat.share_id = token`` and bump ``chat.updated_at`` —
       the plan's snapshot-semantics section frames sharing as a
       user-visible action, so the chat's mtime should reflect it
       (sidebar ordering reflects the change).
    6. ``await db.commit()`` once — the rotate-delete, the insert,
       and the back-pointer update must be atomic.

    The response carries the new token, the relative URL
    (``/s/{token}`` — FE owns absolute URL construction), and the
    snapshot ``created_at`` straight off the new row.
    """
    chat = await _load_owned_chat(db, chat_id=chat_id, user_id=user.id)

    # Rotate-delete: a re-share invalidates every prior URL. We delete
    # the existing snapshot row by PK rather than relying on the FK
    # cascade because the order matters — the new insert must see a
    # NULL ``chat.share_id`` (the unique index on it would otherwise
    # collide with itself across the two consecutive inserts).
    if chat.share_id is not None:
        existing = await db.get(SharedChat, chat.share_id)
        if existing is not None:
            await db.delete(existing)
        chat.share_id = None
        await db.flush()

    token = secrets.token_urlsafe(_TOKEN_BYTES)
    now = now_ms()

    snapshot = SharedChat(
        id=token,
        chat_id=chat.id,
        user_id=user.id,
        title=chat.title,
        history=chat.history,
        created_at=now,
    )
    db.add(snapshot)
    # Flush the snapshot insert before the back-pointer UPDATE — the FK
    # `fk_chat_share_id` on chat.share_id is migration-only, so SQLAlchemy can't
    # auto-order the two statements.
    await db.flush()

    chat.share_id = token
    chat.updated_at = now

    await db.commit()

    return ShareCreateResponse(token=token, url=f"/s/{token}", created_at=now)


@router.delete("/chats/{chat_id}/share", status_code=status.HTTP_204_NO_CONTENT)
async def delete_share(
    chat_id: str,
    user: CurrentUser,
    db: DbSession,
) -> Response:
    """Revoke the active share on an owned chat.

    Behaviour:

    * 404 if the chat doesn't exist or isn't owned by the caller.
    * 204 if the chat exists, is owned, and has no active share —
      DELETE is **idempotent** here; the plan's § API surface is
      explicit that a double-DELETE on the same chat returns 204
      (not 404) so the FE can fire-and-forget without tracking the
      latest server-side state.
    * Otherwise: delete the ``shared_chat`` row by PK, clear
      ``chat.share_id``, bump ``chat.updated_at``, commit, return 204.
    """
    chat = await _load_owned_chat(db, chat_id=chat_id, user_id=user.id)

    if chat.share_id is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    existing = await db.get(SharedChat, chat.share_id)
    if existing is not None:
        await db.delete(existing)
    chat.share_id = None
    chat.updated_at = now_ms()
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/shared/{token}", response_model=SharedChatResponse)
async def get_shared(
    token: str,
    user: CurrentUser,
    db: DbSession,
) -> SharedChatResponse:
    """Read a snapshot by token. Auth is the proxy header; ownership is
    irrelevant.

    The ``CurrentUser`` dependency is the auth gate — an unauthenticated
    request never reaches this handler (the proxy-header check raises
    401 inside ``get_user``). A valid ``X-Forwarded-Email`` may belong
    to any user; the plan deliberately does not require the caller to
    be the original sharer.

    Behaviour:

    * 404 if the token is unknown OR was revoked (the plan locks the
      same status for both so an attacker can't tell them apart).
    * Resolve the ``shared_by`` projection via a lightweight
      ``select(User.name, User.email)`` rather than ``db.get(User, ...)``
      so we don't materialise an entire ``User`` instance just to read
      two columns. If the row is missing (shouldn't happen given the
      ``user_id`` FK + cascade, but defence-in-depth) we still return
      404 to keep the non-leak guarantee.
    * Validate ``shared.history`` through M2's :class:`History` model
      — the plan locks "the share view validates against the same
      schema as the source chat". A malformed history on the stored
      row surfaces as a Pydantic ``ValidationError`` and propagates to
      the central exception handler, which 500s it (correct: that
      represents server-side corruption, not a client error).

    The ``user`` parameter is held only as the auth gate; we deliberately
    don't read it inside the handler (its identity doesn't influence the
    response). The dependency injection is what enforces 401 → 404
    ordering — the handler is unreachable without authentication.
    """
    # ``user`` is held only by the dep injection above as the auth gate;
    # we intentionally do not branch on the caller's identity (any
    # authenticated proxy user may read the snapshot).
    del user

    shared = await db.get(SharedChat, token)
    if shared is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="share not found")

    sharer = (
        await db.execute(select(User.name, User.email).where(User.id == shared.user_id))
    ).one_or_none()
    if sharer is None:
        # The FK + ON DELETE CASCADE makes this unreachable in practice;
        # we still return 404 (not 500) to honour the non-leak rule.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="share not found")

    return SharedChatResponse(
        token=shared.id,
        title=shared.title,
        history=History.model_validate(shared.history),
        shared_by=SharedBy(name=sharer.name, email=sharer.email),
        created_at=shared.created_at,
    )


__all__ = ["router"]
