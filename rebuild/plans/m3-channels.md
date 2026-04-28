# M3 — Channels (full Slack-shape)

## Goal

Build a self-contained, multi-instance-safe channels feature inside `rebuild/`
that delivers the full Slack-shape interaction model — channels with members,
threaded messages, reactions, pinned messages, typing presence, read receipts,
incoming + outgoing webhooks, multipart file uploads stored as MySQL
`MEDIUMBLOB` (5 MiB cap), and `@model` auto-reply that streams an assistant
answer back into the same thread via the shared `OpenAICompatibleProvider`
introduced in M1. Realtime is `python-socketio` with the Redis async manager so
the FastAPI process can scale horizontally without sticky sessions, and the
ported frontend reuses the legacy `src/lib/components/channel/*` shell with
every tools/skills/notes/RAG import deleted. M3 is the largest milestone; this
plan is biased toward precision over brevity.

## Deliverables

- `rebuild/backend/app/models/channels.py` — SQLAlchemy 2 async ORM models for
  every channel-related table listed in section 3.
- `rebuild/backend/app/models/files.py` — `file` + `file_blob` ORM models.
- `rebuild/backend/alembic/versions/0004_m3_channels.py` — single revision
  (`revision = "0004_m3_channels"`, `down_revision = "0003_m2_sharing"`)
  creating all M3 tables, charset/collation inherited from the M0 baseline.
- `rebuild/backend/app/storage/file_store.py` — `FileStore` Protocol +
  `MysqlFileStore` implementation.
- `rebuild/backend/app/realtime/sio.py` — socket.io server with Redis manager,
  connect-time auth from `X-Forwarded-Email`, room joining, and the event
  protocol declared in section 6.
- `rebuild/backend/app/realtime/events.py` — typed event payload models and a
  **thin** `emit_*` helper layer used by the REST routers. Hard cap: ≤80 LOC,
  zero business logic, every helper is one `await sio.emit(room, dto)` plus
  optional payload coercion. If a helper grows past that, the new logic
  belongs in the relevant service file, not in `events.py`.
- `rebuild/backend/app/services/channels/` — service layer, **three files
  only**:
  - `messages.py` — `create_user_message`, `create_bot_message`,
    `create_webhook_message`. Owns the multi-table invariant
    (`channel_message` insert + `channel.last_message_at` denorm + realtime
    `message:create` emit + auto-reply trigger). Three callers: REST POST,
    M4 automation executor, webhook ingress.
  - `mentions.py` — `MENTION_RE` + `classify_mentions(text, *, member_lookup,
    model_lookup) -> list[Mention]`. Pure functions; reused by the FE
    `mention-parser` test fixtures so BE and FE stay in lockstep.
  - `auto_reply.py` — `@model` mention dispatcher, semaphore-bounded
    background task pool with latest-wins cancellation. Lives under
    `services/channels/` (not at the top of `services/`) because it is 100%
    channel-coupled and shares per-channel state with `messages.py`.

  Channel/member/reaction/pin/webhook/file CRUD does **not** get its own
  service file — those endpoints are 5–15 LOC each and live directly in the
  routers (see § Routers and dependencies). The promotion test is in
  [FastAPI-best-practises.md §A.1](FastAPI-best-practises.md): a service file
  is justified only at ≥3 callers, ≥80 LOC of orchestration, OR a multi-table
  transactional invariant. CRUD endpoints fail all three; the service file
  would be a wrapper around a single SELECT/INSERT/UPDATE.
- `rebuild/backend/app/routers/deps.py` — channel-scoped FastAPI dependencies
  (`get_channel`, `get_membership`, `require_owner`, `require_owner_or_admin`)
  and their `Annotated` aliases (`ChannelDep`, `MembershipDep`, `RequireOwner`,
  `RequireOwnerOrAdmin`). Replaces the per-handler `if user.role != "owner": raise 403`
  boilerplate; permission checks become declarative at the route signature.
- `rebuild/backend/app/routers/{channels,channel_messages,channel_members,channel_webhooks,files}.py`
  — REST surface from section 7. CRUD bodies are inlined; service helpers from
  `services/channels/messages.py` are imported only by the message-creation
  endpoints (and by the M4 automation executor).
- `rebuild/frontend/src/routes/(app)/channels/{+layout.svelte, +page.svelte,
  [id]/+page.svelte, [id]/threads/[mid]/+page.svelte}`.
- `rebuild/frontend/src/lib/components/channel/*` — ported components listed in
  section 9, with dead imports removed.
