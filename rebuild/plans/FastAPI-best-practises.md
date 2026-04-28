# FastAPI Best Practises

> **Audience:** every agent (and every human) writing a router, dependency, schema, or service under `rebuild/backend/app/` for the slim Open WebUI rebuild. This is the canonical "do / don't" list for FastAPI work in this project.
> **Authoritative parents:** [`rebuild.md`](../../rebuild.md), [`rebuild/plans/m0-foundations.md`](m0-foundations.md), [`rebuild/plans/database-best-practises.md`](database-best-practises.md). Where this file conflicts with those, those win and this file should be patched.
> **Pin:** **simplicity beats architectural purity, every time.** This is a five-feature internal tool, not a multi-tenant SaaS framework. If a guideline below would force you to add a layer for a single caller, an interface for a single implementation, or a config knob for a value that has never changed, escalate in PR rather than silently doing it. The whole point of the rebuild is to undo the "5,057-line `middleware.py`" and "4,165-line `config.py`" patterns from the legacy fork. Don't reintroduce them.
> **Scope:** general FastAPI / Python web hygiene (Section A), then the specific patterns this rebuild has locked (Section B), then patterns we have explicitly *declined* (Section C), then a checklist agents should mentally run through before opening a PR (Section D).
> **Tested against:** Python 3.12, FastAPI 0.115, Pydantic 2.9, Pydantic-Settings 2.6, SQLAlchemy 2.0.36, Starlette 0.41, httpx 0.27, uvicorn 0.32. Versions pinned in [`m0-foundations.md` § Dependencies](m0-foundations.md#dependencies-with-versions).

---

## A. General FastAPI engineering — universal dos and don'ts

These apply to **any** FastAPI codebase; if you're tempted to break one of them, escalate in PR.

### A.1 Project structure

**DO**

- **Organise by domain, not by file-type.** One package per business concept (`app/routers/chats.py`, `app/models/chat.py`, `app/schemas/chat.py`, `app/services/chat_stream.py`) — not one giant `app/routers.py` and one giant `app/models.py`. The Netflix-Dispatch pattern (each domain owns its router + schemas + service + dependencies) is the same shape and scales fine. The rebuild's layout in [`m0-foundations.md` § File and directory layout](m0-foundations.md#file-and-directory-layout) already follows this.
- **One file per ORM table.** `app/models/<table>.py` exports exactly one model class; `app/models/__init__.py` re-exports them so Alembic autogenerate finds the metadata. Keeps `git blame` honest and cuts merge conflicts during multi-PR feature work.
- **Mount each domain as its own `APIRouter`** (`app/routers/chats.py` exports `router = APIRouter(prefix="/api/chats", tags=["chats"])`). The application factory in `app/main.py` is the only place that knows about every router.
- **Single `/api` prefix, single API version, no `/v1`.** This is a locked decision (`rebuild.md` §4 / consistency report §C). The rebuild has one consumer (the SvelteKit frontend in this repo), so versioning the URL adds rollout coordination cost for zero compatibility benefit. If the API ever needs a breaking change post-cutover, we ship the new shape on a new path (`/api/chats2`) for the migration window — no `Accept-Version` headers, no parallel mounts.
- **Application factory in `app/main.py`.** Build the `FastAPI()` instance inside a `create_app()` function; `app/asgi.py` exports the result for uvicorn. Lets tests construct an isolated app per fixture without import-time side effects.

**DON'T**

- **Don't reach for the repository pattern as a separate layer until you have at least three callers of the same query.** Routers calling `await session.scalar(select(Chat).where(...))` directly is fine for one-shot CRUD. The legacy fork's mistake was the *opposite* — every model had a class-method DAO whether it was used once or fifty times, and the indirection didn't pay back. Promote a query into `app/repos/<table>.py` only when you'd otherwise duplicate it; the M1 `chat_stream.py` does this for `ChatRepo.get` (used by both the streaming path and the M4 automation executor) and that's exactly the threshold.
- **Don't add a service layer for routes that are straight CRUD.** `POST /api/folders` taking a body, validating ownership via a dependency, calling `session.add()`, and returning the row does not need an `app/services/folders.py`. A service file earns its place when it owns multi-step orchestration, transactional boundaries spanning multiple tables, or business invariants too complex for a Pydantic validator (e.g. `chat_stream.py`, `automation_executor.py`, `channels/messages.py`'s `create_bot_message` which has to also bump `channel.last_message_at` and emit a realtime event). Anything thinner is just bureaucracy.
- **Don't split a domain into eight micro-files** (`app/services/channels/{channels,members,messages,reactions,pins,webhooks,files,mentions}.py`) unless each genuinely owns ≥100 LOC of logic. If five of them are 20-line shims, they belong in one `services.py`. The M3 plan inherits this layout from the legacy fork's shape — confirm at implementation time which actually need their own file.
- **Don't introduce per-domain `BaseSettings` subclasses** ("Decouple Pydantic BaseSettings" in the public best-practises lists). The rebuild has one `Settings` class in `app/core/config.py` and that's enough at this scale; multiple settings classes only pay back when modules ship as separable libraries, which ours don't.

### A.2 Async vs sync routes (the single most common foot-gun)

**DO**

