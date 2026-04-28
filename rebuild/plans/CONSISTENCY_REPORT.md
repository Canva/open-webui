# Plan Consistency Report

Fourth pass. Generated after a fresh independent re-audit of the M0–M5 plans
(`rebuild.md`, `rebuild/plans/m{0..5}-*.md`, `database-best-practises.md`,
`MYSQL_FEATURE_AUDIT.md`, `FastAPI-best-practises.md`, `FASTAPI_AUDIT.md`).
The previous (third) pass declared PASS but missed one blocker (the
`Settings.ENV` literal not including `"staging"`), six real inconsistencies,
and eight documentation gaps. All fifteen findings have now been addressed by
in-place edits to the plan files; this document records the diff.

## Verdict

**PASS.**

Plans agree across decision-locks, schema, API, naming, numerics, milestone
dependencies, settings surface, helper contracts, and out-of-scope. No locked
decision in `rebuild.md` §3 / §9 was disturbed.

## Findings closed in this pass

### Blocker

- **B1. `Settings.ENV` literal did not include `"staging"`.** `m0-foundations.md`
  declared `ENV: Literal["dev", "test", "prod"]`, but M4
  (`/test/scheduler/tick` gate) and M5 (smoke pack against
  `archive.openwebui.canva-internal.com`) both branch on
  `settings.ENV in {"test", "staging"}`. With the literal as written, Pydantic
  would reject `ENV=staging` on app startup and the staging smoke pack would
  never run.

  **Fix:** Widened the literal to `Literal["dev", "test", "staging", "prod"]`
  in M0's settings table; the row notes both downstream consumers so a future
  agent doesn't narrow it back.

### Real inconsistencies

