# M0 — Foundations Implementation Plan

> Authoritative parent: [rebuild.md](../../rebuild.md). Section 5 (Phased delivery) and section 10 (Repository layout) are the binding scope for this milestone.

## Goal

Stand up a parallel, fully self-contained `rebuild/` tree in this repo that compiles, lints, type-checks, tests, builds a Docker image, and runs in Buildkite without disturbing any legacy code path. By the end of M0 the tree contains a runnable FastAPI skeleton with trusted-header auth and `/healthz` + `/readyz`, a SvelteKit 2 + Svelte 5 + Tailwind 4 frontend that round-trips a `/api/me` call against the proxy header, MySQL 8.0 + Redis 7 dev compose, an Alembic baseline that creates only the `user` table, and a path-filtered Buildkite pipeline that runs in parallel to the legacy one. No product features ship in M0; the deliverable is the foundation that M1–M5 build on.

## Deliverables

- `rebuild/` directory; isolated tooling; no shared lockfiles or configs with legacy.
- Python 3.12 + FastAPI backend skeleton at [rebuild/backend/](../backend/) with ASGI app factory mounting `/healthz`, `/readyz`, `/api/me`; `Settings(BaseSettings)` in `app/core/config.py`; `get_user` trusted-header dep in `app/core/auth.py`; async SQLAlchemy 2 engine + session factory in `app/core/db.py`; Alembic environment with a single revision creating the `user` table.
- SvelteKit 2 + Svelte 5 + Tailwind 4 frontend at [rebuild/frontend/](../frontend/): root layout calling `/api/me` to verify the trusted-header path; Vitest + Playwright (E2E + Component Testing) wired with MSW.
- Dev infrastructure at [rebuild/infra/](../infra/): `docker-compose.yml` with `mysql:8.0.39`, `redis:7.4-alpine`, and the `app` service; `mysql/my.cnf` pinning `utf8mb4` / `utf8mb4_0900_ai_ci` / `max_allowed_packet=16M`.
- Multi-stage [rebuild/Dockerfile](../Dockerfile) producing one image with frontend assets + backend.
- Self-contained Python config in [rebuild/pyproject.toml](../pyproject.toml) (ruff, mypy strict, pytest); self-contained JS config in [rebuild/package.json](../package.json), `tsconfig.json`, `playwright.config.ts`, `playwright-ct.config.ts`, `vitest.config.ts`.
- [rebuild/Makefile](../Makefile) with rebuild-only targets: `setup`, `dev`, `migrate`, `lint`, `typecheck`, `test-unit`, `test-component`, `test-e2e-smoke`, `build`.
- Buildkite pipeline at [rebuild/.buildkite/rebuild.yml](../.buildkite/rebuild.yml) gated by `if: build.changed_files =~ /^rebuild\//`; top-level `README.md` updated to document the dual-tree state.

## File and directory layout

The tree below is the complete set of files M0 creates under `rebuild/`. Anything not listed is out of scope for M0.

```
rebuild/
  README.md                          # rebuild-tree quickstart
  Makefile                           # rebuild-only targets (setup/dev/lint/test/build)
  Dockerfile                         # multi-stage: frontend -> python deps -> runtime
  .dockerignore                      # excludes node_modules, .venv, tests, fixtures
  pyproject.toml                     # python deps + ruff/mypy/pytest config
  package.json                       # JS deps, npm scripts (dev/build/test:*)
  tsconfig.json                      # strict TS for the frontend
  .gitattributes                     # git-lfs filter for **/tests/visual-baselines/**
  .gitignore                         # rebuild-local ignores (.venv, node_modules, .svelte-kit)
  plans/
    m0-foundations.md                # this document
  .buildkite/
    rebuild.yml                      # path-filtered pipeline
  infra/
    docker-compose.yml               # mysql + redis + app
    mysql/
      my.cnf                         # utf8mb4, max_allowed_packet=16M
      init.sql                       # CREATE DATABASE rebuild charset=utf8mb4
    redis/
      redis.conf                     # appendonly off, maxmemory 256mb dev cap
  backend/
    pyproject.toml -> ../pyproject.toml  # symlinked so backend tooling shares config
    alembic.ini                      # alembic config, points at backend/alembic
    alembic/
      env.py                         # async Alembic env using app.db.base.metadata
      script.py.mako                 # alembic template
      versions/
        0001_baseline.py             # revision="0001_baseline", creates `user` table
    app/
      __init__.py                    # exposes app version
      main.py                        # FastAPI factory, mounts routers, lifespan
      asgi.py                        # uvicorn entrypoint module (`app.asgi:app`)
      core/
        __init__.py
        config.py                    # Settings(BaseSettings)
        constants.py                 # project-wide non-tunable constants (STREAM_HEARTBEAT_SECONDS, …)
        logging.py                   # structlog/standard logging bootstrap
        db.py                        # async engine, session factory, get_session
        auth.py                      # get_user trusted-header dep + upsert_user_from_headers helper
        deps.py                      # Annotated type aliases: CurrentUser, DbSession (Provider added in M1)
        errors.py                    # AppError + FastAPI exception handlers
        ids.py                       # new_id() -> str — project-wide UUIDv7 helper
        time.py                      # now_ms() -> int — project-wide epoch-ms helper
      db/
        __init__.py
        base.py                      # DeclarativeBase + naming convention
        migration_helpers.py         # idempotent op.* wrappers (see § Migration helpers)
      models/
        __init__.py                  # re-exports models (User in M0; chat/folder/etc. added by later milestones)
        user.py                      # User ORM model
      routers/
        __init__.py
        health.py                    # /healthz, /readyz handlers
        me.py                        # /api/me handler (returns current User)
      schemas/
        __init__.py
        _base.py                     # StrictModel(BaseModel) — extra="forbid", strip whitespace
        user.py                      # UserRead pydantic model
    tests/
      __init__.py
      conftest.py                    # async client + MySQL fixture (testcontainers)
      test_health.py                 # /healthz returns 200, /readyz pings db+redis
      test_auth.py                   # trusted-header auto-creates User, missing -> 401; covers both upsert_user_from_headers and get_user
      test_settings.py               # defaults + overrides parse correctly
      test_strict_model.py           # StrictModel rejects unknown fields (one regression case)
      test_ids.py                    # new_id() UUIDv7 version-nibble + intra-ms monotonicity
      test_time.py                   # now_ms() matches a frozen time.time_ns()
      test_constants.py              # smoke imports STREAM_HEARTBEAT_SECONDS + MAX_CHAT_HISTORY_BYTES
      test_no_bare_depends.py        # AST gate: no `Depends(get_session)` / `Depends(get_user)` in route signatures under app/routers/
      test_migrations.py             # alembic up/down idempotency, partial-recovery, AST gate against bare op.* in versions/
  frontend/
    package.json -> ../package.json  # symlink, single JS dep set
    svelte.config.js                 # SvelteKit 2 config, adapter-node
    vite.config.ts                   # Vite 5, vitest config alias to root
    tailwind.config.ts               # Tailwind 4 content globs
    postcss.config.cjs               # @tailwindcss/postcss plugin
    playwright.config.ts             # E2E projects: chromium, firefox, webkit
    playwright-ct.config.ts          # Component testing projects (chromium-only)
    vitest.config.ts                 # jsdom env, src/lib/**/*.test.ts
    src/
      app.html                       # base HTML shell, %sveltekit.head%/%sveltekit.body%
      app.css                        # Tailwind 4 entry: @import "tailwindcss"
      app.d.ts                       # App.PageData + App.Locals { user: User | null }
      hooks.server.ts                # handle: populates event.locals.user via /api/me; rewrites event.fetch to backend URL; forwards X-Forwarded-* headers
      lib/
        api/
          client.ts                  # typed fetch wrapper hitting backend
        msw/
          handlers.ts                # MSW handlers (mock /api/me)
          browser.ts                 # browser worker bootstrap (dev + tests)
          node.ts                    # node server bootstrap (vitest + ct)
      routes/
        +layout.server.ts            # returns { user: locals.user } — auth populate happens in hooks.server.ts handle, not here
        +layout.svelte               # renders user banner ("Hello {email}")
        +page.svelte                 # hello-world placeholder
    static/
      mockServiceWorker.js           # MSW worker (committed, generated by msw init)
    tests/
      unit/                          # vitest unit specs (added by later milestones)
        .gitkeep
      component/                     # Playwright Component Testing specs
        layout.spec.ts               # +layout renders email when load yields user
      e2e/
        smoke.spec.ts                # GET / round-trip with X-Forwarded-Email
      smoke/                         # M5 cutover smoke specs (added later)
        .gitkeep
      visual-baselines/              # git-lfs tracked, empty in M0
        .gitkeep
```