- **Use `async def` for I/O-bound work and `await` every I/O call.** Database queries (`await session.execute(...)`), HTTP calls (`await httpx_client.get(...)`), Redis (`await redis.get(...)`), file streams. The provider stream in M1 (`OpenAICompatibleProvider.stream`) and the SSE generator (`stream_chat`) are the canonical pattern.
- **Use plain `def` for genuinely-blocking work that has no async equivalent.** FastAPI runs `def` handlers in a Starlette threadpool, so a sync `requests.get(...)` inside a `def` route doesn't block the event loop the way it would inside an `async def` route. Prefer this over `asyncio.to_thread` wrappers for whole-route blocking work.
- **For one-off blocking calls inside an otherwise-async route, use `from fastapi.concurrency import run_in_threadpool`** (or `asyncio.to_thread` from Python 3.9+). Pattern: `await run_in_threadpool(blocking_function, arg1, arg2)`. The `MysqlFileStore.put` SHA-256 calculation in M3 falls into this bucket if the file is large enough that hashing visibly stalls the loop — but at the 5 MiB cap it's microseconds, so we don't bother.

**DON'T**

- **Don't call blocking I/O from inside an `async def` route.** No `requests.get(...)`, no `time.sleep(...)`, no sync SQLAlchemy `Session`, no `open(path).read()` for big files, no `subprocess.run(...)`. Every one of those freezes the entire event loop until it returns — the worker can't accept *any* requests in the meantime, including its own healthcheck. This is the single highest-leverage rule on the page; violations are an instant CPU-pinned outage.
- **Don't use `requests` anywhere under `app/`.** httpx (already a dep via the openai SDK) is the one HTTP client. Add `requests` to ruff's `flake8-tidy-imports` ban-list if you want belt-and-braces enforcement (low priority — the dep isn't even installed).
- **Don't use the synchronous `sqlalchemy.orm.Session` in routes.** The M0 baseline gives you `AsyncSession`; use it. The only legitimate sync-Session call site in the rebuild is Alembic migrations (which are sync by design), and even those go via the `op.*` helpers from M0.
- **Don't reach for CPU-bound work** (image processing, PDF rendering, ML inference, tokenizer batches over megabytes of text) **inside any route at all.** Push it to a worker process. The rebuild has no such workload today; if one appears in M3+ it gets its own pattern, not an `async def` containing a Pillow `resize()` call.

### A.3 Dependencies (FastAPI's DI is the cleanest tool in the box)

**DO**

- **Use `Annotated[T, Depends(...)]`** as the canonical syntax (Python 3.9+/FastAPI 0.95+):

  ```python
  from typing import Annotated
  from fastapi import Depends

  CurrentUser = Annotated[User, Depends(get_user)]
  DbSession = Annotated[AsyncSession, Depends(get_session)]

  @router.get("/api/me", response_model=UserRead)
  async def me(user: CurrentUser) -> User:
      return user
  ```

  Two wins: the parameter is a real type alias (mypy is happy) and the `Depends` is invisible at every call site. Define `CurrentUser`/`DbSession` aliases once in `app/core/deps.py` and import them everywhere.
- **Always make dependencies `async def`** unless they're a 3-line pure-Python compute. `async def get_user(...)` runs on the event loop with zero thread-switch overhead; `def get_user(...)` is sent to the threadpool, which costs more than the dependency saves on typical workloads.
- **Use `yield` for resource lifecycle** (DB session, file handles, Redis connection). The `try/finally` runs after the response is sent; SQLAlchemy's `async with AsyncSessionLocal() as session: yield session` handles commit/rollback/close correctly.
- **Use dependencies for cross-cutting validation that touches I/O** ("does this chat exist and belong to me?"). The result is cached for the request, so chaining `Depends(valid_chat_id)` into three other deps issues one DB query, not three. The M1 plan calls this out implicitly via `ChatRepo.get(...)` in `chat_stream.py`; the same shape generalises to a `valid_chat_id(chat_id: str, user: CurrentUser, db: DbSession) -> Chat` dependency that every chat route depends on.
- **Use `dependency_overrides` for tests** (`app.dependency_overrides[get_user] = lambda: fake_user`). Don't monkeypatch internals; FastAPI built this seam exactly so you wouldn't have to. Clear the override in a fixture teardown so it doesn't leak across tests.

**DON'T**

- **Don't put business logic in dependencies.** Validation, auth, resource lookup — yes. Mutating state, calling external services, anything you wouldn't want to silently retry on the next route — no. The dependency runs *before* the route body starts; logging "user opened a chat" inside `valid_chat_id` will fire on every metadata-PATCH and every read.
- **Don't forget the `Depends()` wrapper.** `chat: Chat = Depends(valid_chat_id)` works; `chat: Chat = valid_chat_id` is a query-parameter declaration and FastAPI will return a 422 telling you `chat_id` is required as a query string. The `Annotated` form makes this almost impossible to typo.
- **Don't reach for class-based dependencies for stateless lookups.** The M3 socket.io connect handler does its own user lookup (because it's not in HTTP-route land); HTTP routes get a function-based `get_user` and that's the contract.

### A.4 Pydantic schemas

**DO**

