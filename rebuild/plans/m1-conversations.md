# M1 — Conversations + history

> Milestone 1 of the Open WebUI slim rebuild. Reference the top-level plan at [rebuild.md](../../rebuild.md). All tech, data, and auth decisions are locked there; this document only fills in the implementation detail.

## Goal

Deliver a working single-user-per-request conversation surface: a SvelteKit chat UI backed by a FastAPI app that streams completions from the internal model gateway via the OpenAI-compatible SDK, with chats and folders persisted in MySQL 8.0 against a single JSON `history` column. By the end of M1 a Canva employee can land on the app behind the OAuth proxy, see their sidebar, start a new chat, watch tokens stream in, send follow-ups (creating a branched message tree), pin/archive/delete chats, organise them into folders, switch models picked dynamically from `/v1/models`, and reload the page to see history exactly as it was. No sharing, no channels, no automations, no file uploads — those belong to later milestones.

## Deliverables

- SQLAlchemy 2 async models for `chat` and `folder` under [rebuild/backend/app/models/chat.py](../backend/app/models/chat.py) and [rebuild/backend/app/models/folder.py](../backend/app/models/folder.py).
- A single Alembic revision creating both tables under [rebuild/backend/alembic/versions/0002_m1_chat_folder.py](../backend/alembic/versions/0002_m1_chat_folder.py) (`revision = "0002_m1_chat_folder"`, `down_revision = "0001_baseline"`).
- An `OpenAICompatibleProvider` at [rebuild/backend/app/providers/openai.py](../backend/app/providers/openai.py) with `stream(...)` and `list_models()`, configured via `MODEL_GATEWAY_BASE_URL`.
- Pydantic schemas under [rebuild/backend/app/schemas/chat.py](../backend/app/schemas/chat.py) and [rebuild/backend/app/schemas/folder.py](../backend/app/schemas/folder.py).
- HTTP routers under [rebuild/backend/app/routers/chats.py](../backend/app/routers/chats.py), [rebuild/backend/app/routers/folders.py](../backend/app/routers/folders.py), [rebuild/backend/app/routers/models.py](../backend/app/routers/models.py).
- The streaming function at [rebuild/backend/app/services/chat_stream.py](../backend/app/services/chat_stream.py) (~300 LOC including helpers).
- A reusable assistant-message writer at [rebuild/backend/app/services/chat_writer.py](../backend/app/services/chat_writer.py) exposing `append_assistant_message(session, *, chat_id: str, parent_message_id: str | None, model: str, content: str, status: Literal["complete","cancelled","error"]="complete") -> str` (returns the new message id, atomically updates `chat.history.messages[<id>]`, sets `chat.history.currentId`, and bumps `chat.updated_at`). Used by `chat_stream.py` (M1) and the M4 automation executor for chat-target writes.
- A title-derivation helper at [rebuild/backend/app/services/chat_title.py](../backend/app/services/chat_title.py) exposing `derive_title(first_user_message: str) -> str` (≤ 60 chars, single line, stripped). Called by `POST /api/chats` when the body omits `title` and by the streaming pipeline on the first assistant turn for an untitled chat. Pure function so the unit test is one fixture.
- An in-process stream registry at [rebuild/backend/app/services/stream_registry.py](../backend/app/services/stream_registry.py) — module-level `StreamRegistry` singleton holding a `dict[str, asyncio.Event]` keyed by `assistant_message_id`. Exposes `register(message_id) -> asyncio.Event`, `cancel(message_id) -> bool`, and `cleanup(message_id)` (called from the streaming generator's `finally` block). Powers `POST /api/chats/{id}/messages/{assistant_id}/cancel` (M1) by setting the cancellation event so the in-flight generator catches `asyncio.CancelledError`, persists the partial assistant content via `chat_writer.append_assistant_message(..., status="cancelled")`, and re-raises. Single-replica scope is fine for M1 — cross-replica cancel is a Redis pub/sub follow-up tracked in `m5-hardening.md` § Out of scope.
- SvelteKit 2 routes under [rebuild/frontend/src/routes/(app)/](../frontend/src/routes/(app)/) plus components under [rebuild/frontend/src/lib/components/chat/](../frontend/src/lib/components/chat/).
- Ported markdown pipeline at [rebuild/frontend/src/lib/components/chat/Markdown/](../frontend/src/lib/components/chat/Markdown/) and [rebuild/frontend/src/lib/utils/marked/](../frontend/src/lib/utils/marked/) (citations/sources/embeds removed).
- Svelte 5 runes-based stores at [rebuild/frontend/src/lib/stores/](../frontend/src/lib/stores/) — one `*.svelte.ts` file per store, each exporting a class. Constructed and provided via `setContext` in `(app)/+layout.svelte`. See [m0-foundations.md § Frontend conventions (cross-cutting)](m0-foundations.md#frontend-conventions-cross-cutting) for the canonical pattern; do not redeclare it here.
- Backend tests at [rebuild/backend/tests/](../backend/tests/) (unit + integration), frontend unit/component/e2e tests under [rebuild/frontend/tests/{unit,component,e2e}/](../frontend/tests/).
- A recorded-cassette LLM mock under [rebuild/backend/tests/fixtures/llm/](../backend/tests/fixtures/llm/) and a tiny replay server at [rebuild/backend/tests/llm_mock.py](../backend/tests/llm_mock.py).
- Visual-regression baselines for `chat-empty`, `chat-streamed-reply`, and `chat-sidebar` captured under [rebuild/frontend/tests/visual-baselines/m1/](../frontend/tests/visual-baselines/m1/) (Git LFS).

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

    # Reserved for M2; declared here to avoid a follow-up ALTER. Always NULL in M1.
    # Width matches `shared_chat.id` in M2. Uniqueness is enforced by the M2-owned
    # index `ix_chat_share_id` (see m2-sharing.md), not by a column-level UNIQUE here.
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
# rebuild/backend/app/db/models/folder.py
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

The schema mirrors the legacy fork (see [backend/open_webui/models/chats.py](../../backend/open_webui/models/chats.py) lines 463–533 and [src/lib/components/chat/Chat.svelte](../../src/lib/components/chat/Chat.svelte) around the `userMessage`/`responseMessage` constructors near line 1540) so we don't reinvent the tree algebra.

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
      "model": "gpt-4o" | null,
      "modelName": "GPT-4o" | null,
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
- **`currentId`** points at the *leaf* of the active branch — usually the latest assistant message. The reducer that flattens the tree to a linear conversation walks `parentId` from `currentId` to the root (see legacy [backend/open_webui/utils/misc.py](../../backend/open_webui/utils/misc.py) lines 71–101 — port verbatim).
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
      "model": null, "modelName": null,
      "done": true, "error": null, "cancelled": false, "usage": null
    },
    "a2": {
      "id": "a2", "parentId": "u1",
      "childrenIds": [],
      "role": "assistant", "content": "hello",
      "timestamp": 1745701201,
      "model": "gpt-4o", "modelName": "GPT-4o",
      "done": true, "error": null, "cancelled": false,
      "usage": { "prompt_tokens": 8, "completion_tokens": 1, "total_tokens": 9 }
    },
    "c3": {
      "id": "c3", "parentId": "u1",
      "childrenIds": [],
      "role": "assistant", "content": "hi there!",
      "timestamp": 1745701260,
      "model": "gpt-4o-mini", "modelName": "GPT-4o mini",
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
    model: str | None = None
    modelName: str | None = None
    done: bool = True
    error: dict[str, Any] | None = None
    cancelled: bool = False
    usage: dict[str, Any] | None = None


class History(StrictModel):
    messages: dict[str, HistoryMessage] = {}
    currentId: str | None = None
```

Both inherit from `StrictModel` (defined in M0 — see [m0-foundations.md § Pydantic conventions](m0-foundations.md#pydantic-conventions)) so unknown fields in `chat.history` JSON are rejected at the Python boundary. Every other Pydantic model in M1 (request bodies and response models below) inherits from `StrictModel` for the same reason; the per-class `model_config = ConfigDict(extra="forbid")` boilerplate is **never** repeated.

## Alembic revision

- Filename: [rebuild/backend/alembic/versions/0002_m1_chat_folder.py](../backend/alembic/versions/0002_m1_chat_folder.py)
- `revision = "0002_m1_chat_folder"`
- `down_revision = "0001_baseline"` (the M0 baseline that creates `user`)
- `branch_labels = None`, `depends_on = None`

The migration is fully idempotent, per [rebuild.md § 9 "Robust, idempotent Alembic migrations"](../../rebuild.md#9-decisions-locked) and the M0 helper module ([m0-foundations.md § Migration helpers](m0-foundations.md#migration-helpers)). Every step calls a `*_if_not_exists` / `*_if_exists` wrapper or `execute_if(...)` so a partial application — MySQL DDL auto-commits, so this is the realistic crash mode — re-runs cleanly. Bare `op.create_*` / `op.drop_*` / `op.add_column` / `op.execute` calls are forbidden in this revision and the entire `backend/alembic/versions/` tree (M0 ships a CI grep gate).

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
   This is the one place in M1 where raw DDL is unavoidable — SQLAlchemy 2 has no first-class generated-column support and MySQL 8.0 has no `ADD COLUMN IF NOT EXISTS`. Routing through `execute_if(has_column(...) is False, ...)` keeps the migration re-runnable without a stored procedure.
4. `create_index_if_not_exists` for the four composite indexes on `chat` (`ix_chat_user_updated`, `ix_chat_user_pinned_updated`, `ix_chat_user_archived_updated`, `ix_chat_user_folder_updated`) plus `ix_chat_current_message` on the generated column. (No native `CREATE INDEX IF NOT EXISTS` in MySQL 8.0; the helper inspects `INFORMATION_SCHEMA.STATISTICS` first.)

`downgrade()` reverses in the opposite order, every step idempotent: `drop_index_if_exists` for each named index, `execute_if(has_column("chat","current_message_id"), "ALTER TABLE chat DROP COLUMN current_message_id")`, `drop_table_if_exists("chat")`, `drop_table_if_exists("folder")`. Inline FKs created in step 2 are dropped automatically with the table.

Charset/collation: the M0 baseline configures the database default to `utf8mb4` / `utf8mb4_0900_ai_ci`. We do **not** specify `mysql_charset` or `mysql_collate` in `create_table` — the tables inherit from the database. This keeps the migration grep-clean and avoids drift between baseline and M1. (`create_table_if_not_exists` does set the engine/charset table args defensively, but the values match the database default, so no override actually fires.)

`alembic upgrade head`, `alembic downgrade -1`, and **a second `alembic upgrade head` immediately afterwards** must all succeed cleanly against an empty MySQL 8.0 instance. The first two are exercised by the M0 CI job; the idempotent re-run is asserted by `backend/tests/test_migrations.py::test_upgrade_head_is_idempotent` (added in M0, parametrised here for M1's revision). An additional M1 integration case extends `test_partial_upgrade_recovers` to simulate the realistic crash: pre-create only `folder`, run upgrade, assert `chat`, the generated column, every index, and both FKs end up present.

## Settings additions

M1 extends the M0 `Settings` class with one new field. `MODEL_GATEWAY_BASE_URL` and `MODEL_GATEWAY_API_KEY` are already declared in M0's settings table (`m0-foundations.md` § Settings) so M1 only adds the streaming timeout knob:

| Field | Type | Default | Notes |
|---|---|---|---|
| `SSE_STREAM_TIMEOUT_SECONDS` | `int` | `300` | Whole-request cap on `POST /api/chats/{id}/messages`. Wrapped around the provider iteration via `asyncio.wait_for`. Must equal the M5 per-route timeout for `/api/chats/{id}/messages` (see `m5-hardening.md` § Per-route HTTP timeouts) — diverging the two means a request can be killed by the route timeout before the executor's persist-partial path runs. |

The casing convention from M0 (UPPER_SNAKE_CASE attributes matching env var names) applies; `SSE_STREAM_TIMEOUT_SECONDS` is read as `settings.SSE_STREAM_TIMEOUT_SECONDS` everywhere.

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
class Model:
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
    """The only provider. Reads MODEL_GATEWAY_BASE_URL via the central Settings object.

    Exactly one instance per app; constructed in `lifespan` and stored on
    `app.state.provider`. Routes/services receive it via the M0 `Provider`
    dependency alias. Never instantiated at module import.
    """

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            base_url=settings.MODEL_GATEWAY_BASE_URL,
            api_key=settings.MODEL_GATEWAY_API_KEY or "unused",
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0),
            max_retries=0,  # we control retries ourselves; SDK retries don't compose with SSE.
        )

    async def aclose(self) -> None:
        """Release the underlying httpx pool. Called from lifespan shutdown."""
        await self._client.close()

    async def list_models(self) -> list[Model]:
        try:
            page = await self._client.models.list()
        except (APIStatusError, APIError) as e:
            raise ProviderError(f"gateway list_models failed: {e}", status_code=502) from e

        out: list[Model] = []
        for m in page.data:
            out.append(Model(id=m.id, label=m.id, owned_by=getattr(m, "owned_by", None)))
        out.sort(key=lambda m: m.id)
        return out

    async def stream(
        self,
        *,
        messages: list[dict[str, Any]],   # OpenAI-shape: [{"role": "...", "content": "..."}]
        model: str,
        params: dict[str, Any],           # {"temperature": 0.7, "system": "..."} subset only
    ) -> AsyncIterator[StreamDelta]:
        # `system` is optional — if present we prepend it.
        msgs = list(messages)
        if params.get("system"):
            msgs.insert(0, {"role": "system", "content": params["system"]})

        kwargs: dict[str, Any] = {
            "model": model,
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
async def stream_chat(*, provider: Provider, ...) -> AsyncIterator[bytes]: ...

@router.post("/api/chats/{id}/messages")
async def post_message(
    id: str, body: MessageSend,
    user: CurrentUser, db: DbSession, provider: Provider,
) -> StreamingResponse: ...
```

Tests fake the provider with `app.dependency_overrides[get_provider] = lambda: FakeProvider()` — no monkey-patching of module-level names, no special test-only imports.

Notes:

- `MODEL_GATEWAY_BASE_URL` and `MODEL_GATEWAY_API_KEY` (optional; injected by the gateway sidecar in prod) live on the central `Settings(BaseSettings)` from M0. No other env knobs.
- **Retries.** Zero SDK-level retries. We don't retry mid-stream — partial assistant content is already on the wire and visible to the user. For `list_models()` we let the caller retry by reissuing the HTTP request; the frontend already polls on the model dropdown open.
- **Cancellation.** The route handler propagates `asyncio.CancelledError` (raised by Starlette when the client disconnects); the provider catches it, calls `await stream.close()` to release the connection, and re-raises. This stops billing and frees the upstream slot.
- **Errors.** Everything funnels into `ProviderError(status_code=...)`. The streaming function turns these into a terminal SSE `error` event; non-streaming endpoints turn them into HTTP errors via an exception handler installed at app startup.

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
      share_id: str | None  # always None in M1
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

`POST /api/chats/{id}/title` — convenience wrapper used by the auto-title task (still M1 because it sits on the same provider). Body `{ "messages": [...] }`, response `{ "title": str }`. Calls the provider with a fixed system prompt asking for a ≤6 word title. Non-streaming. Skipped in M1 if it slips — it's a "nice to have" once the streaming path is solid.

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

### Models

`GET /api/models` — passthrough of `/v1/models`.

- Response:
  ```python
  class ModelInfo(StrictModel):
      id: str
      label: str
      owned_by: str | None
  class ModelList(StrictModel):
      items: list[ModelInfo]
  ```
- Errors: 502/504 mirror provider errors.
- Caching: results are cached for 5 minutes in-process with background refresh, matching the cache TTL used by the M3 channel `@model` resolver. Both the `/api/models` router and the channel resolver share the same `provider.list_models()` cache instance.

### SSE streaming

`POST /api/chats/{id}/messages` — append a user message and stream the assistant reply.

- Body:
  ```python
  class MessageSend(StrictModel):
      content: str                      # the user prompt; required, non-empty
      model: str                        # must appear in /v1/models
      parent_id: str | None = None      # branch off this message; defaults to history.currentId
      params: ChatParams = ChatParams() # temperature, system

  class ChatParams(StrictModel):
      temperature: float | None = None  # 0..2
      system: str | None = None         # optional system prompt override
  ```
- Response: `text/event-stream`. Content-Type set explicitly. `Cache-Control: no-cache`, `X-Accel-Buffering: no` (for nginx environments).
- Errors *before* streaming starts: 404 on chat not found, 400 on empty content, 422 on schema validation, 502/504 on provider list-models failure (we validate model membership against the cached `/v1/models`).
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
| `timeout` | `{ "assistant_message_id": str, "limit_seconds": int }` | When the whole-request `SSE_STREAM_TIMEOUT_SECONDS` cap (default 300) is hit by `asyncio.wait_for`; the partial assistant content is persisted with `cancelled: true, done: true` (same persistence shape as `cancelled`). The frame is distinct so the UI can render an "exceeded time limit" affordance instead of a generic cancellation. |

Heartbeat: a `: keep-alive\n\n` comment is sent every `STREAM_HEARTBEAT_SECONDS` (default 15s; the project-wide constant from [m0-foundations.md § Project constants](m0-foundations.md#project-constants), shared with M3 socket.io) during quiet stretches to keep proxies from timing out. Do not hard-code the cadence — import the constant.

`POST /api/chats/{id}/messages/{message_id}/cancel` — explicit cancel for cases where the client can't drop the connection (e.g. multi-tab share). Looks up the in-process stream task by `message_id` and cancels it. Returns 204. Best-effort; if the stream already finished, returns 204 anyway. Implementation details under "Streaming pipeline".

## Streaming pipeline

Lives in `app.services.chat_stream.stream_chat`. The function shape mirrors what FastAPI's `StreamingResponse` expects: an async generator yielding `bytes`. Total LOC including helpers stays around 300; the legacy 5,057-line orchestrator is replaced by this:

```text
async def stream_chat(
    *, chat_id: str, user: User, body: MessageSend,
    db: AsyncSession, provider: OpenAICompatibleProvider, registry: StreamRegistry,
) -> AsyncIterator[bytes]:

    # 1. Load and authorise.
    chat = await ChatRepo.get(db, chat_id, user.id)  # SELECT ... FOR UPDATE on the row.
    if chat is None: raise HTTPException(404)
    history = History.model_validate(chat.history)

    # 2. Validate model. Cache from /api/models is consulted; on miss, bypass and trust.
    if not models_cache.contains(body.model):
        models_cache.refresh()  # cheap; one upstream call.
        if not models_cache.contains(body.model):
            raise HTTPException(400, f"unknown model: {body.model}")

    # 3. Build the linear message thread to send to the provider.
    parent_id = body.parent_id or history.currentId
    user_msg = HistoryMessage(
        id=new_id(), parentId=parent_id, childrenIds=[],
        role="user", content=body.content,
        timestamp=now_ms(),
    )
    assistant_msg = HistoryMessage(
        id=new_id(), parentId=user_msg.id, childrenIds=[],
        role="assistant", content="",
        timestamp=now_ms(),
        model=body.model, modelName=models_cache.label(body.model),
        done=False,
    )

    history.messages[user_msg.id] = user_msg
    history.messages[assistant_msg.id] = assistant_msg
    if parent_id is not None and parent_id in history.messages:
        history.messages[parent_id].childrenIds.append(user_msg.id)
    user_msg.childrenIds.append(assistant_msg.id)
    history.currentId = assistant_msg.id

    # First persistence point: user message + empty assistant placeholder.
    chat.history = history.model_dump()
    chat.updated_at = now_ms()
    if not chat.title or chat.title == "New Chat":
        chat.title = derive_title(body.content)  # first 60 chars, ellipsised
    await db.commit()

    # 4. Open the stream. Register the task so /cancel can kill it.
    yield sse("start", {
        "user_message_id": user_msg.id,
        "assistant_message_id": assistant_msg.id,
    })

    linear = build_linear_thread(history, parent_id=user_msg.id)  # walk parentId chain
    openai_messages = [{"role": m.role, "content": m.content} for m in linear]

    cancel_token = registry.register(assistant_msg.id)  # weakref-keyed, removed on exit
    last_persist = monotonic()
    PERSIST_EVERY_S = 1.0  # back-pressure cap on DB writes during fast streams
    accumulated = []

    try:
        async for delta in provider.stream(
            messages=openai_messages, model=body.model, params=body.params.model_dump(exclude_none=True),
        ):
            if cancel_token.is_set():
                raise asyncio.CancelledError()

            if delta.content:
                accumulated.append(delta.content)
                yield sse("delta", {"content": delta.content})

            if delta.usage:
                assistant_msg.usage = delta.usage
                yield sse("usage", delta.usage)

            # Persist the in-progress assistant content periodically so a server crash
            # doesn't lose minutes of streaming. Cheap because the row is already in scope.
            if monotonic() - last_persist > PERSIST_EVERY_S:
                assistant_msg.content = "".join(accumulated)
                chat.history = history.model_dump()
                await db.commit()
                last_persist = monotonic()

            if delta.finish_reason:
                # Provider says "done"; loop will exit naturally on next iteration.
                pass

    except asyncio.CancelledError:
        assistant_msg.content = "".join(accumulated)
        assistant_msg.cancelled = True
        assistant_msg.done = True
        chat.history = history.model_dump()
        await db.commit()
        yield sse("cancelled", {"assistant_message_id": assistant_msg.id})
        # Don't re-raise: we've cleanly closed the SSE stream. Starlette is happy.
        return
    except ProviderError as e:
        assistant_msg.content = "".join(accumulated)
        assistant_msg.error = {"message": str(e)}
        assistant_msg.done = True
        chat.history = history.model_dump()
        await db.commit()
        yield sse("error", {"message": str(e), "status_code": e.status_code})
        return
    finally:
        registry.unregister(assistant_msg.id)

    # 5. Normal completion.
    assistant_msg.content = "".join(accumulated)
    assistant_msg.done = True
    chat.history = history.model_dump()
    chat.updated_at = now_ms()
    await db.commit()
    yield sse("done", {
        "assistant_message_id": assistant_msg.id,
        "finish_reason": "stop",
    })
```

`sse(event, data)` is a 3-line helper: `f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()`.

`StreamRegistry` is a thin façade over **Redis pub/sub** with an in-process `{message_id: asyncio.Event}` cache. The app is deployed multi-replica from day one (M5 ships >1 pod and channels in M3 require Redis-adapter socket.io across pods), so cancel signals must cross pod boundaries.

Implementation:

- `register(message_id) -> Event`: creates a local `asyncio.Event` and subscribes to Redis channel `stream:cancel:{message_id}`. The subscription handler sets the local event when a cancel message arrives.
- `cancel(message_id)`: publishes `1` to `stream:cancel:{message_id}`. The pod actually running the stream receives the message via its subscription and sets the local event; pods not running this stream simply receive a no-op message and ignore it. `cancel()` is idempotent and best-effort: if the stream already finished it has unsubscribed already.
- `unregister(message_id)`: cancels the subscription and drops the local entry. Always called in a `finally` block.

Subscriptions are short-lived (one per active stream) so the Redis pubsub footprint is small. The Redis connection is the same one used by the socket.io adapter; no new infra.

Cancellation contract (always honoured by the generator):

> The streaming generator must catch `asyncio.CancelledError`, persist the partial assistant content with `cancelled=True, done=True` via the same `chat.history` write path as the success branch, emit the terminal `cancelled` SSE event, and **return** (not re-raise — the SSE stream is already closed cleanly from the client's perspective). Skipping any of these three steps leaves a `done=False` zombie row that the M5 sweeper would later have to clean up. The pseudo-code above shows this exact shape; copy it.

Cancellation paths:

1. **Client disconnect.** Starlette raises `CancelledError` inside the generator on the originating pod. No Redis hop needed.
2. **Explicit `/cancel`.** Reaches any pod via the load balancer; publishes to Redis; the originating pod's subscription sets the local event; next loop iteration raises `CancelledError`.
3. **Server shutdown.** `lifespan` cancels all in-flight tasks; same path.

Timeouts:

- Per-stream: 120 s read on each chunk (provider's `httpx.Timeout(read=120.0)`). Exceeded → `ProviderError(504)` → `error` event.
- Whole-request: a hard 5-minute cap enforced by `asyncio.wait_for` around the provider iteration. Configurable via `SSE_STREAM_TIMEOUT_SECONDS` (default 300). On exceedance the executor catches `asyncio.TimeoutError`, persists the partial assistant content with `cancelled=True, done=True`, and emits a terminal `timeout` SSE frame (`data: {"assistant_message_id": "...", "limit_seconds": 300}`) before returning. This matches the SSE timeout cap defined in the M5 hardening plan; do not diverge.

Partial-message persistence semantics — the loop above guarantees:

- After the user lands on `/api/chats/{id}` mid-stream and reloads, they see the user message and whatever assistant content has already been persisted (≤1 s old).
- A crashed server resumes with the last persisted content; the assistant message stays `done: false` (the UI shows a "stream interrupted" affordance). A future M5 ticket sweeps zombie `done: false` rows older than N minutes; not in scope here.

## Frontend routes and components

Route tree under [rebuild/frontend/src/routes/](../frontend/src/routes/):

```
src/routes/
  +layout.svelte                # global app shell (sidebar + main pane), Tailwind reset
  +layout.server.ts             # SSR check: read X-Forwarded-Email, redirect to /401 if missing
  (app)/
    +layout.svelte              # signed-in shell (sidebar, model selector, "+ new chat")
    +layout.server.ts           # loads sidebar list + folder list once per navigation
    +page.svelte                # / — empty-state landing screen ("start a conversation")
    c/
      [id]/
        +page.svelte            # /c/[id] — conversation view
        +page.server.ts         # loads the full chat for SSR, then SPA takes over
  401/
    +page.svelte                # auth failure
```

Key components under [rebuild/frontend/src/lib/components/chat/](../frontend/src/lib/components/chat/):

- **`Sidebar.svelte`** — folder tree + chat list. Subscribes to `chats` and `folders` stores. Drag-and-drop for moving chats; right-click menu for pin/archive/rename/delete. Virtualised with `content-visibility: auto` (port the v0.9.2 trick from legacy [src/lib/components/](../../src/lib/components/)).
- **`ConversationView.svelte`** — receives chat ID from the route, calls `activeChat.load(id)`, renders the message list and the input. Owns the streaming lifecycle.
- **`MessageList.svelte`** — pure render: maps the linear thread (built by walking `currentId → parentId`) to `<Message />` components. Branch chevrons (`< 2 / 3 >`) appear on messages whose parent has multiple children; clicking switches `currentId` and the linear thread re-derives.
- **`Message.svelte`** — single message bubble. User messages: plain text. Assistant messages: `<Markdown />` while `done` is true; live-rendered tokens while streaming. Footer shows model name and (if present) usage on hover.
- **`MessageInput.svelte`** — single textarea, model selector dropdown, system-prompt + temperature in a collapsed disclosure, Enter to send, Shift+Enter for newline, Esc to cancel an in-flight stream. ~200 LOC max — explicitly *not* a port of the 2.1k-line legacy file. Copy interaction patterns, not code.
- **`Markdown.svelte`** — see "Markdown port" below.
- **`ModelSelector.svelte`** — populated from the `models` store; shows a search input when there are >10 models.
- **`FolderTree.svelte`** — recursive component used inside `Sidebar`.

State + data flow for the streaming send (the most complex flow in M1):

1. User types and hits Enter. `MessageInput` calls `activeChat.send({ content, model, params })`.
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

Source: legacy [src/lib/components/chat/Messages/Markdown.svelte](../../src/lib/components/chat/Messages/Markdown.svelte) and the directory at [src/lib/components/chat/Messages/Markdown/](../../src/lib/components/chat/Messages/Markdown/), plus the marked extensions at [src/lib/utils/marked/](../../src/lib/utils/marked/).

**Keep and port:**

- `Markdown.svelte` (the orchestrator) → [rebuild/frontend/src/lib/components/chat/Markdown/Markdown.svelte](../frontend/src/lib/components/chat/Markdown/Markdown.svelte).
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
- `MarkdownInlineTokens/MentionToken.svelte` — `@user` / `#channel` mentions. M3 introduces channels; until then the mention extension is a footgun. Delete the file; remove the three `mentionExtension(...)` `marked.use` calls.
- `MarkdownInlineTokens/NoteLinkToken.svelte` — note linking; we don't have notes.
- Any `embed` / `source` / `tasks` / `tool_calls` / `code_interpreter` / `reasoning` token branches in `MarkdownTokens.svelte`. The "details group" stays for plain `<details>` HTML, but the `GROUPABLE_DETAIL_TYPES` set shrinks to `new Set([])` (i.e. no special collapsing), and the `tool_calls` / `reasoning` / `code_interpreter` branches are deleted in the same diff.
- `replaceTokens` and `processResponseContent` from `$lib/utils` — they pull in unrelated legacy helpers. Reimplement as two small pure functions in [rebuild/frontend/src/lib/utils/markdown.ts](../frontend/src/lib/utils/markdown.ts) covering only: closed-fence detection (so streaming code blocks render as they arrive) and `<` HTML-escape on raw text. ~40 LOC.

Sanitisation: keep the existing DOMPurify-backed approach in `HTMLToken.svelte`. Add an explicit unit test that the `javascript:` URL scheme is stripped, `<script>` is blocked, and `onerror=` attributes are dropped — these were the three legacy regression points.

## Stores and state

Svelte 5 runes-based stores under [rebuild/frontend/src/lib/stores/](../frontend/src/lib/stores/). The shape is fixed by the project-wide convention in [m0-foundations.md § Frontend conventions (cross-cutting)](m0-foundations.md#frontend-conventions-cross-cutting): **one class per store in a `*.svelte.ts` file, instances constructed and provided via `setContext` in `(app)/+layout.svelte`, downstream components read via `getContext`.** Module-level `$state` is banned for any of these (chats / folders / active chat / models / toast are all per-user; a module-level singleton would leak across SSR requests). Any module that uses runes lives at `*.svelte.ts`, never `*.ts`.

The five stores M1 ships:

| Store | File | Responsibility |
|---|---|---|
| `ChatsStore` | `lib/stores/chats.svelte.ts` | Sidebar list + folder-membership. Methods: `refresh()`, `create(folderId?)`, `patch(id, partial)`, `remove(id)`, `move(id, folderId)`, `togglePin(id)`, `toggleArchive(id)`. Mutations are optimistic with rollback on error. |
| `FoldersStore` | `lib/stores/folders.svelte.ts` | Flat folder list + `byParent` derived map. CRUD methods mirror `ChatsStore`. |
| `ActiveChatStore` | `lib/stores/active-chat.svelte.ts` | The chat currently in view; owns the full `History` and the streaming task. Methods: `load(id)`, `unload()`, `send(req)`, `cancel()`, `switchBranch(parentId, childId)`, `editAndResend(messageId, newContent)`. `streaming: 'idle' \| 'sending' \| 'streaming' \| 'cancelling'` field drives the input UI. |
| `ModelsStore` | `lib/stores/models.svelte.ts` | Model list, refreshed on app boot and on dropdown open if older than 30 s. |
| `ToastStore` | `lib/stores/toast.svelte.ts` | Minimal `{ push(level, message) }`. Surfaces `error` SSE events and HTTP failures. |

Each store is a class with `$state` fields and methods that mutate them. `models.svelte.ts` is the canonical shape:

```ts
// lib/stores/models.svelte.ts
import { getContext, setContext } from 'svelte';
import type { ModelInfo } from '$lib/types';

const KEY = Symbol('models');

export class ModelsStore {
  items = $state<ModelInfo[]>([]);
  loaded = $state(false);
  error = $state<string | null>(null);
  #lastRefreshed = 0;

  constructor(initial: ModelInfo[] = []) {
    this.items = initial;
    this.loaded = initial.length > 0;
  }

  async refresh(): Promise<void> {
    try {
      const res = await fetch('/api/models');
      if (!res.ok) throw new Error(`models ${res.status}`);
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

export function provideModels(initial: ModelInfo[]): ModelsStore {
  const s = new ModelsStore(initial);
  setContext(KEY, s);
  return s;
}

export function useModels(): ModelsStore {
  return getContext<ModelsStore>(KEY);
}
```

Construction site (`(app)/+layout.svelte`):

```svelte
<script lang="ts">
  import { provideChats } from '$lib/stores/chats.svelte';
  import { provideFolders } from '$lib/stores/folders.svelte';
  import { provideModels } from '$lib/stores/models.svelte';
  import { provideActiveChat } from '$lib/stores/active-chat.svelte';
  import { provideToast } from '$lib/stores/toast.svelte';
  let { data, children } = $props();
  provideChats(data.chats);
  provideFolders(data.folders);
  provideModels(data.models);
  provideActiveChat();
  provideToast();
</script>
{@render children()}
```

The `(app)/+layout.server.ts` `load` returns `{ chats, folders, models }` — server-rendered into HTML and re-used as the stores' initial values during hydration, so first paint has the sidebar populated without an extra round-trip. `activeChat` is hydrated separately by `c/[id]/+page.server.ts` on direct deep-links (`provideActiveChat()` starts empty; `useActiveChat().load(id)` is called from `+page.svelte`'s mount via `data.chat`).

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

The SSE reader / `AbortController` follow the same pattern. When the user hits Esc, the input component calls `activeChat.cancel()`, which aborts the controller the store is holding. The `unload()` cleanup in the `$effect` above aborts it as a safety net on route change. The Svelte 5 cleanup contract here is the only correct shape — see [svelte-best-practises.md § 12](svelte-best-practises.md) and the M0 conventions.

The `activeChat.send` implementation lives in [rebuild/frontend/src/lib/stores/active-chat.svelte.ts](../frontend/src/lib/stores/active-chat.svelte.ts) and uses the `parseSSE` helper from [rebuild/frontend/src/lib/utils/sse.ts](../frontend/src/lib/utils/sse.ts) — a 60-line `ReadableStream → AsyncIterable<{event, data}>` parser tested as a unit (see "Tests"). `sse.ts` does not use runes, so it stays `*.ts` (per the M0 naming rule).

## Tests

Backend (pytest + `pytest-asyncio`, MySQL via the M0 docker-compose, lives at [rebuild/backend/tests/](../backend/tests/)):

- **Unit**:
  - `tests/unit/test_history_tree.py` — the `build_linear_thread`, `add_branch`, `derive_title` helpers; covers a multi-branch tree, a circular `parentId` (pathological — must terminate), and an empty history.
  - `tests/unit/test_provider.py` — `OpenAICompatibleProvider.stream` against an in-process `respx`/`httpx` mock; covers token chunks, usage chunk, finish reason, server-sent error, client cancellation.
  - `tests/unit/test_sse.py` — `sse(event, data)` formatting and JSON edge cases (newlines, unicode).
- **Integration**:
  - `tests/integration/test_chats_crud.py` — every endpoint above, against MySQL + the cassette-replay LLM mock; asserts the full `History` shape after a streamed exchange.
  - `tests/integration/test_streaming.py` — end-to-end the SSE generator: send → 5 deltas → done; cancel mid-stream and assert `cancelled: true, done: true` in the persisted `history`; provider error mid-stream and assert `error: {...}, done: true`.
  - `tests/integration/test_models_cache.py` — list models is cached, refresh after TTL, gateway error surfaces as 502.

Frontend (Vitest + Playwright):

- **Unit (Vitest, [rebuild/frontend/tests/unit/](../frontend/tests/unit/))**:
  - `historyTree.test.ts` — pure reducers porting the legacy tree algebra. Same fixtures as the backend `test_history_tree.py` for cross-language parity.
  - `parseSSE.test.ts` — feed it byte chunks split mid-event, mid-line, mid-multibyte UTF-8.
  - `markdown.test.ts` — sanitisation, fenced-code-while-streaming detection, math passthrough, alert syntax.
- **Component (Playwright CT, [rebuild/frontend/tests/component/](../frontend/tests/component/))**:
  - `Message.spec.ts` — renders a fixture corpus of assistant messages: plain, code, math, mermaid, alerts, mid-stream incomplete fences.
  - `MessageInput.spec.ts` — Enter sends, Shift+Enter newlines, Esc fires cancel, model dropdown shows the populated `models` store.
  - `Markdown.spec.ts` — full token table from the legacy fork minus deleted types.
  - `Sidebar.spec.ts` — virtualisation cutoff with 50 / 500 / 5000 chats; folder expand/collapse; drag-and-drop chat into folder.
- **E2E (Playwright + the M0 docker-compose, [rebuild/frontend/tests/e2e/](../frontend/tests/e2e/))** — the four critical paths:
  1. `tests/e2e/send-and-stream.spec.ts` — send → tokens render in order → assistant persisted → reload → message visible identically.
  2. `tests/e2e/cancel-mid-stream.spec.ts` — start a long stream → press Esc → assertion: stream stops, assistant message shows "cancelled" badge, `/api/chats/{id}` returns `cancelled: true, done: true` and the partial content the user already saw.
  3. `tests/e2e/history-crud.spec.ts` — create chat → rename → pin → drag into folder → search the sidebar via `?q=…` (asserts the `LIKE %q%` + `JSON_SEARCH` server-side filter, see `GET /api/chats?q=` below) → archive → restore → delete → assert sidebar reflects every step.
  4. `tests/e2e/reload-persistence.spec.ts` — branch-edit a message → switch branches → reload → branch state preserved.
- **Visual regression (Playwright `toHaveScreenshot`, baselines under [rebuild/frontend/tests/visual-baselines/m1/](../frontend/tests/visual-baselines/m1/))** — capture the three M1-owned surfaces from `rebuild.md` §8 Layer 4: `chat-empty.png` (no chats yet, sidebar visible), `chat-streamed-reply.png` (one completed exchange, deterministic content via cassette), `chat-sidebar.png` (sidebar with mixed pinned/folder/archived rows). Baselines committed via Git LFS; specs use `--prefers-reduced-motion` and frozen `Date.now`.

Cassette strategy for the model gateway mock:

- Replay server is a 60-line FastAPI app at [rebuild/backend/tests/llm_mock.py](../backend/tests/llm_mock.py) exposing `/v1/models` and `/v1/chat/completions`.
- Requests are hashed by `(model, messages, temperature, system)`; the hash maps to a file under `tests/fixtures/llm/<hash>.sse`. On first run with `LLM_RECORD=1`, the mock proxies to a real gateway and records. Subsequent runs replay byte-for-byte.
- Both backend integration tests and frontend E2Es point `MODEL_GATEWAY_BASE_URL` at the mock, so a single set of cassettes serves both layers.
- Cassettes are checked in. Refreshing them is a deliberate PR with a `cassette-refresh` label.

Coverage gate: every CRUD endpoint and every SSE event type has at least one test that asserts on it. PRs that add a router function without an integration test are blocked in code review.

## Dependencies on other milestones

- **Depends on M0** for: trusted-header `get_user`, `Settings` (which already exposes `MODEL_GATEWAY_BASE_URL`), the SQLAlchemy `Base` and async session, the Alembic baseline that creates `user`, the docker-compose stack, the Vite + SvelteKit + Tailwind 4 + Vitest + Playwright skeleton, and the Buildkite path-filtered pipeline.
- **Reserved for M2.** The `share_id` column (`String(43)`) is created on `chat` by M1 so M2 doesn't need an `ALTER ADD COLUMN`. M1 does not read or write it; M2 owns the FK + unique index + uniqueness constraint via its own Alembic revision (`0003_m2_sharing` adds `op.create_foreign_key("fk_chat_share", "chat", "shared_chat", ["share_id"], ["id"])` and `op.create_index("ix_chat_share_id", "chat", ["share_id"], unique=True)`).
- **`append_assistant_message` exposed for M4.** The chat-target writer M4 calls (`app.services.chat_writer.append_assistant_message`) is shipped by M1; it is the same helper `chat_stream.py` uses for non-streaming finalisation. Keeping it here means M4 doesn't need a separate writer or to know the JSON history shape.
- **Nothing in M1 hard-couples M3.** The provider abstraction is the same one M3's `@model` channel auto-reply will use; we keep the contract narrow (`stream(messages, model, params)`) so M3 can wire it in without touching M1 code.

## Acceptance criteria

- [ ] `alembic upgrade head` against an empty MySQL 8.0 instance creates `chat` and `folder` with all indexes and the generated `current_message_id` column. `alembic downgrade -1` reverses it cleanly. Re-running `alembic upgrade head` immediately after `head` is a no-op, and re-running `alembic downgrade base` after `base` is a no-op (covered by the M0 `test_upgrade_head_is_idempotent` / `test_downgrade_base_is_idempotent` cases parametrised over the M1 revision).
- [ ] `test_partial_upgrade_recovers` includes an M1 case: pre-create only `folder` (raw DDL), then `alembic upgrade head` produces `chat`, the generated column, every named index, and both cross-table FKs without operator intervention.
- [ ] `GET /api/models` returns the gateway's `/v1/models` list, cached for 5 minutes in-process with background refresh; gateway errors surface as 502/504.
- [ ] Full chat CRUD (`GET/POST/PATCH/DELETE /api/chats[...]`) round-trips correctly, including history-snapshot read after streaming.
- [ ] Full folder CRUD round-trips, including parent moves and cascade delete (chats are detached, not deleted).
- [ ] `POST /api/chats/{id}/messages` streams `start → delta* → usage? → done` for a successful completion and persists the assistant message with `done: true`.
- [ ] Client disconnect mid-stream persists `cancelled: true, done: true` with whatever content was already streamed; subsequent `GET /api/chats/{id}` returns the same content the client saw.
- [ ] `POST /api/chats/{id}/messages/{message_id}/cancel` aborts an in-flight stream and yields the same `cancelled` event.
- [ ] Provider error mid-stream surfaces a terminal `error` SSE event and persists `error: {...}, done: true`.
- [ ] Reloading `/c/{id}` after a completed exchange shows the chat exactly as it was: same branch, same content, same model footer, same usage.
- [ ] The four Playwright E2E specs above pass on Chromium in the deterministic CI stack.
- [ ] Branching: regenerate creates a sibling assistant message; the branch chevron switches `currentId`; reload preserves the choice.
- [ ] No Svelte component exceeds 400 LOC; `Chat.svelte`-equivalent responsibilities are split across `ConversationView`, `MessageList`, `Message`, `MessageInput`.
- [ ] Every M1 store lives at `lib/stores/<name>.svelte.ts` (not `.ts`) and exports a class instantiated via `setContext` in `(app)/+layout.svelte`. No module-level `$state` for chats / folders / active chat / models / toast (verified by the M0 grep gate). The streaming `AbortController` and any other long-lived browser side-effect is owned by a `$effect(() => { … return () => cleanup(); })` inside the component (verified by code review against the conventions in [m0-foundations.md § Frontend conventions (cross-cutting)](m0-foundations.md#frontend-conventions-cross-cutting)).
- [ ] Total backend LOC for M1 (models, schemas, routers, provider, streaming function, repository) is under 1,800. Total frontend LOC for M1 is under 4,000 excluding the markdown port.
- [ ] `ruff`, `mypy --strict`, `vitest`, and `playwright test` are all green on `rebuild/` CI.

## Out of scope

Explicitly **not** done in M1:

- Sharing (`shared_chat`, `/s/:token`, share/unshare endpoints) — M2.
- Channels — anything `channel*`, socket.io, presence, typing indicators, reactions, threads, webhooks — M3.
- File uploads, attachments, the `file` and `file_blob` tables, `MEDIUMBLOB` — M3.
- Automations, RRULE, scheduler, `automation*` tables — M4.
- Per-user model permissions, model groups, access grants, `access_grant` / `group` tables of any kind.
- Roles or admin UI; everyone with a valid `X-Forwarded-Email` is the same kind of user in M1.
- Full-text or vector search across chats. Sidebar `?q=` is a `LIKE %q%` on `title` plus an optional `JSON_SEARCH(LOWER(history), ...)` for content; we do **not** introduce MeiliSearch / OpenSearch / pgvector.
- Tags on chats. The legacy `meta.tags` field is dropped; if we miss it we add it in a later milestone, but it is not in M1.
- Token counting, cost estimation, rate-limit UI. We surface the gateway's `usage` block as-is and stop.
- Multi-modal content (images, audio, files) in messages. `content` is `str` only.
- Reasoning / tool-call / code-interpreter UI affordances. The provider stream only carries `delta.content` and `usage`; no `delta.tool_calls`.
- Auto-title beyond the optional `POST /api/chats/{id}/title` helper. UI may call it, but it's not on the streaming path.
- Settings / preferences UI beyond the in-input disclosure for `temperature` and `system`. No global settings page in M1.
- Import/export of chats. Out of scope for the empty-slate launch.

## Open questions

- **Auto-title timing.** Plan-locked decision is to call `POST /api/chats/{id}/title` from the frontend after the first assistant message completes. Open: should the backend do it inline at the end of the stream (one fewer round-trip but couples title generation to streaming) or stay client-driven (cleaner but creates a brief "New Chat" flash)? Default to client-driven for M1; revisit in M5 if the flash is annoying.
- **Generated column on MariaDB.** The plan locks MySQL 8.0; `current_message_id` uses `STORED` generated columns which MariaDB also supports but with slightly different syntax. If anyone deploys against MariaDB we'll need a dialect branch in the migration. Flagging only — we are MySQL-only by decision.
- **`SSE_STREAM_TIMEOUT_SECONDS` default.** 300 s (5 min) matches the per-route timeout in the M5 hardening plan. If the model gateway exposes a tighter cap, we should mirror it to fail fast. Will confirm with the gateway team during M1 implementation; default stays at 300 until then.
