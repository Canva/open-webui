# M2 — Conversations + history

> Milestone 1 of the Open WebUI slim rebuild. Reference the top-level plan at [rebuild.md](../../../rebuild.md). All tech, data, and auth decisions are locked there; this document only fills in the implementation detail.

## Goal

Deliver a working single-user-per-request conversation surface: a SvelteKit chat UI backed by a FastAPI app that streams completions from the internal agent gateway via the OpenAI-compatible SDK, with chats and folders persisted in MySQL 8.0 against a single JSON `history` column. By the end of M2 a Canva employee can land on the app behind the OAuth proxy, see their sidebar, start a new chat, watch tokens stream in, send follow-ups (creating a branched message tree), pin/archive/delete chats, organise them into folders, switch agents picked dynamically from the agent catalogue (the upstream gateway exposes them at the OpenAI-compatible `/v1/models` path; the rebuild surfaces them at `/api/agents`), and reload the page to see history exactly as it was. No sharing, no channels, no automations, no file uploads — those belong to later milestones.

> **Terminology note.** Each entry the rebuild surfaces is an *agent* (each agent has a preselected underlying model). The OpenAI SDK / wire format keeps the legacy field name `model` on the request body and the chunk envelope, and the upstream catalogue endpoint stays on the OpenAI path `/v1/models`; the `OpenAICompatibleProvider` is the translation seam, accepting the rebuild's `agent_id` and forwarding it as `model=` to the SDK. Internal types, the rebuild's HTTP API, frontend stores, and the UI all use "agent".

## Deliverables

