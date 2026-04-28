# Plan Consistency Report

Sixth pass. Generated after the eleven fifth-pass findings (1 critical
contradiction, 3 real inconsistencies, 4 documentation gaps, 3 cosmetic
drifts) were closed by surgical edits to `m0-foundations.md`,
`m1-conversations.md`, `m2-sharing.md`, `m3-channels.md`,
`m4-automations.md`, and `m5-hardening.md`. The C1 `StreamRegistry`
contradiction was settled by **locking in Redis pub/sub** as the
in-scope M1 implementation (vs. the deferred-to-M5 alternative);
the rationale and trade-offs vs. in-memory and MySQL-backed are
recorded in chat history and reflected in the M1 deliverables and
streaming-pipeline narrative.

## Verdict

**PASS** — all eleven fifth-pass findings closed; no new findings on
the sixth read-through. All locked decisions in `rebuild.md` §3 / §9
remain honoured. `rebuild.md` §2 already lists "stream-cancel pub/sub"
as a Redis use case, so the C1 resolution requires no edit there.

## Resolution log (5th-pass findings → closure)

### Critical

- **C1. M1 `StreamRegistry` deliverable contradicts the M1
  implementation section.** **Resolved.** Locked in **Redis pub/sub**
  (Option 3 in the C1 trade-off). `m1-conversations.md`:
  - Deliverables bullet rewritten to describe the Redis-backed
    façade (`stream:cancel:{message_id}` pub/sub plus per-pod local
    `dict[str, asyncio.Event]` cache).
  - Streaming-pipeline narrative already described Redis pub/sub
    correctly; left as-is and now consistent with the deliverable.
  - Forward-link to a non-existent M5 § Out of scope bullet removed
    (D3 follows from this).
  - New acceptance criterion `tests/integration/test_stream_registry_cross_pod.py`
    added so cross-pod cancel is exercised at the integration layer
    (`fakeredis` pubsub, two `StreamRegistry` instances, cancel
    propagates within 100 ms).

### Real inconsistencies

- **R1. `StreamRegistry` public method names disagree.** **Resolved.**
  M1 Deliverables bullet now lists `register`, `cancel`, and
  `unregister` — matching the streaming-pipeline narrative and
  pseudo-code's `finally: registry.unregister(assistant_msg.id)`.

- **R2. M3 channel-message creation helper has two names.**
  **Resolved.** Replaced `create_message` with `create_user_message`
  in two `m3-channels.md` locations:
  - `Channel.last_message_at` ORM-model docstring
    (denormalisation note).
  - API surface § Channels — `last_message_at` derivation note.
  Now consistent with M3 Deliverables row, the test acceptance
  shape, and M4's reference shape.

- **R3. M0 settings table cites the wrong URL.** **Resolved.**
  `m0-foundations.md` line 160 now reads "by M5's smoke pack against
  the staging URL (`m5-hardening.md` § Smoke E2E pack)" — naming
  the staging URL at the right level of detail (the hostname is
  platform-team policy, not pinned in the rebuild plan).

### Documentation gaps

- **D1. M1 streaming-pipeline pseudo-code missing SSE-timeout
  handler.** **Resolved.** Added `async with asyncio.timeout(...)`
  wrap around the provider iteration and an `except
  asyncio.TimeoutError:` branch that mirrors the cancellation branch
  but emits a `timeout` SSE frame instead. The cancellation contract
  block now mentions both `CancelledError` and `TimeoutError`. The
  `SSE_STREAM_TIMEOUT_SECONDS` settings row and the `timeout` SSE
  event row are updated to reference `async with asyncio.timeout(...)`
  rather than the previous `asyncio.wait_for` shorthand. M5
  § SSE stream timeout is updated to match. A new acceptance
  criterion exercises the timeout SSE frame end-to-end.

- **D2. M3 socket.io `cors_allowed_origins=[]` hardcoded.**
  **Resolved.** `m3-channels.md` § Stack now passes
  `cors_allowed_origins=settings.CORS_ALLOW_ORIGINS` to
  `socketio.AsyncServer(...)`, mirroring FastAPI's HTTP CORS policy
  (M0 setting). A two-line comment above the call documents the
  prod (single-origin behind the OAuth proxy) vs dev
  (`http://localhost:5173`) intent so the next reader doesn't have
  to reverse-engineer the value.