- **Always declare an explicit `response_model` on every route.** Two wins: it's the contract documented in OpenAPI, and FastAPI strips fields not in the model (defence-in-depth against accidentally exposing an internal column). Pair with `status_code=` and a one-line `description=` so the auto-generated docs are usable.
- **Use Pydantic v2 `model_config = ConfigDict(extra="forbid")` on every request body schema.** Strict-by-default catches typo'd fields (`{"acrhived": true}` → 422 instead of silently ignored). The M1 `History` model already does this; do the same on `ChatPatch`, `FolderCreate`, `MessageSend`, `AutomationCreate`, etc. Inherit from a `StrictModel(BaseModel)` base if you find yourself writing the config dict on more than three classes.
- **Use Pydantic types for validation, not bare `str`/`int`.** `EmailStr`, `AnyUrl`, `Field(min_length=1, max_length=128)`, `Field(ge=0, le=200)`. Free input validation, free OpenAPI, free 422 on bad shapes — all the things you'd otherwise re-implement with `if not email or "@" not in email: raise HTTPException(...)` blocks.
- **Validate enumerations with `Literal[...]` or `StrEnum`** rather than `str` + a runtime check. `status: Literal["pending", "running", "success", "error"]` shows in OpenAPI as a dropdown and rejects bad values at parse time.
- **Use `field_validator` / `model_validator` for cross-field invariants.** "Exactly one of `target_chat_id`/`target_channel_id` is set" (M4) is a Pydantic root validator *plus* a DB CHECK constraint — the validator fires first and gives the user a 422 with a readable message; the CHECK is the safety net.
- **Use `from __future__ import annotations`** at the top of every model file. Lets you use `User | None` instead of `Optional[User]`, dict[str, Any] instead of `Dict[str, Any]`, and forward references without the string quotes.

**DON'T**

- **Don't return raw `dict` from routes when a response model exists.** Return the Pydantic model instance (`return ChatRead(...)`) — FastAPI still re-validates against `response_model`, so you pay the round-trip either way; returning the model gets you static-type checking too.
- **Don't share one Pydantic class for "create" / "read" / "update" by making half the fields optional.** Three small classes (`ChatCreate`, `ChatRead`, `ChatPatch`) is clearer than one with seven optional fields and three different sets of "what does None mean?" rules.
- **Don't put heavy logic in `field_validator`.** Database calls, network requests, expensive parsing — those belong in dependencies or services. Validators run during request parsing on the event loop and have no async escape hatch.
- **Don't use Pydantic v1 syntax in new code.** No `class Config:` inner classes (use `model_config = ConfigDict(...)`); no `@validator` (use `@field_validator` / `@model_validator`); no `.dict()` (use `.model_dump()`); no `.json()` (use `.model_dump_json()`). Pydantic 2.9 is the floor (locked in M0).

### A.5 Application lifecycle

**DO**

- **Use the `lifespan` async context manager**, not `@app.on_event("startup")` / `@app.on_event("shutdown")` (deprecated since FastAPI 0.93):

  ```python
  from contextlib import asynccontextmanager

  @asynccontextmanager
  async def lifespan(app: FastAPI):
      app.state.engine = create_async_engine(settings.DATABASE_URL, ...)
      app.state.redis = redis.from_url(settings.REDIS_URL)
      app.state.provider = OpenAICompatibleProvider()
      app.state.scheduler = AsyncIOScheduler()
      app.state.scheduler.add_job(automation_tick, "interval", seconds=30, id="automation_tick", max_instances=1, coalesce=True)
      app.state.scheduler.start()
      yield
      app.state.scheduler.shutdown(wait=False)
      await app.state.redis.aclose()
      await app.state.engine.dispose()

  app = FastAPI(lifespan=lifespan)
  ```

  All shared singletons (engine, Redis client, provider instance, scheduler) live on `app.state`. Routes reach them via a small dependency (`def get_provider(request: Request) -> Provider: return request.app.state.provider`).
- **Initialise everything inside `lifespan`, not at module import time.** Module-level `engine = create_async_engine(...)` ties the connection to the import — when uvicorn forks workers, every fork gets its own connection from the same socket and you get the classic "BlockingIOError: Resource temporarily unavailable" cascade. Per-process initialisation in `lifespan` is fork-safe.
- **`pool_pre_ping=True` and `pool_recycle=1800`** on the async engine. Pre-ping catches connections the DB has dropped behind your back; recycle stops MySQL's `wait_timeout` from killing a long-lived idle pooled connection. Both are already in M0's `Settings` defaults.

**DON'T**

- **Don't use `@app.on_event(...)`.** Deprecated; will be removed in a future FastAPI. New code uses `lifespan` exclusively.
- **Don't forget to dispose the engine on shutdown.** `await engine.dispose()` returns connections to the OS; without it, graceful shutdown can hang for the connection's `pool_timeout` waiting on releases that already happened.

### A.6 Database session per request

**DO**

- **One `AsyncSession` per HTTP request, scoped via a `yield` dependency:**

  ```python
  # app/core/db.py
  AsyncSessionLocal = async_sessionmaker(
      app.state.engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
  )

  async def get_session() -> AsyncIterator[AsyncSession]:
      async with AsyncSessionLocal() as session:
          yield session
  ```

  The `async with` context manager handles commit/rollback/close — don't add a manual `await session.close()` after it (double-close puts the connection into a limbo state and slowly exhausts the pool).
- **`expire_on_commit=False`.** SQLAlchemy 2's default expires every attribute on commit, which means accessing `chat.title` after `await db.commit()` re-queries the row. With async, that re-query happens lazily *outside* the session's `async with` and explodes with `MissingGreenlet`. Set `expire_on_commit=False` and the loaded attributes stay readable post-commit. This is the canonical async SQLAlchemy gotcha and the fix is one parameter.
- **`autoflush=False`** for the same family of reasons. Implicit flushes during a `select()` can fire DB writes mid-async-context in surprising places; explicit `await session.flush()` when you actually need it.
- **Use SQLAlchemy 2.0's `select()` API**, not the legacy `session.query(...)`. `await session.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id))`. The legacy API works but is deprecated and the async story is awkward.
- **Use `async with session.begin():` for multi-statement transactions** that must be atomic. Single `select` / `insert` / `update` calls don't need it — SQLAlchemy auto-wraps them in a transaction that commits when the dependency teardown hits.
- **Bound the pool.** `DB_POOL_SIZE=10`, `DB_POOL_MAX_OVERFLOW=5` are M0 defaults. With 4 uvicorn workers per pod and 4 pods, that's `(10+5) * 4 * 4 = 240` potential connections — comfortable inside a managed MySQL's typical 500-connection cap, with headroom for the migration job and the on-call's REPL.

