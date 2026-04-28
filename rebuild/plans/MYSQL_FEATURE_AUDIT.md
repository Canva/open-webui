# MySQL 8.0 Feature Audit — Rebuild Plans

> Web research dated 2026-04-28. Cross-checked against `rebuild.md` and `rebuild/plans/m0..m5.md` as of the current commit.

## TL;DR

The plans already reach for the most important MySQL 8.0 levers (native `JSON`, `STORED` generated columns + functional index for `chat.current_message_id`, `MEDIUMBLOB` files, `FOR UPDATE SKIP LOCKED` for the scheduler, `utf8mb4_0900_ai_ci`, atomic UPSERT via `ON DUPLICATE KEY UPDATE`, `MAX_EXECUTION_TIME` hint on the scheduler). There are five MySQL 8.0 features that are clearly worth folding in, and six that are explicitly worth declaring out of scope so a reviewer doesn't ask about them later.

## Already in the plans (no change recommended)

| Feature | Where it shows up | Notes |
|---|---|---|
| Native `JSON` column type | `chat.history`, `channel_message.content` | Used as source-of-truth blob for chat tree. ✓ |
| `GENERATED ALWAYS AS ... STORED` + index | `chat.current_message_id` (m1 §Data model) | Best-practice replacement for "JSON path index"; also explicitly chosen over a functional index on `JSON_UNQUOTE(...)` for clarity. ✓ |
| `JSON_SEARCH` | Sidebar `?q=` (m1, history-crud) | Acceptable for small content; see "Multi-valued indexes" below if scope grows. |
| `MEDIUMBLOB` file storage | `file_blob.data` (m3) | Matches `max_allowed_packet=16M` cap. ✓ |
| `FOR UPDATE SKIP LOCKED` | Scheduler tick (m4 §Tick body, m5 §Scheduler tick) | Standard MySQL 8.0 worker-pool idiom; Percona/37signals (Solid Queue) use the same pattern. ✓ |
| `MAX_EXECUTION_TIME` optimizer hint | Scheduler tick (m5 §APScheduler tick) | Per-statement timeout — the right hammer for that nail. ✓ |
| `ON DUPLICATE KEY UPDATE` upsert | `get_user` first-login race (m0) | Atomic at the index level, race-safe. ✓ |
| `utf8mb4` + `utf8mb4_0900_ai_ci` | DB-default in baseline (m0) | Modern Unicode 9 collation, accent-insensitive ai_ci. ✓ |
| InnoDB row-level locking, FK cascades | Throughout | ✓ |
| CHECK constraint (`channel_message` author exclusivity) | m3 | MySQL 8.0.16+ enforced (not silently ignored). ✓ |

## Recommended additions

### 1. `ALGORITHM=INSTANT` for forward-compatible Alembic ops (M5 ops policy, low cost)

**What:** MySQL 8.0.12+ supports `ALTER TABLE ... ADD COLUMN ..., ALGORITHM=INSTANT, LOCK=DEFAULT` which mutates only the data dictionary — runtime is independent of table size, no rebuild, no concurrent-DML stall. With no algorithm hint MySQL silently picks `INSTANT → INPLACE → COPY`; declaring `INSTANT` makes it fail-fast instead of silently degrading to a multi-hour `COPY`.

**Why for this plan:** The only post-cutover operational risk in the rebuild is a future M-something ALTER on `chat`, `channel_message`, or `file` once they have real data. M5's deploy step runs migrations in a Helm Job with `activeDeadlineSeconds: 300`; a silent fallback to `COPY` on a million-row `chat` table will blow that budget on a single bad migration.

**Concrete change:** Add to M0 §"Alembic baseline conventions" (and reaffirm in M5 §"Database migration step"):