- `rebuild/frontend/src/lib/stores/realtime.svelte.ts`, `channels.svelte.ts`,
  `messages.svelte.ts`, `typing.svelte.ts`, `presence.svelte.ts`,
  `reads.svelte.ts` — one class per store, instances provided via `setContext`
  in `(app)/channels/+layout.svelte`. See
  [m0-foundations.md § Frontend conventions (cross-cutting)](m0-foundations.md#frontend-conventions-cross-cutting)
  for the canonical pattern; do not redeclare it here. Module-level `$state` is
  banned (per-user data → SSR leak), and reactive collections use `SvelteMap` /
  `SvelteSet` from `svelte/reactivity` rather than native `Map` / `Set`
  (mutations on the latter don't notify subscribers — see
  [svelte-best-practises.md § 9](svelte-best-practises.md)).
- `rebuild/backend/tests/{unit,integration,e2e}/channels/*` — pytest + Playwright
  suites covering the regression paths in section 11.
- `rebuild/backend/scripts/bench_channels.py` — async load generator used to
  validate the 200ms p95 fan-out target in section 10.

## Data model

All identifiers are 36-char **UUIDv7** (RFC 9562) strings stored as `String(36)` (= `VARString(36)`) — locked project-wide by `rebuild.md` §9 and `database-best-practises.md` §B.2 — generated app-side via `from app.core.ids import new_id` (the M0 helper), never `uuid.uuid4()`. UUIDv7's leading 48-bit ms timestamp gives near-monotonic InnoDB B-tree insertion locality, which keeps the hot end of the wide composite indexes on `channel_message` (and the `(channel_id, created_at)` lookups that the realtime fan-out depends on) cacheable under load. Hex-digest hashes (e.g. `channel_webhook.token_hash` SHA-256) are still fixed-width `CHAR(64)` because the value is always exactly 64 ASCII chars and the equality lookup wants bit-for-bit comparison. Timestamps are
`BIGINT` epoch **milliseconds** (project-wide convention from `rebuild.md` §4 and
M1 §Data model). Helper: `from app.core.time import now_ms` returns
`time.time_ns() // 1_000_000`. Charset `utf8mb4`, collation
`utf8mb4_0900_ai_ci`, engine `InnoDB`. Foreign keys are declared on every join
so MySQL enforces referential integrity. JSON columns are MySQL 8.0 native
`JSON` (not `LONGTEXT`).

### `channel`

```python
class Channel(Base):
    __tablename__ = "channel"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # ondelete=RESTRICT (not CASCADE / SET NULL) is deliberate. The creator
    # leaving the platform must not silently nuke a populated channel — the
    # admin tooling (`make scripts/transfer-channel-owner.py`) requires the
    # operator to reassign `user_id` to another member before the user can be
    # hard-deleted. SET NULL is rejected because the column is non-nullable
    # (every channel must have a designated owner for moderation actions and
    # for the "founded by" UI label). CASCADE is rejected because deleting a
    # user (e.g. account closure) must not silently take 1000 messages and 50
    # members of someone else's data with them. The result is that
    # `DELETE FROM user WHERE id=...` fails fast with a 1451 if any channel
    # still names the user — which is exactly the safety net we want.
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    archived_at: Mapped[int | None] = mapped_column(BigInteger)
    # Denormalised "most recent message" timestamp, written by
    # `app.services.channels.messages.create_message` /
    # `create_bot_message` / `create_webhook_message` inside the same
    # transaction that inserts the row (see § Service layer). It powers the
    # sidebar's "sort by recency" ordering and the GET /api/channels feed
    # without a per-channel `MAX(created_at)` subquery against
    # `channel_message`. NULL means "no messages yet" — the seed channel and
    # any channel created via POST /api/channels start here. The
    # `ix_channel_recency` index below makes the unread-channel feed lookup
    # an index-only range scan.
    last_message_at: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint("name", name="uq_channel_name"),
        Index("ix_channel_archived", "is_archived"),
        Index("ix_channel_recency", "is_archived", "last_message_at"),
    )
```

Channel name is unique and case-insensitive thanks to `utf8mb4_0900_ai_ci`.
Soft-delete via `is_archived`; hard delete cascades to all child rows. We
deliberately drop the legacy `type` column — there are no DMs and no group DMs.

### `channel_member`

```python
class ChannelMember(Base):
    __tablename__ = "channel_member"

    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channel.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(
        Enum("owner", "admin", "member", name="channel_member_role"),
        nullable=False, default="member",
    )
    last_read_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    joined_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_channel_member_user", "user_id"),
        Index("ix_channel_member_channel_pinned", "user_id", "pinned"),
    )
```

`(channel_id, user_id)` is the PK so duplicate joins are impossible.
`ix_channel_member_user` accelerates "list channels for a user" (the socket.io
connect path). `ix_channel_member_channel_pinned` accelerates the sidebar
"pinned channels" view.

### `channel_message`

```python
class ChannelMessage(Base):
    __tablename__ = "channel_message"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channel.id", ondelete="CASCADE"), nullable=False
    )

    # Exactly one of (user_id, bot_id, webhook_id) is non-null. Enforced by
    # the CHECK constraint below and re-validated at the service layer.
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user.id", ondelete="SET NULL")
    )
    bot_id: Mapped[str | None] = mapped_column(String(128))
    webhook_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("channel_webhook.id", ondelete="SET NULL")
    )

    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("channel_message.id", ondelete="CASCADE")
    )

    # Closed shape — see "channel_message.content JSON shape" below. Validated
    # through a `ChannelMessageContent` StrictModel at every write boundary.
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pinned_at: Mapped[int | None] = mapped_column(BigInteger)
    pinned_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user.id", ondelete="SET NULL")
    )

    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_channel_message_feed", "channel_id", "created_at"),
        Index("ix_channel_message_thread", "parent_id", "created_at"),
        Index("ix_channel_message_pinned", "channel_id", "is_pinned"),
        CheckConstraint(
            "((user_id IS NOT NULL) + (bot_id IS NOT NULL) + (webhook_id IS NOT NULL)) = 1",
            name="ck_channel_message_one_author",
        ),
    )
```

Notes:

- `ix_channel_message_feed` is the hot path: top-level feed pagination is
  `WHERE channel_id = ? AND parent_id IS NULL ORDER BY created_at DESC LIMIT ?`.
  MySQL uses the composite index for the `WHERE channel_id` + ordering.
- `ix_channel_message_thread` powers `WHERE parent_id = ? ORDER BY created_at`.
- `ix_channel_message_pinned` is partial-index-flavoured via `(channel_id,
  is_pinned)` so the pinned drawer is one index seek.
- `parent_id` references `channel_message.id` with `ON DELETE CASCADE`, so
  deleting a thread root tombstones the entire thread atomically.
- Author attribution: `bot_id` is **not** a FK because models are discovered
  dynamically from the gateway's `/v1/models` endpoint and there is no models
  table. The string is the upstream model id (e.g. `gpt-4o-mini`). We keep
  webhook attribution in its own column rather than the legacy `meta.webhook`
  blob so the FE can render it with a single SQL fetch.

#### `channel_message.content` JSON shape

```json
{
  "text": "Hi @gpt-4o-mini, please summarise the design doc.",
  "mentions": [
    { "kind": "model", "id": "gpt-4o-mini", "offset": 3, "length": 13 }
  ],
  "attachments": [
    { "file_id": "<uuid>", "name": "diagram.png", "mime": "image/png", "size": 412034 }
  ],
  "embeds": [
    { "kind": "link", "url": "https://...", "title": "...", "description": "...", "image_url": "..." }
  ],
  "edited": false,
  "automation_id": null,
  "automation_owner_name": null
}
```

- `text`: source text exactly as the author submitted; the FE does the markdown
  rendering. Only `@<token>` mentions are recognised by the server-side parser
  (see Mentions section); other syntaxes such as `<#channel>` or `<@user>` are
  not part of v1 and are treated as plain text.
- `mentions`: pre-resolved offsets to keep the server-side mention parser
  authoritative (used by `@model` dispatcher and unread-counter logic). `kind`
  is `"model"` (matched against the gateway model list) or `"user"` (matched
  against `channel_member`); v1 does not emit any other kinds.
- `attachments`: parallel array to `channel_file` rows for fast render without a
  join; the join row is the source of truth and is always written first.
- `embeds`: optional metadata — out of scope for v1 (no link unfurler) but the
  shape is reserved so we don't break the migration later.
- `edited`: `true` whenever `updated_at != created_at`. Single boolean —
  per-edit history is explicitly out of scope.
- `automation_id` (optional, default `null`): set only when the message is
  authored by the M4 automation executor against a channel target. Holds the
  triggering `automation.id`. Used by the FE to render an "automation" pill on
  the message and by audit queries.
- `automation_owner_name` (optional, default `null`): denormalised display name
  of the automation owner (matches `user.name` at insert time) so the FE can
  render the pill without an extra join. Both fields are nullable; the strict
  Pydantic validator (see § Service layer) accepts them as optional fields and
  rejects any other unknown keys.

### `channel_message_reaction`

```python
class ChannelMessageReaction(Base):
    __tablename__ = "channel_message_reaction"

    message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channel_message.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    emoji: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (Index("ix_reaction_message", "message_id"),)
```

The composite PK `(message_id, user_id, emoji)` makes "toggle reaction"
idempotent. `emoji` is a Unicode codepoint string or `:shortcode:` — there is
no custom emoji upload (out of scope).

### `channel_webhook`

```python
class ChannelWebhook(Base):
    __tablename__ = "channel_webhook"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channel.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    direction: Mapped[str] = mapped_column(
        Enum("incoming", "outgoing", name="channel_webhook_direction"),
        nullable=False,
    )
    # Incoming: random URL-safe token; Outgoing: optional shared secret used in
    # X-Webhook-Signature.
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    # Outgoing only:
    target_url: Mapped[str | None] = mapped_column(String(2048))
    # Incoming + outgoing:
    last_used_at: Mapped[int | None] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_webhook_channel", "channel_id"),
        Index("ix_webhook_token", "token_hash", unique=True),
    )
```

Notes:

- `token_hash` is the SHA-256 of the random URL-safe token, stored as a
  64-character hex string (lowercase). The plaintext token is shown to the user
  **once** at create-time and never persisted, the same way GitHub PATs are
  handled. Lookup is `WHERE token_hash = ?` against the unique index
  `ix_webhook_token`; the comparison is delegated to the unique B-tree, with a
  constant-time string comparison in Python after the DB hit as defence in
  depth.
- A single table covers both directions to keep CRUD trivial. `target_url` is
  null for incoming; `token_hash` for outgoing is the optional shared secret
  used to sign outbound deliveries.

### `channel_file`

```python
class ChannelFile(Base):
    __tablename__ = "channel_file"

    channel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("channel.id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("file.id", ondelete="CASCADE"), primary_key=True
    )
    message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("channel_message.id", ondelete="SET NULL")
    )
    uploaded_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("user.id", ondelete="SET NULL")
    )
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (Index("ix_channel_file_message", "message_id"),)
```

A file is hard-bound to a single channel (no cross-channel reuse) and
optionally to a message — uploads happen *before* the message is posted, so
there is a brief window where `message_id IS NULL`. A nightly cleanup task
purges orphaned `channel_file` rows older than 24h.

### `file`

```python
class File(Base):
    __tablename__ = "file"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(120), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)  # bytes
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_file_owner", "user_id"),
        Index("ix_file_sha", "sha256"),
    )
```

Metadata only. `size` is bound by the 5 MiB cap (`5 * 1024 * 1024`). `sha256`
exists for future de-duplication and is set on insert.

### `file_blob`

```python
class FileBlob(Base):
    __tablename__ = "file_blob"

    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("file.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[bytes] = mapped_column(MEDIUMBLOB, nullable=False)
```

`MEDIUMBLOB` permits up to 16 MiB; we cap at 5 MiB so the row never exceeds
~5.4 MiB including overhead. `file_blob` is **never** joined into list/metadata
queries — selecting it always loads the payload, so the service layer reads it
exclusively via `select(FileBlob.data).where(file_id=...)` and streams to the
client.

## Alembic revision

Single revision file `rebuild/backend/alembic/versions/0004_m3_channels.py` (`revision = "0004_m3_channels"`, `down_revision = "0003_m2_sharing"`) creating every M3 table in dependency order: `file → file_blob → channel → channel_webhook → channel_member → channel_message → channel_message_reaction → channel_file`.

The revision is fully idempotent, per [rebuild.md § 9 "Robust, idempotent Alembic migrations"](../../rebuild.md#9-decisions-locked) and the M0 helper module ([m0-foundations.md § Migration helpers](m0-foundations.md#migration-helpers)). Eight tables and ten indexes is the largest surface in the rebuild and the most likely place for a partial-apply crash to occur (lock contention on InnoDB, transient DBA-side process kill, etc.); the helper pattern means the Helm Job retry just rolls forward.

```python
from app.db.migration_helpers import (
    create_table_if_not_exists, drop_table_if_exists,
    create_index_if_not_exists, drop_index_if_exists,
    create_check_constraint_if_not_exists, drop_constraint_if_exists,
    has_table, execute_if,
)
```

Key operational points:

- Every `create_table_if_not_exists(...)` call passes `mysql_engine="InnoDB"`, `mysql_charset="utf8mb4"`, `mysql_collate="utf8mb4_0900_ai_ci"` (defaulted by the helper) so the table inherits the M0 baseline regardless of server defaults.
- `file_blob.data` is declared as `sa.Column("data", mysql.MEDIUMBLOB(), nullable=False)` — explicit dialect type, **not** `LargeBinary`, otherwise SQLAlchemy emits `LONGBLOB`.
- All composite indexes (`ix_channel_archived`, `ix_channel_recency`, `ix_channel_member_user`, `ix_channel_member_channel_pinned`, `ix_channel_message_feed`, `ix_channel_message_thread`, `ix_channel_message_pinned`, `ix_reaction_message`, `ix_webhook_channel`, `ix_webhook_token` (unique), `ix_channel_file_message`, `ix_file_owner`, `ix_file_sha`) are declared inline as `sa.Index(...)` args inside the corresponding `create_table_if_not_exists` call so they land atomically with their table on a fresh run; the helper skips the entire call (table + inline indexes) on a re-run. Indexes added out-of-band would each need their own `create_index_if_not_exists` because MySQL 8.0 has no native `CREATE INDEX IF NOT EXISTS`. The `channel.last_message_at` column itself is declared inline on the `channel` table (nullable `BigInteger`) so the `ix_channel_recency` composite over `(is_archived, last_message_at)` is buildable in the same `CREATE TABLE`.
- The `CheckConstraint` on `channel_message` (`((user_id IS NOT NULL) + (bot_id IS NOT NULL) + (webhook_id IS NOT NULL)) = 1`, name `ck_channel_message_one_author`) is declared inline in the `create_table_if_not_exists` call so it lands with the table; if the table already exists from a previous partial run *without* the constraint (an inline declaration cannot get split), a follow-on `create_check_constraint_if_not_exists("ck_channel_message_one_author", "channel_message", "((user_id IS NOT NULL) + ...) = 1")` recovers it. The same constraint string is reused by the SQLAlchemy model so subsequent ORM-led inspection is consistent.
- The post-create `ALTER TABLE channel_message ROW_FORMAT=DYNAMIC` is wrapped in `execute_if(has_table("channel_message"), "ALTER TABLE channel_message ROW_FORMAT=DYNAMIC")` so a re-run after the ALTER already applied is harmless (MySQL silently no-ops the change when the row format already matches; the `has_table` guard just keeps us from running it before the table exists). This statement is required because the baseline server config may not set `innodb_default_row_format=DYNAMIC` and TEXT/JSON columns must be stored off-page.
- `downgrade()` mirrors with `drop_table_if_exists(...)` in reverse FK order: `channel_file → channel_message_reaction → channel_message → channel_member → channel_webhook → channel → file_blob → file`. Inline FKs and indexes drop with their owning tables; no separate `drop_index_if_exists` calls are needed.
- The Alembic `env.py` extends the baseline registry with `from app.models import channels, files` so `--autogenerate` works on the next revision.

`alembic upgrade head`, `alembic downgrade -1`, **and a second `alembic upgrade head` immediately afterwards** must all succeed cleanly. M0's `test_upgrade_head_is_idempotent` and `test_downgrade_base_is_idempotent` cover the standard round-trip parametrised over `0004_m3_channels`. The high-stakes case lives in `test_partial_upgrade_recovers`: pre-create `file` + `file_blob` + `channel` (raw DDL, no indexes), then `alembic upgrade head` and assert all eight tables, every named index, the `ck_channel_message_one_author` check constraint, and the `ROW_FORMAT=DYNAMIC` setting on `channel_message` are all present.

## File storage abstraction

The `FileStore` Protocol decouples upload/download/delete from the underlying
medium so an S3 swap is a one-class change.

```python
# rebuild/backend/app/storage/file_store.py
class FileStore(Protocol):
    async def put(self, *, data: bytes, mime: str, name: str, owner_id: str) -> str: ...
    async def get(self, file_id: str) -> AsyncIterator[bytes]: ...
    async def meta(self, file_id: str) -> "FileMeta | None": ...
    async def delete(self, file_id: str) -> None: ...

class MysqlFileStore:
    """MEDIUMBLOB-backed. Streams reads in 256 KiB chunks via MySQL SUBSTRING()
    so we never copy a full row into Python memory."""
    CHUNK = 256 * 1024

    async def put(self, *, data, mime, name, owner_id):
        file_id, sha = new_id(), hashlib.sha256(data).hexdigest()  # UUIDv7 via app.core.ids
        async with session_scope() as s:
            s.add(File(id=file_id, user_id=owner_id, name=name, mime=mime,
                       size=len(data), sha256=sha, created_at=now_ms()))
            s.add(FileBlob(file_id=file_id, data=data))
        return file_id

    async def get(self, file_id):
        async with session_scope() as s:
            size = (await s.execute(select(File.size).where(File.id == file_id))
                   ).scalar_one_or_none()
            if size is None:
                raise FileNotFoundError(file_id)
            offset = 1  # MySQL SUBSTRING is 1-indexed
            while offset <= size:
                row = (await s.execute(
                    text("SELECT SUBSTRING(data, :off, :ln) FROM file_blob "
                         "WHERE file_id = :id"),
                    {"off": offset, "ln": self.CHUNK, "id": file_id},
                )).scalar_one()
                if not row:
                    return
                yield bytes(row)
                offset += self.CHUNK
```

Cap enforcement lives in the FastAPI router, **before** any bytes touch
`FileStore`:

```python
MAX_UPLOAD = 5 * 1024 * 1024

async def read_capped(upload: UploadFile) -> bytes:
    chunks, total = [], 0
    while chunk := await upload.read(64 * 1024):
        total += len(chunk)
        if total > MAX_UPLOAD:
            raise HTTPException(413, "file exceeds 5 MiB cap")
        chunks.append(chunk)
    return b"".join(chunks)
```

`MysqlFileStore.get` returns an `AsyncIterator[bytes]` so FastAPI's
`StreamingResponse` writes to the wire one chunk at a time without ever
materialising the whole file in app memory. The S3 swap (out of scope) is a
new class implementing the same Protocol — no caller change.
`max_allowed_packet=16M` is pinned in `rebuild/infra/mysql/my.cnf` so 5 MiB
inserts succeed with headroom.

## Realtime layer (socket.io)

### Stack

- `python-socketio==5.x` mounted as an ASGI sub-app at `/socket.io`.
- `socketio.AsyncRedisManager(url=settings.REDIS_URL, channel="rebuild-sio")`
  as the client manager. Every emit goes through Redis pub/sub so any FastAPI
  replica can broadcast to any client regardless of which replica owns the
  websocket.

  ```python
  from app.core.constants import STREAM_HEARTBEAT_SECONDS

  sio = socketio.AsyncServer(async_mode="asgi",
      client_manager=AsyncRedisManager(settings.REDIS_URL),
      cors_allowed_origins=[], logger=False, engineio_logger=False,
      max_http_buffer_size=1_000_000,
      ping_interval=STREAM_HEARTBEAT_SECONDS,
      ping_timeout=STREAM_HEARTBEAT_SECONDS * 2)
  app.mount("/socket.io", socketio.ASGIApp(sio))
  ```
- Transport: `websocket` only — long-polling is disabled to reduce surface and
  because the OAuth proxy fronts everything.
- Heartbeat cadence is the project-wide `STREAM_HEARTBEAT_SECONDS` constant
  (M0; default 15s) so socket.io's ping interval and M1's SSE keepalive
  comment are always the same value. The watchdog window in the FE
  (`realtimeStore.ts`) is `2 * STREAM_HEARTBEAT_SECONDS`; do not hard-code
  either side.

### Connect-time auth

The OAuth proxy injects `X-Forwarded-Email` on every request, including the
websocket upgrade. socket.io exposes the upgrade environ via `environ` in the
`connect` handler. The handler delegates to the **same** `upsert_user_from_headers`
helper that backs the M0 HTTP `get_user` dep ([m0-foundations.md § Trusted-header
dependency](m0-foundations.md#trusted-header-dependency)) — there is exactly
one implementation of "trusted header → `User` row" in the codebase, used from
both the request lifecycle and the socket.io connect lifecycle:

```python
from app.core.auth import upsert_user_from_headers
from app.core.db import AsyncSessionLocal
from sqlalchemy import select
from app.models.channels import ChannelMember


@sio.on("connect")
async def on_connect(sid, environ, auth):
    email = environ.get("HTTP_X_FORWARDED_EMAIL")
    if not email:
        raise ConnectionRefusedError("missing trusted header")
    async with AsyncSessionLocal() as db:
        user = await upsert_user_from_headers(
            db, email=email, name=environ.get("HTTP_X_FORWARDED_NAME")
        )
        await db.commit()
        rows = (await db.execute(
            select(ChannelMember.channel_id).where(ChannelMember.user_id == user.id)
        )).scalars().all()
    await sio.save_session(sid, {"user_id": user.id, "email": email})
    for channel_id in rows:
        await sio.enter_room(sid, f"channel:{channel_id}")
    await sio.emit("ready", {"v": 1, "channel_ids": list(rows)}, to=sid)
```

The session is opened *for the lifetime of the connect handler only*; socket.io
doesn't have a request scope to hang it off. Subsequent emits don't need a DB
session — they read pre-loaded data from `sio.save_session` or call out to a
service helper that opens its own session. **There is no separate
`Users.get_or_create_by_email` class** — that would be a second implementation
of the same auth contract, and the day someone adds (say) a `last_seen_at`
update to one but not the other is the day the two paths drift. Keep the
upsert in `app/core/auth.py` and call it from both places.

### Rooms

- `channel:{id}` — one room per channel; every member of that channel is in it.
- `user:{id}` — one private room per user, used for delivery of mentions/notes
  that don't belong to a channel-wide broadcast (e.g. typing-indicators on a
  thread the user is reading).
- No `thread:{id}` rooms — threads piggyback on `channel:{id}` and the FE
  filters by `parent_id`. This keeps room cardinality bounded by channel count
  and avoids a fan-out explosion.

### Event protocol

Every server-side event is a JSON object with a stable shape. The `v` field is
a protocol version used to fail-fast on incompatible clients.

| Event | Direction | Payload |
|---|---|---|
| `ready` | S→C | `{ v:1, channel_ids:[id...] }` |
| `message:create` | S→C | `{ v:1, channel_id, message: ChannelMessageDTO, temp_id?:str }` |
| `message:update` | S→C | `{ v:1, channel_id, message: ChannelMessageDTO }` |
| `message:delete` | S→C | `{ v:1, channel_id, message_id, parent_id?:str }` |
| `reaction:add` | S→C | `{ v:1, channel_id, message_id, user_id, emoji, created_at }` |
| `reaction:remove` | S→C | `{ v:1, channel_id, message_id, user_id, emoji }` |
| `typing:start` | C↔S | `{ v:1, channel_id, parent_id?:str }` (server fans out to room minus sender, augmenting with `user_id`) |
| `typing:stop` | C↔S | `{ v:1, channel_id, parent_id?:str }` |
| `read:update` | S→C | `{ v:1, channel_id, user_id, last_read_at }` |
| `member:join` | S→C | `{ v:1, channel_id, user_id, role }` |
| `member:leave` | S→C | `{ v:1, channel_id, user_id }` |
| `pin:add` | S→C | `{ v:1, channel_id, message_id, by_user_id }` |
| `pin:remove` | S→C | `{ v:1, channel_id, message_id, by_user_id }` |

`ChannelMessageDTO` matches the REST `GET /channels/{id}/messages` response
item exactly so clients have one parser.

`message:create` carries the optional `temp_id` echoed back from the original
REST POST; the FE uses it to reconcile the optimistic insert with the
authoritative server row (see section 9).

### Server-side fan-out semantics

- Only typing events are emitted client→server. Everything else is the result
  of a REST mutation: the router does the DB write, then calls a thin
  `realtime.emit_*` helper that publishes to the room. Routers never bypass
  this helper; otherwise sticky bugs appear where one replica emits to its
  local sids and the others miss it.
- Events are fanned out to the entire `channel:{id}` room *except* read
  receipts (still room-wide so member dots update for everyone) and reactions
  on threaded messages (still room-wide; the FE filters by parent).
- Typing indicators are rate-limited server-side to one event per
  `(user_id, channel_id, parent_id)` per second. Each replica keeps a tiny LRU
  cache (`functools.lru_cache` keyed by tuple, with a manual TTL prune) so the
  rate limit does not require Redis.

### Backpressure / dropped-events strategy

- `python-socketio` queues outbound messages per-sid in memory. We cap each
  sid's queue at 256 messages. On overflow:
  - `typing:*` and `read:update` are silently dropped (best-effort by nature).
  - `message:*`, `reaction:*`, `pin:*`, `member:*` cause `sio.disconnect(sid)`
    so the client falls back to a reconnect-and-resync.
- Each emitter wraps `sio.emit(...)` with a 250ms timeout; if the await never
  resolves (slow Redis), the request still returns 200 but logs a warning. The
  REST mutation has already committed, so on reconnect the client picks up the
  state via REST.

### Reconnect → resync via REST

- Client persists `last_seen_event_id` per channel in `localStorage` (any
  message id will do). On reconnect, after `ready`, the client calls
  `GET /channels/{id}/messages?since={created_at_of_last_seen}&limit=200` for
  every channel listed in `ready` and merges into the message store. This
  bounds the resync window even if the user was offline for hours.
- The REST list endpoint is paginated; the FE follows `next_cursor` until it
  hits the head. The server doesn't track per-client deltas, so this cost is
  paid at reconnect — never during steady state.

## Routers and dependencies

Channel routers follow the project's "skinny router, fat dep, service only when
justified" pattern (see [FastAPI-best-practises.md §A.1](FastAPI-best-practises.md)
and [m0-foundations.md § Dependency type aliases](m0-foundations.md#dependency-type-aliases)).
The cross-cutting concerns — load the channel, check membership, check role —
live as FastAPI dependencies, **not** as private helpers inside every service
function. They are defined once in `app/routers/deps.py` and referenced by
every channel route via the `Annotated` aliases below.

```python
# rebuild/backend/app/routers/deps.py
from typing import Annotated
from fastapi import Depends, HTTPException, Path

from app.core.deps import CurrentUser, DbSession
from app.models.channels import Channel, ChannelMember


async def get_channel(
    channel_id: Annotated[str, Path()], db: DbSession
) -> Channel:
    ch = await db.get(Channel, channel_id)
    if ch is None:
        raise HTTPException(404, detail="channel not found")
    return ch


async def get_membership(
    ch: Annotated[Channel, Depends(get_channel)],
    user: CurrentUser, db: DbSession,
) -> ChannelMember:
    m = await db.get(ChannelMember, (ch.id, user.id))
    if m is None:
        raise HTTPException(403, detail="not a channel member")
    return m


async def require_owner(
    m: Annotated[ChannelMember, Depends(get_membership)],
) -> None:
    if m.role != "owner":
        raise HTTPException(403, detail="owner only")


async def require_owner_or_admin(
    m: Annotated[ChannelMember, Depends(get_membership)],
) -> None:
    if m.role not in ("owner", "admin"):
        raise HTTPException(403, detail="owner or admin only")


ChannelDep          = Annotated[Channel, Depends(get_channel)]
MembershipDep       = Annotated[ChannelMember, Depends(get_membership)]
RequireOwner        = Annotated[None, Depends(require_owner)]
RequireOwnerOrAdmin = Annotated[None, Depends(require_owner_or_admin)]
```

Two properties of FastAPI dependencies that earn their keep here:

- **Per-request caching.** `get_channel` runs once per request even when it is
  reached transitively through `RequireOwner` *and* used directly in the route
  body — the `Channel` row is queried exactly once. This is what makes inlined
  CRUD acceptable: the route body never re-queries data the dependency chain
  has already loaded.
- **Declarative permission at the signature site.** A route reads `_: RequireOwner`
  and the reader knows immediately who can call it; `grep -R RequireOwner backend/`
  enumerates every owner-only endpoint in the codebase. The previous shape
  (private `_check_role(user, channel)` helpers inside each service function)
  could not be grepped meaningfully.

Routers then look like this — channel CRUD inlined, no `services/channels/channels.py`
wrapper layer:

```python
# rebuild/backend/app/routers/channels.py
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.deps import CurrentUser, DbSession
from app.core.ids import new_id
from app.core.time import now_ms
from app.models.channels import Channel, ChannelMember
from app.realtime.events import emit_channel_archived
from app.routers.deps import ChannelDep, RequireOwner, RequireOwnerOrAdmin
from app.schemas.channels import ChannelCreate, ChannelPatch, ChannelRead

router = APIRouter(prefix="/api/channels", tags=["channels"])


@router.post("", response_model=ChannelRead, status_code=status.HTTP_201_CREATED)
async def create_channel(
    body: ChannelCreate, user: CurrentUser, db: DbSession,
) -> Channel:
    ch = Channel(id=new_id(), user_id=user.id, name=body.name,
                 description=body.description, is_private=body.is_private,
                 created_at=now_ms(), updated_at=now_ms())
    db.add(ch)
    db.add(ChannelMember(channel_id=ch.id, user_id=user.id,
                         role="owner", joined_at=now_ms()))
    try:
        await db.commit()
    except IntegrityError as e:
        raise HTTPException(409, detail="channel name already exists") from e
    await db.refresh(ch)
    return ch


@router.patch("/{channel_id}", response_model=ChannelRead)
async def patch_channel(
    body: ChannelPatch, ch: ChannelDep, _: RequireOwnerOrAdmin, db: DbSession,
) -> Channel:
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(ch, field, value)
    ch.updated_at = now_ms()
    await db.commit()
    return ch


@router.post("/{channel_id}/archive", status_code=204)
async def archive_channel(ch: ChannelDep, _: RequireOwner, db: DbSession) -> None:
    ch.is_archived = True
    ch.archived_at = now_ms()
    await db.commit()
    await emit_channel_archived(ch.id)
```

Members, reactions, pins, and webhook CRUD follow the same shape. Only the
**message** routers (top-level posts, thread replies, webhook ingress) reach
into `services/channels/messages.py` — that is the helper M4 also calls, the
one with the multi-table invariant, the one with three callers.

Pydantic request bodies (`ChannelCreate`, `ChannelPatch`, `AddMembersBody`,
`PinRequest`, `ReactionRequest`, `WebhookCreate`, …) all inherit from
[`StrictModel`](m0-foundations.md#pydantic-conventions). The closed
`channel_message.content` shape is enforced by `ChannelMessageContent(StrictModel)`
in `app/schemas/channels.py`; `services/channels/messages.py` validates every
payload through this schema before insert, so the `Mapped[dict[str, Any]]`
column never holds an unvalidated dict.

## API surface (REST)

All endpoints are mounted under the project-wide `/api` prefix (no `/v1` —
`rebuild.md` §4 fixes a single unversioned prefix). Responses are pydantic
models inheriting from `StrictModel`. Errors use FastAPI's `HTTPException`
with structured `{ "detail": "<msg>", "code": "<machine_code>" }`.
Authentication is the M0 trusted-header dependency surfaced as
`Annotated[User, Depends(get_user)]` (the `CurrentUser` alias from
`app/core/deps.py`) unless explicitly stated.

### Channels

- `GET  /api/channels` — list channels visible to caller (member or public).
  Response: `[{id, name, description, is_private, is_archived,
  member_count, last_message_at, unread_count}]`. Field derivations:
  - `last_message_at` is the denormalised `channel.last_message_at` column —
    not a `MAX(channel_message.created_at)` subquery. Every write path
    (`create_message`, `create_bot_message`, `create_webhook_message`)
    updates it inside the same transaction that inserts the row, so the
    column is always within one commit of the truth. The
    `ix_channel_recency` index on `(is_archived, last_message_at)` makes
    sorting the response by recency an index-only scan.
  - `member_count` is `COUNT(*) FROM channel_member WHERE channel_id = …`
    (small per-channel; no denormalisation worth the write-amplification).
  - `unread_count` is computed as
    `COUNT(*) FROM channel_message WHERE channel_id = … AND created_at >
    channel_member.last_read_at` for the calling user's `channel_member`
    row. It uses the `ix_channel_message_feed` covering index
    `(channel_id, created_at)`, so even noisy channels resolve in one
    range probe per channel. Soft-cap at 99 in the response (`"99+"` is
    rendered FE-side); the count is intended only for the sidebar badge,
    not exact accounting.
- `POST /api/channels` — create. Body `{ name, description?, is_private }`. Caller
  becomes `owner` member. 409 on name collision.
- `GET  /api/channels/{id}` — full channel detail.
- `PATCH /api/channels/{id}` — owner/admin only. `{ name?, description?,
  is_private? }`.
- `POST /api/channels/{id}/archive` — owner only; sets `is_archived=true`,
  `archived_at`. Members are kept; channel becomes read-only.
- `POST /api/channels/{id}/unarchive` — owner only.
- `DELETE /api/channels/{id}` — owner only; hard delete cascades to all child rows
  via FK `ON DELETE CASCADE`.

### Members

- `GET  /api/channels/{id}/members` — paginated `[ {user_id, role, joined_at,
  last_read_at, muted, pinned, user:{name,email}} ]`.
- `POST /api/channels/{id}/members` — owner/admin. Body `{ user_ids:[..],
  role:"member"|"admin" }`. Idempotent (existing members no-op).
- `DELETE /api/channels/{id}/members/{user_id}` — owner/admin (or self for "leave"). Emits `member:leave`.
- `PATCH  /api/channels/{id}/members/{user_id}` — `{ role }` change, owner only.
- `POST /api/channels/{id}/members/{user_id}/mute` — self only, `{ muted: bool }`.
- `POST /api/channels/{id}/members/{user_id}/pin`  — self only, `{ pinned: bool }`.

### Messages

- `GET /api/channels/{id}/messages` — top-level messages, paginated by
  `created_at`. Query: `before?:int`, `after?:int`, `limit:int=50` (max 200).
  Default order is reverse-chronological. Returns `{ items:[
  ChannelMessageDTO ], next_cursor:int|null, prev_cursor:int|null }`.
- `POST /api/channels/{id}/messages` — body shape
  `{ content:{text, attachments?, mentions?}, parent_id?:str, temp_id?:str }`.
  `parent_id` is **top-level** (not nested in `content`) because it maps to the
  `channel_message.parent_id` column. Returns the created `ChannelMessageDTO`.
  Triggers the `@model` dispatcher (section 8).
- `GET /api/channels/{id}/messages/{mid}` — single message + reaction summary.
- `PATCH /api/channels/{id}/messages/{mid}` — author only. Body `{ content }`.
  Sets `updated_at` and toggles `content.edited=true`.
- `DELETE /api/channels/{id}/messages/{mid}` — author or owner/admin. Cascade
  deletes thread replies via FK.
- `GET /api/channels/{id}/messages/{mid}/thread` — thread replies for `mid`,
  paginated like the channel feed but filtered by `parent_id=mid`.

### Reactions

- `POST   /api/channels/{id}/messages/{mid}/reactions`  — body `{ emoji }`. Inserts
  via `INSERT IGNORE` so it's idempotent. Emits `reaction:add`.
- `DELETE /api/channels/{id}/messages/{mid}/reactions`  — body `{ emoji }`. Emits
  `reaction:remove`. 204 on success / on missing.

### Pins

- `POST   /api/channels/{id}/messages/{mid}/pin`   — owner/admin or author. Emits
  `pin:add`.
- `DELETE /api/channels/{id}/messages/{mid}/pin`   — owner/admin or pinner. Emits
  `pin:remove`.
- `GET    /api/channels/{id}/pins`                 — list pinned messages,
  paginated by `pinned_at`.

### Read receipts

- `POST /api/channels/{id}/read` — body `{ last_read_at:int }`. Server clamps to
  `min(now, body.last_read_at)`. Emits `read:update` to the channel room so
  every other member sees the dot move in real time.

### Files

- `POST /api/files` — `multipart/form-data` with one `file` field plus
  `channel_id` form field. Streamed read with the 5 MiB cap; returns
  `{ file_id, name, mime, size, sha256, channel_id }`. The server creates
  `file`, `file_blob`, `channel_file` (with `message_id=NULL`) atomically.
- `GET  /api/files/{file_id}` — streamed download. `Content-Disposition` is
  `inline; filename="{name}"` if the mime is `image/*` or `text/*`, else
  `attachment`. `Cache-Control: private, max-age=300`. ETag is the sha256.
  Access check: caller must be a member of any channel the file is bound to.
- `GET  /api/files/{file_id}/meta` — metadata only, no payload load.
- `DELETE /api/files/{file_id}` — uploader or owner/admin of the bound channel.

**Thumbnails**: explicitly out of scope for M3. At the 5 MiB cap, browsers
render images directly from the download endpoint in `<img loading="lazy">`;
combined with the `content-visibility: auto` virtualization ported from M1,
perf is fine for the channel feed. Adding Pillow + thumbnail blobs doubles
upload latency and storage and introduces a derivation cache that is not free
to invalidate. Revisit in M5+ if image-heavy usage emerges.

### Webhooks (incoming, public)

- `POST /api/webhooks/incoming/{webhook_id}` — **does not** use
  `Depends(get_user)`. Validates token from `Authorization: Bearer <token>` or
  `?token=<token>` query param, matched against `token_hash` with a
  constant-time comparison. Body is a JSON message:
  ```json
  { "text": "...", "username": "...", "thread_parent_id": null,
    "attachments": [{ "url": "https://...", "name": "...", "mime": "..." }] }
  ```
  Inline attachments by URL are not fetched in v1 — only `text` is required.
  Successful posts insert a `channel_message` with `webhook_id` set, fan out
  via socket.io, update `channel_webhook.last_used_at`, and respond 202.
  Rate-limited per `webhook_id` to 60 req/min in Redis (token bucket).
  Per-route HTTP timeout: **5 s** end-to-end, applied via the M5
  `@route_timeout(5)` decorator (`m5-hardening.md` § Per-route HTTP timeouts) —
  webhook senders that block past 5 s get a 504 and should retry. The 5 s
  budget covers the constant-time token comparison, the `INSERT` into
  `channel_message`, the `UPDATE` of `channel_webhook.last_used_at`, and the
  socket.io fan-out; the outgoing-webhook delivery (next subsection) is
  fire-and-forget and runs *after* the 202 has been returned, so it does not
  count against the 5 s. The rate-limit value (60 req/min) is the
  `RATELIMIT_WEBHOOK_PER_MIN` setting introduced in M5 § Settings additions.
  Not exposed to the public internet; the OAuth proxy fronts everything.

### Webhooks (outgoing)

- `GET    /api/channels/{id}/webhooks` — owner/admin: list outgoing+incoming
  webhooks (token redacted).
- `POST   /api/channels/{id}/webhooks` — body `{ name, direction, target_url? }`.
  Server generates the token, stores its hash, and returns the plaintext
  exactly once.
- `PATCH  /api/channels/{id}/webhooks/{wid}` — `{ name?, target_url?, is_active? }`.
- `DELETE /api/channels/{id}/webhooks/{wid}` — hard delete.
- Outgoing-webhook delivery: on every `message:create`, the channel-message
  service iterates active outgoing webhooks for the channel and enqueues a
  fire-and-forget POST via an `httpx.AsyncClient` task. The body matches the
  Slack-compatible `{ event_type:"message:create", channel_id, message }`
  envelope. Two attempts max (5s timeout each); failures log + mark
  `is_active=false` after 10 consecutive failures. No retry queue, no DLQ —
  this is best-effort.

## `@model` auto-reply

### Detection

When a message is created, the message service extracts `@<token>` mentions
from `content.text` using a single regex:

```python
MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9][A-Za-z0-9._-]{0,127})")
```

Each match is classified once: if the token equals a model id from the gateway
list, `kind:"model"`; if it matches a `channel_member` username/email-prefix,
`kind:"user"`; otherwise the token is treated as plain text and not added to
`content.mentions`. No other mention syntaxes (`<#channel>`, `<@uuid>`, etc.)
are recognised in v1. The model list comes from the cached output of
`provider.list_models()` (TTL 5 minutes, refreshed in the background). The
same cache instance backs the M1 `/api/models` router; both share a single
TTL.

### Background task lifecycle

- One task per `(channel_id, parent_id_or_root)` triggering message. The task:
  1. Loads the thread context: if `parent_id` is set, fetch the last 32
     messages with `parent_id == parent_id`. Else create a thread by setting
     `parent_id = triggering_message.id` for the reply.
  2. Builds the OpenAI `messages` array: each thread message becomes
     `{ role: 'assistant' if bot_id else 'user', content: text }`. The original
     mention is stripped from the user turn.
  3. Calls `provider.stream(messages=..., model=model_id, params={})` —
     the same `OpenAICompatibleProvider` instance from M1. No multi-provider
     routing; rails forbid it.
  4. As tokens arrive, accumulates them in a single in-progress
     `channel_message` row created with `bot_id=model_id`,
     `content={text:'', mentions:[], attachments:[]}`. Every ~250ms, emits
     `message:update` with the accumulated text. Final commit emits one more
     `message:update` with the complete text and a server-side
     `message:create` already happened at task start.
  5. On completion, `updated_at` is bumped to `now_ms()`.
- Errors (provider 4xx/5xx/timeout): replace the message text with
  `"Failed to reach `{model_id}`: {error}"` and emit a final `message:update`.
  The row stays so the user sees the failure inline.

### Concurrency caps & latest-wins

- Per-channel concurrency cap of **2** simultaneous tasks. Implemented as
  `asyncio.Semaphore(2)` in a `dict[str, Semaphore]` keyed by `channel_id`,
  cleaned up in a weakref-style sweep. New tasks above the cap queue inside
  the semaphore.
- Per-thread latest-wins window of **5s**: a per-process
  `dict[(channel_id, thread_root_id)] -> asyncio.Task` records the active task.
  If a new mention for the same thread arrives within 5s and the previous task
  is still running, `previous.cancel()` is called and a 'cancelled' suffix is
  appended to its in-flight message. This avoids two assistant messages racing
  in the same thread when a user edits or repeats a mention.
- Both structures live **per replica** — they are not Redis-coordinated.
  Cross-replica double-firing is acceptable because (a) a single mention only
  hits one replica's REST handler, and (b) outbound streaming naturally
  serialises through that replica. The tradeoff: a replica restart cancels its
  active streams; the user gets a half-message. On the next mention they retry.

### Bot identity (`bot_id`)

We recommend the **nullable `bot_id` column on `channel_message`** over a
synthetic `model:<model_id>` user, for these reasons:

- The `user` table is the source of truth for humans auto-provisioned from
  `X-Forwarded-Email`. Synthetic rows pollute user listings, mention pickers,
  sharing, and any future audit log with "is this real?" branches.
- Models are discovered dynamically from the gateway; the set is open-ended.
  Sentinel users would need GC or accumulate stale rows.
- FE rendering becomes a single `if bot_id` conditional with zero DB churn.
- The `CheckConstraint` formalises "exactly one of (user_id, bot_id,
  webhook_id) is non-null" at the DB layer, so we can never write an
  ambiguous row.

## Frontend routes and components

### Routes (SvelteKit 2 + Svelte 5)

- `rebuild/frontend/src/routes/(app)/channels/+layout.svelte` — sidebar
  (`ChannelList`) + outlet.
- `rebuild/frontend/src/routes/(app)/channels/+page.svelte` — empty-state
  picker.
- `rebuild/frontend/src/routes/(app)/channels/[id]/+page.svelte` — main feed
  (`ChannelView`).
- `rebuild/frontend/src/routes/(app)/channels/[id]/threads/[mid]/+page.svelte`
  — split thread pane.
- `+layout.ts` `load`: prefetches `/channels`, opens the realtime store.

### Component port list

All ported under `rebuild/frontend/src/lib/components/channel/`. Each item
notes the legacy origin and the dead imports stripped.

**Every ported component is rebuilt against the M0 Svelte 5 idioms** (see
[m0-foundations.md § Frontend conventions (cross-cutting)](m0-foundations.md#frontend-conventions-cross-cutting),
rule 4): callback props (no `createEventDispatcher`), `{#snippet}` +
`{@render}` (no `<slot>`), lowercase event attributes (`onclick`, no
`on:click`), `{@attach}` (no `use:action`), `$state` / `$derived` (no
`writable` / `derived` stores or `let`-as-reactive). The legacy components
listed below universally use the Svelte 4 patterns; the porter must convert
them, not paste them. The frontend lint step's grep gate (`createEventDispatcher`,
`<slot`, `on:click`, `use:`, `$app/stores` — all banned under
`frontend/src/`) catches anything that slips through review.

| Rebuild component | Legacy origin | Dead imports stripped |
|---|---|---|
| `ChannelList.svelte` | `Sidebar.svelte` (channels section only) | tools, skills, notes, calendar |
| `ChannelView.svelte` | `Channel.svelte` | tools menu, skills picker, notes pane, RAG citations |
| `MessageList.svelte` | `Messages.svelte` | citations, sources, evaluation, knowledge |
| `MessageItem.svelte` | `Messages/Message.svelte` | tools/skills indicators, code-interpreter, MCP |
| `Thread.svelte` | `Thread.svelte` | tools menu, skills picker |
| `Reactions.svelte` | inline in `Messages/Message.svelte` | n/a (extracted) |
| `Pins.svelte` | `PinnedMessagesModal.svelte` | n/a |
| `MemberList.svelte` | `ChannelInfoModal/UserList.svelte` | groups, access grants |
| `Composer.svelte` | `MessageInput.svelte` (legacy 32k LOC ⇒ ~600 LOC) | tools, skills, MCP, web-search, code-interpreter, image-gen |
| `FileUpload.svelte` | inline in `MessageInput.svelte` | RAG, knowledge, citations |
| `MentionPicker.svelte` | `MessageInput/MentionList.svelte` | @everyone, groups |
| `WebhookConfig.svelte` | `WebhooksModal.svelte` + `WebhookItem.svelte` | n/a |
| `Navbar.svelte` | `Navbar.svelte` | tools, skills, notes |

### Stores

All seven stores follow the project-wide convention from
[m0-foundations.md § Frontend conventions (cross-cutting)](m0-foundations.md#frontend-conventions-cross-cutting):
**one class per file, instances provided via `setContext` in the channels
layout** (`(app)/channels/+layout.svelte`), file naming `*.svelte.ts`,
collections use `SvelteMap` / `SvelteSet` from `svelte/reactivity` (never
native `Map`/`Set` — mutations on those don't trigger reactivity, which would
silently break optimistic-insert + socket-echo reconciliation, the typing
TTL, and the unread cursor). Module-level `$state` is banned; module-level
`setInterval`/`setTimeout` is banned.

| Store | File | Reactive collection | Notes |
|---|---|---|---|
| `RealtimeStore` | `realtime.svelte.ts` | n/a | Owns the `socket.io-client` instance and exposes `connectionState: 'connecting' \| 'open' \| 'reconnecting' \| 'closed'`. Constructed once in the channels layout's `$effect` so the connection lifecycle matches the route — see "Lifecycle" below. |
| `ChannelsStore` | `channels.svelte.ts` | `SvelteMap<string, Channel>` | Derived `pinned`, `unpinned`, `archived` lists via `$derived`. Hydrated from `GET /channels` and patched on `member:join` / `member:leave` / `channel:archived`. |
| `MessagesStore` | `messages.svelte.ts` | `SvelteMap<string, ChannelMessage[]>` keyed by `channel_id`, values sorted by `created_at` | Optimistic insertion: temp entry with `temp_id` + `status:'pending'`; on `message:create` echo, replace by `temp_id` (falling back to `id`); on REST 4xx/5xx, mark `status:'failed'` with retry control. |
| `ThreadStore` | `thread.svelte.ts` | `SvelteMap<string, ChannelMessage[]>` keyed by `root_message_id` | Populated when a thread is opened and incrementally updated by socket events with matching `parent_id`. |
| `TypingStore` | `typing.svelte.ts` | `SvelteMap<string, SvelteSet<{ user_id: string; expires_at: number }>>` keyed by `channel_id` | Each `typing:start` resets a 4-second TTL on the entry. The 1-second prune sweep is owned by a `$effect` in `(app)/channels/+layout.svelte` (see "Lifecycle" below) — never `setInterval` at module scope. |
| `PresenceStore` | `presence.svelte.ts` | `SvelteSet<string>` (online user ids) | Derived from `member:join`/`leave` plus an at-connect online snapshot; cheap, not strictly required for v1 but the API is wired so a status dot can be added later without store changes. |
| `ReadsStore` | `reads.svelte.ts` | `SvelteMap<string, SvelteMap<string, number>>` (channel → user → last_read_at) | Updated from `read:update`. Drives the read cursor and unread counts. |

#### Lifecycle (sockets, intervals, polling)

Long-lived browser side-effects — the socket.io connection, the typing-prune
interval, any reconnect watchdog — are owned by `$effect` blocks inside
`(app)/channels/+layout.svelte` so they auto-clean on route teardown. Per
[m0-foundations.md § Frontend conventions (cross-cutting)](m0-foundations.md#frontend-conventions-cross-cutting),
none of this can live at module scope: a module-level `setInterval(prune,
1000)` would run on every SSR import (server-side, where there's no DOM and
no real cleanup hook) and accumulate one timer per worker boot.

```svelte
<!-- (app)/channels/+layout.svelte -->
<script lang="ts">
  import { provideRealtime, useRealtime } from '$lib/stores/realtime.svelte';
  import { provideChannels } from '$lib/stores/channels.svelte';
  import { provideMessages } from '$lib/stores/messages.svelte';
  import { provideThread } from '$lib/stores/thread.svelte';
  import { provideTyping, useTyping } from '$lib/stores/typing.svelte';
  import { providePresence } from '$lib/stores/presence.svelte';
  import { provideReads } from '$lib/stores/reads.svelte';
  let { data, children } = $props();
  const realtime = provideRealtime();
  provideChannels(data.channels);
  provideMessages();
  provideThread();
  const typing = provideTyping();
  providePresence(data.online_users);
  provideReads(data.reads);

  $effect(() => {
    realtime.connect();
    return () => realtime.disconnect();
  });

  $effect(() => {
    const id = setInterval(() => typing.prune(Date.now()), 1000);
    return () => clearInterval(id);
  });
</script>
{@render children()}
```

The 5-second pending-message watchdog (used by the optimistic posting
reconciliation in `MessagesStore`) is also owned by a per-message `$effect`
inside `MessageItem.svelte` for messages whose `status === 'pending'` — same
shape: register the `setTimeout` on mount, return a `clearTimeout` cleanup.
Module-scope timers are not used anywhere in M3.

### Optimistic posting & reconciliation

```ts
async function postMessage(channelId, content) {
  const tempId = uuidv7();  // from $lib/utils/ids — wraps the `uuidv7` npm package; matches the backend convention
  messagesStore.upsert(channelId, { id: tempId, temp_id: tempId,
    status: 'pending', ...content, created_at: nanos(), user_id: me.id });
  try {
    await api.post(`/channels/${channelId}/messages`, { content, temp_id: tempId });
    // Socket echo replaces the temp row by temp_id; no write here.
  } catch (e) {
    messagesStore.patch(channelId, tempId, { status: 'failed', error: e });
  }
}
```

A 5-second pending timer guards the REST→socket race: if no socket echo
arrives within 5s and the REST call returned 200, the temp row is swapped to
the REST-returned `id` and marked `status:'sent'`. The timer is owned by a
`$effect` inside `MessageItem.svelte` (active only while
`message.status === 'pending'`); on socket echo, REST failure, or component
unmount, the cleanup function clears the `setTimeout`. This matches the
M0 long-lived-side-effect rule (see [m0-foundations.md § Frontend conventions
(cross-cutting)](m0-foundations.md#frontend-conventions-cross-cutting), rule 3).

### Virtualization

`MessageList` reuses the `content-visibility: auto` strategy ported from M1
(landed legacy-side in v0.9.2). Each `MessageItem` is wrapped in a sentinel div
with `style="content-visibility:auto; contain-intrinsic-size:auto 80px"`. No
`react-virtual`-style windowing — the strategy gives us 90%+ of the perf at
zero JS cost and handles variable message heights gracefully (markdown, code
blocks, images all differ wildly in size).

### Composer mention picker

- `@` keystroke opens `MentionPicker` with two sections: **Models**
  (from `GET /models` cached on connect) and **Members** (from the channel's
  member list). Search is client-side fuzzy match over names.
- Selecting a model inserts `@<model_id>` literal text — the server-side
  parser is the source of truth, so the FE doesn't need to encode markup.

### File upload UX

- Drag-drop or paste into `Composer` triggers `FileUpload` which immediately
  POSTs to `/api/files` with the channel id and shows a per-file progress bar
  (XHR `progress` event). On success, the returned `file_id` is appended to
  the composer state and rendered as an inline preview tile. Posting the
  message attaches the file_ids in `content.attachments`.
- Files >5 MiB are rejected client-side with an inline error before any HTTP
  request is fired.

## Multi-instance scaling

- **Redis as message broker.** `python-socketio.AsyncRedisManager` uses Redis
  pub/sub to fan out emits across replicas. Any client connected to replica A
  receives events emitted by replica B with sub-millisecond Redis latency on
  the local network.
- **Sticky sessions are NOT required.** Every replica maintains the full set
  of room→sid mappings via the manager protocol; an emit on any replica fans
  out to every sid in the room across the cluster.
- **Stateless replicas.** No process-local cache survives a restart that
  isn't reconstructable from MySQL or Redis. Typing rate-limit cache,
  model-list cache, and `@model` task registry are all per-process and
  bounded.
- **Health checks for socket.io upgrade.** The M0 `/healthz` already checks
  HTTP. We add `/readyz` to additionally verify (a) MySQL connectivity, (b)
  Redis pub/sub round-trip via a `ping`, and (c) the socket.io ASGI sub-app
  has been mounted (`hasattr(app, 'mounted_routes')`). The load balancer
  routes the websocket upgrade only when `/readyz` is 200.
- **Connection draining.** SIGTERM triggers a 30-second drain: refuse new
  upgrades, broadcast `server:draining` to existing connections (FE swaps to
  reconnect-with-backoff), then close.

### Benchmark plan (end of M3)

- Tool: `rebuild/backend/scripts/bench_channels.py` — async harness that
  spawns N socket.io clients (`python-socketio.AsyncClient`) across M
  channels, posts messages at a configurable rate, and records the latency
  from `POST /channels/{id}/messages` to `message:create` arrival on every
  receiver.
- Targets:
  - **200ms p95** end-to-end fan-out for **100 concurrent users** spread over
    **10 channels** (10 users/channel) at **10 msg/sec** total.
  - p99 ≤ 500ms.
  - Server CPU < 60% on a single 4-vCPU replica.
  - Redis pub/sub bytes/sec < 1 MiB at 10 msg/sec.
- Run on the same Docker compose used in CI (single FastAPI replica + MySQL +
  Redis), then again with **2 replicas** behind nginx round-robin to verify
  the cross-replica fan-out path.
- Results land in `rebuild/plans/m3-bench-results.md` and gate sign-off.

## Tests

### Unit tests (Vitest + jsdom; pytest for backend)

- **Backend**:
  - `mention_parser` — regex extraction, edge cases (`a@b`, `@@x`, unicode,
    code-fenced mentions, leading/trailing punctuation).
  - `content_validator` — pydantic validation of `ChannelMessage.content`
    via the `ChannelMessageContent` schema (inherits from
    [`StrictModel`](m0-foundations.md#pydantic-conventions); no per-class
    `model_config` repetition) against the closed shape documented in §3.4
    (`text`, `mentions?`, `attachments?`, `embeds?`, `edited`,
    `automation_id?`, `automation_owner_name?`). Tests cover:
    rejects oversized arrays, rejects unsupported attachment mimes, rejects
    unknown keys, accepts the M4 channel-target shape with both
    `automation_id` and `automation_owner_name` set, and accepts user-authored
    messages that omit both automation fields.
  - `auto_reply.dispatcher` — only real-model mentions trigger; cap and
    latest-wins enforced under a fake clock.
  - `file_store.MysqlFileStore` — round-trip put/get with chunked read,
    unicode filenames, exact-cap edge case, ordered chunk yields.
  - `webhook.signature` — outgoing signing and incoming token constant-time
    compare.
- **Frontend**:
  - `messages-store` — optimistic insert / socket reconciliation by
    `temp_id`; out-of-order arrival; failed POST marks status.
  - `message-tree-reducer` — top-level vs threaded grouping, delete cascade.
  - `typing-store` — TTL prune, multi-user merge, dedupe per user.
  - `mention-parser` — FE mirror of BE; same fixtures, same outputs.

### Component tests (Playwright Component Testing + MSW)

- `MessageItem` — markdown, code blocks, mentions, attachments, edited badge,
  bot vs human vs webhook variants.
- `Thread` — open thread, reply, scroll-to-bottom, parent message visible.
- `Reactions` — toggle, count update, hover popover with users.
- `Pins` — empty state, scroll, click-to-jump.
- `Composer` — keyboard (Enter/Shift+Enter), paste image, drag-drop file,
  oversize file rejection, mention picker (model + member sections).
- `FileUpload` — progress bar, error state, multiple files.
- `MentionPicker` — keyboard nav, fuzzy match, model vs user differentiation.
- `WebhookConfig` — create, copy-token (one-shot reveal), revoke.
- Each component test renders against an MSW handler set so the same handlers
  drive E2E in `dev`.

### E2E tests (Playwright + Docker compose)

The three critical paths called out in the brief, plus support tests:

1. **Realtime fan-out across two contexts.**
   - Browser context A signs in as `alice`, B as `bob`. Both join channel
     `#x`. A posts a message; B sees `message:create` arrive within 200ms via
     `page.waitForEvent('websocket')`. A reacts; B sees `reaction:add`. B
     types; A sees `typing:start` then `typing:stop`. B marks read; A's
     unread dot updates. Verifies both single- and two-replica configs (test
     parameterised over docker-compose profiles).

2. **`@model` mention → streamed reply in thread → reactions visible.**
   - Alice posts `@gpt-4o-mini summarise this channel` against the recorded
     OpenAI cassette. The mock SSE replays a 6-token stream; the FE shows
     incremental tokens (`message:update`) on both A and B. Final message has
     `bot_id=gpt-4o-mini` and lives under `parent_id=<alice's message>`.
     A reacts to the bot reply; B sees the reaction on the bot message.
   - Tests also verify the latest-wins cancel: posting a second mention for
     the same model within 5s cancels the first stream.

3. **File upload + preview.**
   - Alice drops a 4 MiB PNG into the composer. Progress bar advances. After
     send, B sees the message with an inline image preview rendered from
     `GET /api/files/{id}`. A 6 MiB upload is rejected client-side with no HTTP.
     A 5.1 MiB upload (bypassing the FE check via Playwright's `request.post`)
     is rejected by the server with 413.

Supporting E2E:

- Incoming webhook end-to-end: `POST /api/webhooks/incoming/<id>` from a stand-in
  cURL Playwright fixture posts a `text` payload; both A and B see it as a
  webhook-attributed `MessageItem`.
- Outgoing webhook end-to-end: configure an outgoing webhook pointing to a
  test FastAPI sink; post a message and assert the sink received the
  Slack-shaped envelope within 2s.
- Pin/unpin: A pins; B sees `pin:add` and the message in `Pins` drawer.
- Member add/remove: A (owner) adds C; C connects in a third context and
  receives the channel in `ready`.
- Archive: A archives `#x`; both A and B see the channel become read-only,
  composer disabled, message list still readable.

The **multi-context** Playwright pattern is the only reliable way to test
realtime; pinning two `BrowserContext` instances with different
`X-Forwarded-Email` headers is non-negotiable per the rebuild's testing
strategy in `rebuild.md` §8.

### Performance regression test

A reduced version of the section-10 benchmark (10 users, 1 channel, 1 msg/sec,
20s wall-clock) runs in CI nightly and asserts p95 ≤ 250ms. Drift triggers a
quarantine + investigation, never a green tick.

## Dependencies on other milestones

- **M0 — Foundations.** Required: `rebuild/` skeleton, MySQL+Redis compose,
  Alembic baseline, trusted-header `get_user` dep, `/healthz`+`/readyz`,
  Docker image, Buildkite path-filtered pipeline, Vitest + Playwright wiring.
- **M1 — Conversations.** Required: `OpenAICompatibleProvider.stream`,
  `OpenAICompatibleProvider.list_models`, the markdown render port (reused in
  `MessageItem`), the SSE schema (loosely informs the bot `message:update`
  cadence). The provider is shared, never re-implemented for channels.
- **Independent of M2** (sharing). Channels never share to public links.
- **Independent of M4** (automations). M4's APScheduler runs after M3 lands;
  if `target_channel_id` is set, M4 calls the M3 service helper
  `app.services.channels.messages.create_bot_message(session, *, channel_id,
  bot_id, content, parent_id=None) -> ChannelMessage` (declared in
  `rebuild/backend/app/services/channels/messages.py`). The helper performs
  the DB insert (honouring the author CHECK constraint), updates
  `channel.last_message_at`, and dispatches the realtime `message:create`
  emit via `app.realtime.events.emit_message_create`. **M4 must not bypass
  this helper or call `sio.emit` directly** — the realtime/persistence
  pairing only stays consistent if every channel write path goes through it.

No milestone depends on M3 reciprocally except M5 hardening, which adds OTel
spans around the realtime emit path and the upload-bytes counter.

## Acceptance criteria

- [ ] All eight ORM tables created via a single Alembic revision; `alembic
  upgrade head` from empty DB succeeds; `alembic downgrade base` reverses
  cleanly. Re-running `alembic upgrade head` immediately after `head` and
  re-running `alembic downgrade base` after `base` are both no-ops (covered by
  the M0 idempotency tests parametrised over the `0004_m3_channels` revision).
- [ ] `test_partial_upgrade_recovers` includes an M3 case: pre-create
  `file` + `file_blob` + `channel` only (raw DDL, no indexes), then
  `alembic upgrade head` produces all eight tables, every named index, the
  `ck_channel_message_one_author` check constraint, and the
  `ROW_FORMAT=DYNAMIC` setting on `channel_message` without operator
  intervention.
- [ ] `MysqlFileStore` round-trips a 5 MiB binary blob; 5 MiB+1B is rejected
  with HTTP 413; `GET /api/files/{id}` streams in 256 KiB chunks with constant
  app-side memory.
- [ ] `app/services/channels/` contains exactly three files (`messages.py`,
  `mentions.py`, `auto_reply.py`); no per-domain CRUD wrapper files
  (`channels.py`, `members.py`, `reactions.py`, `pins.py`, `webhooks.py`,
  `files.py`) are created. CRUD endpoints live directly in
  `app/routers/{channels,channel_members,channel_messages,channel_webhooks,files}.py`.
- [ ] `app/routers/deps.py` exports `get_channel`, `get_membership`,
  `require_owner`, `require_owner_or_admin` plus the `ChannelDep`,
  `MembershipDep`, `RequireOwner`, `RequireOwnerOrAdmin` aliases. Every
  channel route uses these for permission checks (no per-handler
  `if user.role != "owner"` lines outside `routers/deps.py`; verified by an
  AST gate in `tests/test_no_inline_role_checks.py`).
- [ ] `app/realtime/events.py` is ≤80 LOC and contains no business logic
  (verified by `tests/test_events_thin.py`: every helper is `await sio.emit(room, dto)` plus payload coercion only).
- [ ] socket.io connect refuses connections without `X-Forwarded-Email`; a
  valid header auto-provisions the user via the M0 `upsert_user_from_headers`
  helper and joins all member rooms. There is no second `Users.get_or_create_by_email`
  implementation in the codebase (verified by a grep gate).
- [ ] Every event in section 6's protocol is emitted by exactly one service-
  layer code path; routers never emit directly.
- [ ] All endpoints in section 7 return correct status codes and pydantic-
  validated payloads. The OpenAPI spec under `/docs` lists every endpoint
  with examples.
- [ ] Top-level feed pagination uses `ix_channel_message_feed`
  (verified via `EXPLAIN`); thread fetch uses `ix_channel_message_thread`.
- [ ] `channel.last_message_at` is updated within the same DB transaction as
  every `channel_message` insert: an integration test
  `test_create_message_denormalises_last_message_at` posts three messages
  (one user-authored, one bot via `create_bot_message`, one webhook via
  `create_webhook_message`) into a channel and asserts after each commit
  that `SELECT last_message_at FROM channel WHERE id = ?` returns exactly
  the just-inserted message's `created_at`. The same test asserts
  `last_message_at IS NULL` for a freshly-created channel before any
  messages, and that `GET /api/channels` orders the response by descending
  `last_message_at NULLS LAST` (verified by `EXPLAIN` to use
  `ix_channel_recency`).
- [ ] `@model` mention triggers a streamed assistant reply in the same thread
  with `bot_id` set, never as a `user`. Concurrency cap = 2 per channel,
  latest-wins window = 5s, both verified by integration tests.
- [ ] Incoming webhook works without `X-Forwarded-Email`; outgoing webhook
  delivers a Slack-shape JSON envelope to a test sink within 2s of message
  creation.
- [ ] Frontend ports every component listed in section 9; no
  references remain to `tools`, `skills`, `notes`, `knowledge`, `mcp`,
  `code-interpreter`, `image-gen` modules. (Ripgrep gate in CI.)
- [ ] Every M3 store lives at `lib/stores/<name>.svelte.ts` (not `.ts`),
  exports a class instantiated via `setContext` in
  `(app)/channels/+layout.svelte`, and uses `SvelteMap` / `SvelteSet` from
  `svelte/reactivity` (never native `Map` / `Set`) for any reactive
  collection. The socket.io connection lifecycle and the typing-prune
  `setInterval` are owned by `$effect(() => { ...; return () => cleanup(); })`
  inside the channels layout — no module-scope timers anywhere under
  `frontend/src/lib/stores/`. Verified by the M0 grep gate plus a focused
  AST gate (`tests/test_no_module_scope_timers.spec.ts`) that walks the
  stores directory and rejects any `setInterval(`/`setTimeout(` outside an
  `$effect` body.
- [ ] No ported channel component uses `createEventDispatcher`, `<slot>`,
  `on:click`, `use:action`, or `$app/stores` (verified by the project-wide
  grep gate from M0).
- [ ] Optimistic posting reconciles correctly under: socket-arrives-first,
  REST-arrives-first, REST-fails, socket-disconnects-mid-post.
- [ ] Two-context Playwright test confirms 200ms median fan-out latency in CI
  on the deterministic compose stack.
- [ ] Two-replica compose configuration passes the same multi-context test —
  proves Redis-backed fan-out, no sticky sessions.
- [ ] Benchmark in section 10 hits 200ms p95 / 500ms p99 / <60% CPU at the
  declared load; results committed to `rebuild/plans/m3-bench-results.md`.
- [ ] Unit + component suites complete in <3 min wall-clock; E2E suite in <8
  min sharded across 4 workers.
- [ ] No new linter errors; mypy passes in strict mode; ruff passes.
- [ ] Visual-regression baselines `channel-feed.png` and `channel-thread.png`
  captured under `rebuild/frontend/tests/visual-baselines/m3/` (Git LFS),
  rendered against the deterministic two-user channel fixture.

## Out of scope

The following are **not** part of M3 and must be rejected in code review even
when convenient to add:

- DMs and group DMs. The legacy fork's `Channel.type in {'dm','group'}`
  branches are deleted; `channel` has no `type` column.
- Public-internet webhook delivery. The OAuth proxy fronts everything;
  incoming webhooks are an internal-network feature.
- Message editing history. `content.edited` is a single boolean; we do not
  store the prior versions. Repeated edits overwrite `content.text`.
- Message search. The legacy `search_messages_by_channel_ids` is not ported;
  it requires a fulltext index and a UI surface that aren't justified at
  initial scale.
- Audio / video calls.
- Out-of-app notifications (email, Slack pings, push). All notifications are
  in-app via socket events + the unread counter.
- Slash commands.
- Custom emoji uploads. `channel_message_reaction.emoji` accepts unicode
  codepoints and `:shortcode:`-style strings only — there is no admin UI for
  uploading PNG emoji.
- Rich-text composer (Notion/Quill-style). The composer is markdown source +
  a few keyboard shortcuts; rendering uses the M1 markdown pipeline.
- Signed URLs and any object store. Files live in `MEDIUMBLOB`; the
  `FileStore` facade is the only seam for an eventual S3 swap.
- Multi-provider routing. `@model` always targets the single
  `OpenAICompatibleProvider` from M1.
- Per-user permission grants on channels (`access_grant` table from legacy).
  Channel access is binary: member or not, role is owner/admin/member only.
- Thumbnails. Documented in section 7; revisit post-M5 if image use grows.
- Link unfurling / `embeds` population. The schema field is reserved but no
  worker is shipped.

## Open questions

- **Webhook envelope versioning.** We tag every socket payload with `v:1`,
  but the outgoing-webhook envelope shape is not versioned. Decision pending:
  add `event_version: 1` to the body, or version via URL path
  (`/webhooks/v1/...`). Defer until a second consumer exists.
- **Bot-message persistence on cancellation.** When the latest-wins cancel
  fires mid-stream, the partially-streamed `channel_message` row remains with
  whatever text accumulated. Should we (a) keep the partial text and append
  `[cancelled]`, or (b) hard-delete the row? Default plan is (a) for audit
  clarity; revisit after dogfooding.
- **Read-receipt write amplification.** `read:update` fans out channel-wide
  on every scroll-driven update. For a 100-member channel that is 100× the
  write rate of a single user's `last_read_at`. We rate-limit the FE to one
  POST per 2 seconds; if benchmarking shows Redis saturation we'll switch to
  per-user `user:{id}` room emits instead of channel-wide.