**DON'T**

- **Don't share an `AsyncSession` across requests.** Sessions hold transactional state, identity-map caches, and a connection from the pool; sharing them is a recipe for stale reads and silently committed work from another request. One per request, scoped by `yield`.
- **Don't call `session.close()` explicitly inside the dependency body** when you've used `async with AsyncSessionLocal()`. The context manager already does it; calling it again leaves the pool slot in a half-released state.
- **Don't open a transaction, then call an external API, then commit.** Network calls inside `BEGIN ... COMMIT` hold the row lock for the full duration of the call (which can be 30 seconds for the model gateway). Pattern: gather state, commit, *then* call the external service. The M1 streaming flow follows this — the user message is committed before the SSE generator reaches `provider.stream(...)`.
- **Don't hand out the same `AsyncSession` to a `BackgroundTasks` callback.** The session is closed by the time the task runs. If you need DB access in a background task, open a fresh session inside the task body.

### A.7 Streaming responses (SSE)

**DO**

- **Use Starlette's `StreamingResponse`** with an `async generator` yielding `bytes`:

  ```python
  return StreamingResponse(
      stream_chat(chat_id=chat_id, user=user, body=body, db=db, registry=registry),
      media_type="text/event-stream",
      headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
  )
  ```

  `X-Accel-Buffering: no` defeats nginx's response buffering so tokens reach the client as they're produced.
- **Handle `asyncio.CancelledError` inside the generator** to persist any in-flight state and unwind cleanly. Starlette raises it on client disconnect; re-raise after cleanup so the framework knows the response ended on a cancel. M1's `stream_chat` is the reference implementation for this — copy the pattern when adding new SSE endpoints.
- **Send a heartbeat comment frame every ~15 s** (`yield b": keep-alive\n\n"`) during quiet stretches. Reverse proxies often drop idle connections at 60 s; 15 s gives you 4× headroom.
- **Bound the whole stream with `asyncio.wait_for(...)` at a project-wide cap.** `SSE_STREAM_TIMEOUT_SECONDS = 300` (M5). On exceedance, persist the partial state, emit a terminal `timeout` SSE event, and return — don't let the generator hang forever.
- **Persist incrementally inside the loop**, not just at the end. M1 commits the in-progress assistant content every ~1 s so a server crash doesn't lose minutes of streaming. The cost is one extra `UPDATE` per second per active stream — negligible compared to the user experience win.

**DON'T**

- **Don't open a fresh `AsyncSession` inside the generator that's different from the one passed in by the dependency.** The `db` from `Depends(get_session)` lives for the whole request, including the streaming body — that's exactly what you want.
- **Don't `await request.is_disconnected()` on a hot loop.** It's relatively cheap but it does work; check it once per chunk or once per second, not on every byte. M1 doesn't even bother — it relies on `CancelledError` propagation, which is more reliable.
- **Don't build huge intermediate strings** (`"".join(accumulated)` once per chunk inside a 1k-token stream is `O(n²)` allocation). Append to a list and join at persist points only.

### A.8 Background work (BackgroundTasks vs scheduler vs queue)

**DO**

- **Use FastAPI's `BackgroundTasks` for fire-and-forget work that's safe to lose** (logging, sending an email, refreshing a small cache). Tasks run after the response is sent, in the same worker process.
- **Use APScheduler with `SELECT ... FOR UPDATE SKIP LOCKED` for scheduled or recurring work** that has to survive a worker restart. M4 is the reference implementation; the same pattern fits any future "fire every N minutes / check this state on a schedule" need.
- **Use `asyncio.create_task(...)` from inside an `async def` route** when you want to spawn a long-running task that the request itself doesn't wait on but still belongs to this process (e.g. M3's `@model` channel auto-reply). Wrap with a per-channel `Semaphore` so you can't spawn unbounded coroutines. **Always** keep a strong reference to the task (otherwise the GC eats it mid-flight) — store it in the per-channel registry that already owns the cancellation token.

**DON'T**

- **Don't put work in `BackgroundTasks` that someone would page you about if it failed.** No retries, no persistence, no visibility into failures beyond a stderr log line. Anything more important than that belongs in APScheduler-with-DB or a real task queue.
- **Don't introduce Celery, RQ, or arq.** The rebuild's only durable scheduled work is M4 automations, and APScheduler + `SKIP LOCKED` covers it without adding a broker, a worker pool, or a new operational surface (`rebuild.md` §0). Revisit only if a workload appears that genuinely needs cron-with-retries-and-backoff and isn't a fit for the scheduler tick pattern.
- **Don't fire `asyncio.create_task(...)` without a strong reference.** Bare `asyncio.create_task(go())` with the return value discarded is at the mercy of the garbage collector. Pin it in a registry; `await` or cancel it deliberately.

### A.9 Errors and exception handling

**DO**

