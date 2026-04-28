# FastAPI best-practices audit of the M0–M5 plans

> **Status: applied.** All recommendations in this document have been
> incorporated into the M0–M5 plans. The audit text below is preserved as the
> rationale record; see [§ Applied edits log](#applied-edits-log) at the
> bottom for the full list of edits and where they landed.

This document audits the rebuild plans (`m0-foundations.md` … `m5-hardening.md`)
against [`FastAPI-best-practises.md`](FastAPI-best-practises.md). The bias
throughout is **simplicity over correctness theatre**: only changes that
materially reduce defects, drift, or future surprise are flagged. Stylistic
nits that the team can reasonably leave alone are listed separately at the
bottom.

The audit covers ~5,500 LOC of plans. Headline result: the plans are **largely
in line** with the best-practices doc. There are **three real defects** worth
fixing before any code is written, **two style-consistency tightenings** that
are cheap to apply now and expensive later, and **one over-engineering hot
spot** in M3.

---

## Verdict matrix

| Plan | Real defects | Style tightenings | Over-engineering | Overall |
|---|---|---|---|---|
| M0 — Foundations | 0 | 1 | 0 | clean |
| M1 — Conversations | 1 | 2 | 0 | one fix needed |
| M2 — Sharing | 0 | 2 | 0 | clean |
| M3 — Channels | 1 | 0 | 1 | refactor before build |
| M4 — Automations | 0 | 0 | 0 | clean |
| M5 — Hardening | 0 | 0 | 1 (mild) | optional simplification |

---

## Defects (fix before implementation)

### D1 — M1: module-level `OpenAICompatibleProvider()` singleton

`rebuild/plans/m1-conversations.md` ends `app/providers/openai.py` with:

```396:402:rebuild/plans/m1-conversations.md
        for chunk in resp:
            yield chunk.choices[0].delta.content or ""


provider = OpenAICompatibleProvider()
```

This violates two rules in [`FastAPI-best-practises.md`](FastAPI-best-practises.md):

- §A.5 — "Initialise side-effecting objects in `lifespan`, not at import." A
  module-level instance is constructed at first import, which (a) runs before
  Settings has finished loading in some test paths, (b) is shared across forked
  Uvicorn workers in ways that confuse connection pools, and (c) makes test
  override (`app.dependency_overrides`) impossible — there is nothing to
  override.
- §B.4 — Provider must be reachable as a FastAPI dependency. Routes that import
  the singleton directly become un-fakeable in unit tests, which forces
  integration-style HTTP-mocking for what should be a 5-line provider stub.

**Fix.** Construct the provider in `lifespan` and expose it via a dependency,
exactly as the best-practices doc shows:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.provider = OpenAICompatibleProvider()
    yield

def get_provider(request: Request) -> OpenAICompatibleProvider:
    return request.app.state.provider

Provider = Annotated[OpenAICompatibleProvider, Depends(get_provider)]
```

Then `chat_stream(...)` takes `provider: Provider` instead of importing the
module-level name. Tests inject a fake by `app.dependency_overrides[get_provider] = lambda: FakeProvider()`.

The change touches three files: `providers/openai.py`, `core/deps.py`,
`services/chat_stream.py`. ~15 LOC total.

### D2 — M3: socket.io `Users.get_or_create_by_email` duplicates auth logic

```516:520:rebuild/plans/m3-channels.md
    if not email:
        raise ConnectionRefusedError("missing trusted header")
    user = await Users.get_or_create_by_email(
        email, name=environ.get("HTTP_X_FORWARDED_NAME"))
    await sio.save_session(sid, {"user_id": user.id, "email": email})
```

`Users.get_or_create_by_email(...)` is a class that does not exist in any other
plan. The HTTP `get_user` dependency in M0 (`m0-foundations.md` §"Auth")
already does *exactly this* — read trusted headers, upsert the `user` row,
return the `User`. M3 silently re-implements it for socket.io, which means:

- two implementations of the same auth contract drift over time (e.g. the day
  someone adds a `last_seen_at` update to one but not the other);
- two implementations of the upsert race condition handling;
- the test suite has to test "trusted-header → user" twice.

**Fix.** Refactor M0's `get_user` to call a small pure helper:

```python
# app/core/auth.py (new, ~25 LOC)
async def upsert_user_from_headers(
    db: AsyncSession, *, email: str, name: str | None
) -> User: ...
```

Then:

- M0's `get_user` becomes `email = request.headers["X-Forwarded-Email"]; return await upsert_user_from_headers(db, email=email, name=...)`.
- M3's socket.io `connect` handler calls the same helper inside an
  `AsyncSessionLocal()` context.

This is what the best-practices doc means by "do not duplicate auth": one
helper, two callers (HTTP dep + socket.io handler). Document the helper in
M0 and have M3 import it; M3's "Auth" section then becomes a single sentence
("uses the M0 `upsert_user_from_headers` helper").

### D3 — M1, M2, M3: `Mapped[dict]` is too loose for strict mypy

```52:54:rebuild/plans/m1-conversations.md
    # Source of truth for the conversation tree. Shape documented below.
    history: Mapped[dict] = mapped_column(
        MySQLJSON,
```

```48:49:rebuild/plans/m2-sharing.md
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    history: Mapped[dict] = mapped_column(JSON, nullable=False)
```

```167:168:rebuild/plans/m3-channels.md

    content: Mapped[dict] = mapped_column(JSON, nullable=False)
```

`Mapped[dict]` is `Mapped[dict[Unknown, Unknown]]` under mypy strict — the
exact opposite of what the rest of the project does (every other column is
precisely typed). The shapes are documented inline; the type should reflect
that.

**Fix.** Use `Mapped[dict[str, Any]]` (or a narrower `TypedDict` if you want
to push it further, but `dict[str, Any]` matches how SQLAlchemy emits the
JSON column):

```python
from typing import Any
history: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
```

One-line change in each of the three plans. Costs nothing, prevents a wave of
mypy noise on day one of M1 implementation.

---

## Style consistency (apply once, save churn)

### S1 — Pydantic `extra="forbid"` is not uniform

The best-practices doc requires `model_config = ConfigDict(extra="forbid")` on
**every** request body. The plans apply it inconsistently:

- M1: applied to `History` and `HistoryMessage` (lines 215, 232) but **not**
  to `ChatCreate`, `ChatPatch`, `MessageSend`, `ChatParams`.
- M2: not applied to `ShareCreateResponse`, `SharedBy`, `SharedChatResponse`.
- M3: applied to `ChannelMessage.content` validator only (mentioned line 980).
- M4: applied (per-schema, manually).

**Recommendation.** Add `app/schemas/_base.py` once in M0:

```python
from pydantic import BaseModel, ConfigDict

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
```

Then every request schema in M1–M5 inherits from `StrictModel` instead of
`BaseModel`. Two upsides:

- one place to flip a knob (e.g. `populate_by_name=True` if the FE ever
  switches to camelCase);
- impossible to forget on a new schema — you'd have to deliberately import
  `BaseModel` and explain why.

Add a one-liner in M0 §"Pydantic conventions" (currently absent), then update
M1/M2/M3 plans to say "request bodies inherit from `StrictModel`."

### S2 — `Annotated[T, Depends(...)]` should be the project convention

Plans show old-style `Depends()` in parameter defaults:

- `m0-foundations.md` line 182: `db: AsyncSession = Depends(get_session)`
- `m3-channels.md` line 612: `Depends(get_user)` referenced in prose.

The best-practices doc commits to `Annotated[T, Depends(...)]` (lines 51–58)
and provides type aliases in `app/core/deps.py`:

```python
CurrentUser = Annotated[User, Depends(get_user)]
DbSession   = Annotated[AsyncSession, Depends(get_session)]
Provider    = Annotated[OpenAICompatibleProvider, Depends(get_provider)]
```

**Recommendation.** Add `app/core/deps.py` to M0's "Files to create" list
(it's currently missing — the deps live in `app/core/auth.py` and
`app/db/session.py` but there's no central type-alias module). Update M0's
`get_user` example, M1's streaming endpoint signature, M3's "Auth" prose, and
the M4 router signatures to use the aliases. The pattern then propagates
naturally because the aliases are the path of least resistance.

This is a one-pass edit across the four files; the resulting routes are
shorter, type-checkable, and stop re-typing `AsyncSession = Depends(...)` ten
times per file.

---

## Over-engineering

### O1 — M3 service layer is split into 8 files, most are CRUD

```32:34:rebuild/plans/m3-channels.md
- `rebuild/backend/app/services/channels/` — service layer
  (`channels.py`, `members.py`, `messages.py`, `reactions.py`, `pins.py`,
  `webhooks.py`, `files.py`, `mentions.py`).
```

The best-practices doc's promotion criteria for a service file are: ≥80 LOC of
orchestration, ≥3 callers of a query, OR a multi-table transactional invariant.
By that bar:

| File | Justification | Verdict |
|---|---|---|
| `messages.py` | `last_message_at` denorm + emit-realtime + auto-reply trigger; 3+ callers (M3 routers, M4 executor, webhook ingress). | **Keep.** This is the canonical service example in the best-practices doc. |
| `channels.py` | List/get/create/archive — all single-table CRUD. | **Drop.** Inline in router. |
| `members.py` | Add/remove member, change role — single-table CRUD with one FK insert. | **Drop.** Inline in router. |
| `reactions.py` | Toggle a reaction — `INSERT … ON DUPLICATE KEY UPDATE`. | **Drop.** Inline in router. |
| `pins.py` | Two boolean updates. | **Drop.** Inline in router. |
| `webhooks.py` | Create/list/rotate/delete webhook + token hash. The hash is one helper, not a service. | **Drop.** Inline in router; helper goes in `app/core/secrets.py`. |
| `files.py` | Upload/download wraps `FileStore`. | **Drop.** Router calls `FileStore` directly (that's why `FileStore` is a Protocol). |
| `mentions.py` | Pure regex parser + classifier; 2 callers (the FE mirror is a separate file). | **Keep** (or fold into `messages.py`; either is fine). |
| `auto_reply.py` | Semaphore + cancel registry + latest-wins; complex enough to want isolation; 1 caller (the message hook). | **Keep**, but **move** to `app/services/channels/auto_reply.py` for locality (it is 100% channel-coupled). |

**Net change.** From `services/channels/{8 files}` + `services/auto_reply.py`
(9 files, ~600 LOC of glue) to `services/channels/{messages.py, mentions.py,
auto_reply.py}` (3 files, ~400 LOC of actual logic). The dropped service files
are ~20 LOC of "call repo, return result" each — exactly the wrapper boilerplate
the best-practices doc warns against in §A.1 ("Don't add a layer because the
folder exists").

Routers grow by ~10 LOC each (the inlined CRUD), but those 10 LOC were already
going to exist as the body of the service function — they just move one file
up. Net LOC delta: roughly −150.

**Recommendation.** Update M3 §"Files to create" to:

```
- rebuild/backend/app/services/channels/messages.py
- rebuild/backend/app/services/channels/mentions.py     (optional)
- rebuild/backend/app/services/channels/auto_reply.py
```

…and remove `channels.py`, `members.py`, `reactions.py`, `pins.py`,
`webhooks.py`, `files.py` from the service layer. Drop the standalone
`app/services/auto_reply.py` and reference the channels-scoped path
everywhere.

### O2 — M5 per-route timeouts via decorator + middleware (mild)

```122:122:rebuild/plans/m5-hardening.md
Configured in a single dispatch table `app/observability/timeouts.py` and applied via a request-scoped `asyncio.wait_for` in a middleware (`TimeoutMiddleware`). The middleware reads the timeout from a route attribute (`request.scope["route"].timeout_seconds`) set by an `@route_timeout(seconds)` decorator; routes without the decorator inherit the default.
```

The decorator-mutates-route-attribute + middleware-reads-route-attribute pattern
is more machinery than a 50-LOC concern needs. It works, but it spreads a
single feature across three files (`timeouts.py`, the decorator module, the
middleware module) and relies on the slightly awkward `request.scope["route"]`
access.

**Simpler alternative.** Use a dependency factory:

```python
# app/observability/timeouts.py
def timeout(seconds: float):
    async def _enforce(request: Request):
        async with anyio.fail_after(seconds):
            yield
    return Depends(_enforce)

# app/routers/chats.py
@router.post(
    "/{id}/messages",
    response_model=...,
    dependencies=[timeout(300)],
)
async def send_message(...): ...
```

One file, one decorator, declarative at the route declaration. Default
timeout is enforced by a single `TimeoutMiddleware` (kept) that reads `300s`
unless a route-level dep overrides via `request.state.timeout`.

This is a **judgement call**, not a defect. The existing approach is workable;
flag it as something to revisit if the timeouts table grows beyond ~10 routes.
If M5 is already half-implemented when you read this, leave it.

---

## Smaller observations (do at your leisure)

- **N1 — `LOG_LEVEL` is declared in M0 §Settings but M5 lists it as "new".**
  M5 line 10 lists `LOG_LEVEL` and `LOG_FORMAT` together as "five new env
  vars"; only `LOG_FORMAT` (and the three OTel vars) are new. Reword M5 to
  "extends Settings with `LOG_FORMAT`, `OTEL_*`" and reference M0 for
  `LOG_LEVEL`.
- **N2 — M0 does not enumerate the Pydantic conventions.** Add a one-paragraph
  §"Pydantic conventions" pointing at `StrictModel` (S1), `EmailStr`,
  `AnyUrl`, `from __future__ import annotations`, no `Optional[X]` (use
  `X | None`). One paragraph saves five "why didn't you forbid extras"
  comments per PR.
- **N3 — M1's `chat_stream.py` plan does not reference cancellation in the
  prose section.** The streaming code in the best-practices doc requires
  catching `asyncio.CancelledError`, persisting partial output, and
  re-raising. M1's pseudo-code shows the persistence loop but not the
  cancellation handler. Add one sentence: "the generator must catch
  `asyncio.CancelledError`, flush the partial assistant message via
  `chat_writer.append_assistant_message(..., partial=True)`, and re-raise."
- **N4 — Heartbeat cadence numbers should match across plans.** M1
  (streaming) says SSE heartbeat "every 15s", M3 (socket.io) says "every 25s",
  M5 references "default 25s for SSE". Pick one (15s is fine for both) and
  state it in M0 as a project constant `STREAM_HEARTBEAT_SECONDS = 15`.
- **N5 — `app/realtime/events.py` thin emit-helper layer (M3 line 30–31).**
  Worth a sentence in M3 confirming "kept ≤80 LOC, no business logic, just
  typed payload + `await sio.emit(...)`." Otherwise this innocuous file is the
  natural place where a future contributor parks "a tiny bit of validation"
  and it becomes a third service layer by accident.

---

## What is *not* a problem (deliberate calls reaffirmed)

These look like deviations from generic FastAPI advice but are deliberate
project choices that the best-practices doc already explicitly endorses:

- **No repository pattern as a universal layer.** M1's `ChatRepo` is the only
  repo and exists because the chat-history JSON access pattern is shared by
  three callers. Other domains use SQLAlchemy directly in services. This is
  the §A.1 / §C.1 "promote-on-evidence" principle.
- **Single `Settings` class for the whole app.** Per-domain `BaseSettings`
  would be over-engineering for an app this size.
- **Custom rate limiter (M5) instead of `slowapi`.** Justified by the per-user
  + per-org sliding window requirement that `slowapi` does not model. M5's
  ~120 LOC + Redis Lua is well below the cost of bending `slowapi`.
- **Two load-test tools (`bench_channels.py` and `k6_chat.js`).** They cover
  different shapes — multi-context socket.io for M3, simple HTTP fan-out for
  M1 — and `k6` cannot fake socket.io clients without writing a custom
  extension. Keeping both is correct.
- **`bot_id` not declared as a FK on `channel_message`.** Already debated in
  M3 and rationalised. Bots are conceptual, not row-backed; FK would force a
  surrogate `bot` table for nothing.
- **Trusted-header auth, no JWT.** Locked by `rebuild.md` §3, deliberate.
- **`MEDIUMBLOB` files in MySQL.** Locked by `rebuild.md` and audited in
  `database-best-practises.md`.
- **APScheduler in-process, single instance for M4.** Deliberate; ops doc
  `m5-hardening.md` covers the failover story.

---

## Summary of recommended edits

If you want to apply only the fixes that move the needle, do these six things,
in order:

1. **D1.** Move `OpenAICompatibleProvider` construction to `lifespan` in M1.
   Add `get_provider` dep and `Provider` type alias. Update routes/services.
2. **D2.** Add `app/core/auth.upsert_user_from_headers` in M0; have M0's
   `get_user` and M3's socket.io `connect` both call it.
3. **D3.** Replace `Mapped[dict]` with `Mapped[dict[str, Any]]` in M1
   (`Chat.history`), M2 (`SharedChat.history`), M3 (`ChannelMessage.content`).
4. **S1.** Add `StrictModel` in M0; have M1/M2/M3 request bodies inherit from
   it. Remove the per-class `model_config = ConfigDict(extra="forbid")`
   duplication.
5. **S2.** Add `app/core/deps.py` with `CurrentUser`, `DbSession`, `Provider`
   type aliases; update plan code samples to the `Annotated[T, Depends(...)]`
   form.
6. **O1.** Collapse M3's service layer from 9 files to 3
   (`messages.py`, optional `mentions.py`, `auto_reply.py`); inline the rest in
   the routers.

Items 1–3 are 1-line or sub-20-LOC fixes. Items 4–5 are pure plan edits
(no code yet exists). Item 6 deletes ~150 LOC of forecast wrapper boilerplate.

The optional simplification (O2) and observations (N1–N5) can be picked up as
the corresponding milestones come into focus.

---

## Applied edits log

All recommendations above have been applied. The following table maps each
audit item to the plan it lives in now and the section to grep for if you
want to verify or revert.

| Item | Plan | Where it landed |
|---|---|---|
| **D1** — Provider in `lifespan` + `Provider` dep alias | `m1-conversations.md` | New prose block after the `OpenAICompatibleProvider` class showing `lifespan`, `get_provider`, and `Provider = Annotated[...]`. Streaming pseudo-code now takes `provider: OpenAICompatibleProvider` as a parameter. The trailing module-level `provider = OpenAICompatibleProvider()` line is removed. |
| **D2** — `upsert_user_from_headers` shared helper | `m0-foundations.md` § Trusted-header dependency; `m3-channels.md` § Connect-time auth | M0's `get_user` is rewritten to delegate to `upsert_user_from_headers(db, *, email, name)`. M3's socket.io `connect` handler imports the same helper instead of declaring `Users.get_or_create_by_email`. Acceptance criterion added in M3 ("no second auth implementation"). |
| **D3** — `Mapped[dict[str, Any]]` everywhere | M1 `Chat.history`, M2 `SharedChat.history`, M3 `ChannelMessage.content` | All three model snippets updated; `from typing import Any` added where the surrounding code already showed imports. |
| **S1** — `StrictModel` base class | `m0-foundations.md` § Pydantic conventions; `m1-conversations.md`; `m2-sharing.md` | M0 adds `app/schemas/_base.py` with `StrictModel` and a Pydantic conventions section. M1's `History`, `HistoryMessage`, `ChatSummary`, `ChatList`, `ChatCreate`, `ChatPatch`, `MessageSend`, `ChatParams`, `ModelInfo`, `ModelList`, `FolderCreate`, `FolderDeleteResult` all inherit from `StrictModel`. M2's `ShareCreateResponse`, `SharedBy`, `SharedChatResponse` inherit from it; `SharedChatResponse.history` reuses M1's `History` model rather than `dict`. |
| **S2** — `Annotated[T, Depends(...)]` aliases | `m0-foundations.md` § Dependency type aliases | M0 adds `app/core/deps.py` exporting `CurrentUser` and `DbSession`. M1 extends it with `Provider`. New M0 acceptance criterion: routes use `user: CurrentUser` (not `user: User = Depends(get_user)`); enforced by an AST gate in `tests/test_no_bare_depends.py`. |
| **O1** — Collapse M3 service layer | `m3-channels.md` § Deliverables; new § Routers and dependencies | The 8-file `services/channels/` layer collapses to 3: `messages.py`, `mentions.py`, `auto_reply.py`. Channel/member/reaction/pin/webhook/file CRUD inlines into the routers. New `app/routers/deps.py` exports `ChannelDep`, `MembershipDep`, `RequireOwner`, `RequireOwnerOrAdmin`. Worked example for `routers/channels.py` shows the new shape. Acceptance criteria added. |
| **O2** — Timeouts via dependency factory | `m5-hardening.md` § Per-route HTTP timeouts | The `@route_timeout(seconds)` decorator + `request.scope["route"].timeout_seconds` pattern is replaced by a `timeout(seconds)` dependency factory used as `dependencies=[timeout(300)]`. The global `TimeoutMiddleware` is kept only as the 15s default safety net. Rationale paragraph documents why the alternative was rejected. |
| **N1** — `LOG_LEVEL` already in M0 | `m5-hardening.md` § Deliverables (line 10) | M5 deliverables list now reads "Four new env vars" and explicitly notes `LOG_LEVEL` is consumed from M0, not redeclared. |
| **N2** — Pydantic conventions paragraph | `m0-foundations.md` § Pydantic conventions | New section enumerates `StrictModel` inheritance, `from __future__ import annotations`, `T \| None` over `Optional[T]`, curated Pydantic types, and `Field(..., description=...)` for OpenAPI docstrings. |
| **N3** — Cancellation prose in `chat_stream` | `m1-conversations.md` § Streaming pipeline | New "Cancellation contract" callout before the cancellation-paths list spells out catch → persist `cancelled=True, done=True` → emit `cancelled` SSE event → return (don't re-raise). |
| **N4** — Heartbeat constant | `m0-foundations.md` § Project constants; `m1-conversations.md`; `m3-channels.md`; `m5-hardening.md` | M0 adds `app/core/constants.py` exporting `STREAM_HEARTBEAT_SECONDS = 15`. M1's SSE keepalive, M3's socket.io `ping_interval`/`ping_timeout`, and M5's heartbeat acceptance criterion all reference the constant. No hard-coded cadence numbers anywhere. |
| **N5** — `events.py` thin-helper cap | `m3-channels.md` § Deliverables; acceptance criteria | Deliverables note the ≤80 LOC cap and "every helper is one `await sio.emit(...)` plus optional payload coercion." Acceptance criterion added with a `tests/test_events_thin.py` AST gate. |

If anything in this list surprises you on review, the original audit prose
above is unchanged and explains the *why* for each item.