- **D3. M1 forward-links a non-existent M5 § Out of scope bullet.**
  **Resolved as a side-effect of C1.** With Redis pub/sub locked
  into M1, no follow-up work remains for M5 to defer; the
  forward-link is gone from the Deliverables bullet.

- **D4. M4 `/test/scheduler/tick` overlapping startup-gate +
  runtime-gate.** **Resolved.** A one-paragraph note appended to
  `m4-automations.md` § Test hook clarifies the startup-time
  registration is the **primary** control and the runtime check is
  **defence in depth** against a refactor that accidentally moves
  the registration outside the env conditional. Both checks read
  from the same `settings.ENV` source of truth, so they cannot
  disagree.

### Cosmetic drifts

- **X1. M3 `(= VARString(36))` typo.** **Resolved.** Replaced with
  `(= VARCHAR(36))` matching M4 line 28, `database-best-practises.md`
  §B.2, and the `rebuild.md` §9 lock.

- **X2. M1 Folder model code-comment path wrong.** **Resolved.**
  `# rebuild/backend/app/db/models/folder.py` corrected to
  `# rebuild/backend/app/models/folder.py`, matching M1 Deliverables,
  the M1 Chat model code-comment, M0 file layout, and the
  best-practices docs.

- **X3. M2 acceptance criterion overstates the M2 revision.**
  **Resolved.** Both internally inconsistent locations now say the
  same thing:
  - § Data model: "`chat.share_id` was created by M1 … M2 backfills
    the **FK** to `shared_chat.id` and the **unique index** … no
    `op.add_column` lands in M2."
  - § Acceptance criteria: "creates the `shared_chat` table and adds
    the `fk_chat_share_id` foreign key + `ix_chat_share_id` unique
    index against the M1-owned `chat.share_id` column" plus the
    explicit downgrade contract.

## A. Decision-lock conformance
Status: **PASS**

- All `rebuild.md` §9 locked decisions remain honoured: MEDIUMBLOB at
  5 MiB cap, single OpenAI-compatible provider, anyone-with-the-link
  sharing, empty-slate cutover, dual-tree `rebuild/` directory, Git
  LFS visual baselines, UUIDv7 `VARCHAR(36)` ids, single managed
  MySQL 8.0, robust idempotent Alembic migrations, APScheduler with
  MySQL `SELECT … FOR UPDATE SKIP LOCKED` lease.
- Trusted-header auth, no JWT/sessions/keys/LDAP/SCIM/roles/groups:
  honoured everywhere.
- `rebuild.md` §2 description of Redis (socket.io adapter, sliding-
  window rate limits, **stream-cancel pub/sub**, light cache) now
  matches M1's locked-in implementation unconditionally — the C1
  caveat from the previous report is gone.

## B. Schema consistency
Status: **PASS**

- All M1/M2/M3/M4 ORM tables use `String(36)` for every UUID PK and FK.
  `CHAR(64)` reserved for SHA-256 hex digests (`channel_webhook.token_hash`,
  `file.sha256`).
- `Channel.last_message_at` is on the model, indexed by
  `ix_channel_recency`, and written by every channel-message-insert
  path (`create_user_message` / `create_bot_message` /
  `create_webhook_message`) inside the message-create transaction —
  consistent across `m3-channels.md` lines 142, 486, 875, 1463 and
  the M3 Deliverables row.
- `automation.target_chat_id` and `automation.target_channel_id` are
  `ondelete="CASCADE"`; the `ck_automation_exactly_one_target` CHECK
  is not at risk during cascade.
- `automation.model_id` (`String(128)`) and `channel_message.bot_id`
  (`String(128)`) are width-aligned. Pydantic
  `AutomationCreate.model_id` is bounded at 128 chars via
  `Field(max_length=128)`.
- `chat.share_id` is `String(43)` (created by M1, FK + unique index
  added by M2; the M2 wording now matches every other reference).
- `chat.current_message_id` is the STORED generated column projection
  of `history->>'$.currentId'`; surfaced in the rebuild.md §4 summary.