- **Use FastAPI's `HTTPException(status_code=..., detail=...)`** for client-visible errors. Wrap once at the boundary (route or dependency); don't sprinkle `try/except HTTPException` inside service code.
- **Define a small set of custom exception classes for domain errors** (`ChatNotFound`, `NotChatOwner`, `ProviderError`) and a single `app.add_exception_handler(...)` per class that maps each to an `HTTPException`. Keeps service code free of HTTP knowledge.
- **Return a stable error envelope.** The rebuild uses `{"detail": "<msg>", "code": "<machine_code>"}` (M3 §API surface). Keep that shape consistent across routers — the frontend reads `code` for branching, `detail` for display.
- **404, not 403, for "you can't see this resource."** The M2 plan codifies this for sharing — non-owners get `404` to avoid leaking existence. Apply the same rule everywhere unless the spec mandates otherwise.

**DON'T**

- **Don't reach for RFC 9457 (`application/problem+json`) error envelopes.** They're a legitimate standard but the rebuild has one consumer (our own SvelteKit frontend) and the simpler `{detail, code}` shape is already the contract across the plans. RFC 9457 only pays back when third parties consume the API and you want machine-readable error categorisation; we don't have that audience.
- **Don't catch `Exception` broadly** in route bodies. Let unhandled errors propagate to FastAPI's default 500 handler (which logs the traceback and returns a clean `{"detail": "Internal Server Error"}`). Catching everything just to log "something broke" hides bugs that should reach Sentry/Datadog.
- **Don't put stack traces in user-visible error responses.** OWASP basics. The default 500 handler already gets this right; don't override it to "include the traceback for easier debugging" because someone will paste a prod traceback into a slack channel some day.

### A.10 Middleware

**DO**

- **Order middleware deliberately and outermost-first.** FastAPI / Starlette runs `add_middleware(...)` in reverse-add order on the request path: the *last* middleware added is the *first* to see an incoming request. The right order for the rebuild is, from outermost to innermost: (1) `TrustedIpMiddleware` (M5 — strips spoofed `X-Forwarded-Email` from non-allowlisted source IPs), (2) `CorrelationIdMiddleware` (M5 — assigns a request UUID for log correlation), (3) `CORSMiddleware` (so preflight OPTIONS succeeds before auth runs), (4) `SecurityHeadersMiddleware` (M5 — adds CSP, HSTS, etc.), (5) `TimeoutMiddleware` (M5 — per-route `asyncio.wait_for`), (6) anything else custom. To get this order in code, `add_middleware` them in the **reverse** sequence inside `create_app()`. Comment the order at the call site so the next agent doesn't reshuffle.
- **Keep middleware bodies tiny.** Anything heavy (logging, metrics, traces) goes through OTel's instrumented hooks (M5), not custom middleware. Custom middleware is for cross-cutting *correctness* (header stripping, timeouts), not observability.
- **Use `BaseHTTPMiddleware` only when you need the full Starlette middleware contract.** For pure request-mutating logic, an `ASGI` `__call__` is faster (no Starlette overhead) but harder to read. M5's `TrustedIpMiddleware` is `BaseHTTPMiddleware` for clarity; that's the right default.

**DON'T**

- **Don't put auth in middleware.** Auth lives in the `get_user` dependency where it can be overridden in tests, where it can return a typed `User`, and where individual routes can opt out (`/healthz`, `/readyz`, `/api/webhooks/incoming/...`). A middleware-level `if not request.headers.get("X-Forwarded-Email"): raise 401` looks tidy until the first route that needs to skip it.
- **Don't wrap every route in a `try/except` middleware to "centralise error handling".** That's what `app.add_exception_handler(...)` is for; the middleware version intercepts traces and breaks request scope semantics.

### A.11 Testing

**DO**

- **Use `httpx.AsyncClient` with `ASGITransport`** for async integration tests:

  ```python
  @pytest.fixture
  async def client(app) -> AsyncIterator[AsyncClient]:
      async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
          yield ac
  ```

  Don't use `TestClient` for async-heavy code (it spins up its own thread + event loop and the boundaries trip up SSE / WebSocket / streaming tests).
- **Override dependencies for tests via `app.dependency_overrides[dep] = fake`.** Auth, model provider, file store — all overridable. Clear the dict in a fixture teardown so the override doesn't leak.
- **Spin up a real MySQL via `testcontainers-mysql` for integration tests** (M0 already wires this). Don't substitute SQLite — it's missing JSON path operators, generated columns, FK CHECK semantics, and `SELECT FOR UPDATE SKIP LOCKED`. Every one of those features is exercised by the rebuild.
- **Mock the model gateway with cassettes** (M1 / M4 plans). A recorded SSE stream replayed deterministically is the only sane way to test streaming end-to-end without a real upstream.
- **Use `pytest-asyncio` with `asyncio_mode = "auto"`** (M0 default) so you don't have to decorate every async test.

**DON'T**

- **Don't test by importing the route function and calling it directly.** You bypass dependency resolution, request body parsing, response model validation — the things tests are supposed to exercise. Always route through a client.
- **Don't share state between tests via module-level mutable globals.** Per-test fixtures with proper teardown. The "test bleed" failure mode is the one bug class that scales worst with codebase size.

### A.12 Logging and observability

**DO**

- **Use the standard library `logging` module** with a JSON formatter in prod (`LOG_FORMAT=json`) and a human formatter in dev. M5 ships the formatter wiring; new modules just `log = logging.getLogger(__name__)` and use it.
- **Log at the right level.** `INFO` for one-line-per-request route summaries; `WARNING` for retryable failures; `ERROR` for unhandled exceptions; `DEBUG` for verbose trace material that's off in prod. No `print(...)` anywhere.
- **Always include a `correlation_id` (M5) and the OTel `trace_id` / `span_id` in every log line.** Done automatically by the M5 logger config; just don't fight it by configuring a second logger.

**DON'T**