> Every `op.add_column` and `op.alter_column` in a revision file MUST pass `mysql_algorithm="INSTANT", mysql_lock="DEFAULT"` (use raw `op.execute("ALTER TABLE ... , ALGORITHM=INSTANT, LOCK=DEFAULT")` if the SQLAlchemy DSL doesn't expose the option). The CI lint includes a regex that fails the build on any `op.add_column` or `op.alter_column` that lacks the hint. Migrations that genuinely need `COPY` must justify it in a comment and bump `activeDeadlineSeconds`.

This is essentially free now and saves a future on-call.

---

### 2. `BINARY(16)` UUIDs via `UUID_TO_BIN(?, 1)` — **decline, document, and prefer UUIDv7 strings instead**

**What it would be:** Store all `id` columns as `BINARY(16)` instead of `VARCHAR(36)`. With `swap_flag=1` on `UUID_TO_BIN` the time-low/time-high fields of a v1 UUID are reordered so consecutive values cluster in the InnoDB B-tree (≈ insertion locality of an autoincrement). Storage shrinks by ~55%, which propagates into every secondary index (InnoDB secondary indexes carry the PK).

**The plans now use UUIDv7 (RFC 9562) strings, not v4.** This changes the trade-off:

- UUIDv7's leading 48 bits are a Unix-ms timestamp, so the locality benefit `swap_flag=1` was reaching for is **already present in the string form**. We get clustered B-tree inserts on `chat.id`, `channel_message.id`, `file.id`, etc., without any storage-format change.
- The remaining argument for `BINARY(16)` is purely the storage halving (16 bytes vs 36). At the legacy "few chats per Canva employee per day" rate, that's real but doesn't dominate the page budget the way it would on a multi-billion-row table.

**Why I still recommend NOT doing the binary swap for this rebuild:**

- All FKs (`chat.user_id`, `channel_message.channel_id`, etc.) become `BINARY(16)` too. Every Python-side debug log, error message, and JSON payload now needs `BIN_TO_UUID(?, 0)` round-tripping or a custom SQLAlchemy `TypeDecorator`. SQLAlchemy 2 has good support, but the readability cost is non-zero on every SELECT.
- `rebuild.md` §1 makes "stop the LOC explosion" a primary goal. A custom UUID `TypeDecorator` plus a project-wide change to every model is fine engineering but it's not a 5-day decision.
- The locality-of-insertion win that motivates most "switch to BINARY(16)" articles is now baked into the UUIDv7 string form. We get the dominant performance benefit for free.

**Locked in `rebuild.md` §9 (Decisions):**

> **Identifiers are UUIDv7 strings stored as `VARCHAR(36)`.** Generated via `app.core.ids.new_id()`; direct `uuid.uuid4()` is banned by ruff. `BINARY(16)` + `UUID_TO_BIN(?, 1)` considered and rejected. Revisit if `chat` exceeds ~10M rows or secondary-index bloat shows up in the M5 hardening benchmarks.

---

### 3. Recursive CTE for folder-tree queries (M1, low cost)

**What:** MySQL 8.0 native `WITH RECURSIVE folder_tree AS (...) SELECT ...` for descending into folder hierarchies, with `cte_max_recursion_depth` as a guardrail.

**Why for this plan:** M1 §API surface ships `GET /api/folders` as a flat list ("UI builds the tree client-side"). That's fine for the list. But two operations in the plans are inherently recursive:

1. M1 `DELETE /api/folders/{id}` cascades to descendant folders. SQL FK cascade does the right thing for the data, but the **API response** "what changed?" is currently undefined — the frontend has to refetch. A recursive CTE up-front lets the endpoint return the full descendant list (including affected `chat.folder_id` detachments) so the SvelteKit store can do an in-place update instead of a full refresh. That round-trip matters for the sidebar UX with many folders.
2. M1 `POST /api/folders` and `PATCH /api/folders/{id}` need a cycle check ("`409` on cycle: server checks parent chain"). The plan says "checks parent chain" but doesn't say how. Without a CTE that's a Python loop fetching one folder per hop. With a recursive CTE it's one round-trip with `WHERE FIND_IN_SET(...) = 0` cycle-detection — same pattern Oracle/Postgres people are used to.

**Concrete change:** In M1 §Folder CRUD, append:

> The cycle check on `POST/PATCH /api/folders` uses a recursive CTE rooted at the candidate `parent_id`, walking `parent_id` upward; if the target folder id appears in the visited set, return `409 cycle`. The CTE is bounded by `cte_max_recursion_depth = 256` (default 1000 is excessive for our folder depth).
>
> `DELETE /api/folders/{id}` runs a recursive CTE to compute the descendant set, returns `{ "deleted_folder_ids": [...], "detached_chat_ids": [...] }` in the response body, then commits the cascade. The frontend sidebar store consumes this to update in place instead of refetching.

---

### 4. Multi-valued index on `channel_message_reaction` *if* we ever add per-user reaction lookups (decline, document)

**What:** MySQL 8.0.17+ multi-valued indexes (`((CAST(... AS CHAR(50) ARRAY)))`) make `MEMBER OF`, `JSON_CONTAINS`, `JSON_OVERLAPS` index-eligible. Quoted Mydbops/JusDB benchmarks: 4M-row table, 900 ms full scan → 1.2 ms index range scan.

**Why this might be tempting:** M3 puts reactions in a separate `channel_message_reaction` table, which is the right call (per-row, joinable). The MVI question would only arise if we collapsed reactions into a `channel_message.content.reactions: ["+1", "heart"]` JSON array — which the plan explicitly does not do.

**Concrete change:** Add to M3 §"Out of scope" so a future reviewer doesn't propose collapsing the table:

> **Reactions stay in their own `channel_message_reaction` table; we do not collapse them into `channel_message.content` even though MySQL 8.0.17 multi-valued indexes (`MEMBER OF`/`JSON_CONTAINS`) would make per-emoji lookups index-eligible. The JOIN is cheap at our scale and the row form is friendlier to the ORM and to backfills.**

---

### 5. `EXPLAIN ANALYZE` + `sys` schema in the runbook (M5, ~½ day)

**What:**
- `EXPLAIN ANALYZE` (MySQL 8.0.18+) actually executes the query and reports per-step `actual time=start..end loops=N rows=N` next to the planner's estimates. Tree format only.
- `sys` schema ships pre-built views over `performance_schema` for "what queries are slow", "what indexes are unused", "what's blocking what". `mysql.sys` is installed by default in 8.0 data-dir init.

**Why for this plan:** M5's runbook owns "ops". Right now M5 leans on dashboards + structured logs + smoke specs but doesn't tell on-call **how** to debug a slow query at 3am. Both tools are zero-install on MySQL 8.0; both are the right answer for "the chat sidebar is slow, what changed?".

**Concrete change:** Add to M5 §"Runbook" a small "MySQL diagnostics" subsection:

> **Slow-query triage.** First step is `EXPLAIN ANALYZE <query>;` against the staging replica with production-shape data. Compare `actual time` per step against `cost`/`rows` estimates; if estimates are off by >10x, run `ANALYZE TABLE <name>;` to refresh histograms before re-planning. For a candidate-index decision, see "Invisible indexes" below.
>
> **Unused-index audit.** `SELECT * FROM sys.schema_unused_indexes WHERE object_schema = 'rebuild';` flags indexes with zero recorded reads. Don't drop them outright (see "Invisible indexes"). For the converse, `sys.schema_index_statistics` ranks indexes by read volume.
>
> **Blocking / lock contention.** `SELECT * FROM sys.innodb_lock_waits;` for the rare but possible "scheduler row stuck" symptom — should always be empty given `SKIP LOCKED`, but the view is the right place to look first.

---

### 6. Invisible indexes for the staged-rollout / safe-drop pattern (M5, near-zero cost)

**What:** `ALTER TABLE chat ALTER INDEX ix_chat_user_folder_updated INVISIBLE` keeps the index physically present and maintained on writes (so unique constraints and FK enforcement still work) but hides it from the optimizer. Toggling visibility is metadata-only and instant. The Percona / podostack writeups call this the safest way to delete an index you suspect is unused, and to roll out new candidate indexes off-peak.

**Why for this plan:** M0/M1 declare four secondary indexes on `chat` based on plausible access patterns; M3 adds many more on `channel_message`. Some of these will turn out to be unused once real Canva traffic hits. Today's plans have no documented mechanism for retiring an index safely.

**Concrete change:** Add to M5 §"Database migration step" (or a new §"Index lifecycle" subsection):

> **Index retirement procedure.** Suspect indexes are first marked `INVISIBLE` in a one-line Alembic revision (`op.execute("ALTER TABLE chat ALTER INDEX ix_foo INVISIBLE")`). Leave for one full week of prod traffic. If `sys.schema_unused_indexes` and the slow-query log show no regressions, a follow-up revision drops the index. If anything regresses, flip it back to `VISIBLE` — instant, no rebuild. Mirror the same pattern for staged adds: create a new candidate index `INVISIBLE`, observe writes are healthy, then `VISIBLE` to expose it to the planner.

---

### 7. `SET PERSIST_ONLY` for production tunables (M5, near-zero cost)

**What:** MySQL 8.0 `SET PERSIST` writes to `mysqld-auto.cnf` (JSON, with timestamp + user) and survives restart; `SET PERSIST_ONLY` does the same for read-only vars that need a restart to take effect. Inspect via `performance_schema.persisted_variables`.

**Why for this plan:** The compose file pins server settings via `--character-set-server=...`, `--max_allowed_packet=16M`, and friends. In prod (Helm), those become MySQL operator config or a `ConfigMap`. The runbook needs an "I tweaked `innodb_buffer_pool_size` at 4am, here's the audit trail" path.

**Concrete change:** Add to M5 §"Runbook" → "Configuration changes":

> **Live-tuning MySQL.** Use `SET PERSIST <var> = <value>` for dynamic variables and `SET PERSIST_ONLY <var> = <value>` for ones requiring restart. Inspect with `SELECT VARIABLE_NAME, VARIABLE_VALUE, SET_USER, SET_TIME FROM performance_schema.variables_info WHERE VARIABLE_SOURCE='PERSISTED';`. Roll back via `RESET PERSIST <var>;`. All persistent tweaks must be mirrored back into the Helm values file in the next deploy so `mysqld-auto.cnf` doesn't drift from version control.

---

## Recommended explicit non-goals (so they're not re-asked)

These come up in any "MySQL 8 features list" but the plans should mark them out of scope to save reviewer cycles:

| Feature | Recommended decision | Justification |
|---|---|---|
| **InnoDB Cluster / Group Replication / MySQL Router** | Out of scope | The compose, Dockerfile, and `m5-hardening` deploy section all assume a single MySQL instance. Internal scale doesn't justify the operational complexity; the deploy story is "managed MySQL with snapshot backups", to be confirmed by the platform team. |
| **Full-text search (`FULLTEXT` + `MATCH AGAINST`, with or without `ngram` parser)** | Out of scope for M1; revisit if `?q=` becomes painful | M1 explicitly defers full-text. Web evidence (`stackoverflow.com/q/72444384`) shows the `ngram` parser actually loses to `LIKE %q%` for many real-world chat-text queries because token count grows with query length. M1's `JSON_SEARCH` + `LIKE` is the right starting point. |
| **`JSON_TABLE`** | Out of scope | The chat-history JSON is a tree with parent/child links — it doesn't flatten cleanly into a relational shape, and the entire reason `chat.history` exists as a single JSON blob is to avoid the per-message-row table the legacy fork has. Don't cast off the design. |
| **Window functions / hash join / LATERAL** | No specific use; trust the optimizer | None of the M0–M5 query workloads are aggregation-heavy. `LIMIT N FOR UPDATE SKIP LOCKED` doesn't need them; the sidebar list is a single-table indexed range scan. The optimizer in 8.0.17+ uses hash join automatically when it picks; we don't need to plan for it. |
| **Histograms (`ANALYZE TABLE ... UPDATE HISTOGRAM`)** | Out of scope; revisit if M5 perf reveals a need | Useful for low-cardinality columns where indexes don't help; nothing in the schema currently has that shape (booleans like `archived`/`pinned` are paired into composite indexes with `user_id`). |
| **XtraBackup / point-in-time recovery via binlog** | Owned by infra team, not by the rebuild | Deploy is "managed MySQL with snapshot backups, to be confirmed". `m5-hardening.md` should explicitly flag this as a platform-team dependency rather than something the rebuild owns. The relevant note: PITR works if binlog format is `ROW` (default in 8.0); confirm with the managed-MySQL flavor. |

## Suggested edits — file-by-file

Sized so the patches are literally one-paragraph adds, no schema churn.

| File | Section | Add |
|---|---|---|
| `rebuild.md` §9 (Decisions) | new bullet | UUIDv7 (`VARCHAR(36)`) via `app.core.ids.new_id()`; `BINARY(16)` swap rejected. ✅ landed. |
| `rebuild.md` §9 | new bullet | Single managed MySQL instance; no InnoDB Cluster / Group Replication. ✅ landed. |
| `rebuild/plans/m0-foundations.md` §"Migration helpers" | extend `add_column_if_not_exists` | Defaults to `ALGORITHM=INSTANT, LOCK=DEFAULT`; INPLACE/COPY callers pass an override and justify it. CI gate extended to fail any raw `ALTER TABLE` `execute_if` that omits the algorithm clause. ✅ landed. |
| `rebuild/plans/m0-foundations.md` §"ID and time helpers" (new) | helper modules | `app.core.ids.new_id()` (UUIDv7 via `uuid7-standard`) + `app.core.time.now_ms()`; ruff bans `uuid.uuid4()` calls under `app/`. ✅ landed. |
| `rebuild/plans/m1-conversations.md` §"Folder CRUD" | replace cycle-check + delete response | Recursive CTE for cycle detection (`POST`/`PATCH`) and descendant set (`DELETE`); endpoint returns `{deleted_folder_ids, detached_chat_ids}` so the sidebar updates in place. ✅ landed. |
| `rebuild/plans/m3-channels.md` UUID wording + `MysqlFileStore` | uuid4 → UUIDv7 via `new_id()` | ✅ landed. |
| `rebuild/plans/m4-automations.md` model defaults | `_uuid()` → `default=new_id` | ✅ landed. |
| `rebuild/plans/m5-hardening.md` "MySQL diagnostics" subsection | new | `EXPLAIN ANALYZE` on staging replica + the five `sys` schema queries (`schema_unused_indexes`, `schema_index_statistics`, `innodb_lock_waits`, `statement_analysis`, `schema_tables_with_full_table_scans`). ✅ landed. |
| `rebuild/plans/m5-hardening.md` "Index lifecycle" subsection | new | Invisible-index pattern for safe drop and staged add; revision-pair rule. ✅ landed. |
| `rebuild/plans/m5-hardening.md` "Configuration changes" subsection | new | `SET PERSIST` / `SET PERSIST_ONLY` + `performance_schema.variables_info` audit + Helm-values mirror rule. ✅ landed. |
| `rebuild/plans/m5-hardening.md` Out of scope | new bullets | InnoDB Cluster, full-text search, `JSON_TABLE`, window functions / hash-join hints / `LATERAL`, multi-valued indexes, histograms, `BINARY(16)` UUIDs — explicitly declined with reasoning. ✅ landed. |

## Sources

- Multi-valued indexes: https://medium.com/@mydbopsdatabasemanagement/master-multi-valued-indexing-for-faster-queries-in-mysql-8-0-2b8155fb2268, https://www.jusdb.com/blog/improving-query-performance-with-multi-valued-indexing-in-mysql-80
- UUID `BINARY(16)` + `swap_flag`: https://mysql.rjweb.org/doc.php/uuid, https://dev.mysql.com/blog-archive/mysql-8-0-uuid-support/
- Invisible indexes: https://dev.mysql.com/doc/refman/8.0/en/invisible-indexes.html, https://podostack.com/p/invisible-indexes-mysql-testing
- Recursive CTEs: https://dev.mysql.com/blog-archive/mysql-8-0-labs-recursive-common-table-expressions-in-mysql-ctes-part-three-hierarchies/
- Functional indexes / generated columns: https://dev.mysql.com/blog-archive/json-labs-release-effective-functional-indexes-in-innodb/
- `SET PERSIST`: https://dev.mysql.com/doc/refman/en/persisted-system-variables.html, https://www.percona.com/blog/using-mysql-8-persisted-system-variables/
- `EXPLAIN ANALYZE`: https://dev.mysql.com/blog-archive/mysql-explain-analyze/, https://www.percona.com/blog/using-explain-analyze-in-mysql-8/
- `SKIP LOCKED` for queues: https://www.percona.com/blog/using-skip-lock-for-queue-processing-in-mysql/, https://www.bigbinary.com/blog/solid-queue
- `ON DUPLICATE KEY UPDATE` atomicity: https://dev.mysql.com/doc/refman/8.0/en/insert-on-duplicate.html
- `ALGORITHM=INSTANT`: https://dev.mysql.com/blog-archive/mysql-8-0-innodb-now-supports-instant-add-column/
- `ngram` vs `LIKE`: https://stackoverflow.com/questions/72444384/mysql-fulltext-index-ngram-parser-performance
- `LATERAL` derived tables: https://dev.mysql.com/doc/refman/8.0/en/lateral-derived-tables.html
- `sys` schema: https://dev.mysql.com/doc/refman/en/sys-schema.html
- InnoDB Cluster: https://www.mydbops.com/blog/mysql-replication-options-native-vs-innodb-cluster
- Backups (XtraBackup vs mysqldump, PITR): https://docs.percona.com/percona-xtrabackup/8.0/point-in-time-recovery.html