- All timestamps are `BIGINT` epoch milliseconds via
  `app.core.time.now_ms()`, including `user.created_at`. No `DATETIME`
  / `TIMESTAMP` survivors.

## C. API surface
Status: **PASS**

- Single `/api` prefix; no `/v1` survivors.
- M2 share endpoints return `created_at: int` matching the column type.
- M3 webhook ingress timeout (5 s) cross-linked to M5 § Per-route HTTP
  timeouts.
- M4's `POST /api/automations/preview-rrule` is a first-class API row;
  `TargetSelector` does not claim a "Create new chat for each run"
  feature it can't deliver.
- File upload endpoint path collision (M3 `/files` vs M5 `/api/files`)
  resolved to `/api/files`.
- M1 SSE event types: `start`, `delta`, `usage`, `done`, `error`,
  `cancelled`, `timeout` — all seven listed in the API-surface table,
  all seven handled in the streaming-pipeline pseudo-code, all seven
  covered by acceptance criteria.

## D. Naming, settings, and module paths
Status: **PASS**

- `app.core.config` everywhere (M0 / M1 / M4 / M5).
- ORM modules under `app.models.*`: `app.models.user`,
  `app.models.chat`, `app.models.folder`, `app.models.channels`
  (plural), `app.models.files`, `app.models.automation`. M4 imports
  `from app.models.channels import Channel` correctly. The stray
  `app/db/models/folder.py` comment at M1 line 108 is fixed.
- All `Settings` attributes and access sites are UPPER_SNAKE_CASE
  (`settings.ENV`, `settings.AUTOMATION_BATCH_SIZE`,
  `settings.CORS_ALLOW_ORIGINS`, etc.).
- M0 settings table is the canonical entry point; M1 / M4 / M5 each
  have a § Settings additions subsection listing only the fields they
  introduce.
- `Settings.ENV` literal includes `"staging"`. The M0 settings-table
  caption now references "M5's smoke pack against the staging URL"
  (not the legacy archive).
- Test-only scheduler tick endpoint gated by
  `settings.ENV in {"test","staging"}` consistently — and the dual
  startup/runtime gate is explicitly documented as defence in depth.
- `python-socketio.AsyncServer` reads `cors_allowed_origins` from
  `settings.CORS_ALLOW_ORIGINS`, mirroring FastAPI's HTTP CORS.

## E. Numerics
Status: **PASS**

- Stream timeouts: M1 `SSE_STREAM_TIMEOUT_SECONDS` = M5 per-route
  timeout for `/api/chats/{id}/messages` = 300 s. The in-generator
  `async with asyncio.timeout(...)` is the primary deadline and the
  M5 route-layer `timeout(300)` dependency is the backstop;
  divergence is explicitly forbidden in both M1 and M5.
- Webhook ingress timeout: 5 s (M3 + M5 per-route timeouts table).
- Heartbeat cadence: `STREAM_HEARTBEAT_SECONDS = 15` (M0
  `app/core/constants.py`), shared by M1 SSE and M3 socket.io.
- Scheduler tick interval (30 s), `AUTOMATION_BATCH_SIZE` (25),
  `AUTOMATION_TIMEOUT_SECONDS` (120),
  `AUTOMATION_MIN_INTERVAL_SECONDS` (300), file cap (5 MiB), per-sid
  socket queue cap (256), typing rate limit (1/s) all referenced
  consistently with no drift.

## F. Dependencies between milestones
Status: **PASS**

- M1 declares `append_assistant_message`, `derive_title`,
  `StreamRegistry` (Redis-backed) as Deliverables.
- M3 declares `app.services.channels.messages.create_user_message`,
  `create_bot_message`, `create_webhook_message` as Deliverables —
  every other M3 mention now uses `create_user_message` for the
  user-authored variant.
- M4 calls M3's helpers rather than `sio.emit`-ing directly. Dependency
  note explicitly forbids the bypass.
- M3 → M4 is a hard ordering (M4's `automation.target_channel_id`
  declares an inline FK to `channel.id`).
- M5 layers OTel spans on top of M3's emit path and M1's SSE path; both
  are declared as instrumentation seams in their owning milestones.
