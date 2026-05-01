# M5 — Automations

## Goal

Deliver scheduled, server-side prompt execution for the slim rebuild: users define an automation as a name + prompt + model + RRULE recurrence + a single target (chat or channel), and a single in-process APScheduler worker fires due automations every 30 seconds, executes them through the same `OpenAICompatibleProvider` introduced in M2, and persists the assistant response either as an appended assistant message on the target chat or as a new `channel_message` carrying the M4 `bot_id` column (no synthetic user row, per M4's design). The milestone closes the "set it and forget it" use case while strictly reusing the streaming, persistence, and socket layers already built — automations add scheduling, not a parallel runtime.

## Deliverables

- `rebuild/backend/app/models/automation.py` — SQLAlchemy 2 async ORM models for `automation` and `automation_run`, with relationships, indexes, and the chat-or-channel constraint encoded both as a CHECK and as a Pydantic validator.
- `rebuild/backend/app/services/rrule.py` — RFC 5545 RRULE validation, next-fire computation, and N-occurrence preview, all timezone-aware via `python-dateutil` + `zoneinfo`.
- `rebuild/backend/app/services/scheduler.py` — APScheduler `AsyncIOScheduler` setup, tick handler, `SELECT … FOR UPDATE SKIP LOCKED` claim query, per-row dispatch into `asyncio.create_task`.
- `rebuild/backend/app/services/automation_executor.py` — execute pipeline that loads context, calls `OpenAICompatibleProvider.stream(...)`, accumulates output, and writes the result to a chat or channel.
- `rebuild/backend/app/routers/automations.py` — REST endpoints listed under [API surface](#api-surface).
- `rebuild/backend/app/routers/_test_hooks.py` — `/test/scheduler/tick` endpoint registered only when `settings.env in {"test", "staging"}` (the M6 smoke pack runs against staging and needs to fast-forward without waiting for the natural tick).
- `rebuild/backend/alembic/versions/0005_m5_automations.py` — single Alembic revision adding the two tables and their indexes.
- `rebuild/backend/app/main.py` — wire the scheduler into the FastAPI lifespan (`startup`/`shutdown`) so it runs in the same process as the API.
- `rebuild/frontend/src/routes/(app)/automations/+layout.svelte` — instantiates `AutomationsStore` and provides it via `setContext` so both the list and detail routes share one client-side cache (per-request scope, no module-level state — see [m0-foundations.md § Frontend conventions (cross-cutting)](m0-foundations.md#frontend-conventions-cross-cutting)).
- `rebuild/frontend/src/routes/(app)/automations/+page.svelte` — list view.
- `rebuild/frontend/src/routes/(app)/automations/[id]/+page.svelte` — editor + run history view.
- `rebuild/frontend/src/lib/components/automations/{AutomationList,AutomationEditor,RRulePicker,RunHistory,TargetSelector}.svelte` — components ported and trimmed from `src/lib/components/automations/*`.
- `rebuild/frontend/src/lib/api/automations.ts` — typed client for the API surface.
- `rebuild/backend/tests/unit/test_rrule.py`, `tests/unit/test_automation_target.py`, `tests/integration/test_scheduler_tick.py`, `tests/integration/test_run_now.py`.
- `rebuild/frontend/tests/component/{rrule-picker,automation-editor,run-history}.spec.ts` and `rebuild/frontend/tests/e2e/automation-minutely.spec.ts`.
- `rebuild/backend/tests/fixtures/llm/automation_minutely.sse` — recorded SSE cassette for the deterministic E2E run.

## Data model

The two tables live alongside `chat`, `channel`, and `channel_message`. They use SQLAlchemy 2 declarative `Mapped[...]` with the project-wide async `Base`. Primary keys are 36-char **UUIDv7** (RFC 9562) strings stored as `String(36)` (= `VARCHAR(36)`) — locked project-wide by `rebuild.md` §9 and `database-best-practises.md` §B.2 — generated app-side via `from app.core.ids import new_id` (the M0 helper), never `uuid.uuid4()`. Timestamps are `BIGINT` epoch **milliseconds** (project-wide convention from `rebuild.md` §4 and M2/M4). Helper: `from app.core.time import now_ms` returns `time.time_ns() // 1_000_000`. Scheduler comparisons use `UNIX_TIMESTAMP() * 1000` for "now" or pass the value from the application — both `automation.next_run_at` and `automation.last_run_at` are integers, not `DATETIME`s.

```python
# rebuild/backend/app/models/automation.py
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.core.ids import new_id  # UUIDv7 (RFC 9562); see m0 § ID and time helpers
from app.core.time import now_ms

if TYPE_CHECKING:
    from app.models.channels import Channel
    from app.models.chat import Chat
    from app.models.user import User


class Automation(Base):
    __tablename__ = "automation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)  # width matches channel_message.bot_id (M4) so the channel-target write path never overflows; 128 chars covers every gateway model id observed in the wild
    rrule: Mapped[str] = mapped_column(Text, nullable=False)

    # ondelete=CASCADE (not SET NULL) is mandatory: the table-level
    # `ck_automation_exactly_one_target` CHECK requires exactly one of the two
    # targets to be non-null, so SET NULL on either FK would put the row into a
    # both-null state that violates the CHECK and rolls the parent delete back.
    # CASCADE matches the semantic too — an automation has no meaning without a
    # target, so deleting the chat/channel should delete the automations that
    # fired against it (and AutomationRun.automation_id CASCADEs onward to
    # delete the historical run rows).
    target_chat_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chat.id", ondelete="CASCADE"),
        nullable=True,
    )
    target_channel_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("channel.id", ondelete="CASCADE"),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    next_run_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=now_ms)
    updated_at: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=now_ms,
        onupdate=now_ms,
    )

    # All three target-side relationships are deliberately one-way: nothing on
    # User/Chat/Channel ever traverses back to Automation, so we omit
    # `back_populates` and avoid touching M0/M2/M4 models. The list-this-user's
    # automations query in `GET /api/automations` is a plain
    # `select(Automation).where(Automation.user_id == user.id)`.
    user: Mapped["User"] = relationship()
    target_chat: Mapped["Chat | None"] = relationship(foreign_keys=[target_chat_id])
    target_channel: Mapped["Channel | None"] = relationship(foreign_keys=[target_channel_id])
    runs: Mapped[list["AutomationRun"]] = relationship(
        back_populates="automation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "(target_chat_id IS NOT NULL) <> (target_channel_id IS NOT NULL)",
            name="ck_automation_exactly_one_target",
        ),
        Index("ix_automation_user_active", "user_id", "is_active"),
        # The scheduler poll predicate. Composite so the planner can satisfy
        # `is_active = TRUE AND next_run_at <= :now` (with `:now = now_ms()` bound
        # from the application) from the index alone.
        Index("ix_automation_scheduler", "is_active", "next_run_at"),
    )


class AutomationRun(Base):
    __tablename__ = "automation_run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    automation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("automation.id", ondelete="CASCADE"),
        nullable=False,
    )
    chat_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chat.id", ondelete="SET NULL"),
        nullable=True,
    )

    # pending → running → success | error
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False, default=now_ms)
    finished_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    automation: Mapped[Automation] = relationship(back_populates="runs")

    __table_args__ = (
        # Run-history listing: latest-first per automation.
        Index("ix_automation_run_aid_created", "automation_id", "created_at"),
        # Allows resuming or auditing in-flight runs at startup.
        Index("ix_automation_run_status_created", "status", "created_at"),
        CheckConstraint(
            "status IN ('pending','running','success','error')",
            name="ck_automation_run_status",
        ),
    )
```

The `(target_chat_id IS NOT NULL) <> (target_channel_id IS NOT NULL)` CHECK is the XOR enforcement: it rejects rows where both are null and rows where both are set. MySQL 8.0 enforces CHECK constraints natively. The same constraint is duplicated as a Pydantic root validator on `AutomationCreate`/`AutomationUpdate` so callers get a 422 instead of an opaque DB error.

`AutomationCreate.model_id` is also length-bounded with `Annotated[str, Field(min_length=1, max_length=128)]` to mirror the column width and the M4 `channel_message.bot_id` width — without this, a 200-character `model_id` would round-trip OK through `POST /api/automations` and only blow up at execute time when the channel-target write tried to populate `channel_message.bot_id` (`String(128)`). The 128-char ceiling matches every model id observed in the wild (longest known: `meta-llama/Meta-Llama-3.1-405B-Instruct-FP8` at ~52 chars) with comfortable headroom.

All three relationships on `Automation` (`user`, `target_chat`, `target_channel`) are one-way; no reverse-side `back_populates` is required on `User`, `Chat`, or `Channel`, so M0/M2/M4 models are untouched by this milestone. M5 never traverses `user.automations`, `chat.automations`, or `channel.automations` — the only "list automations for this user" query lives in the M5 router and is a direct `select(Automation).where(...)`.

## Alembic revision

- File: `rebuild/backend/alembic/versions/0005_m5_automations.py`
- `revision = "0005_m5_automations"`
- `down_revision = "0004_m4_channels"` (locked: M4's revision is pinned at `0004_m4_channels`; see M4 §Alembic revision).
- `depends_on = None`.

The revision is fully idempotent, per [rebuild.md § 9 "Robust, idempotent Alembic migrations"](../../../rebuild.md#9-decisions-locked) and the M0 helper module ([m0-foundations.md § Migration helpers](m0-foundations.md#migration-helpers)). Bare `op.create_*` / `op.drop_*` calls are forbidden in this revision; the CI grep gate in M0 enforces it.

```python
from app.db.migration_helpers import (
    create_table_if_not_exists, drop_table_if_exists,
    create_index_if_not_exists, drop_index_if_exists,
    create_check_constraint_if_not_exists, drop_constraint_if_exists,
)
```

Operations:

1. `create_table_if_not_exists("automation", ...)` exactly mirroring the SQLAlchemy definition above. The `ck_automation_exactly_one_target` check constraint and the FKs (`automation.user_id → user.id`, `automation.target_chat_id → chat.id`, `automation.target_channel_id → channel.id`) are declared inline so they land atomically with the table on a fresh run.
2. `create_table_if_not_exists("automation_run", ...)` likewise, with the `ck_automation_run_status` check and the FKs (`automation_run.automation_id → automation.id`, `automation_run.chat_id → chat.id`) declared inline.
3. Out-of-band indexes (paired in case the table existed from a partial run without them): `create_index_if_not_exists("ix_automation_user_active", "automation", ["user_id", "is_active"])`, `create_index_if_not_exists("ix_automation_scheduler", "automation", ["is_active", "next_run_at"])`, `create_index_if_not_exists("ix_automation_run_aid_created", "automation_run", ["automation_id", "created_at"])`, `create_index_if_not_exists("ix_automation_run_status_created", "automation_run", ["status", "created_at"])`. (Mandatory because MySQL 8.0 has no native `CREATE INDEX IF NOT EXISTS`.)
4. Out-of-band check constraints in the same vein: `create_check_constraint_if_not_exists("ck_automation_exactly_one_target", "automation", "(target_chat_id IS NOT NULL) <> (target_channel_id IS NOT NULL)")` and `create_check_constraint_if_not_exists("ck_automation_run_status", "automation_run", "status IN ('pending','running','success','error')")` so a re-run after a partial table-only crash repairs the constraint set.

`downgrade()` mirrors with `drop_index_if_exists(...)` for each named index, `drop_constraint_if_exists(..., type_="check")` for both checks, then `drop_table_if_exists("automation_run")` followed by `drop_table_if_exists("automation")` (reverse FK order). Inline FKs and constraints declared in step 1/2 drop with their owning tables.

The migration uses `mysql_engine="InnoDB"` and `mysql_charset="utf8mb4"` (defaulted by `create_table_if_not_exists`) to match M0's baseline.

`alembic upgrade head`, `alembic downgrade -1`, **and a second `alembic upgrade head` immediately afterwards** must all succeed cleanly. Covered by the M0 `test_upgrade_head_is_idempotent` / `test_downgrade_base_is_idempotent` cases parametrised over `0005_m5_automations`. The targeted partial-recovery case in `test_partial_upgrade_recovers` pre-creates `automation` only (raw DDL, no indexes, no check), then runs `alembic upgrade head` and asserts both tables, all four named indexes, and both check constraints end up present.

## RRULE handling

`python-dateutil`'s `rrule` module is the parser/expander. The dependency is added to `rebuild/pyproject.toml`. `app/services/rrule.py` exposes:

```python
def validate(rrule: str, *, tz: str | None) -> None:
    """Raise ValueError on malformed rules, exhausted rules, or rules
    with an effective interval below the minimum."""

def next_fire(rrule: str, *, tz: str | None, after: datetime) -> datetime | None:
    """Return the next UTC datetime strictly after `after`, or None."""

def preview(rrule: str, *, tz: str | None, n: int = 5) -> list[datetime]:
    """Return up to N upcoming UTC datetimes for the editor preview."""
```

Implementation notes:

- Sub-daily frequencies (`MINUTELY`, `HOURLY`) parse with a fixed `DTSTART` of `2000-01-01 00:00:00` so intervals snap to clock boundaries (every-5-min fires at `:00, :05, :10`, etc.). This mirrors the legacy `_parse_rule` behaviour and avoids drift when the automation is edited.
- All other frequencies parse the RRULE as written. If the rule includes a `DTSTART:` line, it is honoured; otherwise the user's local "now" (in their timezone) is used as the anchor.
- The user's `timezone` (IANA string on the `user` row, e.g. `Australia/Sydney`) is resolved through `zoneinfo.ZoneInfo`. An invalid or missing timezone falls back to UTC, with a warning logged. DST transitions are handled by `dateutil`'s rule expansion against the localized "now" — a `FREQ=DAILY;BYHOUR=9;BYMINUTE=0` rule fires at 09:00 local both before and after a DST jump.
- The returned datetimes are normalized to UTC for storage. The DB only ever sees UTC.

Supported `FREQ` values (whitelist enforced at validation time): `MINUTELY`, `HOURLY`, `DAILY`, `WEEKLY`, `MONTHLY`. `SECONDLY` and `YEARLY` are rejected with a 422.

Limits enforced at validation time:

- Effective interval must be ≥ **5 minutes**. Computed by calling `next_fire` twice and measuring the gap; if the gap is less than 300 seconds, the rule is rejected. This catches `FREQ=MINUTELY` (1-minute interval) and `FREQ=MINUTELY;INTERVAL=2`, but allows `FREQ=MINUTELY;INTERVAL=5`. The 5-minute floor is configurable via `settings.automation_min_interval_seconds` for tests (E2E lowers it to 60 seconds so `FREQ=MINUTELY` is accepted).
- The rule must produce at least one occurrence in the next 10 years (otherwise it is "effectively dead" — typical of malformed `UNTIL=` clauses pointing into the past). Returning `None` from `next_fire` triggers a 422.
- One-shot rules (`COUNT=1`) are allowed and behave naturally: after their single execution, `next_run_at` becomes `NULL` and the scheduler stops picking them up.

Validation runs on every `POST` and `PATCH` that touches the `rrule` field, against the current authenticated user's timezone. The same function is reused inside the worker after each run to recompute `next_run_at`.

## Scheduler worker (APScheduler)

The scheduler is a single `AsyncIOScheduler` instance owned by the FastAPI app. It is started in the lifespan `startup` hook and stopped in `shutdown`. There is one trigger:

```python
scheduler.add_job(
    tick,
    trigger="interval",
    seconds=30,
    id="automation_tick",
    max_instances=1,
    coalesce=True,
    misfire_grace_time=30,
)
```

`max_instances=1` and `coalesce=True` mean that if a tick takes more than 30 seconds (it should not), overlapping ticks are merged into a single subsequent tick rather than stacking.

### Tick body

```python
async def tick() -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            now = now_ms()
            stmt = (
                select(Automation)
                .where(
                    Automation.is_active.is_(True),
                    Automation.next_run_at.is_not(None),
                    Automation.next_run_at <= now,
                )
                .order_by(Automation.next_run_at)
                .limit(settings.automation_batch_size)  # default 25
                .with_for_update(skip_locked=True)
            )
            due = (await session.execute(stmt)).scalars().all()

            run_ids: list[tuple[str, str]] = []
            for automation in due:
                run = AutomationRun(
                    automation_id=automation.id,
                    status="pending",
                )
                session.add(run)
                run_ids.append((automation.id, run.id))
            # `async with session.begin()` commits and releases the row locks here.

    for automation_id, run_id in run_ids:
        asyncio.create_task(_execute(automation_id, run_id))
```

Sequence:

1. Open one transaction.
2. `SELECT … FROM automation WHERE is_active = TRUE AND next_run_at <= :now ORDER BY next_run_at LIMIT 25 FOR UPDATE SKIP LOCKED` (where `:now = now_ms()` is bound from the application) — MySQL 8.0 native locking. Other instances polling at the same time skip these rows entirely.
3. For each row, insert one `automation_run` with `status='pending'` referencing the automation. We do **not** advance `next_run_at` here.
4. Commit, releasing the row locks.
5. Outside the transaction, spawn one `asyncio.create_task(_execute(automation_id, run_id))` per claimed automation.

`_execute` (in [Execute pipeline](#execute-pipeline)) opens its own session, sets `automation_run.status='running'`, runs the prompt, then in a final transaction:

- Updates `automation.last_run_at = now_ms()`.
- Computes `automation.next_run_at = to_ms(next_fire(rrule, tz=user.timezone, after=utcnow_dt()))` — `None` if the rule has no further occurrences. (`next_fire` keeps working in `datetime` for RRULE arithmetic; the result is converted to epoch ms before persistence.)
- Updates `automation_run.status` to `success` or `error`, sets `automation_run.error` and `automation_run.finished_at` (epoch ms).

### Crash safety

Because the SELECT-and-insert-pending transaction does **not** advance `next_run_at`, if the worker process crashes between claiming a row and finishing its execution:

- The `automation_run` row remains as `status='pending'` (or `'running'` if the executor got that far).
- `automation.next_run_at` is still in the past.
- The next 30-second tick on the same or another process re-selects the row with `FOR UPDATE SKIP LOCKED` and creates a new `pending` run.

A startup hook on the API marks any orphaned `status IN ('pending','running')` runs with `created_at < now - 5 minutes` as `error` with `error='worker crash before completion'`, so they don't sit forever in the run history. This sweep is idempotent and safe to run on every API boot.

The trade-off is that the *response* of a crashed automation may have been partially streamed to the chat/channel (M2 SSE persistence is incremental). This is fine for the chat target — the partial assistant message is still in `chat.history` and is reachable in the run history. For the channel target, partial output is discarded because the channel write is a single insert at the end of the stream (see [Execute pipeline](#execute-pipeline)).

### Single-process versus multi-process

Recommendation: **one APScheduler instance per app instance**. There is no leader election, no Redis lock, no scheduler-only deployment. Coordination is entirely delegated to `SELECT … FOR UPDATE SKIP LOCKED`:

- Two instances polling at the same instant each receive a *disjoint* subset of due rows — InnoDB row-level locking guarantees this.
- The cost is N small queries every 30s instead of one. At our scale (≤ a few hundred automations) that is negligible.
- The benefit is that the scheduler scales horizontally with the API: deploying more app pods linearly increases scheduler throughput. There is no separate process type to operate, monitor, or autoscale.
- Failure modes are symmetric: if any one app pod dies, the rest pick up its work on the next tick. There is no SPOF.

This was the explicit decision in the top-level plan ("APScheduler is fine; no Celery, no RQ"), and `SKIP LOCKED` is what makes it safe.

### Test hook

```python
# rebuild/backend/app/routers/_test_hooks.py
@router.post("/test/scheduler/tick", include_in_schema=False)
async def force_tick() -> dict[str, int]:
    if settings.env not in {"test", "staging"}:
        raise HTTPException(status_code=404)
    from app.services.scheduler import tick
    await tick()
    return {"ok": 1}
```

Registered in `app/main.py` only when `settings.env in {"test", "staging"}`. The E2E suite calls this endpoint via Playwright's `request.post()` to fast-forward the scheduler instead of waiting 30 seconds; the M6 staging smoke pack uses the same endpoint to validate the scheduler end-to-end without 30-second waits in the smoke job. Production (`ENV == "prod"`) returns 404. The unit and integration suites import `tick` directly.

Both gates are deliberate. The startup-time registration is the **primary** control — production never even mounts the route, so a refactor that breaks the inner `if` cannot expose it. The runtime `if settings.env not in {"test", "staging"}` check inside the handler is **defence in depth** against the failure mode where a future refactor accidentally moves the registration outside the env conditional (e.g. someone unifies all routers into a single registration block to "simplify"). Both checks read from the same `settings.env` source of truth, so they cannot disagree.

## Execute pipeline

Given an `automation_id` and `run_id`, `_execute` does:

1. Load the `Automation` row and its owning `User` in one session.
2. Set `automation_run.status='running'` and commit (so the UI's run-now polling sees the transition).
3. Resolve context messages:
   - **Chat target.** Load `Chat.history` (the M2 JSON blob) and walk the `messages` tree from `currentId` back to root, in chronological order. The result is `[{role, content}, ...]` matching what the M2 SSE endpoint sends to the provider.
   - **Channel target.** No prior context — channel automations are stateless posts. The "context" is the empty list.
4. Build the prompt list: `[{"role": "system", "content": automation.prompt}] + context`. The automation's `prompt` is treated as the system instruction; for channel posts where there is no context, this is the entire input.
5. Call `provider.stream(messages=…, model=automation.model_id, params={})` — the same `OpenAICompatibleProvider` instance from M2, exposed via `app.state.provider`. Iterate the SSE chunks and accumulate the full assistant text into a single string. We are not relaying tokens to a browser here, so there is no need to spool through the M2 SSE adapter — we read the chunks and concatenate.
6. Persist the result based on target:
   - **Chat target.** Call the M2-owned helper `app.services.chat_writer.append_assistant_message(session, *, chat_id=automation.target_chat_id, parent_message_id=chat.history["currentId"], model=automation.model_id, content=full_response, status="complete")`. The helper atomically updates `chat.history.messages[<id>]`, sets `chat.history.currentId`, bumps `chat.updated_at`, and returns the new message id. The message structure (parentId, childrenIds, role, model, timestamp) matches what the M2 streaming endpoint produces, so the chat displays identically whether the response came from the user's browser or from a scheduled run. The `automation_run.chat_id` is set to the existing chat id.
   - **Channel target.** Call the M4-owned helper `app.services.channels.messages.create_bot_message(session, *, channel_id=automation.target_channel_id, bot_id=automation.model_id, content=ChannelMessageContent(text=full_response, mentions=[], attachments=[], embeds=[], edited=False, automation_id=automation.id, automation_owner_name=user.name), parent_id=None) -> ChannelMessage`. The helper does the DB insert (honouring the `(user_id IS NOT NULL) + (bot_id IS NOT NULL) + (webhook_id IS NOT NULL) = 1` CHECK), updates `channel.last_message_at`, and dispatches the realtime `message:create` emit through `app.realtime.events.emit_message_create`. **M5 does not call `sio.emit` directly and does not insert `channel_message` rows directly** — going through the M4 service is the only way to keep the persistence/realtime pairing consistent (M4 §Dependencies on other milestones). `automation_id` and `automation_owner_name` are part of the M4 `ChannelMessageContent` schema (M4 §3.4); the strict validator accepts them. The `automation_run.chat_id` is left `NULL`.
7. In a final transaction, set `automation.last_run_at = now_ms()`, recompute `automation.next_run_at` (epoch ms), set `automation_run.status='success'` and `automation_run.finished_at = now_ms()`.

### Error handling

Any exception raised between step 3 and step 6 is caught:

```python
except Exception as exc:
    log.exception("automation %s run %s failed", automation_id, run_id)
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            update(AutomationRun)
            .where(AutomationRun.id == run_id)
            .values(
                status="error",
                # Hard 4000-char cap — `automation_run.error` is a TEXT column
                # (column-level cap of 65,535 bytes) but the per-run history UI
                # only ever shows the first ~10 lines and the full traceback is
                # already in the structured log line emitted by `log.exception`
                # above (correlated by `run_id`). Truncating here keeps row
                # widths bounded for the `ix_automation_run_aid_created` index
                # and makes a runaway provider error (e.g. a 1MB HTML page from
                # an upstream 502) cheap to store and cheap to ship to the UI.
                error=str(exc)[:4000],
                finished_at=now_ms(),
            )
        )
        await session.execute(
            update(Automation)
            .where(Automation.id == automation_id)
            .values(
                last_run_at=now_ms(),
                next_run_at=to_ms(next_fire(automation.rrule, tz=user.timezone, after=utcnow_dt())),
            )
        )
```

Crucially, on error we **still advance** `last_run_at` and `next_run_at`. This prevents retry storms: a permanently-failing automation (bad model id, prompt that always trips a content filter, deleted target channel) records one error per RRULE interval, not one error per 30-second tick.

### Cancellation and timeouts

Each `_execute` is wrapped in `asyncio.wait_for(..., timeout=settings.automation_timeout_seconds)` with a default of 120 seconds. A timeout is treated as an error with `error="timeout after Ns"`. This caps the worst-case impact of a misbehaving model on the scheduler.

### Run-now path

`POST /api/automations/{id}/run-now` is **inline**, not via the scheduler. It:

1. Inserts an `automation_run` with `status='pending'` directly.
2. Awaits `_execute(automation_id, run_id)` in the request handler.
3. Returns the resulting run record (now `success` or `error`).

This guarantees the response body reflects the actual outcome, which the UI relies on for the run-now button. The scheduler is not involved, so there is no race with the next tick.

## Settings additions

M5 extends the M0 `Settings` class with three new fields. The casing convention from M0 applies (env-var keys UPPER_SNAKE / Python attributes lowercase, bridged by `case_sensitive=False` — see [m0-foundations.md § Settings(BaseSettings) "Casing convention (locked)"](m0-foundations.md#settingsbasesettings)); the env-var keys appear in the "Field" column below as `AUTOMATION_*` and the Python attribute access is `settings.automation_*` everywhere in the scheduler/executor/router code.

| Field | Type | Default | Notes |
|---|---|---|---|
| `AUTOMATION_BATCH_SIZE` | `int` | `25` | LIMIT applied to the `SELECT … FOR UPDATE SKIP LOCKED` claim query in the scheduler tick. Caps how many automations a single tick can claim and execute concurrently per replica. Raise cautiously — the executor budget is `AUTOMATION_BATCH_SIZE × AUTOMATION_TIMEOUT_SECONDS` worst-case wall time for a tick. |
| `AUTOMATION_TIMEOUT_SECONDS` | `int` | `120` | `asyncio.wait_for` timeout around `_execute`. Caps the worst-case impact of a misbehaving model on the scheduler. Independent of `SSE_STREAM_TIMEOUT_SECONDS` (M2) because the executor accumulates the response server-side and does not relay tokens to a browser. |
| `AUTOMATION_MIN_INTERVAL_SECONDS` | `int` | `300` | Floor on RRULE effective interval, validated on `POST /api/automations`. The 5-minute default exists to cap fan-out into the model gateway and to keep the scheduler tick budget tractable. The E2E suite lowers this to `60` so `FREQ=MINUTELY` rules can be tested without waiting; production must not lower it without re-running the M4/M5 load benchmark from `m6-hardening.md`. |

## API surface

All endpoints are mounted at `/api/automations`, require the trusted-header user dependency from M0, and return JSON. Pydantic models are colocated with the router under `rebuild/backend/app/schemas/automation.py`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/automations` | List the calling user's automations. Response: `{items: AutomationListItem[]}` where each item carries `id, name, model_id, rrule, target_chat_id, target_channel_id, is_active, last_run_at, next_run_at, last_run_status`. Paginated only if needed (per-user count is small); cursor=`updated_at,id`. |
| `POST` | `/api/automations` | Create. Body: `AutomationCreate` (`name, prompt, model_id, rrule, target_chat_id?, target_channel_id?, is_active?`). 201 with full `AutomationDetail`. Validation: RRULE valid for the user's timezone; exactly one target set; target row exists and is owned by the user (chat) or membership-visible (channel). |
| `GET` | `/api/automations/{id}` | Details + last 10 runs. Response: `AutomationDetail` with `runs: AutomationRun[]` (length ≤ 10) and `next_runs: datetime[]` (length 5, computed on the fly via `preview`). |
| `PATCH` | `/api/automations/{id}` | Partial update of any field. Re-validates RRULE if changed; recomputes `next_run_at` if `rrule` or `is_active` changed. If `is_active` flips false-to-true, `next_run_at` is recomputed from now; if true-to-false, `next_run_at` is set to `NULL`. |
| `DELETE` | `/api/automations/{id}` | 204. Cascade-deletes all `automation_run` rows. |
| `POST` | `/api/automations/{id}/run-now` | Inline trigger. Synchronous. Returns the resulting `AutomationRun`. Does not touch `next_run_at` or `last_run_at` — the scheduler still owns those. |
| `GET` | `/api/automations/{id}/runs?cursor=…&limit=…` | Paginated run history, latest first. Default limit 25, max 100. Cursor is opaque base64 of `(created_at, id)` to avoid offset drift on busy automations. |
| `POST` | `/api/automations/preview-rrule` | Non-mutating helper for the editor's "Next 5 runs" panel and live RRULE validation. Body: `{rrule: string}`. Response: `{next_runs: datetime[]}` (length 5, computed in the caller's IANA timezone via the same `validate` / `preview` helpers from `app.services.rrule` used by `POST /api/automations`). Returns 422 with the parser error on an invalid RRULE. Client-side throttled: `<RRulePicker>` debounces to one call per change, so the editor stays well below any reasonable server-side limit. No dedicated rate-limit bucket is added in M6 (the buckets are chat completions, file uploads, and webhook ingress); the request is still subject to the global per-route HTTP timeout in `m6-hardening.md` § Per-route HTTP timeouts. |

All endpoints enforce ownership: the requesting `user.id` must equal `automation.user_id`. There is no admin override (the rebuild has no admin role — see top-level plan section 3). For the channel target, the user must be a member of `target_channel_id` at create/update time; subsequent membership loss is a soft failure handled at execute time (the run errors with `error="not a member"` and is not retried until the user fixes it or removes the automation).

## Frontend

Routes under `rebuild/frontend/src/routes/(app)/automations/`:

- `+page.svelte` — list view. Fetches `GET /api/automations` on mount and renders `<AutomationList>`. New-automation button navigates to `/automations/new` (`+page.svelte` under `[id]/+page.svelte` handles `id === "new"` by rendering an empty editor).
- `[id]/+page.svelte` — editor + run history. Fetches `GET /api/automations/{id}` and renders `<AutomationEditor>` + `<RunHistory>`.

Components under `rebuild/frontend/src/lib/components/automations/`, all ported and trimmed from the legacy `src/lib/components/automations/*` tree:

- **`AutomationList.svelte`** — table of name, target (chat link or channel name), `next_run_at` formatted relatively, `last_run_status` badge, active toggle. Click row → editor. Empty state with "Create your first automation" CTA.
- **`AutomationEditor.svelte`** — form with name, prompt (textarea), `<ModelDropdown>` (reuses M2's model selector), `<RRulePicker>`, `<TargetSelector>`, active toggle, save/delete/run-now buttons. State is the loaded automation; edits are local until "Save". Save sends `PATCH` (or `POST` if id === "new"). Run-now button posts and then begins polling `GET /api/automations/{id}/runs?limit=1` every 1.5s for up to 60s, replacing the latest run row in `<RunHistory>` as its status transitions `pending → running → success|error`. The polling lifecycle (interval registration + cleanup, plus a 60s deadline `setTimeout`) is owned by a single `$effect` inside `<AutomationEditor>` so it auto-cleans on unmount or on a second run-now click — per [m0-foundations.md § Frontend conventions (cross-cutting)](m0-foundations.md#frontend-conventions-cross-cutting), rule 3, this must not be `onMount` + `onDestroy` and must not live at module scope:
  ```svelte
  let polling = $state<{ runId: string } | null>(null);
  $effect(() => {
    if (!polling) return;
    const controller = new AbortController();
    const intervalId = setInterval(() => pollOnce(polling.runId, controller.signal), 1500);
    const deadlineId = setTimeout(() => { polling = null; }, 60_000);
    return () => { clearInterval(intervalId); clearTimeout(deadlineId); controller.abort(); };
  });
  ```
- **`RRulePicker.svelte`** — direct port of `ScheduleDropdown.svelte` from the legacy tree. Frequency tabs (`Once`, `Hourly`, `Daily`, `Weekly`, `Monthly`, `Custom`), interval input, weekday picker, hour/minute pickers, custom raw RRULE textarea. **The picker is a stateful form-control wrapper** — the parent owns the canonical RRULE string and the picker decomposes it into its UI controls — so it exposes a single `$bindable` prop, used as `<RRulePicker bind:value={automation.rrule} />`. This is the one place in M5 where `$bindable` is the right call (per [svelte-best-practises.md § 5](../best-practises/svelte-best-practises.md), `$bindable` is reserved for genuine two-way controls; M5 does not introduce any others — every other parent/child relationship uses callback props). Includes a "Next 5 runs" preview that calls the debounced `POST /api/automations/preview-rrule` endpoint (see [API surface](#api-surface)) so RRULE validation errors surface live as the user edits.
- **`RunHistory.svelte`** — virtualized list of `AutomationRun` rows with status badge, relative `created_at`, duration (`finished_at - created_at`), and an expand toggle that shows the linked chat (if `chat_id` set) or the error text. Loads page 1 on mount; "Load more" pages via the cursor.
- **`TargetSelector.svelte`** — single-choice toggle between "Chat" and "Channel". When "Chat" is selected, shows a chat picker (search-as-you-type against `GET /api/chats?q=…`) — the user picks an existing chat and successive runs append to its history. **There is no "create a new chat per run" affordance in v1**; supporting it would require a new backend field (`new_chat_per_run: bool`), per-run chat-create logic in the executor, and an extra schema migration to track which chat each run produced — none of which earn their keep before users have asked for the feature. If this is wanted later it lands as a focused follow-up. When "Channel" is selected, lists the user's channels via `GET /api/channels`. Disabled (with explanatory tooltip) if M4 has not shipped — see [Dependencies on other milestones](#dependencies-on-other-milestones).

State management: the list and detail routes use `+page.server.ts` `load` (server-only — see [sveltekit-best-practises.md § 2.1 / § 2.3](../best-practises/sveltekit-best-practises.md); the data is auth-gated and comes from our own backend). Client-side cache lives in an `AutomationsStore` class at `src/lib/stores/automations.svelte.ts`, instantiated and provided via `setContext` in `(app)/automations/+layout.svelte`. The shape follows the project-wide convention from [m0-foundations.md § Frontend conventions (cross-cutting)](m0-foundations.md#frontend-conventions-cross-cutting): no module-level `$state`, no module-scope timers, `*.svelte.ts` filename, optimistic updates with rollback on error. Editor edits are optimistic — on save the local state updates first, then on server response the canonical data replaces it; on error the UI rolls back and a `toast.push('error', …)` is fired.

The legacy `TerminalDropdown.svelte` is **not** ported. Terminals are out of scope for the rebuild.

## Tests

### Unit

- `tests/unit/test_rrule.py` — table-driven cases:
  - `validate` accepts `FREQ=DAILY;BYHOUR=9`, `FREQ=WEEKLY;BYDAY=MO,WE,FR`, `FREQ=MINUTELY;INTERVAL=5`, `FREQ=HOURLY`, `FREQ=MONTHLY;BYMONTHDAY=1`, `RRULE:FREQ=DAILY;COUNT=1` with an explicit `DTSTART`.
  - `validate` rejects `FREQ=SECONDLY`, `FREQ=YEARLY`, malformed strings, `FREQ=MINUTELY` (1-min interval below 5-min floor), `UNTIL=20000101T000000Z` (no future occurrences).
  - `next_fire` honours the user's timezone across DST boundaries: `FREQ=DAILY;BYHOUR=9;BYMINUTE=0` for `Australia/Sydney` returns 09:00 local both before and after the October DST jump (verified by computing the gap between consecutive fires across the boundary).
  - `preview` returns 5 strictly-increasing UTC datetimes.
- `tests/unit/test_automation_target.py` — Pydantic root validator rejects payloads with both targets, neither target, and mismatched ownership.

### Integration

- `tests/integration/test_scheduler_tick.py` —
  - Insert a due automation and an undue automation, call `tick()` directly, assert exactly one `automation_run` is created in `pending` state, then assert the scheduler advanced `last_run_at` and `next_run_at` after `_execute` finishes (via `await asyncio.gather(*pending_tasks)`).
  - Run two concurrent `tick()` invocations against the same DB and assert no duplicate `automation_run` was created (proves `FOR UPDATE SKIP LOCKED` is in effect).
  - Simulate a crash: monkey-patch `_execute` to `raise CancelledError` after inserting the pending run, then call the orphan-sweep startup hook and assert the run is marked `error` with the crash sentinel.
- `tests/integration/test_run_now.py` — call `POST /api/automations/{id}/run-now` against a chat-target automation with a recorded SSE cassette, assert the chat's `history.messages` gained an assistant message with the cassette body, the returned run is `success`, and `next_run_at` is unchanged.

### Component (Playwright CT)

- `tests/component/rrule-picker.spec.ts` — switching frequency rebuilds the rrule string; the preview list updates within 300ms of input; the custom-raw textarea round-trips a known valid string.
- `tests/component/automation-editor.spec.ts` — required-field validation; save call payload matches the expected shape (asserted via MSW handler).
- `tests/component/run-history.spec.ts` — pagination via the cursor; expand toggle reveals the chat link or error.

### E2E (the critical-path lock)

- `tests/e2e/automation-minutely.spec.ts`:
  1. Sign in via the `X-Forwarded-Email` header, navigate to `/automations/new`.
  2. Fill in name, prompt (deterministic so the cassette matches), pick a model, pick `FREQ=MINUTELY;INTERVAL=5` in the picker (E2E env lowers the min-interval floor to 60s, so this is accepted).
  3. Set target to a freshly-created chat. Save.
  4. `await request.post("/test/scheduler/tick")`.
  5. Poll `GET /api/automations/{id}/runs` until length ≥ 1 and `status === "success"` (max 5 seconds).
  6. Open the chat, assert the assistant message body equals the cassette body.
  7. Repeat steps 4–5 with a channel-target automation (created in a separate test) and assert the new `channel_message` arrives in a second `BrowserContext` via the M4 socket.io listener.

A single recorded SSE cassette `tests/fixtures/llm/automation_minutely.sse` covers the deterministic prompt for both the chat and channel cases; the request hash includes `model`, `messages`, and `stream=true` so the same cassette is used regardless of target.

## Dependencies on other milestones

- **Hard dependency on M0** — Alembic baseline, async session factory, settings, `/healthz`, trusted-header auth, FastAPI lifespan plumbing.
- **Hard dependency on M2** — `OpenAICompatibleProvider`, `Chat` table, `chat.history` JSON shape, the `app.services.chat_writer.append_assistant_message` helper (declared in M2 §Deliverables), and the `models` discovery used by the editor's model picker.
- **Hard dependency on M4** — channel target uses the `channel`, `channel_member`, `channel_message` tables, the `channel_message.bot_id` column (M4's design — no synthetic user is inserted; the row carries a non-null `bot_id` and null `user_id`/`webhook_id`), the optional `automation_id` / `automation_owner_name` fields on `channel_message.content` (M4 §3.4), and the M4-owned service helper `app.services.channels.messages.create_bot_message(...)` which performs the DB insert and the realtime `message:create` broadcast. M5 must call this helper rather than emitting socket events directly. **M4 must land before M5's Alembic revision applies**, because M5's `automation` model declares an inline FK from `target_channel_id` to `channel.id` — without `channel`, the migration fails at apply time. The milestone ordering in `rebuild.md` §0 (M4 → M5) already enforces this; do not attempt a "chat-only mode" workaround that defers the FK, because the inline declaration makes that incoherent. If a hard deadline ever forced M5 first, the right path would be to split M5 into M4a (chat-only, drops the `target_channel_id` column entirely) and M4b (adds the column + FK + UI in a follow-up revision once M4 lands), not to feature-flag a half-built schema.

## Acceptance criteria

- [ ] `automation` and `automation_run` tables exist with the exact columns, indexes, and CHECK constraints listed under [Data model](#data-model).
- [ ] Alembic migration `0005_m5_automations` is reversible: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` round-trips on a fresh MySQL 8.0. Re-running `alembic upgrade head` immediately after `head` and re-running `alembic downgrade base` after `base` are both no-ops (covered by the M0 idempotency tests parametrised over the M5 revision).
- [ ] `test_partial_upgrade_recovers` includes an M5 case: pre-create `automation` only (raw DDL, no indexes, no check), then `alembic upgrade head` produces `automation_run`, all four named indexes, and both `ck_automation_*` check constraints without operator intervention.
- [ ] `POST /api/automations` rejects malformed RRULEs with 422 and a human-readable detail.
- [ ] `POST /api/automations` rejects payloads with both `target_chat_id` and `target_channel_id`, or neither, with 422.
- [ ] `POST /api/automations` rejects RRULEs with effective interval below `settings.automation_min_interval_seconds` (default 300, i.e. 5 minutes).
- [ ] APScheduler runs in-process, ticks every 30s, claims due automations with `FOR UPDATE SKIP LOCKED`, and dispatches `_execute` via `asyncio.create_task`.
- [ ] Two concurrent processes against the same DB never produce duplicate `automation_run` rows for the same `(automation_id, tick)` window (verified by the integration test).
- [ ] Killing the worker process mid-`_execute` (`kill -9` simulated by `CancelledError`) does **not** advance `next_run_at`, and the next tick re-claims the automation. The orphaned `pending`/`running` row is swept to `error` on next API boot.
- [ ] A successfully-executed chat-target automation appends an assistant message visible in the chat UI with no manual reload.
- [ ] A successfully-executed channel-target automation produces a new `channel_message` with `bot_id=automation.model_id`, `user_id IS NULL`, `webhook_id IS NULL`, that arrives in connected sockets within the test's 200ms window.
- [ ] `POST /api/automations/{id}/run-now` returns synchronously with the final run status; the scheduler is not involved.
- [ ] An automation that errors does so exactly once per RRULE interval (no retry storm).
- [ ] FK CASCADE on `automation.target_chat_id` and `automation.target_channel_id`: deleting the parent `chat` (or `channel`) row cascades to delete every automation pointing at it, and onward to every `automation_run` belonging to those automations. Verified by an integration test that creates an automation against a chat, runs it once to populate `automation_run`, deletes the chat, and asserts both `automation` and `automation_run` rows are gone — and asserts the `ck_automation_exactly_one_target` CHECK is **never** violated mid-cascade (the test would otherwise see an `IntegrityError` from MySQL aborting the parent delete).
- [ ] `POST /api/automations/preview-rrule` returns `{next_runs: [t0, t1, t2, t3, t4]}` for a valid `FREQ=HOURLY` RRULE and 422 for `"FREQ=NOT_REAL"`. Sub-`AUTOMATION_MIN_INTERVAL_SECONDS` rules return `next_runs` (the helper validates RRULE syntax only; the interval-floor check lives on `POST /api/automations` so the editor can surface a softer warning before commit).
- [ ] DST correctness: a `FREQ=DAILY;BYHOUR=9;BYMINUTE=0` automation owned by a user with `timezone='Australia/Sydney'` fires at 09:00 local on the day of the DST transition (verified by a unit test that inspects three consecutive `next_fire` results across the boundary).
- [ ] One-shot rules (`COUNT=1`) execute exactly once and then `next_run_at IS NULL`; the scheduler stops picking them up.
- [ ] `/test/scheduler/tick` is registered only when `settings.env in {"test", "staging"}`; the route is absent in production (returns 404).
- [ ] Visual-regression baselines `automation-list.png` and `automation-editor.png` captured under `rebuild/frontend/tests/visual-baselines/m4/` (Git LFS) against the deterministic editor + run-history fixture.
- [ ] The E2E test `automation-minutely.spec.ts` passes deterministically against the recorded SSE cassette.
- [ ] `AutomationsStore` lives at `lib/stores/automations.svelte.ts` (not `.ts`), exports a class instantiated via `setContext` in `(app)/automations/+layout.svelte`. The run-now `setInterval` polling and 60s deadline `setTimeout` in `<AutomationEditor>` live inside a single `$effect(() => { …; return () => cleanup(); })`. No module-scope timers anywhere under `frontend/src/lib/stores/` (verified by the M0 grep gate). `<RRulePicker>` exposes its rule via `value = $bindable<string>('')` and is the only `$bindable` introduced by M5.
- [ ] `make format` and `make test` pass under `rebuild/`.

## Out of scope

- Multi-step automations. One automation = one prompt.
- Chained automations (output of one feeding the next).
- Input variables / templating beyond a fixed `{{date}}` token (deferred — easy to add later as a pre-execute string substitution; not on the critical path).
- Per-run notifications (email, webhook, Slack ping). Channel-target automations naturally surface in Slack-shape via the channel UI; chat-target automations are visible in the chat list. No email notifier is built.
- Automation marketplace, sharing automations across users, public automation templates.
- Per-automation rate limiting beyond the global RRULE min-interval floor.
- Retries with backoff. The scheduler runs the rule on its schedule; if a run fails, the next attempt is the next scheduled fire, not an immediate retry.
- Tools, terminals, function-calling, code-interpreter, web-search, image-generation. The legacy executor's tool/feature/filter resolution path is not ported. Automations call the model with the user's prompt and nothing else.
- Admin-level views, cross-user run dashboards, usage analytics.
- Pause-all / kill-switch for automations beyond the per-row `is_active` toggle.

## Open questions

- **Run-now concurrency.** Should `run-now` be allowed while a scheduled run is already in flight for the same automation? Current decision: yes (both runs proceed independently, each producing a chat assistant message or channel post). If product testing surfaces user confusion, we add a 409 conflict guard at run-now time. No code work needed up front.
- **Channel target authorship.** The post carries `bot_id=automation.model_id` (per M4) plus the `automation_owner_name` field in `content` so the UI can render "via @sam's automation 'Daily standup'". Confirm copy with design before launch.
- **Editor preview endpoint.** `POST /api/automations/preview-rrule` is a small helper that exists purely for the live "next 5 runs" UI. It is non-mutating and cheap. Acceptable, or fold into a query parameter on `GET /api/automations`? Keeping it as a separate endpoint for clarity unless review pushes back.
