# M3 — Sharing

## Goal

Add anyone-with-the-link sharing for an individual chat, scoped to authenticated proxy users. The chat owner mints an unguessable share token that captures a point-in-time snapshot of the conversation; any user the OAuth proxy authenticates can open `/s/{token}` and read the snapshot through the M2 message renderer. Revoking a share deletes the row and clears the back-pointer on the original chat — the URL stops working immediately. There is no per-user grant model, no public-internet exposure, no `shared_chat_access` table; possession of the token plus a valid `X-Forwarded-Email` is the entire access check, as locked in `rebuild.md` section 3 and section 9.

## Deliverables

- New SQLAlchemy 2 async model `SharedChat` at `rebuild/backend/app/models/shared_chat.py` plus a thin repository module.
- Alembic revision adding the `shared_chat` table, the FK on `chat.share_id` (which already exists from M2), and the unique index `ix_chat_share_id`. **No `op.add_column` for `chat.share_id`** — M2 already created the column at width `String(43)`; M3 only adds the FK and uniqueness.
- FastAPI router `rebuild/backend/app/routers/shares.py` with `POST /api/chats/{chat_id}/share`, `DELETE /api/chats/{chat_id}/share`, and `GET /api/shared/{token}`.
- Pydantic response schemas for share creation and snapshot retrieval.
- SvelteKit route `rebuild/frontend/src/routes/s/[token]/+page.svelte` rendering the snapshot read-only with the M2 `Message` and `Markdown` components.
- Share button + share modal mounted in the M2 chat header, with state machine: not shared → generate → shared (copy/stop).
- Unit, component, and E2E tests covering the critical path and the auth boundary.
- Visual-regression baseline `share-view.png` captured under [rebuild/frontend/tests/visual-baselines/m2/](../../frontend/tests/visual-baselines/m2/) (Git LFS).
- Updated OpenAPI schema; no env vars introduced.

## Data model

`shared_chat` is a flat snapshot table. The primary key is the share token itself: 32 random bytes encoded with `secrets.token_urlsafe(32)`, which yields an unpadded URL-safe base64 string of length 43. We store it directly as the PK so the URL path segment is the row key — no secondary lookup, no separate token column.

```python
# rebuild/backend/app/models/shared_chat.py
from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, String
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SharedChat(Base):
    __tablename__ = "shared_chat"

    id: Mapped[str] = mapped_column(String(43), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Same JSON shape as `chat.history` (M2). Typed as `dict[str, Any]` for
    # mypy strict; validated through M2's `History` schema at the boundary.
    history: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )  # epoch ms (project-wide convention; see rebuild.md §4)

    __table_args__ = (
        Index("ix_shared_chat_chat_id", "chat_id"),
        Index("ix_shared_chat_user_id", "user_id"),
    )
```

`chat.share_id` was created by M2 (the `0002_m2_chat_folder` revision adds the nullable `String(43)` column on `chat`; see `m2-conversations.md` § Dependencies on other milestones). M3 backfills the **FK** to `shared_chat.id` and the **unique index** `ix_chat_share_id` against that pre-existing column — no `op.add_column` lands in M3's revision (see § Alembic revision below for the precise decomposition). The FK uses `ON DELETE SET NULL` so that deleting a `shared_chat` row never leaves a dangling pointer. The column is set when a share is created and cleared on revoke. Conversely, deleting a `chat` cascades to delete its `shared_chat` rows via the `chat_id` FK.

Notes:

- `id` length 43 matches the unpadded URL-safe base64 length of 32 raw bytes. Storing as `VARCHAR(43)` instead of `VARCHAR(64)` removes any ambiguity and gives MySQL a tight key.
- `history` is the same JSON shape as `chat.history` from M2 (the message tree dict). Storing the full snapshot inline means the share endpoint never has to join back to `chat`, which is exactly what we want for a read-only view of a possibly-mutated original.
- We do NOT store `updated_at`. A share is immutable after creation; re-share is delete + create (see Snapshot semantics).
- We do NOT store `model_id`, `folder_id`, `archived`, or any other chat metadata — only what the renderer needs.

## Alembic revision

- File: `rebuild/backend/alembic/versions/0003_m3_sharing.py`.
- `revision = "0003_m3_sharing"`.
- `down_revision = "0002_m2_chat_folder"` (the M2 revision that introduced `chat` and `folder` and reserved the `chat.share_id` column at `String(43)`).