- **Don't log PII.** Emails are tagged `pii: email` in the M5 formatter so the log pipeline can drop them; never put them in span attributes (use the SHA-256 hash). Never log webhook tokens or share tokens — the regex redaction filter is a backstop, not a substitute for not writing them in the first place.
- **Don't log every successful 200.** FastAPI/uvicorn already emits an access log per request; a second app-level "got chat 200" is just noise. Reserve INFO logs for events the on-call would actually care about.

### A.13 Deployment

**DO**

- **Run uvicorn with multiple workers** in prod (`uvicorn app.asgi:app --workers $WORKERS`), or wrap with `gunicorn -k uvicorn.workers.UvicornWorker -w $WORKERS` if you need gunicorn's process-supervision features. The Helm chart in M5 picks one; `WORKERS = (2 * cpu_cores) + 1` for an I/O-bound workload is the standard formula. The rebuild is I/O-bound, so the formula applies.
- **Initialise the engine, Redis client, scheduler in `lifespan`, not at import time** (re-stating §A.5) — fork-safe per-worker initialisation matters more here than in any other section.
- **Healthcheck `/healthz` is dependency-free**; `/readyz` pings DB + Redis with a per-call timeout. Orchestrator readiness probe routes traffic only when `/readyz` is 200; liveness uses `/healthz`. M0 ships both.

**DON'T**

- **Don't enable `--reload` in production.** Watches the filesystem; pointless and slow under prod load.
- **Don't terminate TLS at uvicorn.** Reverse proxy / ingress (nginx / Envoy / k8s Ingress) does that. Uvicorn speaks plain HTTP behind it.

---

## B. Patterns this rebuild has locked

The patterns below are *project-wide*, locked in `rebuild.md` and the milestone plans. New code adopts them by default; deviations require an explicit "we're going off-pattern because…" comment in the PR.

### B.1 Trusted-header auth, no JWT

The single auth dependency is `get_user(request) -> User` (`m0-foundations.md` § Trusted-header dependency). It reads `X-Forwarded-Email`, optionally checks against a domain allowlist, looks up the row by email, auto-creates if missing via `INSERT ... ON DUPLICATE KEY UPDATE`, and returns. Total surface: ~30 LOC.

Routes inject it via `Annotated[User, Depends(get_user)]`. No JWT, no cookies, no API keys, no session table — these are explicitly declined (`rebuild.md` §3). Webhook ingress (`POST /api/webhooks/incoming/{webhook_id}`) is the *only* unauthenticated path and validates a hashed token in its handler.

The trusted-IP allowlist enforcement (`TRUSTED_PROXY_CIDRS`, M5) sits in a middleware *outside* the auth dep, so a misconfigured ingress can't leak header injection.

### B.2 One pattern for IDs, one for time

- IDs: `from app.core.ids import new_id` returns a UUIDv7 string. Stored as `String(36)` (`VARCHAR(36)`) on every PK and FK. Never `uuid.uuid4()`; never `CHAR(36)`. (See `database-best-practises.md` §B.2 for the locked rationale.) Ruff bans `uuid4` calls under `app/`.
- Time: `from app.core.time import now_ms` returns `int(time.time_ns() // 1_000_000)`. Stored as `BIGINT` on every timestamp column. Never `datetime`, never `DATETIME`, never seconds. JSON serialises the same integer.

Both helpers exist precisely so the test suite can monkeypatch a single symbol to freeze time / pin a deterministic id. New code uses the helpers; tests of the helpers themselves are exempt.

### B.3 Single `Settings(BaseSettings)`

`app/core/config.py` exports one `Settings` instance, loaded from env vars + `.env`, immutable after import. New env vars get added to the table in `m0-foundations.md` § `Settings(BaseSettings)`. No per-domain settings classes; no `lru_cache` wrapper indirection (the import-time singleton is the cache).

`SecretStr` for any secret — keeps it out of accidental log lines.

### B.4 Single `OpenAICompatibleProvider` instance

The provider is constructed in `lifespan` and stored on `app.state.provider`. Routes get it via a tiny dep:

```python
def get_provider(request: Request) -> OpenAICompatibleProvider:
    return request.app.state.provider

Provider = Annotated[OpenAICompatibleProvider, Depends(get_provider)]
```

Single instance per worker. No provider matrix, no LiteLLM, no second provider class. The OpenAI SDK is just transport.

### B.5 Service layer only where it earns its keep

The rebuild has services where the work is genuinely complex; everything else is router-direct.

- **Has a service file:** `app/services/chat_stream.py` (multi-step streaming + persistence + cancellation), `app/services/chat_writer.py` (shared writer used by M1 streaming and M4 chat-target writes), `app/services/scheduler.py` + `app/services/automation_executor.py` (M4 — separable so the tick logic is unit-testable in isolation), `app/services/channels/messages.py` (M3 — `create_bot_message` etc. own the `last_message_at` denorm + realtime emit pairing that M4 also calls into), `app/services/auto_reply.py` (M3 — semaphore-bounded background tasks).
- **Doesn't need one:** chat CRUD, folder CRUD, share endpoints, share/unshare, file upload, file download, channel CRUD, channel member operations, reactions, pins, automation CRUD. These all live in `app/routers/<x>.py` and call the session directly.

Promoting a router function into a service is fine when (a) a second caller appears, (b) the function exceeds ~80 LOC of orchestration, or (c) it spans multiple tables under one transactional invariant. Otherwise leave it in the router.

### B.6 Realtime (`python-socketio`) goes through one module