The two symlinks (`backend/pyproject.toml`, `frontend/package.json`) keep tool-discovery happy when developers `cd` into a sub-tree, while preserving the rule that `rebuild/` has exactly one Python config and one JS config.

## Backend skeleton

### Package layout

The backend is a single Python package called `app`, installed in editable mode from [rebuild/pyproject.toml](../pyproject.toml). All imports are absolute (`from app.core.config import settings`). Only the modules and tests listed under `backend/app/` in the layout above exist in M0.

### ID and time helpers

Two zero-dependency helpers under `app/core/` are referenced by every later milestone, so they ship in M0:

- **`app/core/ids.py`** — `new_id() -> str` returns a **UUIDv7** (RFC 9562) string in canonical hyphenated `VARCHAR(36)` form. Project-wide identifier generator; every `id` column on every table is populated by this helper, never `uuid.uuid4()`. UUIDv7 is chosen over UUIDv4 because the leading 48 bits are a millisecond Unix timestamp, which gives near-monotonic insertion order in the InnoDB clustered B-tree (and in every secondary index that carries the PK) — the same locality benefit a `BIGINT` autoincrement would, without giving up application-side generation, FK portability, or globally-unique cross-shard keys. Implementation imports from `uuid7-standard` (a tiny RFC-9562 backport for Python 3.12; in Python 3.13+ this can be swapped for stdlib `uuid.uuid7()` with no caller changes). Ruff is configured to error on direct `uuid.uuid4()` / `uuid4()` calls anywhere under `app/` (`flake8-tidy-imports` `banned-api`) so the helper is the only path; tests are exempt.

- **`app/core/time.py`** — `now_ms() -> int` returns `time.time_ns() // 1_000_000`. Project-wide timestamp source for every `BIGINT` epoch-ms column (chats, channels, automations, files). Centralised so the test suite can monkey-patch a single symbol to freeze time.

Both modules are <30 LOC each, fully typed, covered by `tests/test_ids.py` and `tests/test_time.py` (asserts UUIDv7 version nibble = `7`, asserts monotonicity within a millisecond, asserts `now_ms` matches a frozen `time.time_ns`).

### `Settings(BaseSettings)`

All configuration lives in `app/core/config.py`. The class loads from environment variables and an optional `.env` file in `rebuild/backend/`. Values are immutable after import.

| Field | Type | Default | Notes |
|---|---|---|---|
| `ENV` | `Literal["dev", "test", "staging", "prod"]` | `"dev"` | Switches Alembic test fixture and CORS rules. `"staging"` is required by M4's `/test/scheduler/tick` gate (`m4-automations.md` § Test hook) and by M5's smoke pack against the staging URL (`m5-hardening.md` § Smoke E2E pack). |
| `HOST` | `str` | `"0.0.0.0"` | Uvicorn bind. |
| `PORT` | `int` | `8080` | Same as legacy default for proxy parity. |
| `LOG_LEVEL` | `str` | `"INFO"` | Passed to `logging.basicConfig`. |
| `DATABASE_URL` | `str` | `"mysql+asyncmy://rebuild:rebuild@mysql:3306/rebuild?charset=utf8mb4"` | Pool config below. |
| `DB_POOL_SIZE` | `int` | `10` | SQLAlchemy `pool_size`. |
| `DB_POOL_MAX_OVERFLOW` | `int` | `5` | SQLAlchemy `max_overflow`. |
| `DB_POOL_RECYCLE_SECONDS` | `int` | `1800` | Avoids stale MySQL connections. |
| `REDIS_URL` | `str` | `"redis://redis:6379/0"` | Used by `/readyz` only in M0. |
| `MODEL_GATEWAY_BASE_URL` | `str \| None` | `None` | Wired in M1; loaded in M0 to fail fast on misconfig. |
| `MODEL_GATEWAY_API_KEY` | `SecretStr \| None` | `None` | Same. |
| `TRUSTED_EMAIL_HEADER` | `str` | `"X-Forwarded-Email"` | Header read by `get_user`. |
| `TRUSTED_NAME_HEADER` | `str` | `"X-Forwarded-Name"` | Optional display name source. |
| `TRUSTED_EMAIL_DOMAIN_ALLOWLIST` | `list[str]` | `[]` | Empty means accept any header value. CSV in env. |
| `MAX_UPLOAD_BYTES` | `int` | `5_242_880` | 5 MiB cap (matches `rebuild.md` §9). |
| `CORS_ALLOW_ORIGINS` | `list[str]` | `[]` | CSV-parsed. Empty in prod, `["http://localhost:5173"]` for dev. |
| `READYZ_DB_TIMEOUT_MS` | `int` | `1000` | Per-call timeout in `/readyz`. |
| `READYZ_REDIS_TIMEOUT_MS` | `int` | `500` | Per-call timeout in `/readyz`. |

Pydantic-settings 2 reads CSVs into `list[str]` automatically when annotated, and the `SecretStr` type prevents the API key from leaking into log lines.