- M2's Alembic revision adds the FK + unique index against the
  M1-owned `chat.share_id` column; M2 acceptance criterion and § Data
  model paragraph both say so.
- Redis is required from M1 onward (stream cancel), M3 onward
  (socket.io adapter), and M5 onward (rate limits) — no surprise
  dependency added by any later milestone.

## G. Out-of-scope conformance
Status: **PASS**

- No DMs / group DMs / channel `type` column anywhere.
- No tools, skills, notes, knowledge, MCP, code-interpreter, image-gen
  modules under `rebuild/`. M3 acceptance gate runs a ripgrep check.
- No `BINARY(16)` UUID storage anywhere; UUIDv7 `VARCHAR(36)` lock holds.
- "Create a new chat per automation run" is explicitly out-of-scope for
  v1 (M4 § Frontend).

## H. Test coverage
Status: **PASS**

- History search has an E2E in M1 (`history-crud.spec.ts`).
- Trusted-proxy CIDR enforcement has an E2E in M5 (`X-Forwarded-Email`
  stripped outside `TRUSTED_PROXY_CIDRS`).
- `Channel.last_message_at` denormalisation has an integration test in
  M3 acceptance.
- FK CASCADE behaviour for M4 automations has an integration test in
  M4 acceptance.
- `POST /api/automations/preview-rrule` happy and 422 paths covered in
  M4 acceptance.
- M2 share `created_at: int` covered by the M2 contract test.
- M1 SSE `timeout` event covered by the new
  `tests/integration/test_streaming.py::test_timeout_persists_partial_and_emits_timeout_frame`
  acceptance criterion.
- M1 cross-pod stream cancel covered by the new
  `tests/integration/test_stream_registry_cross_pod.py` acceptance
  criterion.
- Visual-regression baselines owned per-milestone (M1, M2, M3, M4, M5).
- `test_partial_upgrade_recovers` extended per-milestone (M1, M2, M3, M4)
  — every revision has a documented partial-apply recovery case.

## I. Visual regression and Git LFS
Status: **PASS**

- `.gitattributes` glob `**/tests/visual-baselines/**` filter=lfs is
  correct.
- Per-milestone capture owners: M1 (`chat-empty`, `streamed-reply`,
  `sidebar`), M2 (`share-view`), M3 (`channel-feed`, `channel-thread`),
  M4 (`automation-list`, `automation-editor`), M5 (`error-banner`,
  `rate-limited-toast`).

## J. Other observations (informational)

- `Channel.user_id` carries a docstring documenting the `RESTRICT`
  choice and the `backend/scripts/transfer_channel_owner.py` admin
  tool. Unchanged.
- `automation_run.error` truncation has its explanatory comment
  citing the `ix_automation_run_aid_created` index width concern.
  Unchanged.
- `channel_member.role` remains an inline `Enum` (acceptable per
  `database-best-practises.md` §C). Unchanged.
- `Chat.archived` vs `Channel.is_archived` naming difference left
  as-is (cosmetic; renaming would churn the API). Unchanged.
- `bench_channels.py` (M3 acceptance) and `k6_chat.js` (M5 nightly)
  coexist intentionally. Unchanged.
- `cte_max_recursion_depth = 256` is set per-statement, not
  engine-wide; documented in M1 § Cycle detection. Unchanged.
- `rebuild.md` §4 still does not enumerate `channel_message.pinned_at`
  or `channel_message.pinned_by`; the disclaimer added in pass 4
  ("the table is a summary; the authoritative column list lives in
  the milestone plan that creates it") covers it. Cosmetic.

## Files reviewed

- `rebuild.md`
- `rebuild/plans/m0-foundations.md`
- `rebuild/plans/m1-conversations.md`
- `rebuild/plans/m2-sharing.md`
- `rebuild/plans/m3-channels.md`
- `rebuild/plans/m4-automations.md`
- `rebuild/plans/m5-hardening.md`
- `rebuild/plans/database-best-practises.md`
- `rebuild/plans/MYSQL_FEATURE_AUDIT.md`
- `rebuild/plans/FastAPI-best-practises.md`
- `rebuild/plans/FASTAPI_AUDIT.md`