M3's `app/realtime/sio.py` owns the `AsyncServer` instance, the connect-time auth, and the room joining. Service helpers (`channels/messages.py::create_bot_message`) call `app.realtime.events.emit_message_create(...)` after persisting; **routers and other services never `sio.emit(...)` directly** (the persistence/emit pairing only stays consistent if every channel write goes through the service). M4's automation executor honours this (called out in its plan); future code must too.

### B.7 Migrations through helpers, never bare `op.*`

Every Alembic revision uses the M0 `*_if_not_exists` / `*_if_exists` helpers. CI grep-gates bare `op.create_*` / `op.drop_*` / `op.add_column` calls in `backend/alembic/versions/`. (`rebuild.md` §9.) See `database-best-practises.md` §A.4 for the full list of dos and don'ts.

### B.8 Test stack: Vitest + Playwright on the FE, pytest + httpx + testcontainers on the BE

`asyncio_mode = "auto"` in `pyproject.toml`. `testcontainers[mysql]` for any test that touches the DB. `respx` (or the cassette mock) for any test that touches the model gateway. `app.dependency_overrides` for swapping `get_user` and the file store; never monkeypatch internals.

---

## C. Patterns we have explicitly declined (and why)

When something below comes up in code review, point at this section.

| Pattern | Status | Reason | Where to revisit |
|---|---|---|---|
| Repository pattern as a separate per-table layer | Declined | The legacy fork's `Chats.get_by_id_and_user_id(...)` style added an indirection per table that paid back only when a query had ≥3 callers. Rebuild promotes a query into `app/repos/<x>.py` only when that threshold is hit (currently: `ChatRepo.get` only). | When >3 routes/services share a query |
| Per-domain `BaseSettings` subclasses | Declined | One global `Settings` is fine at this scale; multiple settings classes cost more in import-graph complexity than they save in module isolation. | If we ever ship a module as a separable library |
| RFC 9457 `application/problem+json` errors | Declined | One frontend consumer; the `{detail, code}` envelope already documented across M3/M4 is the contract. RFC 9457 pays back when third parties consume the API. | If a third-party API consumer ever appears |
| `slowapi` for rate limiting | Declined | Per-IP keying is useless behind the OAuth proxy (every request looks like one IP). M5 ships a ~120-line custom Redis-Lua sliding-window limiter keyed on `X-Forwarded-Email`; cheaper than shoehorning `slowapi` into a token-cost bucket. | Never |
| Class-based dependencies | Default avoid | Function-based deps with `Annotated` are clearer for stateless lookups (auth, resource validation). Class-based deps earn their place only when there's genuine per-request state to hold. | Per-route, with justification |
| Celery / RQ / arq / Dramatiq | Declined | Only durable scheduled workload is M4 automations; APScheduler + `SELECT ... FOR UPDATE SKIP LOCKED` covers it without a broker. | If a workload appears that needs cron + retry + DLQ |
| Multiple `FastAPI` instances mounted as sub-apps | Declined | Single application, single OpenAPI doc, single auth boundary. Sub-apps complicate startup, lifespan, dependency resolution, and OpenAPI generation. | Never at this scale |
| API versioning in the URL (`/api/v1`) | Declined | One in-house consumer; breaking changes ship as `/api/chats2`-style new paths during a coordinated rollout, not as `/v2/`. | If the API ever becomes a public product |
| Request body in `GET` | Declined | Spec-illegal in HTTP, broken by some proxies, breaks client-side caching. Use query params or convert to `POST`. | Never |
| `@app.on_event("startup")` / `@app.on_event("shutdown")` | Declined | Deprecated since FastAPI 0.93; use `lifespan` (§A.5). | Never |
| Pydantic v1 syntax in new code | Declined | Pydantic 2.9 floor (`pyproject.toml`); v1 syntax (`Config` inner class, `@validator`, `.dict()`, `.json()`) is silently deprecated and will go away. | Never |
| Returning raw `dict`s from routes | Default avoid | Defeats `response_model` strict-shape guarantees and doubles serialisation cost (FastAPI revalidates anyway). Return Pydantic instances. | Internal admin/debug routes only |
| Sync DB driver under `app/` | Declined | Async-only; sync `Session` blocks the event loop and serialises every other request behind it. Alembic is the only sync caller (and it's outside `app/`). | Never |
| `requests` library | Declined | httpx is the one HTTP client (already a transitive dep via openai). | Never |
| Per-route logging middleware | Declined | OTel + uvicorn access logs already provide per-request observability; an app-level middleware that logs every 200 is noise + 1× CPU per request. | Never |
| Nested settings via `env_nested_delimiter` | Declined | Single flat `Settings` class with `LIST_OF_THINGS: list[str]` parsed from CSV is enough; nested settings are only useful if you have ≥5 logical config groups. | Never at this scale |
| Custom `JSONResponse` subclasses for performance | Declined | FastAPI's default Pydantic-backed response already uses `pydantic-core` (Rust); switching to `orjson` or `ujson` doesn't move the needle for our payload sizes. | Per-route, only with a benchmark |

---

## D. Pre-PR checklist for agents

Before opening a PR that adds or changes a router, dependency, schema, or service, run through this list. Don't tick a box you don't believe.

**New route**

- [ ] Lives under `app/routers/<domain>.py`; the router is mounted in `app/main.py` exactly once.
- [ ] Function is `async def` (unless it does only blocking I/O for which there's no async equivalent — then plain `def`).
- [ ] All I/O calls are `await`ed; no `requests`, no sync `Session`, no `time.sleep`, no blocking file ops.
- [ ] `Annotated[T, Depends(...)]` for every dependency; never bare `Depends()` in the parameter default.
- [ ] `response_model=` set; `status_code=` set when not 200; one-line `description=` for the OpenAPI doc.
- [ ] Auth: `Annotated[User, Depends(get_user)]` (or webhook token validation for ingress).
- [ ] Errors via `HTTPException` or a custom exception with a registered handler; never returns a `dict` with an `error` key.
- [ ] Pagination: cursor-based, not OFFSET. (`database-best-practises.md` §A.3.)
- [ ] `LIMIT` is set on every query that could ever return >1 page.
- [ ] No N+1 — joins, batched IN, or eager loads (`selectinload`).

**New dependency**

- [ ] `async def` (unless it's a 3-line pure compute).
- [ ] Validates one thing well; doesn't mutate state.
- [ ] If it loads a row, returns the typed model (not a dict).
- [ ] Uses `yield` if it acquires a resource; the `try/finally` releases it.

**New Pydantic schema**

- [ ] `from __future__ import annotations` at file top.
- [ ] `model_config = ConfigDict(extra="forbid")` on request bodies.
- [ ] Uses `Field(...)` constraints (`min_length`, `max_length`, `ge`, `le`, `pattern`) where applicable.
- [ ] Uses `EmailStr`, `AnyUrl`, `Literal[...]`, etc. instead of bare `str`.
- [ ] No `class Config:`; no `@validator`; no `.dict()` / `.json()` (Pydantic v1 forms).
- [ ] Cross-field invariants in `@model_validator`, not in the route body.

**New service / module**

- [ ] Earns its place: ≥80 LOC of orchestration, ≥3 callers of a query, or a multi-table transactional invariant. If none of those, inline it in the router.
- [ ] No HTTP knowledge inside the service (no `HTTPException`, no `status_code`); raise domain exceptions and let a registered handler map them.
- [ ] Takes its `AsyncSession` as a parameter; doesn't open its own session unless it's a background task that survives the request.
- [ ] Realtime emit (M3+) goes through `app.realtime.events.emit_*`, not direct `sio.emit(...)`.

**New `lifespan` hook**

- [ ] Initialises in the body before `yield`; cleans up after.
- [ ] Stores the resource on `app.state.<name>`.
- [ ] Has a small `def get_<name>(request) -> <Type>` accessor in the same module.
- [ ] On shutdown, gracefully stops/closes/disposes (`await scheduler.shutdown(wait=False)`, `await redis.aclose()`, `await engine.dispose()`).

**New test**

- [ ] Async — `httpx.AsyncClient` with `ASGITransport`; never `TestClient` for SSE/WebSocket/streaming.
- [ ] Overrides `get_user` (and any external-service dep) via `app.dependency_overrides`; clears it on teardown.
- [ ] Uses the testcontainer-MySQL fixture for any DB-touching path; never SQLite.
- [ ] Asserts on the response body shape, not just `resp.status_code == 200`.
- [ ] One assertion per behaviour; long stacked assertions are anti-debugging.

**Background work**

- [ ] If it's safe-to-lose: `BackgroundTasks` is fine.
- [ ] If it's recurring or must survive a restart: APScheduler + `SELECT ... FOR UPDATE SKIP LOCKED` (M4 pattern).
- [ ] If it's an in-process spawn (`@model` reply): `asyncio.create_task(...)` with the task pinned in a registry so the GC can't eat it; bounded by a `Semaphore`.

**Deploy / config**

- [ ] New env var added to `Settings` in `app/core/config.py`, with a default that makes sense in dev and an explicit value in `values-prod.yaml`.
- [ ] `SecretStr` if it's a secret.
- [ ] CSV-parsed `list[str]` for list-shaped values; no JSON-in-env-var.

---

## E. References

- [`rebuild.md`](../../rebuild.md) — top-level locked decisions (especially §3 auth, §9 datatypes/migrations, §10 layout).
- [`rebuild/plans/m0-foundations.md`](m0-foundations.md) — `Settings`, `get_user`, `get_session`, lifespan, migration helpers, ruff/mypy config, test scaffolding.
- [`rebuild/plans/m1-conversations.md`](m1-conversations.md) — the canonical example of a streaming endpoint, a service module, and per-domain Pydantic schemas with `extra="forbid"`.
- [`rebuild/plans/m3-channels.md`](m3-channels.md) — service/realtime split, mention parser, file upload + streaming download.
- [`rebuild/plans/m4-automations.md`](m4-automations.md) — APScheduler + `SKIP LOCKED` background work, lifespan-hosted scheduler, run-now inline path, test-only endpoint gated by `settings.ENV`.
- [`rebuild/plans/m5-hardening.md`](m5-hardening.md) — middleware ordering, OTel hooks, per-route timeouts, rate-limit dependency factory, deploy pipeline.
- [`rebuild/plans/database-best-practises.md`](database-best-practises.md) — sister document covering everything DB-shaped.

External:

- FastAPI tutorial: https://fastapi.tiangolo.com/tutorial/
- FastAPI advanced: https://fastapi.tiangolo.com/advanced/ (lifespan, middleware, SSE, async tests)
- Pydantic v2: https://docs.pydantic.dev/latest/
- Pydantic Settings: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
- SQLAlchemy 2 async: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- Starlette middleware: https://www.starlette.io/middleware/
- python-socketio: https://python-socketio.readthedocs.io/en/latest/server.html
- APScheduler: https://apscheduler.readthedocs.io/en/3.x/
- httpx: https://www.python-httpx.org/
- The widely-cited FastAPI best-practices repo: https://github.com/zhanymkanov/fastapi-best-practices (treat as one opinion among many; the rules above are this project's house style and where they conflict, this file wins).