**Casing convention (locked).** Every field on `Settings` is declared with the same UPPER_SNAKE_CASE name as its env var; access from code is therefore always `settings.MODEL_GATEWAY_BASE_URL`, never `settings.model_gateway_base_url`. The convention is uniform across every milestone (M1–M5). Pydantic-settings 2 supports either casing, but mixing them causes silent attribute errors when the wrong case is used at a call site, so the project pins one. Later milestones that extend `Settings` with new fields (M1's `SSE_STREAM_TIMEOUT_SECONDS`, M4's `AUTOMATION_*` knobs, M5's `OTEL_*`, `LOG_FORMAT`, `TRUSTED_PROXY_CIDRS`, `RATELIMIT_*`, `ALLOWED_FILE_TYPES`) follow the same UPPER_SNAKE_CASE rule and are listed in their plans' "Settings additions" subsection. The launch-banner cutoff (`PUBLIC_LAUNCH_BANNER_UNTIL`) is intentionally **not** a backend `Settings` field — it lives only on the SvelteKit side as a `PUBLIC_*` static env var (see `m5-hardening.md` § In-product banner).

### Trusted-header dependency

`app/core/auth.py` is the only auth surface and exposes two symbols: a pure helper and the FastAPI dependency that wraps it.

**`upsert_user_from_headers(db, *, email, name) -> User`** is the pure helper that contains the entire "trusted header → `User` row" contract. It is `async`, takes an `AsyncSession` plus the already-extracted/validated email and optional name, and:

1. Lowercases + URL-decodes the email.
2. If `settings.TRUSTED_EMAIL_DOMAIN_ALLOWLIST` is non-empty and the email domain is not in it, raises `HTTPException(status_code=401, detail="email domain not allowed")`.
3. Looks up `User` by email via `await db.scalar(select(User).where(User.email == email))`.
4. If absent, inserts with `name = unquote(name or email)`. Uses `INSERT ... ON DUPLICATE KEY UPDATE id = id` to remain idempotent under concurrent first-time logins.
5. Returns the `User` row.

**`get_user(request, db) -> User`** is the FastAPI dependency. It reads the header named by `settings.TRUSTED_EMAIL_HEADER` (default `X-Forwarded-Email`), raises `HTTPException(status_code=401, detail="missing trusted header")` if missing or empty, then delegates to `upsert_user_from_headers(db, email=email, name=request.headers.get(settings.TRUSTED_NAME_HEADER))`.

The two-symbol split is deliberate: M3's socket.io `connect` handler authenticates from the same trusted headers but lives outside the FastAPI request lifecycle, so it cannot use `Depends(get_user)`. Instead it opens its own `AsyncSessionLocal()` and calls `upsert_user_from_headers` directly. Keeping the upsert in a pure helper means the auth contract has exactly one implementation; if the day ever comes when "first login" needs to also write a `last_seen_at` or an audit row, it's one line in one file.

There is no `get_optional_user` in M0; `/healthz` and `/readyz` are the only unauthenticated routes.

### Dependency type aliases

`app/core/deps.py` defines reusable `Annotated[T, Depends(...)]` aliases so route signatures stay short and the project-wide convention is "always `Annotated`, never bare `Depends()` in a parameter default." M0 ships two; M1 adds `Provider`.

```python
# rebuild/backend/app/core/deps.py
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_user
from app.core.db import get_session
from app.models.user import User

CurrentUser = Annotated[User, Depends(get_user)]
DbSession   = Annotated[AsyncSession, Depends(get_session)]
```

Routes use them directly:

```python
@router.get("/api/me", response_model=UserRead)
async def me(user: CurrentUser) -> User:
    return user
```

Rule for revision authors and route authors: **never write `db: AsyncSession = Depends(get_session)` or `user: User = Depends(get_user)` in a route signature.** Use `db: DbSession` and `user: CurrentUser`. The first form silently becomes a query-parameter declaration if you forget the `Depends()` wrapper; the alias form is impossible to typo. A ruff custom rule (or a `tests/test_no_bare_depends.py` AST gate) enforces this in `backend/app/routers/`.

### Pydantic conventions

Every Pydantic schema under `app/schemas/` inherits from `app/schemas/_base.StrictModel`, never directly from `BaseModel`:

```python
# rebuild/backend/app/schemas/_base.py
from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Project-wide Pydantic base.

    - extra="forbid": typo'd request fields (`{"acrhived": true}`) become a 422
      instead of being silently ignored. Closes the most common shape-drift bug
      in JSON-body APIs.
    - str_strip_whitespace=True: incoming strings have leading/trailing
      whitespace stripped at validation time, so the DB never stores
      `"  hello  "`.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
```

Conventions enforced by review:

- Request and response bodies inherit from `StrictModel`. M0's `UserRead` is the first example; M1–M5 follow.
- Use `from __future__ import annotations` at the top of every schema module so forward refs and `T | None` work uniformly under mypy strict.
- Prefer `T | None` over `Optional[T]`.
- Prefer the curated Pydantic types (`EmailStr`, `AnyUrl`, `SecretStr`, `Annotated[int, Field(ge=…, le=…)]`) over hand-rolled validators.
- Field-level docstrings via `Field(..., description="…")` flow into the OpenAPI doc — use them for any non-obvious request field.

If you ever need to override `extra="forbid"` (e.g. an opaque webhook envelope), do it in the subclass with an explicit `model_config = ConfigDict(extra="allow")` and a one-line comment justifying the relaxation.

### Project constants

`app/core/constants.py` holds non-tunable, project-wide numeric constants that two or more milestones agree on. Constants live here (not in `Settings`) when they are *implementation* values rather than deployment knobs — changing them is a code review, not an env-var flip.

```python
# rebuild/backend/app/core/constants.py
"""Project-wide constants. Not tunable per environment."""

STREAM_HEARTBEAT_SECONDS: int = 15
"""Heartbeat cadence for SSE (M1 chat streaming) and socket.io (M3 channels).

Single source of truth so the FE timeout-watchdog window stays consistent
across both transports. 15s is short enough that a stalled upstream is
detected before LB idle-cutoff, long enough that idle connections don't
generate measurable load.
"""

MAX_CHAT_HISTORY_BYTES: int = 1_048_576  # 1 MiB; enforced in M1 chat service
"""Cap on `chat.history` JSON payload. Larger and writes start contending on
the row lock; almost always a sign of a bug rather than a real conversation."""
```

M1 (`chat_stream.py`) and M3 (`realtime/sio.py`) both import `STREAM_HEARTBEAT_SECONDS` from here; neither hard-codes the value. Ditto `MAX_CHAT_HISTORY_BYTES` from M1's chat service.

### `/healthz` and `/readyz` semantics

Both live in `app/routers/health.py` and are mounted without auth.

- `GET /healthz`: returns `{"status": "ok"}` immediately. Does no I/O. Used by the orchestrator's liveness probe.
- `GET /readyz`: pings MySQL with `SELECT 1` (timeout `READYZ_DB_TIMEOUT_MS`) and Redis with `PING` (timeout `READYZ_REDIS_TIMEOUT_MS`), then returns `{"status": "ready", "checks": {"db": "ok", "redis": "ok"}}` with `200`. On any failure it returns `{"status": "unready", "checks": {...}}` with `503`. Used by the orchestrator's readiness probe and by Docker compose `healthcheck`.

### `/api/me`

`app/routers/me.py` exposes a single `GET /api/me` that depends on `get_user` and returns `UserRead(id, email, name, timezone, created_at)`. `created_at` is the BIGINT epoch-ms value straight from the row (project-wide convention from `rebuild.md` §4); the FE renders it via the same `Date(ms)` helper used for chat / channel / automation timestamps. This is the round-trip endpoint the frontend hits to prove the trusted-header path works end-to-end.

### Alembic baseline

The first revision `0001_baseline.py` creates exactly one table, and uses the M0 helper module so re-running a partially-applied revision is a no-op (filename convention is `<revid>.py` with no date prefix, matching the M1–M4 revisions `0002_m1_chat_folder.py`, `0003_m2_sharing.py`, `0004_m3_channels.py`, `0005_m4_automations.py`):

```python
from app.db.migration_helpers import (
    create_table_if_not_exists,
    drop_table_if_exists,
)

def upgrade() -> None:
    create_table_if_not_exists(
        "user",
        sa.Column("id", sa.String(36), primary_key=True),       # UUIDv7 (RFC 9562) via app.core.ids.new_id()
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("created_at", sa.BigInteger(), nullable=False),  # epoch ms via app.core.time.now_ms() — matches every other timestamp in the project (rebuild.md §4, database-best-practises.md §A.1)
        sa.UniqueConstraint("email", name="uq_user_email"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )

def downgrade() -> None:
    drop_table_if_exists("user")
```

No other tables. Alembic's `env.py` wires `target_metadata = app.db.base.Base.metadata` and uses an async runner (`run_async_migrations`) so migrations work against the same `asyncmy` URL.

### Migration helpers

Every Alembic revision in the rebuild — M0 baseline plus M1–M4 — calls only the wrappers defined in `app/db/migration_helpers.py`. The wrappers fall into two camps: those that map to a MySQL-native `IF NOT EXISTS` / `IF EXISTS` clause (CREATE/DROP TABLE, DROP INDEX on MySQL 8.0.29+), and those that introspect the live schema with SQLAlchemy `inspect()` and skip the underlying `op.*` call when the object already exists or has already been removed. MySQL 8.0 does not support `IF NOT EXISTS` on `CREATE INDEX`, `ALTER TABLE ADD COLUMN`, `ADD CONSTRAINT`, or `ADD FOREIGN KEY`, so the inspect-then-emit pattern is mandatory for those — confirmed against the MySQL 8.0 Reference Manual at the time of writing (see [rebuild.md § 9 "Robust, idempotent Alembic migrations"](../../rebuild.md#9-decisions-locked)). The full surface, in one file:

```python
# rebuild/backend/app/db/migration_helpers.py
from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op


def _inspector() -> sa.engine.reflection.Inspector:
    return sa.inspect(op.get_bind())


def has_table(name: str) -> bool:
    return _inspector().has_table(name)


def has_column(table: str, column: str) -> bool:
    if not has_table(table):
        return False
    return any(c["name"] == column for c in _inspector().get_columns(table))


def has_index(table: str, name: str) -> bool:
    if not has_table(table):
        return False
    return any(i["name"] == name for i in _inspector().get_indexes(table))


def has_unique_constraint(table: str, name: str) -> bool:
    if not has_table(table):
        return False
    return any(u["name"] == name for u in _inspector().get_unique_constraints(table))


def has_foreign_key(table: str, name: str) -> bool:
    if not has_table(table):
        return False
    return any(fk["name"] == name for fk in _inspector().get_foreign_keys(table))


def has_check_constraint(table: str, name: str) -> bool:
    if not has_table(table):
        return False
    return any(cc["name"] == name for cc in _inspector().get_check_constraints(table))


def create_table_if_not_exists(name: str, *columns: Any, **kw: Any) -> None:
    """Idempotent op.create_table. Uses MySQL native IF NOT EXISTS via the
    SQLAlchemy `mysql_create_if_not_exists=True` table-arg so the DDL itself
    is `CREATE TABLE IF NOT EXISTS`, which is atomic and race-free across
    parallel migration jobs (rare but possible during canary rollouts)."""
    if has_table(name):
        return
    kw.setdefault("mysql_engine", "InnoDB")
    kw.setdefault("mysql_charset", "utf8mb4")
    kw.setdefault("mysql_collate", "utf8mb4_0900_ai_ci")
    # mysql_create_if_not_exists is a table_arg recognised by the MySQL
    # dialect; it emits IF NOT EXISTS in the rendered CREATE statement.
    kw["mysql_create_if_not_exists"] = True
    op.create_table(name, *columns, **kw)


def drop_table_if_exists(name: str) -> None:
    if has_table(name):
        op.drop_table(name)


def create_index_if_not_exists(
    name: str, table: str, columns: list[str | sa.Column[Any]],
    *, unique: bool = False, **kw: Any,
) -> None:
    if has_index(table, name):
        return
    op.create_index(name, table, columns, unique=unique, **kw)


def drop_index_if_exists(name: str, table: str) -> None:
    if has_index(table, name):
        op.drop_index(name, table_name=table)


def add_column_if_not_exists(
    table: str,
    column: sa.Column[Any],
    *,
    algorithm: str = "INSTANT",
    lock: str = "DEFAULT",
) -> None:
    """Idempotent op.add_column that pins the MySQL DDL algorithm.

    Defaults to ``ALGORITHM=INSTANT, LOCK=DEFAULT`` (MySQL 8.0.12+) so the
    operation is metadata-only and runtime is independent of table size. If the
    column type/position is incompatible with INSTANT, MySQL fails fast with
    1845 (instead of silently downgrading to ALGORITHM=COPY and locking the
    table for hours). Callers that genuinely need INPLACE/COPY pass the
    explicit override and justify it in a comment in the revision file.
    """
    if has_column(table, column.name):
        return
    if algorithm.upper() == "INSTANT" and lock.upper() == "DEFAULT":
        # SQLAlchemy doesn't render ALGORITHM/LOCK on ADD COLUMN, so emit raw
        # DDL with the same column definition the dialect would produce.
        ddl = sa.schema.CreateColumn(column).compile(dialect=op.get_bind().dialect)
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN {ddl}, ALGORITHM=INSTANT, LOCK=DEFAULT"
        )
    else:
        op.add_column(table, column)


def drop_column_if_exists(table: str, column: str) -> None:
    if has_column(table, column):
        # DROP COLUMN cannot use ALGORITHM=INSTANT (MySQL 8.0); INPLACE is the
        # best we can do. Tables that would block on this are explicitly called
        # out in the revision's comment block.
        op.execute(f"ALTER TABLE {table} DROP COLUMN {column}, ALGORITHM=INPLACE, LOCK=NONE")


def create_foreign_key_if_not_exists(
    name: str, source_table: str, referent_table: str,
    local_cols: list[str], remote_cols: list[str], **kw: Any,
) -> None:
    if has_foreign_key(source_table, name):
        return
    op.create_foreign_key(name, source_table, referent_table, local_cols, remote_cols, **kw)


def drop_constraint_if_exists(name: str, table: str, *, type_: str) -> None:
    """type_ ∈ {"foreignkey","unique","check","primary"}."""
    found = {
        "foreignkey": has_foreign_key,
        "unique": has_unique_constraint,
        "check": has_check_constraint,
    }.get(type_, lambda _t, _n: True)(table, name)
    if found:
        op.drop_constraint(name, table, type_=type_)


def create_check_constraint_if_not_exists(
    name: str, table: str, condition: str | sa.sql.elements.ColumnElement[bool],
) -> None:
    if not has_check_constraint(table, name):
        op.create_check_constraint(name, table, condition)


def execute_if(condition: bool, sql: str) -> None:
    """Escape hatch for raw DDL (e.g. MySQL generated columns) guarded by an
    application-level predicate the caller has already evaluated against
    `_inspector()`."""
    if condition:
        op.execute(sql)
```

Rules for revision authors (enforced by review and by a CI grep gate):

- **No bare `op.create_table`, `op.create_index`, `op.add_column`, `op.create_foreign_key`, `op.create_check_constraint`, `op.create_unique_constraint`, `op.drop_table`, `op.drop_index`, `op.drop_column`, `op.drop_constraint`** in any file under `backend/alembic/versions/`. Use the helper variants exclusively. Enforced by the `tests/test_migrations.py::test_no_bare_op_calls` AST gate (an AST walk is strictly more reliable than a regex against the file text — multi-line calls, in-comment matches, and `op.execute(...)` raw DDL all confound a grep) which runs in the Buildkite `unit` step.
- **`op.execute` is allowed but only via `execute_if(condition, sql)`** so the caller has to think about the precondition. The single legitimate use in M1 is the MySQL generated column on `chat.current_message_id`; the precondition is `not has_column("chat", "current_message_id")`. Any raw `ALTER TABLE` emitted via `execute_if` MUST end with `, ALGORITHM=<INSTANT|INPLACE|COPY>, LOCK=<DEFAULT|NONE|SHARED|EXCLUSIVE>` so the migration's blocking behaviour is explicit at the call site, not implicit. The `test_no_bare_op_calls` AST gate also fails any `execute_if` whose SQL string starts with `ALTER TABLE` and lacks the algorithm clause.
- **`add_column_if_not_exists` defaults to `ALGORITHM=INSTANT, LOCK=DEFAULT`** (MySQL 8.0.12+). This is the right default for new columns: the operation is metadata-only and a 100M-row `chat` table costs the same to widen as an empty one. If a column genuinely cannot be added INSTANT (most common cause: it would push the row off-page, e.g. a wide TEXT default mid-table), pass `algorithm="INPLACE"` (or `"COPY"` as a last resort) explicitly and justify the choice in a comment block above the call. The Helm migration Job's `activeDeadlineSeconds: 300` is sized for INSTANT-class operations; INPLACE/COPY revisions must bump the override in the same PR (see `m5-hardening.md` § Database migration step).
- **Every `upgrade()` must be a re-runnable no-op on a fully-upgraded schema.** This is verified by an integration test that runs `alembic upgrade head` twice in succession against the same MySQL container and asserts the second run is a no-op (no `CREATE`/`ALTER` in the binlog).
- **Every `downgrade()` must be a re-runnable no-op on a fully-downgraded schema.** Same pattern: `alembic downgrade base` twice, second run is a no-op.

### Alembic helper test gate

`backend/tests/test_migrations.py` (added in M0 alongside the helper module) covers the contract for every revision the repo will ever hold:

- `test_upgrade_head_is_idempotent`: `alembic upgrade head` from empty DB succeeds; second run is a no-op (asserted by counting rows in `INFORMATION_SCHEMA.TABLES` before and after).
- `test_downgrade_base_is_idempotent`: `alembic upgrade head` then `alembic downgrade base` then `alembic downgrade base` — second downgrade is a no-op.
- `test_partial_upgrade_recovers`: simulate a crash mid-migration by manually applying the first half of M1's revision via raw DDL (`CREATE TABLE folder` only), then run `alembic upgrade head` and assert the migration completes and `chat`, `folder`, all indexes, and the generated column exist. This is the test that proves the helper pattern actually does what it promises.
- `test_no_bare_op_calls`: walks every `.py` under `backend/alembic/versions/`, parses the AST, and asserts no `Attribute` node matches `op.create_*`/`op.drop_*`/`op.add_column` outside of the helper module. Same test also asserts that any `execute_if(..., sql=...)` whose SQL string begins with `ALTER TABLE` ends with `ALGORITHM=` and `LOCK=` clauses (case-insensitive), so the blocking behaviour of every raw DDL is explicit.

These four tests live next to the helper module and run in the M0 unit-test step. Every later milestone adds at most a parametrised case to `test_partial_upgrade_recovers` for the new revision; no other change.

## Frontend skeleton

### Frontend conventions (cross-cutting)

These conventions are pinned in M0 once and inherited by every later milestone (M1–M5). They are enforced by review and the linked CI gates; do not redeclare them in the per-milestone plans. M1/M3/M4 should reference this section by link instead of re-stating the rules.

**Source-of-truth references.** [`rebuild/plans/svelte-best-practises.md`](svelte-best-practises.md) and [`rebuild/plans/sveltekit-best-practises.md`](sveltekit-best-practises.md) are the project's canonical Svelte 5 / SvelteKit 2 references. When this plan or any milestone plan disagrees with them, the best-practices docs win and the plan is patched.

1. **Module naming: `*.svelte.ts` for runes, `*.ts` for everything else.** The Svelte compiler only enables runes inside `.svelte` and `*.svelte.ts` / `*.svelte.js` files. Any module that uses `$state`, `$derived`, `$effect`, `$props`, `$bindable`, or `$inspect` lives at `src/lib/.../<name>.svelte.ts`; pure utilities (the typed fetch client, MSW handlers, ID helpers, format helpers) stay `*.ts`. The frontend ESLint config pins this — `$state(` / `$derived(` / `$effect(` referenced from a non-`*.svelte.ts` file is a lint error.

2. **Shared client state pattern: class + `setContext`, never module-level `$state` for user data.** A SvelteKit server is a long-running process shared across every request. Top-level `let foo = $state(...)` in a module imported during SSR is shared across all concurrent users — a per-user data leak (see [sveltekit-best-practises.md § 8.1](sveltekit-best-practises.md)). The convention for the rebuild is therefore:
   - Wrap shared state as a small class with `$state` fields (and methods that mutate them) in a `*.svelte.ts` file.
   - In the nearest layout that owns the state (typically `(app)/+layout.svelte`), call `setContext(KEY, new FooStore(initialData))`.
   - Downstream components call `getContext(KEY)` to read/write. Per-render, per-request, SSR-safe by construction.
   - Module-level `$state` is **only** acceptable for genuinely client-only, non-user-scoped values (e.g. an in-memory toast queue used after hydration, theme preference). It is banned for chats, channels, messages, automations, the active user, the current model, or anything else derived from the request.
   The pattern is shown end-to-end in [sveltekit-best-practises.md § 8.2](sveltekit-best-practises.md). M1's `chats` / `folders` / `activeChat` / `models`, M3's `channels` / `messages` / `typing` / `presence` / `reads`, and M4's `automations` all follow this shape; the `(app)/+layout.svelte` is the singular construction site.

3. **Long-lived browser side-effects live in `$effect` with a cleanup return.** Every SSE reader, socket subscription, `setInterval`, `setTimeout` race-watchdog, and polling loop is owned by a `$effect(() => { ... return () => cleanup(); })` inside the component (or store class) that needs it. `$effect` no-ops on the server, runs once on mount, and auto-cleans on teardown — which makes it the only correct primitive for these. **Module-scope `setInterval` / `setTimeout` is banned**: it runs on every SSR import, never cleans up, and accumulates one timer per worker boot. Concrete owners: M1's SSE reader lives in `ConversationView.svelte`, M3's socket subscription and typing-prune interval live in `(app)/channels/+layout.svelte`, M4's run-now polling lives in `<AutomationEditor>`.

4. **Svelte 5 idioms — what to use, what is banned.** Every component (new or ported from the legacy fork) follows these without exception; M3's component port list inherits this without restating it per-component:

   | Use | Don't |
   |---|---|
   | Callback props (`onfoo` / `onclick`) | `createEventDispatcher`, `dispatch('foo')` |
   | `{#snippet}` + `{@render}` for slot-shaped composition | `<slot>` / `<slot name="...">` |
   | Lowercase event attributes (`onclick`, `oninput`) | `on:click`, `on:input` |
   | `{@attach}` for DOM attachments | `use:action` |
   | `$derived` (default) — `$effect` only for true side-effects | `$effect(() => { x = ... })` to set state |
   | `$bindable` only on form-control wrappers (parent owns the value) | `$bindable` for one-way data flow that should be a callback |
   | `SvelteMap` / `SvelteSet` from `svelte/reactivity` for reactive collections | `new Map()` / `new Set()` in reactive code |
   | `$state.raw(...)` for large API payloads replaced wholesale | Deep-proxy `$state(...)` for read-once response data |
   | `$app/state` (the `page` / `navigating` / `updated` reactive objects) | `$app/stores` (deprecated since SvelteKit 2.12) |
   | `error()` / `redirect()` (called) | `throw error(...)` / `throw redirect(...)` (SvelteKit 1 idiom) |

   A grep gate in the lint step rejects any of `createEventDispatcher`, `<slot`, `on:click`, `use:`, or `$app/stores` under `frontend/src/`. The conversion table is duplicated for convenience in [svelte-best-practises.md § 17](svelte-best-practises.md).

5. **Mutations: direct REST calls to FastAPI, not SvelteKit form actions — by deliberate decision.** The SvelteKit layer in the rebuild is a thin SSR shell in front of a FastAPI backend. SvelteKit form actions and `use:enhance` would have to proxy every mutation through `event.fetch` to FastAPI anyway, doubling the surface area without delivering progressive-enhancement value (every user is behind the OAuth proxy with JS enabled). **Every mutation in M1–M4 (chat CRUD, folder CRUD, message send, share/unshare, channel CRUD, message post, reaction toggle, pin, automation CRUD, run-now) is therefore a typed `fetch` from a store action against the FastAPI `/api/...` route, with the optimistic update applied locally and rolled back on error.** This is a conscious trade-off — we forgo `use:enhance` in exchange for a single mutation pattern that matches the realtime (socket.io) and streaming (SSE) paths, both of which already bypass form actions. SvelteKit's built-in CSRF check (`kit.csrf.checkOrigin`, on by default) stays on as a backstop; it never fires in steady state because no first-party form actions exist to protect. If a future feature genuinely benefits from progressive enhancement (e.g. a public marketing page form), it gets a `+page.server.ts` action at that point — not before. Reviewers should reject "convert this to a form action" suggestions on M1–M4 routes; cite this paragraph.

### Stack and packaging

- SvelteKit 2 with `@sveltejs/adapter-node` (we serve from the same container as the backend in dev, separate ports).
- Svelte 5 (runes mode enabled by default in SvelteKit 2).
- Tailwind 4 via `@tailwindcss/vite` (the v4-native Vite plugin; no `tailwind.config.cjs` content globs needed but a `tailwind.config.ts` is kept for future plugin registration).
- TypeScript 5 with `strict: true`, `noUncheckedIndexedAccess: true`.

### `app.html`

Standard SvelteKit shell with `%sveltekit.head%`/`%sveltekit.body%`. The body has `<div id="app">%sveltekit.body%</div>`. No custom inline scripts.

### Auth populate via `hooks.server.ts handle` (not layout-only)

The `/api/me` round-trip happens once per server request, in `src/hooks.server.ts`'s `handle`, and the result is parked on `event.locals.user`. The root `+layout.server.ts` then just returns `{ user: locals.user }`. Doing it in the layout alone would be subtly wrong: layout `load` results are cached across sibling navigations, so a stale `null` from the first request would leak into the next one (see [sveltekit-best-practises.md § 6.2 / § 6.3](sveltekit-best-practises.md) and the anti-pattern in § 15 — "Auth in `+layout.server.ts` only"). `hooks.server.ts handle` runs on every server request, including form-action POSTs and `+server.ts` endpoints, and is the single right place to materialise the request-scoped user.

```ts
// src/hooks.server.ts (sketch)
export const handle: Handle = async ({ event, resolve }) => {
  const email = event.request.headers.get('x-forwarded-email');
  if (email) {
    const res = await event.fetch(`${BACKEND_URL}/api/me`, {
      headers: {
        'x-forwarded-email': email,
        'x-forwarded-name': event.request.headers.get('x-forwarded-name') ?? '',
      },
    });
    event.locals.user = res.ok ? await res.json() : null;
  } else {
    event.locals.user = null;
  }
  return resolve(event);
};
```

```ts
// src/routes/+layout.server.ts
export const load: LayoutServerLoad = ({ locals }) => ({ user: locals.user });
```

`hooks.server.ts` also rewrites the `event.fetch` URL so it reaches the FastAPI service inside the compose network and forwards the incoming `X-Forwarded-Email` (and `X-Forwarded-Name`) headers — that hook continues to do double duty (auth populate + backend rewrite). `App.Locals` in `app.d.ts` declares `user: User | null` so every downstream `event.locals.user` access is typed. The default `+layout.svelte` renders `Hello {data.user.email}` and a small JSON dump for debugging — that is the entire visible UI in M0.

### Env handling

A typed env barrel at `src/lib/env.ts` reads `import.meta.env.PUBLIC_*` for browser-visible config and `$env/dynamic/private` for SSR-only values. Only one var is wired in M0:

- `PUBLIC_API_BASE_URL` — defaults to `""` (same-origin); used by the typed fetch client.

The backend URL for SSR proxying is derived from `process.env.BACKEND_URL` (default `http://app:8080`) inside `hooks.server.ts`.

## Infrastructure (rebuild/infra)

`infra/docker-compose.yml` defines three services. All names are namespaced (`rebuild_*`) so they cannot collide with any legacy compose project the engineer happens to have running.

```yaml
name: rebuild
services:
  mysql:
    image: mysql:8.0.39
    container_name: rebuild_mysql
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_0900_ai_ci
      - --max_allowed_packet=16M
      - --default-authentication-plugin=caching_sha2_password
    environment:
      MYSQL_ROOT_PASSWORD: rebuild
      MYSQL_DATABASE: rebuild
      MYSQL_USER: rebuild
      MYSQL_PASSWORD: rebuild
    ports:
      - "13306:3306"
    volumes:
      - rebuild_mysql_data:/var/lib/mysql
      - ./mysql/my.cnf:/etc/mysql/conf.d/rebuild.cnf:ro
      - ./mysql/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "-prebuild"]
      interval: 5s
      timeout: 3s
      retries: 20

  redis:
    image: redis:7.4-alpine
    container_name: rebuild_redis
    command: ["redis-server", "/usr/local/etc/redis/redis.conf"]
    ports:
      - "16379:6379"
    volumes:
      - ./redis/redis.conf:/usr/local/etc/redis/redis.conf:ro
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

  app:
    build:
      context: ..
      dockerfile: Dockerfile
    container_name: rebuild_app
    environment:
      ENV: dev
      DATABASE_URL: mysql+asyncmy://rebuild:rebuild@mysql:3306/rebuild?charset=utf8mb4
      REDIS_URL: redis://redis:6379/0
      TRUSTED_EMAIL_HEADER: X-Forwarded-Email
      CORS_ALLOW_ORIGINS: http://localhost:5173
    ports:
      - "8080:8080"
    depends_on:
      mysql:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8080/healthz"]
      interval: 5s
      timeout: 3s
      retries: 20

volumes:
  rebuild_mysql_data:
```

`infra/mysql/my.cnf`:

```ini
[mysqld]
character_set_server      = utf8mb4
collation_server          = utf8mb4_0900_ai_ci
max_allowed_packet        = 16M
innodb_strict_mode        = 1
local_infile              = 0
sql_mode                  = STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION
```

`infra/mysql/init.sql` is a no-op assertion (the database is already created by `MYSQL_DATABASE`); it just sets the database default charset and collation explicitly:

```sql
ALTER DATABASE rebuild CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
```

`infra/redis/redis.conf` contains only what M0 needs:

```
appendonly no
maxmemory 256mb
maxmemory-policy allkeys-lru
```

The compose ports are intentionally non-default (`13306`, `16379`) so the engineer can run rebuild compose alongside legacy compose without conflicts.

## Dockerfile

[rebuild/Dockerfile](../Dockerfile) is three stages, distinct from the legacy [Dockerfile](../../Dockerfile). It installs no ML deps (no torch, sentence-transformers, faster-whisper, ollama).

```dockerfile
# Stage 1 — frontend build
FROM --platform=$BUILDPLATFORM node:22-alpine3.20 AS frontend
WORKDIR /work
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tsconfig.json svelte.config.js vite.config.ts tailwind.config.ts postcss.config.cjs ./
COPY frontend ./frontend
RUN npm run --workspace frontend build

# Stage 2 — Python deps
FROM python:3.12.7-slim-bookworm AS pydeps
WORKDIR /work
RUN pip install --no-cache-dir uv==0.5.5
COPY pyproject.toml uv.lock* ./
COPY backend ./backend
RUN uv sync --frozen --no-dev --project backend

# Stage 3 — runtime
FROM python:3.12.7-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 app && \
    useradd  --system --uid 10001 --gid app --home-dir /app --shell /bin/false app
WORKDIR /app
COPY --from=pydeps   /work/backend/.venv  /app/.venv
COPY --from=pydeps   /work/backend        /app/backend
COPY --from=frontend /work/frontend/build /app/frontend
ENV PATH="/app/.venv/bin:${PATH}"
USER app
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=10 \
  CMD curl -fsS http://localhost:${PORT}/healthz || exit 1
CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8080"]
```

Notes: non-root `app` user fixed at UID 10001 for predictable volume permissions; final image targets < 250 MB on `python:3.12.7-slim-bookworm`. The image is single-purpose (FastAPI). Frontend assets are colocated at `/app/frontend` but routing them is M1+.

## Tooling (linting, types, tests)

### Ruff

Configured in [rebuild/pyproject.toml](../pyproject.toml) under `[tool.ruff]`:

```toml
[tool.ruff]
line-length = 100
target-version = "py312"
src = ["backend"]
extend-exclude = [".venv", "node_modules", "frontend"]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "ASYNC", "RET", "PL", "PT", "TID"]
ignore = ["PLR0913"]

[tool.ruff.lint.per-file-ignores]
"backend/alembic/versions/*" = ["E501"]
"backend/tests/*" = ["PLR2004"]
```

### Mypy strict

```toml
[tool.mypy]
python_version = "3.12"
strict = true
warn_unused_ignores = true
warn_unreachable = true
disallow_any_explicit = false  # SQLAlchemy generics force a few Any escapes
plugins = ["pydantic.mypy"]
files = ["backend/app"]

[[tool.mypy.overrides]]
module = ["asyncmy.*", "alembic.*"]
ignore_missing_imports = true
```

### Pytest

```toml
[tool.pytest.ini_options]
addopts = "-ra -q --strict-markers --strict-config"
asyncio_mode = "auto"
testpaths = ["backend/tests"]
filterwarnings = ["error::DeprecationWarning"]
```

The `conftest.py` boots a fresh MySQL via `testcontainers-mysql` (matching version 8.0.39) for the test suite, runs Alembic upgrade head, and yields an async HTTPX client bound to the FastAPI app.

### Vitest

`rebuild/frontend/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";
import { sveltekit } from "@sveltejs/kit/vite";

export default defineConfig({
  plugins: [sveltekit()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.{test,spec}.ts"],
    setupFiles: ["src/lib/msw/node.ts"],
    coverage: { provider: "v8", reporter: ["text", "html"] },
  },
});
```

### Playwright (E2E)

`rebuild/frontend/playwright.config.ts` defines three projects, **chromium**, **firefox**, **webkit**, all running against `http://localhost:5173`. `globalSetup` runs `docker compose -f ../infra/docker-compose.yml up -d --wait` and seeds a single user via the API. Each test sets `extraHTTPHeaders: { "X-Forwarded-Email": "alice@canva.com" }` per `BrowserContext`.

### Playwright Component Testing

Initialised via `npm init playwright@latest -- --ct` against the Svelte template, output committed at `rebuild/frontend/playwright-ct.config.ts` and `rebuild/frontend/playwright/index.ts`. The CT config registers a single project against chromium only (CT does not need browser-matrix coverage; that lives in E2E). The `playwright/index.html` template imports `../src/app.css` so component tests render with Tailwind 4 styles applied.

### MSW

`npx msw init static/ --save` writes `static/mockServiceWorker.js`. Two bootstraps:

- `src/lib/msw/browser.ts`: starts the worker in dev when `import.meta.env.DEV && import.meta.env.PUBLIC_USE_MSW === "1"`. Off in production builds.
- `src/lib/msw/node.ts`: registered as a Vitest setup file and as the CT global `beforeMount` hook so component tests mock network without real HTTP.

`src/lib/msw/handlers.ts` ships a single handler in M0: `GET /api/me -> 200 { id, email, name, ... }`.

## CI: Buildkite pipeline

[rebuild/.buildkite/rebuild.yml](../.buildkite/rebuild.yml) is the new pipeline. The legacy [.buildkite/pipeline.yaml](../../.buildkite/pipeline.yaml) is unchanged. Both pipelines are wired into the same Buildkite project so PRs can trigger both, but the path filter ensures only the relevant pipeline runs work.

```yaml
env:
  IMAGE_REPO: "699983977898.dkr.ecr.us-east-1.amazonaws.com/container-build/data-platform/open-webui-rebuild"

agents:
  - queue=container-build-prod

steps:
  - label: ":python: lint (ruff)"
    key: lint-py
    if: build.changed_files =~ /^rebuild\//
    commands:
      - cd rebuild && uv sync --frozen --group dev --project backend
      - cd rebuild && uv run --project backend ruff check backend
      - cd rebuild && uv run --project backend ruff format --check backend
    timeout_in_minutes: 5

  - label: ":mypy: typecheck"
    key: typecheck
    if: build.changed_files =~ /^rebuild\//
    commands:
      - cd rebuild && uv sync --frozen --group dev --project backend
      - cd rebuild && uv run --project backend mypy backend/app
    timeout_in_minutes: 5

  - label: ":javascript: lint+typecheck (frontend)"
    key: lint-fe
    if: build.changed_files =~ /^rebuild\//
    commands:
      - cd rebuild && npm ci
      - cd rebuild && npm run -s lint
      - cd rebuild && npm run -s check
    timeout_in_minutes: 5

  - label: ":pytest: unit"
    key: unit
    if: build.changed_files =~ /^rebuild\//
    commands:
      - cd rebuild && uv sync --frozen --group dev --project backend
      - cd rebuild && uv run --project backend pytest backend/tests -x
    timeout_in_minutes: 8

  - label: ":vitest: unit (frontend)"
    key: unit-fe
    if: build.changed_files =~ /^rebuild\//
    commands: [cd rebuild && npm ci, cd rebuild && npm run -s test:unit]
    timeout_in_minutes: 5

  - label: ":playwright: component"
    key: component
    if: build.changed_files =~ /^rebuild\//
    commands:
      - cd rebuild && npm ci
      - cd rebuild && npx playwright install --with-deps chromium
      - cd rebuild && npm run -s test:ct
    timeout_in_minutes: 10

  - label: ":playwright: e2e-smoke"
    key: e2e-smoke
    if: build.changed_files =~ /^rebuild\//
    depends_on: [unit, unit-fe]
    commands:
      - cd rebuild && docker compose -f infra/docker-compose.yml up -d --wait
      - cd rebuild && npm ci && npx playwright install --with-deps chromium firefox webkit
      - cd rebuild && npm run -s test:e2e:smoke
      - cd rebuild && docker compose -f infra/docker-compose.yml down -v
    timeout_in_minutes: 15

  - wait

  - label: ":docker: build image"
    key: build-image
    if: build.changed_files =~ /^rebuild\//
    commands:
      - docker build --build-arg BUILD_HASH=${BUILDKITE_COMMIT} -t ${IMAGE_REPO}:${BUILDKITE_COMMIT} rebuild
    timeout_in_minutes: 15
    plugins:
      - Canva/universal-fetch#stable: ~
```

Wall-clock budgets per job (alerting target, not hard timeout): `lint-py` 2 min, `typecheck` 2 min, `lint-fe` 2 min, `unit` (backend) 4 min, `unit-fe` 2 min, `component` 5 min, `e2e-smoke` 8 min, `build-image` 10 min. The legacy pipeline's `branches: "main"` push step is mirrored later in M5 (deploy pipeline); M0 does not push images.

## Dependencies (with versions)

Pin to ranges that match the major/minor specified in [rebuild.md](../../rebuild.md) §2. Exact patch versions are floating; verify at install time.

### Python (`rebuild/pyproject.toml`)

```toml
[project]
name = "rebuild"
version = "0.0.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "fastapi >=0.115,<0.116",
  "uvicorn[standard] >=0.32,<0.33",
  "sqlalchemy[asyncio] >=2.0.36,<2.1",
  "asyncmy >=0.2.10,<0.3",
  "alembic >=1.13,<1.14",
  "pydantic >=2.9,<3",
  "pydantic-settings >=2.6,<3",
  "python-socketio >=5.11,<6",     # installed for M3, unused in M0
  "apscheduler >=3.10,<4",          # installed for M4, unused in M0
  "openai >=1.55,<2",               # installed for M1, unused in M0
  "httpx >=0.27,<0.29",
  "redis >=5.1,<6",
  "uuid7-standard >=1.1,<2",        # RFC 9562 UUIDv7 backport (Python 3.12); see app/core/ids.py
]

[dependency-groups]
dev = [
  "ruff >=0.7.4,<0.8",
  "mypy >=1.13,<2",
  "pytest >=8.3,<9",
  "pytest-asyncio >=0.24,<0.25",
  "pytest-cov >=5,<6",
  "anyio >=4.6,<5",
  "testcontainers[mysql] >=4.8,<5",
  "fakeredis >=2.26,<3",
]
```

### JavaScript (`rebuild/package.json`)

```json
{
  "name": "rebuild-frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite dev",
    "build": "vite build",
    "preview": "vite preview",
    "check": "svelte-kit sync && svelte-check --tsconfig ./tsconfig.json",
    "lint": "eslint . && prettier --check .",
    "format": "prettier --write .",
    "test:unit": "vitest run",
    "test:ct": "playwright test -c playwright-ct.config.ts",
    "test:e2e:smoke": "playwright test -c playwright.config.ts --grep @smoke"
  },
  "devDependencies": {
    "@sveltejs/adapter-node": "^5.2.9",
    "@sveltejs/kit": "^2.8.0",
    "@sveltejs/vite-plugin-svelte": "^4.0.0",
    "svelte": "^5.1.9",
    "svelte-check": "^4.0.5",
    "typescript": "^5.6.3",
    "vite": "^5.4.10",
    "vitest": "^2.1.4",
    "jsdom": "^25.0.1",
    "@playwright/test": "^1.48.2",
    "@playwright/experimental-ct-svelte": "^1.48.2",
    "msw": "^2.6.4",
    "tailwindcss": "^4.0.0",
    "@tailwindcss/vite": "^4.0.0",
    "@tailwindcss/postcss": "^4.0.0",
    "postcss": "^8.4.47",
    "eslint": "^9.14.0",
    "eslint-plugin-svelte": "^2.46.0",
    "@typescript-eslint/eslint-plugin": "^8.13.0",
    "@typescript-eslint/parser": "^8.13.0",
    "prettier": "^3.3.3",
    "prettier-plugin-svelte": "^3.2.7",
    "prettier-plugin-tailwindcss": "^0.6.8"
  }
}
```

Versions are floating within their major. If install fails because of a yanked patch, bump the minor and document the deviation in the PR description.

## Tests gating M0

The following must run green in CI before the milestone is closed.

**Backend (pytest):**
- `test_health.py`: `healthz_ok`, `readyz_ok` (live MySQL testcontainer + fakeredis), `readyz_db_down` returns 503.
- `test_auth.py`: `missing_header_returns_401`, `creates_user_on_first_request`, `reuses_user_on_subsequent_requests`, `domain_allowlist_rejects`.
- `test_settings.py`: defaults match the env-var table; `CORS_ALLOW_ORIGINS=a,b` parses to `["a","b"]`.
- Alembic round-trip: `upgrade head` → `downgrade base` succeeds against a fresh testcontainer MySQL.

**Frontend (Vitest + Playwright):**
- Vitest: typed fetch client (de)serializes `UserRead` from a fixture.
- Playwright CT: `+layout.svelte` mounted with `data.user = fixture` renders `Hello alice@canva.com`.
- Playwright E2E (`@smoke` tag): chromium + firefox + webkit each navigate to `/` with `X-Forwarded-Email: alice@canva.com` and assert the email is in the DOM and `/api/me` returned 200.

**Image build:** `docker build -f rebuild/Dockerfile rebuild` succeeds; `docker run` exits 0 on `/healthz` curl after compose-up.

## Acceptance criteria

- [ ] Top-level `rebuild/` directory exists with the layout in [§ File and directory layout](#file-and-directory-layout).
- [ ] `cd rebuild && make setup` provisions Python venv via `uv` and installs node deps via `npm ci` without errors.
- [ ] `cd rebuild && make dev` starts MySQL + Redis + FastAPI app via compose, all healthchecks pass within 60s.
- [ ] `curl -H 'X-Forwarded-Email: alice@canva.com' localhost:8080/api/me` returns `200` with a JSON body containing the email.
- [ ] `curl localhost:8080/api/me` (no header) returns `401`.
- [ ] `curl localhost:8080/healthz` returns `200`; `curl localhost:8080/readyz` returns `200` while compose is healthy.
- [ ] `cd rebuild && make migrate` runs `alembic upgrade head` against the dev MySQL and the `user` table is present with `utf8mb4_0900_ai_ci` collation and `InnoDB` engine. Re-running `make migrate` immediately afterwards produces zero DDL (verified by `tests/test_migrations.py::test_upgrade_head_is_idempotent`).
- [ ] `app/db/migration_helpers.py` exists and exposes the full helper surface (`create_table_if_not_exists`, `drop_table_if_exists`, `create_index_if_not_exists`, `drop_index_if_exists`, `add_column_if_not_exists`, `drop_column_if_exists`, `create_foreign_key_if_not_exists`, `drop_constraint_if_exists`, `create_check_constraint_if_not_exists`, `execute_if`); the four migration-contract tests (`test_upgrade_head_is_idempotent`, `test_downgrade_base_is_idempotent`, `test_partial_upgrade_recovers`, `test_no_bare_op_calls`) run green in CI.
- [ ] `app/core/auth.py` exposes both `upsert_user_from_headers(db, *, email, name)` and the `get_user` dep; `get_user` calls the helper. `tests/test_auth.py` covers both call shapes.
- [ ] `app/core/deps.py` exports `CurrentUser` and `DbSession`; `app/routers/me.py` uses `user: CurrentUser` (not `user: User = Depends(get_user)`).
- [ ] `app/schemas/_base.py` exports `StrictModel`; `UserRead` inherits from it; `tests/test_strict_model.py` asserts that posting `{"id": "...", "email": "...", "extra": 1}` to a stub endpoint returns 422.
- [ ] `app/core/constants.py` exports `STREAM_HEARTBEAT_SECONDS = 15` and `MAX_CHAT_HISTORY_BYTES = 1_048_576`. M1 and M3 plans reference these by import path (verified by a `tests/test_constants.py` smoke import).
- [ ] `src/hooks.server.ts` populates `event.locals.user` from `GET /api/me` on every server request; `src/routes/+layout.server.ts` is a one-liner returning `{ user: locals.user }`. `App.Locals.user` is typed as `User | null` in `app.d.ts`. A regression test (`frontend/tests/component/auth-locals.spec.ts`) asserts that a route handler reading `event.locals.user` sees the same value the client receives in `data.user`.
- [ ] The "Frontend conventions (cross-cutting)" section is referenced (not redeclared) by every store / state declaration in M1, M3, and M4. A grep gate fails any `frontend/src/lib/stores/*.ts` (without the `.svelte.ts` infix) that contains `$state(`, `$derived(`, or `$effect(`.
- [ ] `cd rebuild && make lint` runs ruff + ESLint + Prettier check with zero errors.
- [ ] `cd rebuild && make typecheck` runs mypy strict and `svelte-check` with zero errors.
- [ ] `cd rebuild && make test-unit` runs both backend pytest and frontend Vitest, all green.
- [ ] `cd rebuild && make test-component` runs Playwright CT with at least one passing component test.
- [ ] `cd rebuild && make test-e2e-smoke` runs the `@smoke` E2E suite against compose, green on chromium + firefox + webkit.
- [ ] `cd rebuild && make build` produces a runnable Docker image; `docker run --rm <image> python -c "import app.main"` exits 0.
- [ ] Buildkite pipeline file `rebuild/.buildkite/rebuild.yml` exists with the path filter `if: build.changed_files =~ /^rebuild\//` on every step.
- [ ] A test PR touching only `README.md` does not trigger any rebuild step in Buildkite. A test PR touching `rebuild/backend/app/main.py` triggers the rebuild pipeline and not the legacy one.
- [ ] Legacy [Makefile](../../Makefile) still works (no shared targets touched, no shared lockfiles modified).
- [ ] `rebuild.md` link `[rebuild/plans/m0-foundations.md](rebuild/plans/m0-foundations.md)` resolves to this document.

## Out of scope

The following are explicitly NOT delivered in M0. Each belongs to a later milestone or is a non-goal of the rebuild.

- Any chat / conversation / message tables or endpoints (M1).
- SSE streaming endpoint or any provider call (`OpenAICompatibleProvider` is referenced only as a placeholder import in M1).
- Sharing tables, share endpoints, public `/s/:token` route (M2).
- Any channel tables, socket.io handlers, Redis adapter wiring, threads/reactions/pins/webhooks (M3).
- Any automation tables, APScheduler worker, RRULE editor (M4).
- File upload endpoints, `file` / `file_blob` tables (M3).
- OpenTelemetry, structured-log shipping, rate limits, request timeouts beyond uvicorn defaults, deploy pipeline, runbooks (M5).
- Visual regression baselines (the directory is created and Git LFS configured, but no baselines are captured in M0). Baseline ownership: M1 captures `chat-empty`, `chat-streamed-reply`, `chat-sidebar` under `frontend/tests/visual-baselines/m1/`; M2 captures `share-view` under `…/m2/`; M3 captures `channel-feed`, `channel-thread` under `…/m3/`; M4 captures `automation-list`, `automation-editor` under `…/m4/`; M5 wires the visual-regression CI gate that fails on diffs above tolerance.
- Any UI beyond the hello-world layout. No login page, no settings, no sidebar, no markdown renderer.
- Migration tool from legacy data. Per [rebuild.md §9](../../rebuild.md), the cutover is empty-slate.
- Provider matrix, LiteLLM, Anthropic/Gemini SDKs, Ollama integration.
- Object storage; files (when added in M3) live in `MEDIUMBLOB`.
- Any modification to legacy `backend/`, `src/`, `pyproject.toml`, `package.json`, or `.buildkite/pipeline.yaml`.

## Open questions

The following are minor and do not block starting M0; flag them at the M0 review.

1. **ECR repo name for the rebuild image.** The pipeline assumes `container-build/data-platform/open-webui-rebuild` to keep the rebuild image distinct from legacy. If org policy prefers a single repo with separate tags (e.g. `open-webui:rebuild-<sha>`), update [rebuild/.buildkite/rebuild.yml](../.buildkite/rebuild.yml) accordingly.
2. **Trusted-name header URL-decoding semantics.** The legacy pattern silently swallows decode errors (lines 573–576 of [backend/open_webui/routers/auths.py](../../backend/open_webui/routers/auths.py)). We mirror that behaviour in M0; confirm at review whether a malformed name should instead 400.
3. **`@playwright/experimental-ct-svelte` Svelte 5 readiness.** As of writing, CT-Svelte's runes-mode support is experimental. If CT cannot render Svelte 5 components reliably during M0, the fallback is to keep CT on a placeholder Svelte 4-style component for the milestone and revisit when the package GA-releases Svelte 5 support. This does not affect E2E or unit coverage.
4. **Email-domain allowlist default.** [rebuild.md §3](../../rebuild.md) does not specify whether the proxy is expected to deliver only Canva emails or whether the app should still enforce a domain check. M0 ships an empty-list default (accept anything the proxy forwards) and exposes `TRUSTED_EMAIL_DOMAIN_ALLOWLIST` so the deploy pipeline can pin `canva.com` later. Confirm at the M0 review.