The revision uses the M0 helper module exclusively, per [rebuild.md § 9 "Robust, idempotent Alembic migrations"](../../../rebuild.md#9-decisions-locked) and [m0-foundations.md § Migration helpers](m0-foundations.md#migration-helpers). Bare `op.create_*` / `op.drop_*` calls are forbidden; the CI grep gate fails the build on a hit.

```python
from app.db.migration_helpers import (
    create_table_if_not_exists, drop_table_if_exists,
    create_index_if_not_exists, drop_index_if_exists,
    create_foreign_key_if_not_exists, drop_constraint_if_exists,
)
```

Operations, in order:

1. `create_table_if_not_exists("shared_chat", ...)` with the columns and the `ix_shared_chat_chat_id` / `ix_shared_chat_user_id` indexes declared inline (so they land atomically with the table on a fresh run, and are skipped wholesale on a re-run).
2. `create_foreign_key_if_not_exists("fk_chat_share_id", "chat", "shared_chat", ["share_id"], ["id"], ondelete="SET NULL")`.
3. `create_index_if_not_exists("ix_chat_share_id", "chat", ["share_id"], unique=True)` — a chat has at most one active share at a time; uniqueness is enforced at the DB layer in addition to the application logic. (The M2 model declares the column without `unique=True`; uniqueness lands in this index, not as a column-level UNIQUE.) The helper inspects existing indexes via `INFORMATION_SCHEMA.STATISTICS` first because MySQL 8.0 has no native `CREATE INDEX IF NOT EXISTS`.

**No `op.add_column("chat", "share_id", ...)` and no `add_column_if_not_exists` either.** M2 already created the column at `String(43)` as part of the `0002_m2_chat_folder` revision; M3 owns only the FK and the unique index.

`downgrade()` reverses in the opposite order, every step idempotent: `drop_index_if_exists("ix_chat_share_id", "chat")`, `drop_constraint_if_exists("fk_chat_share_id", "chat", type_="foreignkey")`, `drop_table_if_exists("shared_chat")`. It does **not** drop `chat.share_id` (M2 owns that column and any cleanup belongs to its downgrade).

`alembic upgrade head`, `alembic downgrade -1`, **and a second `alembic upgrade head` immediately afterwards** must all succeed cleanly. The first two are the standard M0 `test_upgrade_head_is_idempotent` / `test_downgrade_base_is_idempotent` cases parametrised for `0003_m3_sharing`; the third is the same `test_upgrade_head_is_idempotent` extension. A targeted partial-recovery case in `test_partial_upgrade_recovers` pre-creates only `shared_chat` (raw DDL) and asserts the upgrade still adds the FK and the unique index.

## API surface

All endpoints are mounted under the existing API prefix and protected by the M0 `get_user(request) -> User` dependency. There is no separate "verified user" tier in the rebuild — the proxy header is the only gate.

### `POST /api/chats/{chat_id}/share`

- Auth: any authenticated user; the chat must belong to the caller.
- Behaviour:
  - Load chat by `chat_id`. If not found OR `chat.user_id != user.id`, return `404` (we do not leak existence to non-owners).
  - If `chat.share_id` is already set, **delete the old `shared_chat` row and clear the back-pointer first** (token rotation; see Snapshot semantics). This keeps the invariant "at most one active share per chat" and ensures stale links do not survive a re-share.
  - Generate `token = secrets.token_urlsafe(32)`.
  - Insert `SharedChat(id=token, chat_id=chat.id, user_id=user.id, title=chat.title, history=chat.history)`.
  - Set `chat.share_id = token` and commit in the same transaction.
  - Return `ShareCreateResponse`.
- Response (`200 OK`):
  ```json
  {
    "token": "JX8…",
    "url": "/s/JX8…",
    "created_at": 1745701234567
  }
  ```
  `created_at` is a BIGINT epoch-ms integer matching the storage type and the project-wide convention from `rebuild.md` §4. The FE renders it via the same `Date(ms)` helper used everywhere else. The `url` is a relative path — the SvelteKit app constructs the absolute URL from `window.location.origin` so the same response works in dev, staging, and prod without any base-URL config.
- Errors:
  - `401` — missing/invalid `X-Forwarded-Email` (handled by `get_user`).
  - `404` — chat does not exist or does not belong to the caller.

### `DELETE /api/chats/{chat_id}/share`

- Auth: any authenticated user; the chat must belong to the caller.
- Behaviour:
  - Load chat. If not found OR not owned by caller, `404`.
  - If `chat.share_id` is `NULL`, return `204` (idempotent — DELETE on an unshared chat is a no-op success).
  - Delete the `shared_chat` row by token, set `chat.share_id = NULL`, commit.
- Response: `204 No Content`.
- Errors: `401`, `404` as above.

### `GET /api/shared/{token}`

- Auth: any valid `X-Forwarded-Email`. The `get_user` dep is applied at the router level, so an unauthenticated request returns `401` before the handler runs — even if the token is valid. This is asserted in the auth E2E test.
- Behaviour: `SELECT * FROM shared_chat WHERE id = :token`. If not found, `404`.
- Response (`200 OK`):
  ```json
  {
    "token": "JX8…",
    "title": "Refactor draft",
    "history": { "messages": { … }, "currentId": "…" },
    "shared_by": { "name": "Sam Hinton", "email": "sam@…" },
    "created_at": 1745701234567
  }
  ```
  `shared_by` is resolved by joining `shared_chat.user_id → user`. We expose name + email because the proxy already authenticated the caller, so there is no information-leak concern beyond what the proxy already permits.
- Errors:
  - `401` — missing/invalid `X-Forwarded-Email`.
  - `404` — token unknown OR revoked.

Pydantic schemas live in `rebuild/backend/app/schemas/share.py`. All three inherit from the project-wide `StrictModel` (see [m0-foundations.md § Pydantic conventions](m0-foundations.md#pydantic-conventions)) so unknown fields in any future request body are rejected with 422 instead of being silently ignored. The `history` field reuses M2's `History` model rather than `dict[str, Any]` so the share view validates against the same schema as the source chat.

```python
from __future__ import annotations

from pydantic import EmailStr

from app.schemas._base import StrictModel
from app.schemas.history import History


class ShareCreateResponse(StrictModel):
    token: str
    url: str
    created_at: int          # epoch ms — matches shared_chat.created_at storage type


class SharedBy(StrictModel):
    name: str
    email: EmailStr


class SharedChatResponse(StrictModel):
    token: str
    title: str
    history: History
    shared_by: SharedBy
    created_at: int          # epoch ms
```

Both `created_at` fields are BIGINT epoch ms (project-wide convention from `rebuild.md` §4). The router returns `shared_chat.created_at` straight off the row — no `datetime.fromtimestamp` conversion. The frontend renders via the same `Date(ms)` helper used everywhere else.

## Snapshot semantics

The snapshot is captured at share time and is **not live**. Editing the original chat after sharing — adding messages, regenerating, renaming — does not update the share. To publish a fresh version the owner must explicitly re-share, which deletes the old `shared_chat` row, rotates the token, and inserts a new one. Anyone holding the old URL gets a `404`.

Rationale, briefly:

- **Predictability.** A reader following a shared link sees exactly what the owner saw at the moment of sharing. No surprises if the owner later prunes or amends the conversation.
- **Privacy.** If the owner adds something sensitive to the chat after sharing, the live shape would silently expose it. A snapshot makes the disclosure boundary explicit.
- **Simplicity.** A live view would need real-time invalidation, partial-update endpoints, and ordering guarantees against the streaming write path. A snapshot is one row, one query, no coordination.
- **Token rotation on re-share.** Treating re-share as delete + insert means the token is the unit of disclosure: revoking it is a single DELETE, and there is no "update that silently keeps an old URL alive" trap.

This semantics is documented in the share modal copy ("Sharing creates a snapshot at this moment in time. To share later edits, click Stop sharing and Generate a new link.") and in the API docstring.

## Frontend route

The public-from-the-proxy share view lives at `rebuild/frontend/src/routes/s/[token]/+page.svelte`. It:

- Loads via `+page.server.ts` (server-only `load`) that calls `GET /api/shared/{token}` using the SvelteKit `fetch` (which forwards the proxy headers in our deployment). Server `load` is the right primitive here per [sveltekit-best-practises.md § 2.1 / § 2.3](../best-practises/sveltekit-best-practises.md): the response is auth-gated, comes from our own backend, and the share view never needs to refetch on client navigation. A universal `+page.ts` would also re-run on the client during in-app navigation, which is wasted work for a snapshot.
- On `404`, renders a minimal "This share link is no longer active" panel rather than redirecting away — readers should know the link is dead, not be silently bounced to home.
- On `401`, lets the proxy's interception take over; the SvelteKit handler does nothing special.
- Renders the same `Message` and `Markdown` components used by the M2 conversation view, in read-only mode (no edit, no regenerate, no continue, no input box, no model selector, no scroll-to-bottom-on-stream behaviour).
- Header layout:
  - Title (the snapshot's `title`).
  - Subline: "Shared by {shared_by.name} • {created_at, relative}".
  - No clone-chat button in M3. (The legacy fork's "Clone Chat" is intentionally dropped — out of scope below.)
- Body: the message list, max-width matching the conversation view, with `content-visibility: auto` virtualization carried over from M2 for long histories.
- No realtime subscription. The page is a pure read.

The route has no layout dependency on the authenticated app shell; it uses a thin layout (`rebuild/frontend/src/routes/s/+layout.svelte`) that renders only the read-only header and footer chrome. This keeps the share view from accidentally pulling in sidebar, model store, automations stores, or any other M4/M5 surface area.

## Owner UX

- A `Share` button is added to the M2 chat header, immediately to the right of the chat title. It is hidden if the chat has zero messages (sharing an empty chat is a no-op).
- Clicking opens a modal `ShareModal.svelte` with an explicit state machine:
  - **Not shared** (`chat.share_id == null`): the modal shows a short explainer (snapshot semantics) and a primary action `Generate share link`. Clicking POSTs to `/api/chats/{id}/share` and transitions to the next state.
  - **Shared** (`chat.share_id != null`): the modal shows the absolute URL in a read-only input, a `Copy link` button (uses `navigator.clipboard.writeText` with a toast confirmation), a `Stop sharing` destructive action, and a small note that the snapshot was captured at `{created_at}`.
  - **Stop sharing** triggers a confirm dialog ("Stop sharing? The current link will stop working immediately."), then DELETEs and transitions back to `Not shared`. The chat is also re-fetched so `share_id` clears in local state.
- The chat header also surfaces a small `Copy link` icon-button when `chat.share_id` is set, so a return visit doesn't require reopening the modal.
- All three actions (generate, copy, stop) are debounced and disabled while in flight; the modal closes on `Escape` and on backdrop click only when not in flight.

## Tests

### Unit (`rebuild/backend/tests/unit/`)

- `test_token.py` — `secrets.token_urlsafe(32)` returns a 43-char URL-safe string; collisions are vanishingly improbable; we don't reimplement the generator, but we assert the length and charset of the value our handler returns.
- `test_snapshot.py` — given a synthetic `chat` with a known `history` and `title`, the share creation function copies `title` and `history` byte-for-byte into the new `shared_chat` row, and subsequent mutation of the original `chat.history` does not affect the snapshot (verifies we are storing a copy of the dict, not a reference, when SQLAlchemy serialises through JSON).
- `test_rotation.py` — calling `share` twice on the same chat deletes the first row, inserts a second with a different token, and updates `chat.share_id` to the new token.

### Component (Playwright CT, `rebuild/frontend/tests/component/`)

- `share-modal.spec.ts` — drives `ShareModal.svelte` through all three states with MSW handlers for the three endpoints. Asserts: copy button writes to `navigator.clipboard`, stop-sharing requires confirmation, generate-link reflects the returned URL.
- `shared-view.spec.ts` — renders `+page.svelte` against a fixture snapshot covering markdown, code blocks, and math, asserting it uses the same `Message` component as the conversation view (no input box, no regen controls, no model selector). Includes a long-history fixture (200+ messages) to exercise virtualization.

### E2E (Playwright, `rebuild/frontend/tests/e2e/`)

The critical path test, per `rebuild.md` section 8:

- `share-and-read.spec.ts` — context A is the owner (`X-Forwarded-Email: alice@…`). Owner creates a chat, exchanges a couple of messages, opens the share modal, generates a link, and copies it. Context B (`bob@…`) navigates to the URL and reads the snapshot. Asserts content matches.
- `revoke.spec.ts` — same setup; owner clicks Stop sharing; context B refreshes and gets the "no longer active" panel.
- `rotation.spec.ts` — owner generates a link, then generates a second one (re-share). The first URL returns the dead-link panel; the second URL works.

Auth E2E (sits in the same file because it is the security backstop):

- `auth-required.spec.ts` — uses a `BrowserContext` that explicitly omits `X-Forwarded-Email`. Hitting `GET /api/shared/{token}` with a known-valid token returns `401`. The same assertion is repeated against a fully invalid token to confirm `401` precedes `404` in the dependency chain.
- A second case: a request with a header value not on the proxy's allowlist (simulated by configuring the test app with a deny-all allowlist) also returns `401`.

All E2E specs run against the deterministic stack from M0 (app + MySQL + Redis + recorded LLM mock).

## Dependencies on other milestones

- **M2 (hard).** Requires the `chat` table, the `chat.history` JSON column, the conversation page, and the `Message` + `Markdown` components. Without M2 there is nothing to share and no renderer to reuse.
- **M0 (hard).** Requires the `get_user` proxy-header dependency, the Alembic baseline, Vitest/Playwright/MSW wiring, and the deterministic E2E stack.
- **No dependency on M4, M5, M6.** Channels, automations, and hardening are independent.

## Acceptance criteria

- [ ] `alembic upgrade head` creates the `shared_chat` table and adds the `fk_chat_share_id` foreign key + `ix_chat_share_id` unique index against the M2-owned `chat.share_id` column (no `op.add_column` against `chat` lands in M3; the column was created by `0002_m2_chat_folder`); `alembic downgrade -1` cleanly reverses (drops the FK, the unique index, and the `shared_chat` table — leaves `chat.share_id` intact for M2's downgrade to handle). Re-running `alembic upgrade head` immediately after `head`, and re-running `alembic downgrade base` after `base`, are both no-ops (covered by the M0 idempotency tests parametrised over the M3 revision).
- [ ] `test_partial_upgrade_recovers` includes an M3 case: pre-create `shared_chat` only (raw DDL), then `alembic upgrade head` produces the `fk_chat_share_id` foreign key and the `ix_chat_share_id` unique index without operator intervention.
- [ ] `POST /api/chats/{id}/share` by the owner returns a 43-char token and a relative URL; the response token equals the new `chat.share_id`.
- [ ] `POST /api/chats/{id}/share` by a non-owner returns `404` (not `403` — we do not leak existence).
- [ ] A second `POST` on the same chat rotates the token; the previous token returns `404`.
- [ ] `DELETE /api/chats/{id}/share` clears `chat.share_id` and the shared row; `GET /api/shared/{old_token}` returns `404` thereafter; a second `DELETE` on the same chat is a `204` no-op.
- [ ] `GET /api/shared/{token}` with a valid `X-Forwarded-Email` returns the snapshot regardless of whether the caller is the owner.
- [ ] `GET /api/shared/{token}` with no `X-Forwarded-Email` returns `401` even when the token is valid.
- [ ] `/s/{token}` renders the snapshot using the M2 `Message` and `Markdown` components, with no input box, no regen, no model selector.
- [ ] The share modal walks through `not shared → shared → not shared` states with copy and stop-sharing actions wired up.
- [ ] All unit, component, and E2E tests listed above are present and green in CI.
- [ ] OpenAPI schema includes the three endpoints with correct request/response models.
- [ ] `tests/visual-baselines/m2/share-view.png` captured against the deterministic snapshot fixture (committed via Git LFS); diff tolerance configured per `rebuild.md` §8 Layer 4.

## Out of scope

- No `shared_chat_access` table, per-user grants, group grants, or role-based visibility.
- No share-link expiry, view counts, or analytics.
- No public-internet exposure — every share request still goes through the OAuth proxy and requires `X-Forwarded-Email`.
- No live shares — re-sharing is the only way to publish updated content.
- No "Clone Chat" button on the shared view (legacy feature dropped).
- No password-protected shares, no email-of-recipient restrictions.
- No bulk share operations, no list-of-my-shares page (a chat with `share_id != null` is self-evident in the sidebar; a dedicated index is not justified at this scope).
- No share-by-channel-post integration — that is a future M4 enhancement, not part of M3.

## Open questions

None blocking. The plan in `rebuild.md` is unambiguous on access model, snapshot semantics, schema, and route shape; nothing here required a deviation. One implementation-time check to confirm during M3 itself: that `asyncmy` correctly serialises `dict` values into MySQL `JSON` for the `history` column on insert (the M2 plan establishes this for `chat.history`, and M3 reuses the same path, so this should be a non-issue).