- SQLAlchemy 2 async models for `chat` and `folder` under [rebuild/backend/app/models/chat.py](../../backend/app/models/chat.py) and [rebuild/backend/app/models/folder.py](../../backend/app/models/folder.py).
- A single Alembic revision creating both tables under [rebuild/backend/alembic/versions/0002_m2_chat_folder.py](../../backend/alembic/versions/0002_m2_chat_folder.py) (`revision = "0002_m2_chat_folder"`, `down_revision = "0001_baseline"`).
- An `OpenAICompatibleProvider` at [rebuild/backend/app/providers/openai.py](../../backend/app/providers/openai.py) with `stream(...)` and `list_agents()`, configured via `AGENT_GATEWAY_BASE_URL`. The provider is the translation seam: it accepts an `agent_id` from the rebuild and passes it as `model=...` to the OpenAI SDK; in the other direction it reads the SDK's `Model` objects (an SDK type — wire-format only) from `/v1/models` and projects them into the rebuild's `Agent` dataclass.
- Pydantic schemas under [rebuild/backend/app/schemas/chat.py](../../backend/app/schemas/chat.py) and [rebuild/backend/app/schemas/folder.py](../../backend/app/schemas/folder.py).
- HTTP routers under [rebuild/backend/app/routers/chats.py](../../backend/app/routers/chats.py), [rebuild/backend/app/routers/folders.py](../../backend/app/routers/folders.py), [rebuild/backend/app/routers/agents.py](../../backend/app/routers/agents.py).
- The streaming pipeline at [rebuild/backend/app/services/chat_stream.py](../../backend/app/services/chat_stream.py) — exports `prepare_stream` (pre-yield validation + first persist), `stream_assistant_response` (post-validation SSE generator), `PreparedStream` (the dataclass handed between them), `sse`, and `build_linear_thread`. See § Streaming pipeline below for the rationale of the two-function split (Phase 4c fix for the Starlette "response already started" race + leaked `SELECT FOR UPDATE` row lock).
- A reusable assistant-message writer at [rebuild/backend/app/services/chat_writer.py](../../backend/app/services/chat_writer.py) exposing `append_assistant_message(session, *, chat_id: str, parent_message_id: str | None, agent_id: str, content: str, status: Literal["complete","cancelled","error"]="complete") -> str` (returns the new message id, atomically updates `chat.history.messages[<id>]`, sets `chat.history.currentId`, and bumps `chat.updated_at`). Enforces the `MAX_CHAT_HISTORY_BYTES` cap from [m0-foundations.md § Project constants](m0-foundations.md#project-constants) on the resulting `chat.history` JSON before write — see § History-size enforcement below for the precise behaviour. Used by `chat_stream.py` (M2) and the M5 automation executor for chat-target writes.
- A title-derivation helper at [rebuild/backend/app/services/chat_title.py](../../backend/app/services/chat_title.py) exposing `derive_title(first_user_message: str) -> str` (≤ 60 chars, single line, stripped). Called by `POST /api/chats` when the body omits `title` and by the streaming pipeline on the first assistant turn for an untitled chat. Pure function so the unit test is one fixture.
- A Redis-backed stream registry at [rebuild/backend/app/services/stream_registry.py](../../backend/app/services/stream_registry.py) — module-level `StreamRegistry` singleton holding a per-pod `dict[str, asyncio.Event]` keyed by `assistant_message_id` and a thin pub/sub façade over Redis (`stream:cancel:{message_id}`) so cancel signals cross pod boundaries from day one. Exposes `register(message_id) -> asyncio.Event` (creates the local event and subscribes to the per-message Redis channel), `cancel(message_id) -> bool` (publishes to the channel; returns whether the publish succeeded; idempotent), and `unregister(message_id)` (cancels the subscription and drops the local entry; called from the streaming generator's `finally` block). Powers `POST /api/chats/{id}/messages/{assistant_id}/cancel` (M2): the cancel publishes to Redis, every pod with a local subscription for that `message_id` receives the message and sets its event, the in-flight generator catches `asyncio.CancelledError`, persists the partial assistant content via `chat_writer.append_assistant_message(..., status="cancelled")`, and emits the terminal `cancelled` SSE frame. The Redis connection is the same one M4 uses for the socket.io adapter and M6 uses for rate limits — no new infra.
- SvelteKit 2 routes under [rebuild/frontend/src/routes/(app)/](../../frontend/src/routes/(app)/) plus components under [rebuild/frontend/src/lib/components/chat/](../../frontend/src/lib/components/chat/).
- Ported markdown pipeline at [rebuild/frontend/src/lib/components/chat/Markdown/](../../frontend/src/lib/components/chat/Markdown/) and [rebuild/frontend/src/lib/utils/marked/](../../frontend/src/lib/utils/marked/) (citations/sources/embeds removed).
- Promote the M1 smoke components into dedicated routes at [rebuild/frontend/src/routes/(app)/(internal)/smoke/code-block/+page.svelte](../../frontend/src/routes/(app)/(internal)/smoke/code-block/+page.svelte) and [rebuild/frontend/src/routes/(app)/(internal)/smoke/mermaid/+page.svelte](../../frontend/src/routes/(app)/(internal)/smoke/mermaid/+page.svelte) so the M1 visual baselines `code-block-tokyo-night.png` and `mermaid-tokyo-night.png` re-target the dedicated routes (M1 currently snapshots placeholder mounts on `/settings`). The two pages mount `CodeBlockSmoke.svelte` and `MermaidSmoke.svelte` from M1 verbatim — M2 owns the markdown + Shiki + Mermaid pipeline that the smoke components were authored to exercise, so the dedicated routes are the natural M2 home. Behind a `(internal)/` route group with **no auth bypass** (still gated by the M0 trusted-header `getUser` server load that protects every `(app)/...` route): these are internal pipeline smoke surfaces, not public chrome, and only ever rendered by the visual-regression Playwright runner. Update [frontend/tests/e2e/visual-m1.spec.ts](../../frontend/tests/e2e/visual-m1.spec.ts) to point `goto()` at the new routes; the baseline filenames stay `code-block-tokyo-night.png` / `mermaid-tokyo-night.png` so existing LFS-tracked PNGs (once the M1 backfill lands per [m1-theming.md § Visual regression](m1-theming.md)) are not re-keyed.
- Svelte 5 runes-based stores at [rebuild/frontend/src/lib/stores/](../../frontend/src/lib/stores/) — one `*.svelte.ts` file per store, each exporting a class. Constructed and provided via `setContext` in `(app)/+layout.svelte`. See [m0-foundations.md § Frontend conventions (cross-cutting)](m0-foundations.md#frontend-conventions-cross-cutting) for the canonical pattern; do not redeclare it here.
- Backend tests at [rebuild/backend/tests/](../../backend/tests/) (unit + integration), frontend unit/component/e2e tests under [rebuild/frontend/tests/{unit,component,e2e}/](../../frontend/tests/).
- A recorded-cassette LLM mock under [rebuild/backend/tests/fixtures/llm/](../../backend/tests/fixtures/llm/) and a tiny replay server at [rebuild/backend/tests/llm_mock.py](../../backend/tests/llm_mock.py).
- Visual-regression baselines for `chat-empty`, `chat-streamed-reply`, and `chat-sidebar` captured under [rebuild/frontend/tests/visual-baselines/m1/](../../frontend/tests/visual-baselines/m1/) (Git LFS).
- **M1 cleanup: delete the dead `--color-status-*` literals from `frontend/src/app.css`'s M0 `@theme {}` block.** The M1 `@theme inline { --color-status-success: var(--status-success); --color-status-warning: var(--status-warning); --color-status-danger: var(--status-danger); --color-status-info: var(--status-info); }` block immediately below silently supersedes the three M0 declarations (`--color-status-success`, `--color-status-warning`, `--color-status-danger` — `--color-status-info` only exists in the M1 inline block, never in the M0 block). M1's p3b-fix dispatch flagged the redundancy. It is a **no-op delete** (zero runtime change — Tailwind utilities like `text-status-success` / `bg-status-warning/20` resolve identically before and after) and should land alongside the first M2 surface that consumes a `text-status-*` / `bg-status-*` utility (status badges, error toasts, the streaming-state dot) so the deletion is reviewed in context. The `--color-mention-sky`, `--color-signal-blue`, and `--color-signal-blue-pressed` declarations in the same M0 `@theme {}` block stay (different category, not in the M1 inline block); only the three status literals on lines 56–58 of `app.css` go.

## Data model

Two tables. Both use the database-default `utf8mb4` / `utf8mb4_0900_ai_ci` charset/collation set by the M0 baseline; no per-table override. All identifiers are 36-char **UUIDv7** (RFC 9562) strings stored as `VARCHAR(36)`, generated app-side via `from app.core.ids import new_id` (the M0 helper); the leading 48-bit ms-precision timestamp gives near-monotonic InnoDB B-tree insertion locality, so the wide composite indexes on `chat` (`ix_chat_user_updated`, `ix_chat_user_pinned_updated`, `ix_chat_user_archived_updated`, `ix_chat_user_folder_updated`) stay tight and cacheable. All timestamps are `BIGINT` epoch **milliseconds** UTC (project-wide convention, see `rebuild.md` §4). Helper: `from app.core.time import now_ms` returns `time.time_ns() // 1_000_000`.

### `chat`

```python
# rebuild/backend/app/models/chat.py
from __future__ import annotations
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.mysql import JSON as MySQLJSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Chat(Base):
    __tablename__ = "chat"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, default="New Chat")

    # Source of truth for the conversation tree. Shape documented below.
    # `dict[str, Any]` (not bare `dict`) for mypy strict; the JSON shape is
    # validated through the `History` Pydantic model on every read/write
    # boundary, never trusted raw.
    history: Mapped[dict[str, Any]] = mapped_column(
        MySQLJSON,
        nullable=False,
        server_default=text("(JSON_OBJECT('messages', JSON_OBJECT(), 'currentId', NULL))"),
    )

    folder_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("folder.id", ondelete="SET NULL"),
        nullable=True,
    )

    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))

    # Reserved for M3; declared here to avoid a follow-up ALTER. Always NULL in M2.
    # Width matches `shared_chat.id` in M3. Uniqueness is enforced by the M3-owned
    # index `ix_chat_share_id` (see m3-sharing.md), not by a column-level UNIQUE here.
    share_id: Mapped[str | None] = mapped_column(String(43), nullable=True)

    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Persistent reflection of history.currentId, materialised as a generated column
    # so the sidebar's "current branch leaf" check is index-friendly without parsing JSON.
    current_message_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        # MySQL syntax: STORED so it can be indexed without recomputation.
        server_default=text("(JSON_UNQUOTE(JSON_EXTRACT(history, '$.currentId')))"),
    )

    __table_args__ = (
        Index("ix_chat_user_updated", "user_id", "updated_at"),
        Index("ix_chat_user_pinned_updated", "user_id", "pinned", "updated_at"),
        Index("ix_chat_user_archived_updated", "user_id", "archived", "updated_at"),
        Index("ix_chat_user_folder_updated", "user_id", "folder_id", "updated_at"),
        Index("ix_chat_current_message", "current_message_id"),
    )
```

Notes on the generated column: SQLAlchemy 2 doesn't have first-class support for MySQL `GENERATED ALWAYS AS (...) STORED`, so the migration emits the DDL by hand (see the Alembic section). The `server_default` above is **not** the live source — the migration replaces the column with a true generated one. Treat the model declaration as read-only on this column.

The other "hot" lookups (`pinned`, `archived`, `folder_id`) are plain columns, not JSON, so they get ordinary composite indexes paired with `user_id` and `updated_at`. We considered functional indexes on JSON paths for these and discarded that approach: they live as scalar columns in the legacy schema for a reason and will continue to.

### `folder`

```python
# rebuild/backend/app/models/folder.py
from __future__ import annotations
from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Folder(Base):
    __tablename__ = "folder"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("folder.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    expanded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_folder_user_parent", "user_id", "parent_id"),
    )
```

Folder deletion cascades to its children but **not** to chats — chats fall back to "no folder" via the `ON DELETE SET NULL` on `chat.folder_id`. This matches the UX where deleting a folder shouldn't take its conversations down with it.

### JSON shape of `chat.history`

The schema mirrors the legacy fork (see [backend/open_webui/models/chats.py](../../../backend/open_webui/models/chats.py) lines 463–533 and [src/lib/components/chat/Chat.svelte](../../../src/lib/components/chat/Chat.svelte) around the `userMessage`/`responseMessage` constructors near line 1540) so we don't reinvent the tree algebra.

```json
{
  "messages": {
    "<message_id>": {
      "id": "<message_id>",
      "parentId": "<message_id>" | null,
      "childrenIds": ["<message_id>", ...],
      "role": "user" | "assistant" | "system",
      "content": "<text>",
      "timestamp": 1745701234,
      "agent_id": "gpt-4o" | null,
      "agentName": "GPT-4o" | null,
      "done": true,
      "error": { "message": "..." } | null,
      "cancelled": false,
      "usage": { "prompt_tokens": 12, "completion_tokens": 87, "total_tokens": 99 } | null
    }
  },
  "currentId": "<message_id>" | null
}
```

Field semantics (locked):

- **`messages`** is an object keyed by message ID, not an array. This makes O(1) updates during streaming (we mutate `history.messages[id].content`) and avoids re-encoding the whole array per delta.
- **`parentId` / `childrenIds`** form the message tree. The root user message has `parentId: null`. An assistant message's parent is always the user message it answers. Branching (regenerate, edit-and-resend) happens by adding a new child to an existing parent — `childrenIds` is then `>1` and the UI picks the active branch via `currentId`.
- **`currentId`** points at the *leaf* of the active branch — usually the latest assistant message. The reducer that flattens the tree to a linear conversation walks `parentId` from `currentId` to the root (see legacy [backend/open_webui/utils/misc.py](../../../backend/open_webui/utils/misc.py) lines 71–101 — port verbatim).
- **`done`** is `false` while a stream is in flight, `true` once persistence is final. Cancellation flips `cancelled: true` and `done: true`.
- **`usage`** is filled in only on the final SSE event from the gateway (`usage` chunk).
- **No `files`, `sources`, `embeds`, `statusHistory`, `annotation`, `mentions`, or `tasks` fields.** Those belong to scrapped features. The Pydantic validator rejects unknown fields strictly.

Concrete example: a user sends "hi", the assistant replies "hello", the user regenerates to get a second assistant response, and that second response is the active leaf:

```json
{
  "currentId": "c3",
  "messages": {
    "u1": {
      "id": "u1", "parentId": null,
      "childrenIds": ["a2", "c3"],
      "role": "user", "content": "hi",
      "timestamp": 1745701200,
      "agent_id": null, "agentName": null,
      "done": true, "error": null, "cancelled": false, "usage": null
    },
    "a2": {
      "id": "a2", "parentId": "u1",
      "childrenIds": [],
      "role": "assistant", "content": "hello",
      "timestamp": 1745701201,
      "agent_id": "gpt-4o", "agentName": "GPT-4o",
      "done": true, "error": null, "cancelled": false,
      "usage": { "prompt_tokens": 8, "completion_tokens": 1, "total_tokens": 9 }
    },
    "c3": {
      "id": "c3", "parentId": "u1",
      "childrenIds": [],
      "role": "assistant", "content": "hi there!",
      "timestamp": 1745701260,
      "agent_id": "gpt-4o-mini", "agentName": "GPT-4o mini",
      "done": true, "error": null, "cancelled": false,
      "usage": { "prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12 }
    }
  }
}
```

The Pydantic representation for round-tripping (NOT used as a column type — the column is raw JSON):

```python
# rebuild/backend/app/schemas/history.py
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
```

Both inherit from `StrictModel` (defined in M0 — see [m0-foundations.md § Pydantic conventions](m0-foundations.md#pydantic-conventions)) so unknown fields in `chat.history` JSON are rejected at the Python boundary. Every other Pydantic model in M2 (request bodies and response models below) inherits from `StrictModel` for the same reason; the per-class `model_config = ConfigDict(extra="forbid")` boilerplate is **never** repeated.

## Alembic revision

- Filename: [rebuild/backend/alembic/versions/0002_m2_chat_folder.py](../../backend/alembic/versions/0002_m2_chat_folder.py)
- `revision = "0002_m2_chat_folder"`
- `down_revision = "0001_baseline"` (the M0 baseline that creates `user`)
- `branch_labels = None`, `depends_on = None`

The migration is fully idempotent, per [rebuild.md § 9 "Robust, idempotent Alembic migrations"](../../../rebuild.md#9-decisions-locked) and the M0 helper module ([m0-foundations.md § Migration helpers](m0-foundations.md#migration-helpers)). Every step calls a `*_if_not_exists` / `*_if_exists` wrapper or `execute_if(...)` so a partial application — MySQL DDL auto-commits, so this is the realistic crash mode — re-runs cleanly. Bare `op.create_*` / `op.drop_*` / `op.add_column` / `op.execute` calls are forbidden in this revision and the entire `backend/alembic/versions/` tree (M0 ships a CI grep gate).

```python
from app.db.migration_helpers import (
    create_table_if_not_exists, drop_table_if_exists,
    create_index_if_not_exists, drop_index_if_exists,
    create_foreign_key_if_not_exists, drop_constraint_if_exists,
    has_column, execute_if,
)
```

The migration runs in this order so foreign keys resolve cleanly:

1. `create_table_if_not_exists("folder", ...)` with all columns. Self-referential FK on `parent_id` is declared inside the `create_table` call, so it lands atomically with the table itself (no separate `create_foreign_key` step needed for self-FKs).
2. `create_table_if_not_exists("chat", ...)` with every base column *except* `current_message_id`. `history` is declared as `mysql.JSON()`, `nullable=False`, with `server_default=sa.text("(JSON_OBJECT('messages', JSON_OBJECT(), 'currentId', NULL))")`. The two cross-table FKs (`chat.user_id → user.id ON DELETE CASCADE`, `chat.folder_id → folder.id ON DELETE SET NULL`) are also declared inline so they land with the table; on a re-run, the helper sees the table already exists and skips the call entirely.
3. Add the MySQL generated column out of band, guarded by an inspector check:
   ```python
   execute_if(
       not has_column("chat", "current_message_id"),
       """
       ALTER TABLE chat
       ADD COLUMN current_message_id VARCHAR(36)
       GENERATED ALWAYS AS (JSON_UNQUOTE(JSON_EXTRACT(history, '$.currentId'))) STORED
       """,
   )
   ```
   This is the one place in M2 where raw DDL is unavoidable — SQLAlchemy 2 has no first-class generated-column support and MySQL 8.0 has no `ADD COLUMN IF NOT EXISTS`. Routing through `execute_if(has_column(...) is False, ...)` keeps the migration re-runnable without a stored procedure.
4. `create_index_if_not_exists` for the four composite indexes on `chat` (`ix_chat_user_updated`, `ix_chat_user_pinned_updated`, `ix_chat_user_archived_updated`, `ix_chat_user_folder_updated`) plus `ix_chat_current_message` on the generated column. (No native `CREATE INDEX IF NOT EXISTS` in MySQL 8.0; the helper inspects `INFORMATION_SCHEMA.STATISTICS` first.)

`downgrade()` reverses in the opposite order, every step idempotent. The shape that ships:

1. `drop_index_if_exists("ix_chat_current_message", "chat")` — must run before the next step, because MySQL refuses to `DROP COLUMN` a column that is the sole referenced column of an index.
2. `execute_if(has_column("chat", "current_message_id"), "ALTER TABLE chat DROP COLUMN current_message_id, ALGORITHM=COPY, LOCK=SHARED")` — symmetric with the upgrade-side ALGORITHM/LOCK pinning so the AST gate accepts the call site.
3. `drop_table_if_exists("chat")` — cascades to the four `user_id`-leading composite indexes (`ix_chat_user_updated`, `ix_chat_user_pinned_updated`, `ix_chat_user_archived_updated`, `ix_chat_user_folder_updated`) and to both cross-table FKs.
4. `drop_table_if_exists("folder")` — cascades to `ix_folder_user_parent` and the inline self-FK.

We deliberately do **not** issue an explicit `drop_index_if_exists` for the four `user_id`-leading indexes before the table drop. InnoDB requires every FK column to be backed by an index; once we've dropped enough of the composite indexes that there's only one left covering `user_id`, MySQL rejects `DROP INDEX` on that survivor with error 1553 ("needed in a foreign key constraint"). Letting `drop_table` cascade — which is what the dispatch already promised for the inline FKs themselves — is the cleanest fix and keeps the downgrade idempotent on retry. The migration file's `downgrade()` carries the long-form rationale next to the calls.

Charset/collation: the M0 baseline configures the database default to `utf8mb4` / `utf8mb4_0900_ai_ci`. We do **not** specify `mysql_charset` or `mysql_collate` in `create_table` — the tables inherit from the database. This keeps the migration grep-clean and avoids drift between baseline and M2. (`create_table_if_not_exists` does set the engine/charset table args defensively, but the values match the database default, so no override actually fires.)

`alembic upgrade head`, `alembic downgrade -1`, and **a second `alembic upgrade head` immediately afterwards** must all succeed cleanly against an empty MySQL 8.0 instance. The first two are exercised by the M0 CI job; the idempotent re-run is asserted by `backend/tests/test_migrations.py::test_upgrade_head_is_idempotent` (added in M0, parametrised here for M2's revision). An additional M2 integration case extends `test_partial_upgrade_recovers` to simulate the realistic crash: pre-create only `folder`, run upgrade, assert `chat`, the generated column, every index, and both FKs end up present.

## Settings additions

M2 extends the M0 `Settings` class with one new field. `AGENT_GATEWAY_BASE_URL` and `AGENT_GATEWAY_API_KEY` are already declared in M0's settings table (`m0-foundations.md` § Settings) so M2 only adds the streaming timeout knob:

| Field | Type | Default | Notes |
|---|---|---|---|
| `SSE_STREAM_TIMEOUT_SECONDS` | `int` | `300` | Whole-request cap on `POST /api/chats/{id}/messages`. Wrapped around the provider iteration via `async with asyncio.timeout(...)` *inside the streaming generator* so the persist-partial branch owns the cleanup path. Must equal the M6 per-route timeout for `/api/chats/{id}/messages` (see `m6-hardening.md` § Per-route HTTP timeouts) — diverging the two means a request can be killed by the route timeout before the executor's persist-partial path runs. |

The casing convention from M0 applies (env-var key UPPER_SNAKE / Python attribute lowercase, bridged by `case_sensitive=False` — see [m0-foundations.md § Settings(BaseSettings) "Casing convention (locked)"](m0-foundations.md#settingsbasesettings)); the env var is `SSE_STREAM_TIMEOUT_SECONDS` and the Python attribute is `settings.sse_stream_timeout_seconds` everywhere.

## Provider abstraction

A single class wrapping the OpenAI Python SDK, pointed at the gateway. Everything else is unwanted complexity.

```python
# rebuild/backend/app/providers/openai.py
from __future__ import annotations
import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
from openai import AsyncOpenAI, APIError, APIStatusError, APITimeoutError, RateLimitError

from app.core.config import settings

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Agent:
    """In-process projection of a surfaced agent.

    The OpenAI SDK still calls each entry it returns from
    ``client.models.list()`` a ``Model`` (a wire-format type). The
    rebuild's product domain calls each surfaced entry an *agent* —
    each agent has a preselected underlying model. ``list_agents``
    below is the translation seam that maps SDK ``Model`` objects to
    this dataclass.
    """

    id: str
    label: str          # human-readable; falls back to id
    owned_by: str | None


@dataclass(slots=True)
class StreamDelta:
    content: str = ""        # token text, may be empty on the final chunk
    finish_reason: str | None = None
    usage: dict | None = None


class ProviderError(Exception):
    """Wrapper for upstream gateway failures. Always carries an HTTP-friendly message."""
    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class OpenAICompatibleProvider:
    """The only provider. Reads AGENT_GATEWAY_BASE_URL via the central Settings object.

    Translation seam between the rebuild's product vocabulary
    ("agent") and the OpenAI wire format ("model"): callers pass
    ``agent_id``; we forward it as ``model=`` to the OpenAI SDK and
    project the SDK's ``Model`` objects back into our own ``Agent``
    dataclass.

    Exactly one instance per app; constructed in `lifespan` and stored on
    `app.state.provider`. Routes/services receive it via the M0 `Provider`
    dependency alias. Never instantiated at module import.
    """

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            base_url=settings.agent_gateway_base_url,
            api_key=settings.agent_gateway_api_key or "unused",
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0),
            max_retries=0,  # we control retries ourselves; SDK retries don't compose with SSE.
        )

    async def aclose(self) -> None:
        """Release the underlying httpx pool. Called from lifespan shutdown."""
        await self._client.close()

    async def list_agents(self) -> list[Agent]:
        # Wire path stays on the OpenAI name `/v1/models`; the SDK
        # method is `client.models.list()`. We project each entry into
        # the rebuild's `Agent` dataclass.
        try:
            page = await self._client.models.list()
        except (APIStatusError, APIError) as e:
            raise ProviderError(f"gateway list_agents failed: {e}", status_code=502) from e

        out: list[Agent] = []
        for m in page.data:
            out.append(Agent(id=m.id, label=m.id, owned_by=getattr(m, "owned_by", None)))
        out.sort(key=lambda a: a.id)
        return out

    async def stream(
        self,
        *,
        messages: list[dict[str, Any]],   # OpenAI-shape: [{"role": "...", "content": "..."}]
        agent_id: str,
        params: dict[str, Any],           # {"temperature": 0.7, "system": "..."} subset only
    ) -> AsyncIterator[StreamDelta]:
        # `system` is optional — if present we prepend it.
        msgs = list(messages)
        if params.get("system"):
            msgs.insert(0, {"role": "system", "content": params["system"]})

        # The OpenAI SDK keyword is `model=`, even though we accept
        # an `agent_id` from the rebuild — this is the translation seam.
        kwargs: dict[str, Any] = {
            "model": agent_id,
            "messages": msgs,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if "temperature" in params:
            kwargs["temperature"] = params["temperature"]

        try:
            stream = await self._client.chat.completions.create(**kwargs)
        except APITimeoutError as e:
            raise ProviderError("upstream timeout", status_code=504) from e
        except RateLimitError as e:
            raise ProviderError("upstream rate-limited", status_code=429) from e
        except APIStatusError as e:
            raise ProviderError(
                f"upstream {e.status_code}: {e.message}", status_code=502
            ) from e

        try:
            async for chunk in stream:
                # OpenAI SSE shape: chunks have either a delta on choices[0] or a usage block.
                if chunk.usage is not None:
                    yield StreamDelta(usage=chunk.usage.model_dump())
                    continue
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = StreamDelta(
                    content=(choice.delta.content or ""),
                    finish_reason=choice.finish_reason,
                )
                yield delta
        except asyncio.CancelledError:
            await stream.close()
            raise
        except APIError as e:
            raise ProviderError(f"stream interrupted: {e}", status_code=502) from e
```

The provider is constructed exactly once in `lifespan` and exposed via a dependency. There is **no** module-level singleton — that would (a) run before `Settings` is fully resolved in some test paths, (b) be impossible to override via `app.dependency_overrides` in unit tests, and (c) confuse Uvicorn worker-fork semantics if we ever moved off the lifespan-per-process model. The wiring (constructor in `app/main.py`, dependency in `app/core/deps.py`) is:

```python
# rebuild/backend/app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.providers.openai import OpenAICompatibleProvider

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.provider = OpenAICompatibleProvider()
    try:
        yield
    finally:
        await app.state.provider.aclose()

app = FastAPI(lifespan=lifespan)
```

```python
# rebuild/backend/app/core/deps.py  (extends the M0 file)
from typing import Annotated
from fastapi import Depends, Request

from app.providers.openai import OpenAICompatibleProvider


def get_provider(request: Request) -> OpenAICompatibleProvider:
    return request.app.state.provider


Provider = Annotated[OpenAICompatibleProvider, Depends(get_provider)]
```

Routes and services that need the provider take it as a parameter:

```python
async def stream_assistant_response(*, provider: Provider, ...) -> AsyncIterator[bytes]: ...

@router.post("/api/chats/{id}/messages")
async def post_message(
    id: str, body: MessageSend,
    user: CurrentUser, db: DbSession, provider: Provider,
) -> StreamingResponse: ...
```

Tests fake the provider with `app.dependency_overrides[get_provider] = lambda: FakeProvider()` — no monkey-patching of module-level names, no special test-only imports.

Notes:

- `AGENT_GATEWAY_BASE_URL` and `AGENT_GATEWAY_API_KEY` (optional; injected by the gateway sidecar in prod) live on the central `Settings(BaseSettings)` from M0. No other env knobs.
- **Retries.** Zero SDK-level retries. We don't retry mid-stream — partial assistant content is already on the wire and visible to the user. For `list_agents()` we let the caller retry by reissuing the HTTP request; the frontend already polls on the agent dropdown open.
- **Cancellation.** The route handler propagates `asyncio.CancelledError` (raised by Starlette when the client disconnects); the provider catches it, calls `await stream.close()` to release the connection, and re-raises. This stops billing and frees the upstream slot.
- **Errors.** Everything funnels into `ProviderError(status_code=...)`. The streaming generator (`stream_assistant_response`) catches these in its outer `except ProviderError:` branch, persists the partial assistant content with `error: {...}, done: true`, and yields a terminal SSE `error` event before returning. Non-streaming endpoints turn the same exception into HTTP errors via the central handler in `app/core/errors.py`.

## API surface

All routes are mounted under `/api`. All require `get_user` from M0. JSON in, JSON out, except the streaming endpoint.

### Chat CRUD

`GET /api/chats` — list current user's chats.

- Query: `folder_id?: str | "none"`, `archived?: bool=false`, `pinned?: bool`, `q?: str`, `limit?: int=50` (≤200), `cursor?: str` (opaque, encodes `(updated_at, id)`).
- Response:
  ```python
  class ChatSummary(StrictModel):
      id: str
      title: str
      pinned: bool
      archived: bool
      folder_id: str | None
      created_at: int
      updated_at: int
  class ChatList(StrictModel):
      items: list[ChatSummary]
      next_cursor: str | None
  ```
- Errors: 401 missing header (handled by `get_user`).

`POST /api/chats` — create a new (empty) chat.

- Body:
  ```python
  class ChatCreate(StrictModel):
      title: str | None = None
      folder_id: str | None = None
  ```
- Response: `ChatRead` (full chat with empty `history`).
- Errors: 404 if `folder_id` doesn't belong to the user.

`GET /api/chats/{id}` — full chat including `history`.

- Response: `ChatRead`:
  ```python
  class ChatRead(ChatSummary):
      history: History  # the schema above
      share_id: str | None  # always None in M2
  ```
- Errors: 404 if not found or not owned.

`PATCH /api/chats/{id}` — partial update of metadata.

- Body:
  ```python
  class ChatPatch(StrictModel):
      title: str | None = None
      folder_id: str | None = None  # null to detach
      pinned: bool | None = None
      archived: bool | None = None
  ```
- Response: `ChatRead`.
- Errors: 404, 422.

`DELETE /api/chats/{id}` — hard delete. Returns `204`.

`POST /api/chats/{id}/title` — convenience wrapper used by the auto-title task (still M2 because it sits on the same provider). Body `{ "messages": [...] }`, response `{ "title": str }`. Calls the provider with a fixed system prompt asking for a ≤6 word title. Non-streaming. Skipped in M2 if it slips — it's a "nice to have" once the streaming path is solid.

### Folder CRUD

`GET /api/folders` — flat list (UI builds the tree client-side).

- Response: `list[FolderRead]` with `id, parent_id, name, expanded, created_at, updated_at`.

`POST /api/folders` — create.

- Body:
  ```python
  class FolderCreate(StrictModel):
      name: str
      parent_id: str | None = None
  ```
- Errors: 422 on empty name; 404 on missing parent; 409 on cycle (server checks parent chain — see "Cycle detection" below).

`PATCH /api/folders/{id}` — rename, move (`parent_id`), or toggle `expanded`. Same cycle check applies whenever `parent_id` changes (a folder cannot be moved into one of its own descendants).

`DELETE /api/folders/{id}` — cascades to descendant folders. Chats inside are detached (their `folder_id` becomes `NULL`).

- Response (200):
  ```python
  class FolderDeleteResult(StrictModel):
      deleted_folder_ids: list[str]   # the target folder + every descendant
      detached_chat_ids: list[str]    # chats whose folder_id was just set to NULL
  ```
- The frontend `folders` and `chats` stores consume this payload to update in place; without it, the sidebar has to refetch both lists after every folder deletion.

#### Cycle detection and descendant computation (recursive CTE)

Both the cycle check (on `POST` and `PATCH`) and the descendant set (for `DELETE`) are computed in a single MySQL 8.0 recursive CTE — one round-trip instead of N Python-side `SELECT` hops, and a hard guard against pathological depths via the session variable `cte_max_recursion_depth = 256` (default 1000 is excessive for a folder tree the user maintains by hand).

`cte_max_recursion_depth = 256` is set per-statement, not per-connection. The folder router executes `await session.execute(text("SET SESSION cte_max_recursion_depth = 256"))` immediately before each recursive CTE, inside the same transaction. We deliberately do **not** wire it onto the SQLAlchemy `engine.connect` event (a) because every other statement in the codebase wants the default 1000 — silently lowering it globally would surface as confusing "max recursion" errors anywhere a future migration adds a deeper CTE — and (b) so the value is visible at the call site for code review. The constant `FOLDER_CTE_MAX_DEPTH = 256` lives in `app/services/folders.py` next to the CTE, not in `app/core/constants.py`, because it is intrinsic to this query rather than a project-wide tunable.

**Cycle check** (used by `POST` when `parent_id` is set, and by `PATCH` when `parent_id` changes). Walk *upward* from the candidate `parent_id` toward the root; if the folder being created/moved appears in the visited set, the move would create a cycle:

```sql
WITH RECURSIVE ancestors AS (
    SELECT id, parent_id, 0 AS depth
    FROM folder
    WHERE id = :candidate_parent_id AND user_id = :user_id
    UNION ALL
    SELECT f.id, f.parent_id, a.depth + 1
    FROM folder f
    JOIN ancestors a ON f.id = a.parent_id
    WHERE f.user_id = :user_id AND a.depth < 256
)
SELECT 1 FROM ancestors WHERE id = :folder_being_moved LIMIT 1;
```

A non-empty result → `409 cycle`. The `user_id` filter on every iteration is intentional (defence in depth — the FK already enforces it, but a buggy future revision shouldn't accidentally walk into another user's tree).

**Descendant set** (used by `DELETE`). Walk *downward* from the target folder, collecting every descendant id in one pass:

```sql
WITH RECURSIVE descendants AS (
    SELECT id, parent_id, 0 AS depth
    FROM folder
    WHERE id = :folder_id AND user_id = :user_id
    UNION ALL
    SELECT f.id, f.parent_id, d.depth + 1
    FROM folder f
    JOIN descendants d ON f.parent_id = d.id
    WHERE f.user_id = :user_id AND d.depth < 256
)
SELECT id FROM descendants;
```

The router executes the CTE first, then issues `UPDATE chat SET folder_id = NULL WHERE folder_id IN (...)` (capturing `detached_chat_ids` from the rowset) and finally `DELETE FROM folder WHERE id IN (...)`. The whole sequence is wrapped in one `BEGIN ... COMMIT` so partial failures roll back cleanly. The DB-level FK cascade (`folder.parent_id ON DELETE CASCADE`, `chat.folder_id ON DELETE SET NULL`) is still in place as a belt-and-braces guarantee — the recursive CTE exists to populate the *response*, not to do the cascade itself.

### Agents

`GET /api/agents` — projection of the gateway's `/v1/models` (the upstream wire path stays on its OpenAI name).

- Response:
  ```python
  class AgentInfo(StrictModel):
      id: str
      label: str
      owned_by: str | None
  class AgentList(StrictModel):
      items: list[AgentInfo]
  ```
- Errors: 502/504 mirror provider errors.
- Caching: results are cached for 5 minutes in-process with background refresh, matching the cache TTL used by the M4 channel `@agent` resolver. Both the `/api/agents` router and the channel resolver share the same `provider.list_agents()` cache instance.

### SSE streaming

`POST /api/chats/{id}/messages` — append a user message and stream the assistant reply.

- Body:
  ```python
  class MessageSend(StrictModel):
      content: str                      # the user prompt; required, non-empty
      agent_id: str                     # must appear in the cached agent catalogue
      parent_id: str | None = None      # branch off this message; defaults to history.currentId
      params: ChatParams = ChatParams() # temperature, system

  class ChatParams(StrictModel):
      temperature: float | None = None  # 0..2
      system: str | None = None         # optional system prompt override
  ```
- Response: `text/event-stream`. Content-Type set explicitly. `Cache-Control: no-cache`, `X-Accel-Buffering: no` (for nginx environments).
- Errors *before* streaming starts: 404 on chat not found, 400 on empty content, 422 on schema validation, 502/504 on provider list-agents failure (we validate agent membership against the cached agent catalogue, which the provider sources from the upstream `/v1/models`).
- Errors *during* streaming: terminal SSE `error` event (see below); the HTTP status is already 200 because headers have been sent.

SSE event types (each event has both `event:` and `data:` lines, separated by `\n\n`; UTF-8; JSON-encoded payloads):

| event | data shape | when |
|---|---|---|
| `start` | `{ "user_message_id": str, "assistant_message_id": str }` | After the chat row has been updated with the user message and a placeholder assistant message; before any provider call. |
| `delta` | `{ "content": str }` | For each non-empty token chunk from the provider. |
| `usage` | `{ "prompt_tokens": int, "completion_tokens": int, "total_tokens": int }` | Once, just before `done`, when the provider sends its usage block. May be omitted if the gateway doesn't return it. |
| `done` | `{ "assistant_message_id": str, "finish_reason": str \| null }` | On normal completion; the assistant message has been persisted with `done: true`. |
| `error` | `{ "message": str, "status_code": int }` | On provider failure; the partial content is still persisted with `error: {...}` and `done: true`. |
| `cancelled` | `{ "assistant_message_id": str }` | When the client disconnects; the assistant message is persisted with `cancelled: true, done: true`. |
| `timeout` | `{ "assistant_message_id": str, "limit_seconds": int }` | When the whole-request `SSE_STREAM_TIMEOUT_SECONDS` cap (default 300) is hit by the in-generator `async with asyncio.timeout(...)` block; the partial assistant content is persisted with `cancelled: true, done: true` (same persistence shape as `cancelled`). The frame is distinct so the UI can render an "exceeded time limit" affordance instead of a generic cancellation. |

Heartbeat: a `: keep-alive\n\n` comment is sent every `STREAM_HEARTBEAT_SECONDS` (default 15s; the project-wide constant from [m0-foundations.md § Project constants](m0-foundations.md#project-constants), shared with M4 socket.io) during quiet stretches to keep proxies from timing out. Do not hard-code the cadence — import the constant.

`POST /api/chats/{id}/messages/{message_id}/cancel` — explicit cancel for cases where the client can't drop the connection (e.g. multi-tab share). Looks up the in-process stream task by `message_id` and cancels it. Returns 204. Best-effort; if the stream already finished, returns 204 anyway. Implementation details under "Streaming pipeline".

## Streaming pipeline

Lives in `app.services.chat_stream`. The module exports five public symbols — `prepare_stream`, `stream_assistant_response`, `PreparedStream`, `sse`, `build_linear_thread` — used together by `app.routers.chats.post_message` to implement `POST /api/chats/{id}/messages`. The legacy fork's 5,057-line orchestrator is replaced by this two-function split.

### Why two functions, not one (Phase 4c rationale)

The original dispatch shipped a single `stream_chat(...)` async generator that did both pre-flight validation (chat lookup, agent membership, history-cap, user-message persist) and the streaming body. Phase 4c discovered two real bugs in that shape and split the pipeline at the `await db.commit()` boundary to fix them:

1. **Starlette "response already started" race.** Any `HTTPException` raised inside the generator (404 on missing chat, 400 on unknown agent, 413 on initial cap overflow) fires *after* `StreamingResponse` has already sent `http.response.start` with status 200. FastAPI's exception handlers cannot rewrite a status that's already on the wire, so the client received a 200 with an empty body instead of the intended JSON error.
2. **Leaked `SELECT FOR UPDATE` row lock.** The pre-flight `SELECT ... FOR UPDATE` lock on the chat row was held across the entire provider iteration (potentially 5 minutes), serialising any other write against that chat behind the in-flight stream. With the M5 automation executor's chat-target write coming online, this becomes a real contention path.

The fix: validation and the first persist run synchronously from the route's perspective in `prepare_stream`, releasing the lock before the route returns the `StreamingResponse`. The post-validation generator (`stream_assistant_response`) opens the response body and owns the SSE event taxonomy, the persist throttle, and the four terminal branches. The split is load-bearing — collapsing it back into one function silently re-introduces both bugs.

### Public surface

```python
# app/services/chat_stream.py

@dataclass(slots=True)
class PreparedStream:
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
    """Pre-yield validation + first persist. Raises HTTPException(404) on
    missing chat, HTTPException(400) on unknown agent, or
    HistoryTooLargeError (→ 413 via the M0 central handler) on initial
    cap overflow. All three surface as proper JSON HTTP responses
    because the response body has not opened yet."""


async def stream_assistant_response(
    *,
    db: AsyncSession,
    provider: OpenAICompatibleProvider,
    registry: StreamRegistry,
    prepared: PreparedStream,
) -> AsyncIterator[bytes]:
    """The post-validation SSE generator. Yields raw SSE byte frames
    plus periodic ``: keep-alive\n\n`` heartbeats. Owns the four
    terminal branches (cancel / timeout / mid-stream cap overflow /
    provider error) and the normal-completion done frame."""


def sse(event: str, data: Any) -> bytes: ...
def build_linear_thread(history: History, *, parent_id: str) -> list[HistoryMessage]: ...
```

The route wires them together:

```python
# app/routers/chats.py

@router.post("/chats/{chat_id}/messages", response_class=StreamingResponse)
async def post_message(
    chat_id: str, body: MessageSend, user: CurrentUser,
    db: DbSession, provider: Provider,
    registry: StreamRegistryDep, agents_cache: AgentsCacheDep,
) -> StreamingResponse:
    prepared = await prepare_stream(
        chat_id=chat_id, user=user, body=body, db=db, agents_cache=agents_cache,
    )
    return StreamingResponse(
        stream_assistant_response(
            db=db, provider=provider, registry=registry, prepared=prepared,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

### `prepare_stream` — pre-yield validation

Runs four steps, in order, all before any byte hits the response wire:

1. **Load + authorise.** `SELECT ... FROM chat WHERE id = :id AND user_id = :uid FOR UPDATE`. Returns the chat row or raises `HTTPException(404, "chat not found")`. The `FOR UPDATE` lock is intentional: it serialises concurrent writes against the same chat (e.g. an M5 automation executor's chat-target write colliding with this in-flight stream) and is released by the commit at step 4.
2. **Agent membership.** `agents_cache.contains(body.agent_id)` — on miss, refresh once and recheck. On second miss, raise `HTTPException(400, "unknown agent: ...")`.
3. **Seed history.** Mutate the in-memory `History` to insert the user message + an empty assistant placeholder. The assistant id is pre-allocated via `new_id()` here (not inside the generator) so `prepare_stream` can return both ids and the cancel registry can key on the assistant id from the moment the response opens. Set `chat.title` via `derive_title(body.content)` if the chat is untitled.
4. **Enforce cap + commit.** `_enforce_history_cap(history.model_dump())` raises `HistoryTooLargeError` (mapped to 413 by the M0 central handler in `app/core/errors.py`) if the serialised JSON exceeds `MAX_CHAT_HISTORY_BYTES`. Otherwise assign back, bump `updated_at`, and `await db.commit()` — releasing the row lock before the route returns.

All three error classes (404 / 400 / 413) reach the client as proper JSON HTTP responses because they are raised before `StreamingResponse` opens the response body.

### `stream_assistant_response` — the SSE generator

The generator structure (consult `app/services/chat_stream.py` for the full implementation; the shape below is the binding contract):

```text
# Re-attach the chat row to the (now-detached) session — load-bearing one-liner;
# see the § "Re-attach contract" note below for why this is required, not optional.
db.add(chat)

yield sse("start", {"user_message_id": ..., "assistant_message_id": ...})

cancel_event = await registry.register(assistant_msg.id)

try:
    try:
        # Whole-request cap enforced INSIDE the generator so the persist-partial
        # branch owns the cleanup path. asyncio.timeout (Python 3.11+) raises
        # TimeoutError at the async-with boundary — distinct from CancelledError
        # so the timeout branch can emit its own "timeout" SSE frame. The M6
        # route-layer timeout dependency is set to the same value as a backstop
        # but the in-generator deadline is the primary cap.
        async with asyncio.timeout(settings.sse_stream_timeout_seconds):
            async for delta in provider.stream(messages=..., agent_id=..., params=...):
                if cancel_event.is_set():
                    raise asyncio.CancelledError

                if delta.content:
                    accumulated.append(delta.content)
                    yield sse("delta", {"content": delta.content})

                if delta.usage:
                    assistant_msg.usage = delta.usage
                    yield sse("usage", delta.usage)

                # Persist the in-progress assistant content periodically so a
                # server crash doesn't lose minutes of streaming. The cap is
                # enforced on every checkpoint — overflow during streaming
                # surfaces via the HistoryTooLargeError branch below as a
                # terminal "error" SSE frame, not as an HTTPException.
                if monotonic() - last_persist > PERSIST_EVERY_S:
                    assistant_msg.content = "".join(accumulated)
                    payload = history.model_dump()
                    _enforce_history_cap(payload)
                    chat.history = payload
                    await db.commit()
                    last_persist = monotonic()
    except TimeoutError:
        # SSE_STREAM_TIMEOUT_SECONDS exceeded.
        yield await _close_with_timeout(...)
        return
except asyncio.CancelledError:
    # Client disconnect OR explicit /cancel via Redis pub/sub — same shape.
    yield await _close_with_cancel(...)
    return
except HistoryTooLargeError:
    # Mid-stream cap hit — truncate accumulated content to fit, persist,
    # emit terminal "error" with code="history_too_large".
    yield await _close_with_history_overflow(...)
    return
except ProviderError:
    # Upstream gateway failure — persist partial with error: {...}, emit "error".
    yield await _close_with_provider_error(...)
    return
finally:
    if state.pending_next is not None and not state.pending_next.done():
        state.pending_next.cancel()
    await registry.unregister(assistant_msg.id)

# Normal completion path.
assistant_msg.content = "".join(accumulated)
assistant_msg.done = True
payload = history.model_dump()
_enforce_history_cap(payload)
chat.history = payload
chat.updated_at = now_ms()
await db.commit()
yield sse("done", {"assistant_message_id": ..., "finish_reason": state.finish_reason})
```

### Re-attach contract (`db.add(chat)` at the top of the generator)

Note the `db.add(chat)` re-attach at the top of `stream_assistant_response`. FastAPI's `Depends(get_session)` `async with` exits the moment the route handler returns the `StreamingResponse` — *before* Starlette starts iterating the generator body. The `AsyncExitStack` that owns the dependency yield-cleanup unwinds at the boundary of the route function, not after the response body is sent. The session's `close()` clears the identity map and detaches every persistent object (including `chat`), so subsequent `await db.commit()` calls in the persist throttle and terminal branches would silently no-op (no UPDATE issued).

`db.add(chat)` re-attaches the persistent object so the unit-of-work resumes tracking attribute mutations; the row is not re-INSERTed because its primary key matches an existing row. This is empirically observed (Phase 4c session-yield/teardown log probes) and documented project-wide in [`FastAPI-best-practises.md` § A.7](../best-practises/FastAPI-best-practises.md#a7-streaming-responses-sse) so future SSE routes don't re-discover the trap. The reference worked example for the pattern is `app/services/chat_stream.py::stream_assistant_response`.

### Helpers and registry

`sse(event, data)` is a 3-line helper: `f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()`.

`StreamRegistry` is a thin façade over **Redis pub/sub** with an in-process `{message_id: asyncio.Event}` cache. The app is deployed multi-replica from day one (M6 ships >1 pod and channels in M4 require Redis-adapter socket.io across pods), so cancel signals must cross pod boundaries.

Implementation:

- `register(message_id) -> Event`: creates a local `asyncio.Event` and subscribes to Redis channel `stream:cancel:{message_id}`. The subscription handler sets the local event when a cancel message arrives.
- `cancel(message_id)`: publishes `1` to `stream:cancel:{message_id}`. The pod actually running the stream receives the message via its subscription and sets the local event; pods not running this stream simply receive a no-op message and ignore it. `cancel()` is idempotent and best-effort: if the stream already finished it has unsubscribed already.
- `unregister(message_id)`: cancels the subscription and drops the local entry. Always called in a `finally` block.

Subscriptions are short-lived (one per active stream) so the Redis pubsub footprint is small. The Redis connection is the same one used by the socket.io adapter; no new infra.

Cancellation contract (always honoured by the generator):

> The streaming generator must catch `asyncio.CancelledError` *and* `asyncio.TimeoutError`, persist the partial assistant content with `cancelled=True, done=True` via the same `chat.history` write path as the success branch, emit the terminal `cancelled` (or `timeout`) SSE event, and **return** (not re-raise — the SSE stream is already closed cleanly from the client's perspective). Skipping any of these three steps leaves a `done=False` zombie row that the M6 sweeper would later have to clean up. The pseudo-code above shows this exact shape; copy it.

Cancellation paths:

1. **Client disconnect.** Starlette raises `CancelledError` inside the generator on the originating pod. No Redis hop needed.
2. **Explicit `/cancel`.** Reaches any pod via the load balancer; publishes to Redis; the originating pod's subscription sets the local event; next loop iteration raises `CancelledError`.
3. **Server shutdown.** `lifespan` cancels all in-flight tasks; same path.

Timeouts:

- Per-stream: 120 s read on each chunk (provider's `httpx.Timeout(read=120.0)`). Exceeded → `ProviderError(504)` → `error` event.
- Whole-request: a hard 5-minute cap enforced inside the generator via `async with asyncio.timeout(settings.sse_stream_timeout_seconds)` wrapped around the provider iteration. Configurable via the `SSE_STREAM_TIMEOUT_SECONDS` env var (default 300). On exceedance the generator catches `TimeoutError`, persists the partial assistant content with `cancelled=True, done=True`, and emits a terminal `timeout` SSE frame (`data: {"assistant_message_id": "...", "limit_seconds": 300}`) before returning. The cap lives inside the generator (not in the route-layer `timeout(seconds)` dependency from M6) so the persist-partial branch always owns the cleanup path; the M6 route timeout remains in place as a backstop and is set to the same 300 s value, so neither tripping nor diverging is possible. Do not diverge the two values.

Partial-message persistence semantics — the loop above guarantees:

- After the user lands on `/api/chats/{id}` mid-stream and reloads, they see the user message and whatever assistant content has already been persisted (≤1 s old).
- A crashed server resumes with the last persisted content; the assistant message stays `done: false` (the UI shows a "stream interrupted" affordance). A future M6 ticket sweeps zombie `done: false` rows older than N minutes; not in scope here.

### History-size enforcement

Every `chat.history` write in M2 (`chat_writer.append_assistant_message`, the user-message append in `POST /api/chats/{id}/messages`, and the per-second checkpoint inside `chat_stream.py`) caps the serialised JSON at `MAX_CHAT_HISTORY_BYTES` (1 MiB, declared in [m0-foundations.md § Project constants](m0-foundations.md#project-constants)). The check sits inside `chat_writer.py` as a single helper:

```python
from app.core.constants import MAX_CHAT_HISTORY_BYTES

def _enforce_history_cap(history: dict[str, Any]) -> None:
    encoded = json.dumps(history, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_CHAT_HISTORY_BYTES:
        raise HistoryTooLargeError(size=len(encoded), cap=MAX_CHAT_HISTORY_BYTES)
```

`HistoryTooLargeError` is mapped to `HTTPException(status_code=413, detail="chat history exceeds 1 MiB cap")` by the M0 `app/core/errors.py` exception handler for the request-side path. The streaming generator catches it inside the persist loop, emits a terminal `error` SSE frame (`data: {"assistant_message_id": "...", "code": "history_too_large"}`), persists the partial assistant content **truncated to fit** with `done=True, error={"code": "history_too_large"}`, and returns. The M5 automation executor's chat-target call site (`m5-automations.md` § Execute pipeline) catches the same exception and records it on `automation_run.error`. Covered by `tests/integration/test_streaming.py::test_history_cap_413_on_oversized_user_message` and `tests/unit/test_history_tree.py::test_enforce_cap_rejects_oversized_payload`.

## Frontend routes and components

Route tree under [rebuild/frontend/src/routes/](../../frontend/src/routes/):

```
src/routes/
  +layout.svelte                # global app shell (sidebar + main pane), Tailwind reset
  +layout.server.ts             # SSR check: read X-Forwarded-Email, redirect to /401 if missing
  (app)/
    +layout.svelte              # signed-in shell (sidebar, agent selector, "+ new chat")
    +layout.server.ts           # loads sidebar list + folder list once per navigation
    +page.svelte                # / — empty-state landing screen ("start a conversation")
    c/
      [id]/
        +page.svelte            # /c/[id] — conversation view
        +page.server.ts         # loads the full chat for SSR, then SPA takes over
  401/
    +page.svelte                # auth failure
```

Key components under [rebuild/frontend/src/lib/components/chat/](../../frontend/src/lib/components/chat/):

- **`Sidebar.svelte`** — folder tree + chat list. Subscribes to `chats` and `folders` stores. Drag-and-drop for moving chats; right-click menu for pin/archive/rename/delete. Virtualised with `content-visibility: auto` (port the v0.9.2 trick from legacy [src/lib/components/](../../../src/lib/components/)).
- **`ConversationView.svelte`** — receives chat ID from the route, calls `activeChat.load(id)`, renders the message list and the input. Owns the streaming lifecycle.
- **`MessageList.svelte`** — pure render: maps the linear thread (built by walking `currentId → parentId`) to `<Message />` components. Branch chevrons (`< 2 / 3 >`) appear on messages whose parent has multiple children; clicking switches `currentId` and the linear thread re-derives.
- **`Message.svelte`** — single message bubble. User messages: plain text. Assistant messages: `<Markdown />` while `done` is true; live-rendered tokens while streaming. Footer shows agent name and (if present) usage on hover.
- **`MessageInput.svelte`** — single textarea, agent selector dropdown, system-prompt + temperature in a collapsed disclosure, Enter to send, Shift+Enter for newline, Esc to cancel an in-flight stream. ~200 LOC max — explicitly *not* a port of the 2.1k-line legacy file. Copy interaction patterns, not code.
- **`Markdown.svelte`** — see "Markdown port" below.
- **`AgentSelector.svelte`** — populated from the `agents` store; shows a search input when there are >10 agents.
- **`FolderTree.svelte`** — recursive component used inside `Sidebar`.

State + data flow for the streaming send (the most complex flow in M2):

1. User types and hits Enter. `MessageInput` calls `activeChat.send({ content, agent_id, params })`.
2. The store optimistically inserts a `pending` user message and an empty assistant message into its in-memory `history`. UI re-renders immediately.
3. The store opens `fetch("/api/chats/{id}/messages", { method: "POST", body, signal })` and reads the body as a `ReadableStream`. A small `parseSSE(stream)` helper yields `{event, data}` records.
4. On `start`: replace the optimistic IDs with the server-assigned ones (`user_message_id`, `assistant_message_id`) so subsequent edits/branches use the canonical keys.
5. On `delta`: append `data.content` to `history.messages[assistant_id].content`. The `<Message>` component is rune-reactive and re-renders.
6. On `usage`: store the usage block.
7. On `done` / `cancelled` / `error`: flip the assistant message's status flags, surface a toast on `error`, and stop reading.
8. If the user hits Esc, the input component calls `activeChat.cancel()`, which calls `controller.abort()` on the `AbortController` the store is holding. The browser drops the connection, the server lands in the `CancelledError` branch, and the SSE side already stops yielding. The store's lifecycle (controller registration + abort on cancel/unmount) is anchored in `ConversationView.svelte`'s top-level `$effect`, never in module-scope `setInterval`/`setTimeout` or in `onMount`/`onDestroy` (see [m0-foundations.md § Frontend conventions (cross-cutting)](m0-foundations.md#frontend-conventions-cross-cutting), rule 3).

Optimistic message append, streaming token render, and error states all live in this one store action. No separate websocket, no SSR-hydration of streams.

Tailwind 4 utility approach: the M0 baseline ships `@tailwindcss/vite` with a single CSS entry point at `src/app.css`. Components only use utility classes; no per-component CSS files except for the markdown renderer's typographic resets and code-block styling, which live next to `Markdown.svelte` as a short scoped `<style>` block. No `tailwind.config.*` JS hacks; everything that needs theming goes through CSS variables on `:root`.

SSR vs SPA boundary: the layout `+layout.server.ts` runs server-side and pre-fetches the sidebar + folders so the initial paint is meaningful. `/c/[id]/+page.server.ts` server-loads the full chat (including history). After hydration, all subsequent navigation is client-side via `goto()` and the stores. Streaming SSE is **never** SSR-rendered — the client opens it after hydration.

## Markdown port

Source: legacy [src/lib/components/chat/Messages/Markdown.svelte](../../../src/lib/components/chat/Messages/Markdown.svelte) and the directory at [src/lib/components/chat/Messages/Markdown/](../../../src/lib/components/chat/Messages/Markdown/), plus the marked extensions at [src/lib/utils/marked/](../../../src/lib/utils/marked/).

**Keep and port:**

- `Markdown.svelte` (the orchestrator) → [rebuild/frontend/src/lib/components/chat/Markdown/Markdown.svelte](../../frontend/src/lib/components/chat/Markdown/Markdown.svelte).
- `MarkdownTokens.svelte` and `MarkdownInlineTokens.svelte` (and the `TextToken`, `CodespanToken` children) → renamed into `Markdown/Tokens.svelte` and `Markdown/InlineTokens.svelte`.
- `KatexRenderer.svelte` (math).
- `AlertRenderer.svelte` (GitHub-style alerts).
- `ColonFenceBlock.svelte` (mermaid + iframe-able blocks). Keep mermaid; drop any non-mermaid colon-fence types that referenced legacy features.
- `HTMLToken.svelte` (sanitised HTML pass-through).
- `ConsecutiveDetailsGroup.svelte` (collapses adjacent `<details>` blocks).
- `marked/extension.ts`, `marked/katex-extension.ts`, `marked/colon-fence-extension.ts`, `marked/strikethrough-extension.ts`, `marked/footnote-extension.ts` → ported as-is.
- `CodeBlock.svelte` (syntax highlighting + copy/download). Trim the "open in artefact"/"send to canvas" buttons to just copy + download.

**Delete entirely from the port:**

- `Source.svelte`, `SourceToken.svelte` — citation/RAG bubbles. Out of scope; we have no retrieval.
- `marked/citation-extension.ts` — the `[1]`/`[doc:...]` markup parser. Deleted.
- `MarkdownInlineTokens/MentionToken.svelte` — `@user` / `#channel` mentions. M4 introduces channels; until then the mention extension is a footgun. Delete the file; remove the three `mentionExtension(...)` `marked.use` calls.
- `MarkdownInlineTokens/NoteLinkToken.svelte` — note linking; we don't have notes.
- Any `embed` / `source` / `tasks` / `tool_calls` / `code_interpreter` / `reasoning` token branches in `MarkdownTokens.svelte`. The "details group" stays for plain `<details>` HTML, but the `GROUPABLE_DETAIL_TYPES` set shrinks to `new Set([])` (i.e. no special collapsing), and the `tool_calls` / `reasoning` / `code_interpreter` branches are deleted in the same diff.
- `replaceTokens` and `processResponseContent` from `$lib/utils` — they pull in unrelated legacy helpers. Reimplement as two small pure functions in [rebuild/frontend/src/lib/utils/markdown.ts](../../frontend/src/lib/utils/markdown.ts) covering only: closed-fence detection (so streaming code blocks render as they arrive) and `<` HTML-escape on raw text. ~40 LOC.

Sanitisation: keep the existing DOMPurify-backed approach in `HTMLToken.svelte`. Add an explicit unit test that the `javascript:` URL scheme is stripped, `<script>` is blocked, and `onerror=` attributes are dropped — these were the three legacy regression points.

## Stores and state

Svelte 5 runes-based stores under [rebuild/frontend/src/lib/stores/](../../frontend/src/lib/stores/). The shape is fixed by the project-wide convention in [m0-foundations.md § Frontend conventions (cross-cutting)](m0-foundations.md#frontend-conventions-cross-cutting): **one class per store in a `*.svelte.ts` file, instances constructed and provided via `setContext` in `(app)/+layout.svelte`, downstream components read via `getContext`.** Module-level `$state` is banned for any of these (chats / folders / active chat / agents / toast are all per-user; a module-level singleton would leak across SSR requests). Any module that uses runes lives at `*.svelte.ts`, never `*.ts`.

The five stores M2 ships:

| Store | File | Responsibility |
|---|---|---|
| `ChatsStore` | `lib/stores/chats.svelte.ts` | Sidebar list + folder-membership. Methods: `refresh()`, `create(folderId?)`, `patch(id, partial)`, `remove(id)`, `move(id, folderId)`, `togglePin(id)`, `toggleArchive(id)`. Mutations are optimistic with rollback on error. |
| `FoldersStore` | `lib/stores/folders.svelte.ts` | Flat folder list + `byParent` derived map. CRUD methods mirror `ChatsStore`. |
| `ActiveChatStore` | `lib/stores/active-chat.svelte.ts` | The chat currently in view; owns the full `History` and the streaming task. Methods: `load(id)`, `unload()`, `send(req)`, `cancel()`, `switchBranch(parentId, childId)`, `editAndResend(messageId, newContent)`. `streaming: 'idle' \| 'sending' \| 'streaming' \| 'cancelling'` field drives the input UI. |
| `AgentsStore` | `lib/stores/agents.svelte.ts` | Agent catalogue, refreshed on app boot and on dropdown open if older than 30 s. |
| `ToastStore` | `lib/stores/toast.svelte.ts` | Minimal `{ push(level, message) }`. Surfaces `error` SSE events and HTTP failures. |

Each store is a class with `$state` fields and methods that mutate them. `agents.svelte.ts` is the canonical shape:

```ts
// lib/stores/agents.svelte.ts
import { getContext, setContext } from 'svelte';
import type { AgentInfo } from '$lib/types';

const KEY = Symbol('agents');

export class AgentsStore {
  items = $state<AgentInfo[]>([]);
  loaded = $state(false);
  error = $state<string | null>(null);
  #lastRefreshed = 0;

  constructor(initial: AgentInfo[] = []) {
    this.items = initial;
    this.loaded = initial.length > 0;
  }

  async refresh(): Promise<void> {
    try {
      const res = await fetch('/api/agents');
      if (!res.ok) throw new Error(`agents ${res.status}`);
      this.items = (await res.json()).items;
      this.loaded = true;
      this.error = null;
      this.#lastRefreshed = Date.now();
    } catch (e) {
      this.error = String(e);
    }
  }

  maybeRefresh(maxAgeMs = 30_000): void {
    if (Date.now() - this.#lastRefreshed > maxAgeMs) void this.refresh();
  }
}

export function provideAgents(initial: AgentInfo[]): AgentsStore {
  const s = new AgentsStore(initial);
  setContext(KEY, s);
  return s;
}

export function useAgents(): AgentsStore {
  return getContext<AgentsStore>(KEY);
}
```

Construction site (`(app)/+layout.svelte`):

```svelte
<script lang="ts">
  import { provideChats } from '$lib/stores/chats.svelte';
  import { provideFolders } from '$lib/stores/folders.svelte';
  import { provideAgents } from '$lib/stores/agents.svelte';
  import { provideActiveChat } from '$lib/stores/active-chat.svelte';
  import { provideToast } from '$lib/stores/toast.svelte';
  let { data, children } = $props();
  provideChats(data.chats);
  provideFolders(data.folders);
  provideAgents(data.agents);
  provideActiveChat();
  provideToast();
</script>
{@render children()}
```

The `(app)/+layout.server.ts` `load` returns `{ chats, folders, agents }` — server-rendered into HTML and re-used as the stores' initial values during hydration, so first paint has the sidebar populated without an extra round-trip. `activeChat` is hydrated separately by `c/[id]/+page.server.ts` on direct deep-links (`provideActiveChat()` starts empty; `useActiveChat().load(id)` is called from `+page.svelte`'s mount via `data.chat`).

Streaming state is **client-only** — there is no useful SSR representation of an in-flight stream, and SvelteKit's `streamed` page-data isn't a fit (we want SSE, not a single async chunk). The streaming generator inside `ActiveChatStore.send()` is owned by the calling component's `$effect` — never by `onMount` + `onDestroy`, never module-scope:

```svelte
<!-- ConversationView.svelte -->
<script lang="ts">
  import { useActiveChat } from '$lib/stores/active-chat.svelte';
  let { data } = $props();
  const activeChat = useActiveChat();

  $effect(() => {
    activeChat.load(data.chat.id);
    return () => activeChat.unload(); // aborts the SSE AbortController and clears in-progress flags
  });
</script>
```

The SSE reader / `AbortController` follow the same pattern. When the user hits Esc, the input component calls `activeChat.cancel()`, which aborts the controller the store is holding. The `unload()` cleanup in the `$effect` above aborts it as a safety net on route change. The Svelte 5 cleanup contract here is the only correct shape — see [svelte-best-practises.md § 12](../best-practises/svelte-best-practises.md) and the M0 conventions.

The `activeChat.send` implementation lives in [rebuild/frontend/src/lib/stores/active-chat.svelte.ts](../../frontend/src/lib/stores/active-chat.svelte.ts) and uses the `parseSSE` helper from [rebuild/frontend/src/lib/utils/sse.ts](../../frontend/src/lib/utils/sse.ts) — a 60-line `ReadableStream → AsyncIterable<{event, data}>` parser tested as a unit (see "Tests"). `sse.ts` does not use runes, so it stays `*.ts` (per the M0 naming rule).

## User journeys

The list of click-paths a real user takes on M2-owned surfaces. Each row binds three layers of coverage (pixel-diff baseline / geometric-invariant spec / impeccable design review) per [visual-qa-best-practises.md § The three layers](../best-practises/visual-qa-best-practises.md#the-three-layers). A row without all three columns populated is a gap, and the M2 acceptance criteria below block milestone-complete on any gap.

| Journey | Visual baseline (Layer A) | Geometric invariants (Layer B) | Impeccable review (Layer C) |
|---------|---------------------------|-------------------------------|-----------------------------|
| Cold load → empty sidebar + empty composer | `chat-empty-tokyo-night.png` | n/a (empty state — no interactive controls whose layout can collide at this granularity) | sign-off required |
| New chat → type → open `+ Options` → Temperature + System visible | `composer-options-open-tokyo-night.png` | `tests/component/composer-options-geometry.spec.ts` (desktop + narrow viewports) | sign-off required |
| New chat → type → send → stream → reload | `chat-streamed-reply-tokyo-night.png` | covered by `tests/e2e/send-and-stream.spec.ts` (behavioural E2E); add a `Message-geometry.spec.ts` covering footer + action-row positioning when regenerate branches land in M3 | sign-off required |
| Populated sidebar: 3 pinned + 5 loose + 2 folders + 4 archived hidden | `chat-sidebar-tokyo-night.png` | `Sidebar-geometry.spec.ts` (follow-up — tracked in § M2 follow-ups) | sign-off required |
| Cancel mid-stream (Esc) → partial assistant bubble shows "cancelled" | baseline follow-up (M3) | covered by `tests/e2e/cancel-mid-stream.spec.ts` (behavioural); add geometric assert on the cancelled-badge placement in M3 | sign-off required |

The `verifier` uses this table as its checklist: every row must have a green run of Layer A + Layer B, plus a recorded impeccable finding list with no Blockers, before M2 is declared complete. Follow-up rows mentioned above are cheap to extend the same helpers to; they do not gate M2 itself.

## Tests

Backend (pytest + `pytest-asyncio`, MySQL via the M0 docker-compose, lives at [rebuild/backend/tests/](../../backend/tests/)):

- **Unit**:
  - `tests/unit/test_history_tree.py` — `build_linear_thread` and the in-process tree-mutation helpers; covers a multi-branch tree, a circular `parentId` (pathological — must terminate), and an empty history.
  - `tests/unit/test_provider.py` — `OpenAICompatibleProvider.stream` against an in-process `respx`/`httpx` mock; covers token chunks, usage chunk, finish reason, server-sent error, client cancellation.
  - `tests/unit/test_sse.py` — `sse(event, data)` formatting and JSON edge cases (newlines, unicode).
  - `tests/unit/test_chat_title.py` — `derive_title(first_user_message)` against the canonical fixture set: short input, multi-line, leading/trailing whitespace, ≥60-char overflow ellipsis, unicode-grapheme boundaries. Pure function so the unit test is one fixture file.
  - `tests/unit/test_agents_cache.py` — pure cache mechanics with the provider injected as a fake: TTL refresh boundary, `contains()` / `label()` lookup, single-flight under concurrent refresh. Complements the integration-side cache test below (the unit test pins the in-memory state machine; the integration test exercises it against a real provider error path).
- **Integration**:
  - `tests/integration/test_chats_crud.py` — every endpoint above, against MySQL + the cassette-replay LLM mock; asserts the full `History` shape after a streamed exchange.
  - `tests/integration/test_streaming.py` — end-to-end the SSE generator: send → 5 deltas → done; cancel mid-stream and assert `cancelled: true, done: true` in the persisted `history`; provider error mid-stream and assert `error: {...}, done: true`; `SSE_STREAM_TIMEOUT_SECONDS` exceeded surfaces a terminal `timeout` frame; oversized initial user message returns 413 from `prepare_stream` before the response body opens.
  - `tests/integration/test_agents_cache.py` — `list_agents` is cached, refresh after TTL, gateway error surfaces as 502.
  - `tests/integration/test_chat_writer.py` — `append_assistant_message` end-to-end through `AsyncSession`, asserting the `chat.history` JSON mutation, the `currentId` bump, the `updated_at` bump, and the history-cap rejection path. **Lives under `integration/` rather than `unit/` because the helper writes via `AsyncSession` and exercises the SQLAlchemy unit-of-work + history-cap path together; substituting an in-memory fake for the session would assert the wrong contract.**
  - `tests/integration/test_folders_crud.py` — folder CRUD round-trip including the recursive CTE for cycle-detection (`POST` / `PATCH` parent-change) and the descendant set + chat-detach cascade (`DELETE`).
  - `tests/integration/test_stream_registry_cross_pod.py` — pod-A registers, pod-B cancels via Redis pub/sub, pod-A's local `asyncio.Event` fires within 100 ms (the test that backs the cross-pod acceptance criterion above).

Frontend (Vitest + Playwright):

- **Unit (Vitest, [rebuild/frontend/tests/unit/](../../frontend/tests/unit/))**:
  - `historyTree.test.ts` — pure reducers porting the legacy tree algebra. Same fixtures as the backend `test_history_tree.py` for cross-language parity.
  - `parseSSE.test.ts` — feed it byte chunks split mid-event, mid-line, mid-multibyte UTF-8.
  - `markdown.test.ts` — sanitisation, fenced-code-while-streaming detection, math passthrough, alert syntax.
- **Component (Playwright CT, [rebuild/frontend/tests/component/](../../frontend/tests/component/))**:
  - `Message.spec.ts` — renders a fixture corpus of assistant messages: plain, code, math, mermaid, alerts, mid-stream incomplete fences.
  - `MessageInput.spec.ts` — Enter sends, Shift+Enter newlines, Esc fires cancel, agent dropdown shows the populated `agents` store.
  - `Markdown.spec.ts` — full token table from the legacy fork minus deleted types.
  - `Sidebar.spec.ts` — virtualisation cutoff with 50 / 500 / 5000 chats; folder expand/collapse; drag-and-drop chat into folder.
- **E2E (Playwright + the M0 docker-compose, [rebuild/frontend/tests/e2e/](../../frontend/tests/e2e/))** — the four critical paths:
  1. `tests/e2e/send-and-stream.spec.ts` — send → tokens render in order → assistant persisted → reload → message visible identically.
  2. `tests/e2e/cancel-mid-stream.spec.ts` — start a long stream → press Esc → assertion: stream stops, assistant message shows "cancelled" badge, `/api/chats/{id}` returns `cancelled: true, done: true` and the partial content the user already saw.
  3. `tests/e2e/history-crud.spec.ts` — create chat → rename → pin → drag into folder → search the sidebar via `?q=…` (asserts the `LIKE %q%` + `JSON_SEARCH` server-side filter, see `GET /api/chats?q=` below) → archive → restore → delete → assert sidebar reflects every step.
  4. `tests/e2e/reload-persistence.spec.ts` — branch-edit a message → switch branches → reload → branch state preserved.
- **Visual regression (Playwright `toHaveScreenshot`, baselines under [rebuild/frontend/tests/visual-baselines/m1/](../../frontend/tests/visual-baselines/m1/))** — capture the four M2-owned surfaces per the three-layer discipline in [visual-qa-best-practises.md § Layer A](../best-practises/visual-qa-best-practises.md#layer-a--pixel-diff-baselines): `chat-empty.png` (no chats yet, sidebar visible), `chat-streamed-reply.png` (one completed exchange, deterministic content via cassette), `chat-sidebar.png` (sidebar with mixed pinned/folder/archived rows), and `composer-options-open-tokyo-night.png` (composer with the `+ Options` disclosure expanded, exposing Temperature + System). Baselines committed via Git LFS; specs use `--prefers-reduced-motion` and frozen `Date.now`.
- **Geometric invariants (Playwright Component Testing, under [rebuild/frontend/tests/component/](../../frontend/tests/component/))** — one `*-geometry.spec.ts` spec per component whose layout a user can visibly stress. Each spec mounts the component's existing CT harness at a deterministic viewport and asserts overlap / containment / min-content-width / no-text-clipping via `tests/e2e/helpers/geometry.ts`, per [visual-qa-best-practises.md § Layer B](../best-practises/visual-qa-best-practises.md#layer-b--geometric-invariants). Unlike the baselines, these fail on the FIRST run when the bug is present — that is the whole point. M2 ships `composer-options-geometry.spec.ts` (open Options → Temperature and System must not collide, must stay inside the composer, must not be clipped) covering both the desktop (`sm:grid-cols-[120px_1fr]`) and narrow (`grid-cols-1`) layouts. Subsequent components get their own `*-geometry.spec.ts` as surfaces ship. Escalation to `@journey-m2` e2e specs is reserved for multi-surface invariants (none in M2 yet).

Cassette strategy for the agent gateway mock:

- Replay server is a 60-line FastAPI app at [rebuild/backend/tests/llm_mock.py](../../backend/tests/llm_mock.py) exposing `/v1/models` and `/v1/chat/completions` (the path keeps the OpenAI wire name so the OpenAI SDK on the rebuild's side serialises unchanged).
- Requests are hashed by `(model, messages, temperature, system)` — the hash key matches the OpenAI wire body, including the wire field name `model` even though the rebuild calls each entry an agent. The hash maps to a file under `tests/fixtures/llm/<hash>.sse`. On first run with `LLM_RECORD=1`, the mock proxies to a real gateway and records. Subsequent runs replay byte-for-byte.
- Both backend integration tests and frontend E2Es point `AGENT_GATEWAY_BASE_URL` at the mock, so a single set of cassettes serves both layers.
- Cassettes are checked in. Refreshing them is a deliberate PR with a `cassette-refresh` label.

Coverage gate: every CRUD endpoint and every SSE event type has at least one test that asserts on it. PRs that add a router function without an integration test are blocked in code review.

## Dependencies on other milestones

- **Depends on M0** for: trusted-header `get_user`, `Settings` (which already exposes `AGENT_GATEWAY_BASE_URL`), the SQLAlchemy `Base` and async session, the Alembic baseline that creates `user`, the docker-compose stack, the Vite + SvelteKit + Tailwind 4 + Vitest + Playwright skeleton, and the Buildkite path-filtered pipeline.
- **Reserved for M3.** The `share_id` column (`String(43)`) is created on `chat` by M2 so M3 doesn't need an `ALTER ADD COLUMN`. M2 does not read or write it; M3 owns the FK + unique index + uniqueness constraint via its own Alembic revision (`0003_m3_sharing` calls `create_foreign_key_if_not_exists("fk_chat_share_id", "chat", "shared_chat", ["share_id"], ["id"], ondelete="SET NULL")` and `create_index_if_not_exists("ix_chat_share_id", "chat", ["share_id"], unique=True)` — both via the M0 helper module, never bare `op.*`, per `m0-foundations.md` § Migration helpers).
- **`append_assistant_message` exposed for M5.** The chat-target writer M5 calls (`app.services.chat_writer.append_assistant_message`) is shipped by M2; it is the same helper `chat_stream.py` uses for non-streaming finalisation. Keeping it here means M5 doesn't need a separate writer or to know the JSON history shape.
- **Nothing in M2 hard-couples M4.** The provider abstraction is the same one M4's `@agent` channel auto-reply will use; we keep the contract narrow (`stream(messages, agent_id, params)`) so M4 can wire it in without touching M2 code.

## Acceptance criteria

- [ ] `alembic upgrade head` against an empty MySQL 8.0 instance creates `chat` and `folder` with all indexes and the generated `current_message_id` column. `alembic downgrade -1` reverses it cleanly. Re-running `alembic upgrade head` immediately after `head` is a no-op, and re-running `alembic downgrade base` after `base` is a no-op (covered by the M0 `test_upgrade_head_is_idempotent` / `test_downgrade_base_is_idempotent` cases parametrised over the M2 revision).
- [ ] `test_partial_upgrade_recovers` includes an M2 case: pre-create only `folder` (raw DDL), then `alembic upgrade head` produces `chat`, the generated column, every named index, and both cross-table FKs without operator intervention.
- [ ] `GET /api/agents` returns the agent catalogue projected from the gateway's `/v1/models` (the upstream wire path stays on its OpenAI name), cached for 5 minutes in-process with background refresh; gateway errors surface as 502/504.
- [ ] Full chat CRUD (`GET/POST/PATCH/DELETE /api/chats[...]`) round-trips correctly, including history-snapshot read after streaming.
- [ ] Full folder CRUD round-trips, including parent moves and cascade delete (chats are detached, not deleted).
- [ ] `POST /api/chats/{id}/messages` streams `start → delta* → usage? → done` for a successful completion and persists the assistant message with `done: true`.
- [ ] Client disconnect mid-stream persists `cancelled: true, done: true` with whatever content was already streamed; subsequent `GET /api/chats/{id}` returns the same content the client saw.
- [ ] `POST /api/chats/{id}/messages/{message_id}/cancel` aborts an in-flight stream and yields the same `cancelled` event.
- [ ] Provider error mid-stream surfaces a terminal `error` SSE event and persists `error: {...}, done: true`.
- [ ] Whole-request timeout (exceeding `SSE_STREAM_TIMEOUT_SECONDS`) surfaces a terminal `timeout` SSE event with `assistant_message_id` and `limit_seconds`, and persists `cancelled: true, done: true` with the partial content the client already saw. Covered by `tests/integration/test_streaming.py::test_timeout_persists_partial_and_emits_timeout_frame` with `SSE_STREAM_TIMEOUT_SECONDS` overridden to a small value.
- [ ] `StreamRegistry` cancel crosses pod boundaries via Redis pub/sub: a unit test against `fakeredis` registers a stream on pod A, calls `cancel(message_id)` from pod B's registry instance, and asserts the local `asyncio.Event` on pod A is set within 100 ms (`tests/integration/test_stream_registry_cross_pod.py`).
- [ ] Reloading `/c/{id}` after a completed exchange shows the chat exactly as it was: same branch, same content, same agent footer, same usage.
- [ ] The four Playwright E2E specs above pass on Chromium in the deterministic CI stack.
- [ ] **Three-layer visual QA** (per [visual-qa-best-practises.md](../best-practises/visual-qa-best-practises.md)): every row in § User journeys has (a) a committed baseline PNG under `tests/visual-baselines/m1/` produced by the manual refresh workflow, (b) a green geometric-invariant spec — CT `*-geometry.spec.ts` by default under `tests/component/`, escalating to `@journey-m2` under `tests/e2e/journeys/` only for multi-surface invariants, and (c) an `impeccable` design-review pass with zero Blockers. Polish findings are filed into § M2 follow-ups rather than blocking acceptance. `make test-component` and `make test-visual` both green; the verifier records the impeccable pass output.
- [ ] Branching: regenerate creates a sibling assistant message; the branch chevron switches `currentId`; reload preserves the choice.
- [ ] No Svelte component exceeds 400 LOC; `Chat.svelte`-equivalent responsibilities are split across `ConversationView`, `MessageList`, `Message`, `MessageInput`.
- [ ] Every M2 store lives at `lib/stores/<name>.svelte.ts` (not `.ts`) and exports a class instantiated via `setContext` in `(app)/+layout.svelte`. No module-level `$state` for chats / folders / active chat / agents / toast (verified by the M0 grep gate). The streaming `AbortController` and any other long-lived browser side-effect is owned by a `$effect(() => { … return () => cleanup(); })` inside the component (verified by code review against the conventions in [m0-foundations.md § Frontend conventions (cross-cutting)](m0-foundations.md#frontend-conventions-cross-cutting)).
- [ ] Total backend LOC for M2 (SQLAlchemy ORM modules, schemas, routers, provider, services, repository — i.e. every file under `rebuild/backend/app/` shipped or extended by this milestone, including the `app/models/` SQLAlchemy directory) is under **3,000**. Total frontend LOC for M2 (the M2-specific surface only — `lib/components/chat/`, the five M2 stores `lib/stores/{chats,folders,active-chat,agents,toast}.svelte.ts`, `lib/utils/{history-tree,sse,markdown}.ts`, `lib/utils/marked/`, `lib/types/`, the chat routes under `routes/(app)/`) is under **4,400**, **excluding** (a) the ported markdown pipeline (separately tracked at ~1,202 LOC) and (b) shared frontend infrastructure that future milestones inherit (`lib/api/client.ts` extensions, `lib/msw/handlers.ts` extensions, the `(internal)/smoke/...` routes promoted out of M1).
  - **Backend re-baseline rationale.** M2 was originally dispatched with a 1,800 LOC backend cap. Net came in at ~2,891. The overage is concentrated in `app/services/chat_stream.py` (~840 LOC) and `app/routers/chats.py` (~550 LOC), which together carry the SSE pipeline (six event types × four terminal branches × heartbeat tick × persist throttle), the prepare/stream split that landed in Phase 4c to fix the Starlette "response already started" race + leaked `SELECT FOR UPDATE` row lock (see § Streaming pipeline below for the rationale), and the history-cap enforcement that has to fire on every persist boundary. Phase 4a/4c review confirmed the code is functionally correct and free of duplication; the original 1,800 number was set during dispatch before the streaming-hardening detail was understood. Re-baselined here at 3,000 to give a defensible upper bound that reflects the validated implementation. An optional refactor (extract heartbeat + persist-throttle into a helper module) is tracked in [m6-hardening.md § M2 follow-ups](m6-hardening.md#m2-follow-ups) and lands only if the file is touched again for unrelated reasons — chasing it pre-emptively is not justified by a passing pipeline.
  - **Frontend re-baseline rationale.** Originally dispatched at 4,000 LOC against a looser definition. Net came in at ~4,226 against the broader scope; the re-baseline tightens the definition (the explicit file-list above) so shared infrastructure that future milestones consume — the API client, the MSW handler registry, the smoke-route shells — is excluded from the M2-only count. The explicit cap moves to 4,400 to leave a small headroom for the inevitable end-of-milestone polish PR. The per-component cap (≤400 LOC each, see the bullet above) is unchanged and stays enforced — that is the rule that actually catches "Chat.svelte regrowth", not the rolled-up budget.
- [ ] `ruff`, `mypy --strict`, `vitest`, and `playwright test` are all green on `rebuild/` CI.

## Out of scope

Explicitly **not** done in M2:

- Sharing (`shared_chat`, `/s/:token`, share/unshare endpoints) — M3.
- Channels — anything `channel*`, socket.io, presence, typing indicators, reactions, threads, webhooks — M4.
- File uploads, attachments, the `file` and `file_blob` tables, `MEDIUMBLOB` — M4.
- Automations, RRULE, scheduler, `automation*` tables — M5.
- Per-user agent permissions, agent groups, access grants, `access_grant` / `group` tables of any kind.
- Roles or admin UI; everyone with a valid `X-Forwarded-Email` is the same kind of user in M2.
- Full-text or vector search across chats. Sidebar `?q=` is a `LIKE %q%` on `title` plus an optional `JSON_SEARCH(LOWER(history), ...)` for content; we do **not** introduce MeiliSearch / OpenSearch / pgvector.
- Tags on chats. The legacy `meta.tags` field is dropped; if we miss it we add it in a later milestone, but it is not in M2.
- Token counting, cost estimation, rate-limit UI. We surface the gateway's `usage` block as-is and stop.
- Multi-modal content (images, audio, files) in messages. `content` is `str` only.
- Reasoning / tool-call / code-interpreter UI affordances. The provider stream only carries `delta.content` and `usage`; no `delta.tool_calls`.
- Auto-title beyond the optional `POST /api/chats/{id}/title` helper. UI may call it, but it's not on the streaming path.
- Settings / preferences UI beyond the in-input disclosure for `temperature` and `system`. No global settings page in M2.
- Import/export of chats. Out of scope for the empty-slate launch.

## Open questions

- **Auto-title timing.** Plan-locked decision is to call `POST /api/chats/{id}/title` from the frontend after the first assistant message completes. Open: should the backend do it inline at the end of the stream (one fewer round-trip but couples title generation to streaming) or stay client-driven (cleaner but creates a brief "New Chat" flash)? Default to client-driven for M2; revisit in M6 if the flash is annoying.
- **Generated column on MariaDB.** The plan locks MySQL 8.0; `current_message_id` uses `STORED` generated columns which MariaDB also supports but with slightly different syntax. If anyone deploys against MariaDB we'll need a dialect branch in the migration. Flagging only — we are MySQL-only by decision.
- **`SSE_STREAM_TIMEOUT_SECONDS` default.** 300 s (5 min) matches the per-route timeout in the M6 hardening plan. If the agent gateway exposes a tighter cap, we should mirror it to fail fast. Will confirm with the gateway team during M2 implementation; default stays at 300 until then.