- **R1. Settings attribute casing mixed across plans.** M0 / M1 used
  `settings.UPPERCASE_NAME` (M0's auth dep on `settings.TRUSTED_EMAIL_HEADER`,
  M1's provider on `settings.MODEL_GATEWAY_BASE_URL`); M4 used lowercase
  (`settings.env`, `settings.automation_min_interval_seconds`); M5 mixed both
  (`settings.CORS_ALLOW_ORIGINS` uppercase but `settings.env` lowercase in
  smoke prose). Pydantic-settings 2 will resolve attribute names by exact
  case — mixing is a runtime AttributeError waiting to happen.

  **Fix:** Pinned UPPER_SNAKE_CASE in M0 § Settings ("Casing convention
  (locked)" paragraph) and converted every lowercase reference in
  `m4-automations.md`, `m5-hardening.md`, and `FastAPI-best-practises.md` to
  uppercase. Acceptance criteria reads `settings.AUTOMATION_MIN_INTERVAL_SECONDS`
  / `settings.ENV` consistently.

- **R2. `user.created_at` was `DateTime`, contradicting the project-wide
  BIGINT epoch-ms convention.** `rebuild.md` §4 and
  `database-best-practises.md` §A.1 require `BIGINT` epoch milliseconds for
  every timestamp. The M0 baseline migration declared
  `sa.DateTime(timezone=False)` for `user.created_at`. Mixing types is the
  exact failure mode the no-mixing rule was written to prevent.

  **Fix:** Converted the M0 baseline column to `sa.BigInteger()` with an
  inline comment pointing at the convention; updated the `/api/me` prose to
  spell out that the FE renders `created_at` via the same `Date(ms)` helper
  it uses for chats, channels, and automations; extended the `rebuild.md` §4
  timestamp paragraph to explicitly include `user` (and `channel_member`,
  `channel_file`) and to re-state "no `DATETIME` / `TIMESTAMP` columns
  anywhere".

- **R3. M2 share response schemas declared `created_at: datetime` but the
  column is `BIGINT`.** `ShareCreateResponse` and `SharedChatResponse` in
  `m2-sharing.md` were typed `datetime`, while
  `SharedChat.created_at: Mapped[int]` (BigInteger epoch ms). The handlers
  would have either errored at serialise time or silently introduced
  unexplained `datetime.fromtimestamp()` conversions divergent from the rest
  of the API.

  **Fix:** Pydantic schemas are now `created_at: int`. Two example response
  bodies further down the doc were updated from ISO-8601 strings to integer
  epoch ms. A new sentence after the schema block makes the convention
  explicit and points at `rebuild.md` §4.

- **R4. `channel_message.bot_id` (`String(128)`) was narrower than
  `automation.model_id` (`String(255)`).** M4's channel-target executor
  copies `automation.model_id → channel_message.bot_id`; a 200-char model id
  would round-trip through `POST /api/automations` and then blow up at
  execute time when the M3 column rejected it.

  **Fix:** Narrowed `automation.model_id` to `String(128)` (longest model id
  observed in the wild is ~52 chars; 128 has comfortable headroom). Added a
  Pydantic length validator on `AutomationCreate.model_id`
  (`Annotated[str, Field(min_length=1, max_length=128)]`) so the 422 happens
  on POST instead of at execute. Updated the rebuild.md §4 summary to show
  `String(128)` on both columns and to spell out that the widths are linked.

- **R5. `rebuild.md` §2 mermaid description claimed "Redis (… scheduler
  locks …)".** M4 explicitly uses `SELECT … FOR UPDATE SKIP LOCKED` against
  MySQL for scheduler claim; nothing about scheduler state lives in Redis.
  The mermaid label would have led a reader to expect a Redis-based lease
  that doesn't exist.

  **Fix:** Rewrote the §2 description: MySQL "rows + file blobs + scheduler
  row-lease via `SELECT … FOR UPDATE SKIP LOCKED`" with a forward-link to M4
  § Scheduler; Redis "socket.io cross-replica adapter, sliding-window rate
  limiters, stream-cancel pub/sub, light cache — *not* scheduler locks".

- **R6. M4 `TargetSelector` "Create new chat for each run" affordance had
  undefined backend semantics.** The UI copy said `target_chat_id` would be
  set to "the user's 'Automations' folder default" — a folder id, not a chat
  id, and the executor had no `_create_new_chat_per_run` branch. The feature
  was either undefined or required a non-trivial schema migration nobody had
  scoped.

  **Fix:** Removed the affordance from `TargetSelector.svelte`. The plan now
  explicitly states "no 'create a new chat per run' affordance in v1" with a
  one-sentence note on what would be required to add it later (new
  `new_chat_per_run` column, per-run chat-create logic in the executor, a
  migration to track which chat each run produced).

### Documentation gaps

- **D1. M5 deliverables said "five new env vars" including `LOG_LEVEL`,
  which is already in M0.**

  **Fix:** Reworded the deliverable to "New env vars … `OTEL_*`,
  `LOG_FORMAT`. `LOG_LEVEL` already exists from M0 and is not redeclared."
  Forward-link to the new § Settings additions section in M5.

- **D2. M1, M4, M5 introduced settings without listing them anywhere.** New
  `Settings` fields (`SSE_STREAM_TIMEOUT_SECONDS`, the `AUTOMATION_*`
  family, `OTEL_*`, `LOG_FORMAT`, `RATELIMIT_*`, `TRUSTED_PROXY_CIDRS`,
  `ALLOWED_FILE_TYPES`, `LAUNCH_BANNER_UNTIL`) were referenced in code
  blocks but didn't appear in any settings table.

  **Fix:** Added a `## Settings additions` subsection to M1 (1 field),
  M4 (3 fields), and M5 (10 fields). Each subsection has the same
  `| Field | Type | Default | Notes |` shape as M0's table and ends with a
  reminder of the UPPER_SNAKE_CASE casing convention. M0's settings prose
  now lists the downstream additions by name so the M0 table stays the
  canonical entry point.

- **D3. `rebuild.md` §4 data-model summary was missing columns the
  milestone plans actually create.** `chat.current_message_id` (M1 STORED
  generated), `channel.is_archived` / `archived_at` / `last_message_at`
  (M3), `automation.created_at` / `updated_at` (M4), and most join-table
  `created_at`s were absent. Readers used the §4 table as the architecture
  cheat-sheet and would build a mental model that didn't match.

  **Fix:** Updated every row in the §4 table to include the missing columns
  with brief callouts (e.g. `current_message_id` (STORED generated from
  `history`)`, "Width 128 matches `automation.model_id` (m4 § Data
  model)"). Added a closing sentence stating the table is a summary and the
  authoritative column list lives in the milestone plan that creates it.

- **D4. M1 `derive_title` and `StreamRegistry` were used in pseudocode but
  not listed as deliverables.** Both are non-trivial helpers (the title
  helper is what `POST /api/chats` calls when no title is supplied; the
  stream registry is what `POST … /cancel` calls to actually stop a
  generator). A reviewer scanning Deliverables would not realise they had
  to be implemented.

  **Fix:** Added two new bullets to M1 § Deliverables — one for
  `app/services/chat_title.derive_title` (pure helper, ≤ 60 chars), one for
  `app/services/stream_registry.StreamRegistry` (module-level singleton with
  `register / cancel / cleanup` and a forward-link to the M5 out-of-scope
  note about cross-replica cancel via Redis pub/sub).

- **D5. M1 mixed module-level `provider = OpenAICompatibleProvider()` and
  `app.state.provider`.** The pseudo-code finished with
  `provider = OpenAICompatibleProvider()` but the docstring and M4 referred
  to `app.state.provider`. Already addressed by the FastAPI audit; this
  pass verified the M1 § Provider lifecycle paragraph (`lifespan`,
  `get_provider`, `Provider = Annotated[...]`) is the only construction
  story now and that no module-level singleton survives.

- **D6. M3 webhook ingress route had no per-route timeout cross-link to
  M5.** M5 § Per-route HTTP timeouts targets webhook ingress at 5 s but M3
  didn't say so, so a reader reviewing M3 in isolation would not know the
  route is bounded.

  **Fix:** Added a paragraph under M3 § Webhooks (incoming, public)
  spelling out the 5 s `@route_timeout(5)` budget, what's covered (token
  compare, INSERT, UPDATE last_used_at, socket fan-out), what's *not*
  (outgoing-webhook delivery, fire-and-forget post-202), and the
  `RATELIMIT_WEBHOOK_PER_MIN` setting it pairs with.

- **D7. `cte_max_recursion_depth = 256` was mentioned in M1 but the
  setting mechanism was undefined.** A reader couldn't tell whether the
  router would `SET SESSION` per call, configure it on the engine connect
  event, or rely on a pool-level setting.

  **Fix:** Added an explanatory paragraph in M1 § Cycle detection: the
  folder router executes `SET SESSION cte_max_recursion_depth = 256`
  per-statement, immediately before each recursive CTE, inside the same
  transaction. Documented why the setting is *not* engine-wide (every other
  query wants the default 1000; lowering it globally would surface as
  confusing recursion errors anywhere a future migration adds a deeper
  CTE) and where the constant lives (`app/services/folders.py` next to
  the CTE, not `app/core/constants.py`).

- **D8. The previous CONSISTENCY_REPORT declared PASS while the issues
  above were open.**

  **Fix:** This document. The "What changed file-by-file" section below
  lists the concrete diff applied in this pass.

## A. Decision-lock conformance
Status: **PASS**

- All `rebuild.md` §9 locked decisions remain honoured: MEDIUMBLOB at 5 MiB
  cap, single OpenAI-compatible provider, anyone-with-the-link sharing,
  empty-slate cutover, dual-tree `rebuild/` directory, Git LFS visual
  baselines, UUIDv7 `VARCHAR(36)` ids, single managed MySQL 8.0, robust
  idempotent Alembic migrations.
- Trusted-header auth, no JWT/sessions/keys/LDAP/SCIM/roles/groups: honoured
  everywhere.
- `rebuild.md` §2 mermaid description and prose now match M4: scheduler
  lease in MySQL, Redis only for socket.io fan-out / rate limits / cancel
  pub/sub.

## B. Schema consistency
Status: **PASS**

- All M3 ORM tables (`channel`, `channel_member`, `channel_message`,
  `channel_message_reaction`, `channel_webhook`, `channel_file`, `file`,
  `file_blob`) and both M4 tables (`automation`, `automation_run`) use
  `String(36)` for every UUID PK and FK; `CHAR(64)` is reserved for SHA-256
  hex digests.
- `Channel.last_message_at` is declared on the ORM model, backed by an
  Alembic-inline column declaration, indexed by `ix_channel_recency`, and
  written by every channel-message-insert path inside the message-create
  transaction. Surfaced in the rebuild.md §4 summary.
- `automation.target_chat_id` and `automation.target_channel_id` are
  `ondelete="CASCADE"`; the `ck_automation_exactly_one_target` CHECK is no
  longer at risk during cascade.
- `automation.model_id` (`String(128)`) and `channel_message.bot_id`
  (`String(128)`) are width-aligned. Pydantic
  `AutomationCreate.model_id` is bounded at 128 chars via `Field(max_length=128)`.
- `chat.share_id` is `String(43)` (M1) and matches `shared_chat.id`
  (M2). No double-declaration in M2's Alembic.
- `chat.current_message_id` is the STORED generated column projection of
  `history->>'$.currentId'`; surfaced in the rebuild.md §4 summary.
- All timestamps are `BIGINT` epoch milliseconds via
  `app.core.time.now_ms()` — including `user.created_at`. No `DATETIME` /
  `TIMESTAMP` survivors anywhere.

## C. API surface
Status: **PASS**

- Single `/api` prefix; no `/v1` survivors.
- M2 share endpoints return `created_at: int` matching the column type.
- M3 webhook ingress timeout (5 s) cross-linked to M5 § Per-route HTTP
  timeouts.
- M4's `POST /api/automations/preview-rrule` is a first-class API row;
  `TargetSelector` no longer claims a "Create new chat for each run"
  feature it can't deliver.
- File upload endpoint path collision (M3 `/files` vs M5 `/api/files`)
  resolved to `/api/files`.

## D. Naming, settings, and module paths
Status: **PASS**

- `app.core.config` everywhere (M0 / M1).
- ORM modules under `app.models.*`: `app.models.user`, `app.models.chat`,
  `app.models.folder`, `app.models.channels` (plural), `app.models.files`,
  `app.models.automation`, `app.models.automation_run`. M4 imports
  `from app.models.channels import Channel` correctly.
- All `Settings` attributes and access sites are UPPER_SNAKE_CASE
  (`settings.ENV`, `settings.AUTOMATION_BATCH_SIZE`, etc.). The convention
  is pinned in M0 § Settings.
- M0 settings table is the canonical entry point; M1 / M4 / M5 each have a
  § Settings additions subsection listing only the fields they introduce,
  with type, default, and rationale.
- `Settings.ENV` literal includes `"staging"`.
- Test-only scheduler tick endpoint gated by
  `settings.ENV in {"test","staging"}` consistently (M4 router, M4
  acceptance, M5 staging smoke spec).

## E. Numerics
Status: **PASS**

- Stream timeouts: M1 `SSE_STREAM_TIMEOUT_SECONDS` = M5 per-route timeout
  for `/api/chats/{id}/messages` = 300 s.
- Webhook ingress timeout: 5 s (M3 + M5 per-route timeouts table).
- Heartbeat cadence: `STREAM_HEARTBEAT_SECONDS = 15` (M0
  `app/core/constants.py`), shared by M1 SSE and M3 socket.io.
- Scheduler tick interval (30s), `AUTOMATION_BATCH_SIZE` (25),
  `AUTOMATION_TIMEOUT_SECONDS` (120),
  `AUTOMATION_MIN_INTERVAL_SECONDS` (300), file cap (5 MiB), per-sid
  socket queue cap (256), typing rate limit (1/s) all referenced
  consistently with no drift.

## F. Dependencies between milestones
Status: **PASS**

- M1 declares `append_assistant_message`, `derive_title`, `StreamRegistry`
  as Deliverables (the latter two were added in this pass).
- M3 declares `app.services.channels.messages.create_bot_message`,
  `create_user_message`, `create_webhook_message` as Deliverables (used by
  M4).
- M4 calls M3's helpers rather than `sio.emit`-ing directly. Dependency
  note explicitly forbids the bypass.
- M3 → M4 is a hard ordering (M4's `automation.target_channel_id`
  declares an inline FK to `channel.id`).
- M5 layers OTel spans on top of M3's emit path and M1's SSE path; both
  are declared as instrumentation seams in their owning milestones.

## G. Out-of-scope conformance
Status: **PASS**

- No DMs / group DMs / channel `type` column anywhere.
- No tools, skills, notes, knowledge, MCP, code-interpreter, image-gen
  modules under `rebuild/`. M3 acceptance gate runs a ripgrep check.
- No `BINARY(16)` UUID storage anywhere; UUIDv7 `VARCHAR(36)` lock holds.
- "Create a new chat per automation run" is explicitly out-of-scope for
  v1 (M4 § Frontend), with one paragraph spelling out what would be
  required to add it later.

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
- M2 share `created_at: int` (matching column type) — covered by the
  existing M2 contract test (no schema change is needed; the test was
  already asserting an integer).
- Visual-regression baselines owned per-milestone (M1, M2, M3, M4, M5).

## I. Visual regression and Git LFS
Status: **PASS**

- `.gitattributes` glob `**/tests/visual-baselines/**` filter=lfs is
  correct.
- Per-milestone capture owners: M1 (`chat-empty`, `streamed-reply`,
  `sidebar`), M2 (`share-view`), M3 (`channel-feed`, `channel-thread`),
  M4 (`automation-list`, `automation-editor`), M5 (`error-banner`,
  `rate-limited-toast`).

## J. Other findings
Status: **CLEAN**

- `Channel.user_id` carries a docstring documenting the `RESTRICT` choice
  and the `transfer-channel-owner.py` admin tool.
- `automation_run.error` truncation has an explanatory comment citing the
  `ix_automation_run_aid_created` index width concern.
- `channel_member.role` remains an inline `Enum` (acceptable per
  `database-best-practises.md` §C).
- `Chat.archived` vs `Channel.is_archived` naming difference left as-is
  (cosmetic; renaming would churn the API).
- `bench_channels.py` (M3 acceptance) and `k6_chat.js` (M5 nightly)
  coexist intentionally.
- `cte_max_recursion_depth = 256` is set per-statement, not engine-wide;
  documented in M1 § Cycle detection.

## What changed file-by-file in this pass

- `rebuild.md`
  - §2 mermaid description: "scheduler locks" removed from Redis;
    MySQL row-lease called out; Redis role spelled out as socket.io
    adapter / rate limits / cancel pub/sub / light cache.
  - §4 timestamp paragraph: extended to include `user`,
    `channel_member`, `channel_file`; added the no-`DATETIME` rule.
  - §4 data-model table: added `current_message_id` (`chat`),
    `is_archived` / `archived_at` / `last_message_at` (`channel`),
    `joined_at` (`channel_member`), `created_at` on every join table,
    `created_at` / `updated_at` (`automation`); `automation.model_id`
    width called out as `String(128)` matching `channel_message.bot_id`.
  - Closing sentence stating the table is a summary; authoritative
    column list lives in the milestone plan that creates it.

- `rebuild/plans/m0-foundations.md`
  - § Settings: `ENV` literal widened to
    `Literal["dev", "test", "staging", "prod"]` with the M4 / M5
    consumers cited.
  - § Settings: new "Casing convention (locked)" paragraph pinning
    UPPER_SNAKE_CASE attributes and listing the downstream additions
    by name.
  - Alembic baseline `user.created_at`: `sa.DateTime(timezone=False)`
    → `sa.BigInteger()` with an inline comment.
  - § `/api/me`: spells out that `created_at` is BIGINT epoch ms and
    rendered FE-side via the project-wide `Date(ms)` helper.

- `rebuild/plans/m1-conversations.md`
  - § Deliverables: new `chat_title.derive_title` bullet.
  - § Deliverables: new `stream_registry.StreamRegistry` bullet with
    forward-link to M5's cross-replica cancel out-of-scope note.
  - New § Settings additions before Provider abstraction documenting
    `SSE_STREAM_TIMEOUT_SECONDS`.
  - § Cycle detection: extra paragraph on `SET SESSION
    cte_max_recursion_depth = 256` semantics.

- `rebuild/plans/m2-sharing.md`
  - Schemas: `created_at: datetime` → `created_at: int` on
    `ShareCreateResponse` and `SharedChatResponse`; example response
    bodies updated from ISO-8601 strings to integer epoch ms.
  - New explanatory sentence after the schema block citing
    `rebuild.md` §4.

- `rebuild/plans/m3-channels.md`
  - § Webhooks (incoming, public): new paragraph documenting the
    5 s `@route_timeout(5)` budget, what's covered vs not, and the
    `RATELIMIT_WEBHOOK_PER_MIN` pairing.

- `rebuild/plans/m4-automations.md`
  - `Automation.model_id`: `String(255)` → `String(128)` with an
    inline comment citing the M3 width and observed model-id lengths.
  - § Data model: new paragraph on the 128-char ceiling, the
    `Field(max_length=128)` Pydantic validator, and rationale.
  - All `settings.env` / `settings.automation_*` access sites
    (router, scheduler, executor, test hook, acceptance criteria)
    converted to UPPER_SNAKE_CASE.
  - New § Settings additions listing `AUTOMATION_BATCH_SIZE`,
    `AUTOMATION_TIMEOUT_SECONDS`, `AUTOMATION_MIN_INTERVAL_SECONDS`.
  - `TargetSelector.svelte` prose: "Create new chat for each run"
    affordance removed; new sentence stating it's out-of-scope for v1
    and what it would take to add later.

- `rebuild/plans/m5-hardening.md`
  - § Deliverables: "Five new env vars" reworded to call out the
    four genuinely new ones and the M0 forward-reference for
    `LOG_LEVEL`; pointer to the new § Settings additions section.
  - New § Settings additions covering `OTEL_EXPORTER_OTLP_ENDPOINT`,
    `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES`, `LOG_FORMAT`,
    `RATELIMIT_CHAT_TOKENS_PER_MIN`,
    `RATELIMIT_FILE_UPLOADS_PER_MIN`, `RATELIMIT_WEBHOOK_PER_MIN`,
    `TRUSTED_PROXY_CIDRS`, `ALLOWED_FILE_TYPES`, `LAUNCH_BANNER_UNTIL`.
  - `settings.env` (smoke spec) → `settings.ENV`.

- `rebuild/plans/FastAPI-best-practises.md`
  - `settings.env` (M4 cross-reference) → `settings.ENV`.

- `rebuild/plans/CONSISTENCY_REPORT.md`
  - This file. Regenerated to reflect the fourth-pass diff.

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
