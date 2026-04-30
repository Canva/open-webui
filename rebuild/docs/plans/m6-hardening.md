# M6 — Hardening + deploy

## Goal

Take the rebuild from "feature complete on a developer laptop" to "running in production at Canva-internal scale, with the OAuth proxy pointed at it and the legacy service decommissioned." This milestone delivers observability (OpenTelemetry traces, metrics, and structured JSON logs), per-user rate limits and per-route timeouts, security hardening for the trusted-header auth boundary, the Buildkite deploy pipeline, and an end-to-end cutover runbook. Per `rebuild.md` section 9, **no data migration tool is built**: the new app launches with empty MySQL and Redis. Users start fresh on chats, channels, and automations. The legacy fork remains accessible read-only at `archive.openwebui.canva-internal.com` for 30 days as a reference, then the DB snapshot is retained per Canva's standard retention policy and the service is decommissioned. There is no parallel-run period and no per-team rollout — a single big-bang proxy switch on cutover day.

## Deliverables

- `rebuild/backend/app/observability/` package: OTel bootstrap (`otel.py`), structured JSON logger (`logging.py`), correlation-id middleware (`middleware.py`), and ASGI/SQLAlchemy/socket.io instrumentation glue.
- New env vars wired through `Settings` for observability: `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES`, and `LOG_FORMAT` (`json` in prod, `text` in dev). `LOG_LEVEL` already exists from M0 (`m0-foundations.md` §Settings) and is not redeclared. The full list of M6-introduced backend settings (the rate-limit, trusted-proxy, and file-upload knobs added in later sections) is collected in [§ Settings additions](#settings-additions) below so M0's settings table stays the canonical reference. The launch banner is owned by SvelteKit as a `PUBLIC_LAUNCH_BANNER_UNTIL` env var (frontend-only, not part of `Settings`); per-route HTTP timeouts are not env-driven (constants on the route declarations).
- `rebuild/backend/app/security/` package: trusted-IP allowlist middleware (`trusted_ip.py`), security-headers middleware (`headers.py`), CORS configuration helper, MIME/extension sniffer used by the file upload endpoint.
- `rebuild/backend/app/ratelimit/` package: Redis-backed sliding-window limiter, FastAPI dependency, and three configured buckets (chat completions, file uploads, webhook ingress).
- `rebuild/.buildkite/rebuild.yml` build/test/push/deploy pipeline (path-filtered to `rebuild/**`), with stages `lint → test → build → push → deploy-staging → smoke → deploy-prod`.
- `rebuild/infra/k8s/` Helm chart skeleton: `Chart.yaml`, `values.yaml`, `values-staging.yaml`, `values-prod.yaml`, templates for `Deployment`, `Service`, `Ingress`, `HorizontalPodAutoscaler`, `PodDisruptionBudget`, `NetworkPolicy`, `ConfigMap`, `Secret` (sealed-secret refs), two `ServiceAccount` objects (`openwebui-rebuild` runtime / `openwebui-rebuild-migrate` Job), and a one-shot `Job` for `alembic upgrade head`. Both `ServiceAccount`s carry the `eks.amazonaws.com/role-arn` annotation that binds them to the matching Aurora IAM database user via IRSA. Today both annotations point at the same IAM role (the single IAM user with `ALL PRIVILEGES`); the future least-privilege split flips the migration `ServiceAccount`'s role-arn — and the `DATABASE_IAM_AUTH_MIGRATE_USER` env var on the Job — without touching application code. See [m0-foundations.md § IAM database authentication](m0-foundations.md#iam-database-authentication) and [database-best-practises.md § B.9](../best-practises/database-best-practises.md). The only DB credential the cluster ever sees is a short-lived `rds:GenerateDBAuthToken` minted at connect time (M0 helper).
- `rebuild/runbooks/cutover.md`: T-minus runbook for cutover day plus rollback.
- `rebuild/runbooks/oncall.md`: on-call quick-reference (alerts, dashboards, common ops, restart procedures).
- `rebuild/comms/`: Slack pre-cutover post, Slack post-cutover post, in-product banner copy, and FAQ markdown.
- `rebuild/backend/tests/load/k6_chat.js`: k6 load script targeting the chat completion endpoint.
- `rebuild/backend/tests/chaos/`: pytest-driven chaos scenarios (kill-pod-mid-stream, kill-scheduler-mid-tick, kill-migration-pod-mid-apply).
- `rebuild/backend/tests/integration/test_trusted_proxy.py`: asserts the `TrustedIpMiddleware` strips `X-Forwarded-Email` from requests outside `settings.TRUSTED_PROXY_CIDRS` and emits a redacted `security.trusted_proxy.miss` log line; covers both the inside-CIDR (200 with the expected `User`) and outside-CIDR (header stripped, route returns 401) paths. Referenced by the M6 acceptance criterion on the trusted-proxy boundary.
- Smoke E2E pack (5 specs) in `rebuild/frontend/tests/smoke/` reused as the post-deploy gate.
- A grafana dashboard JSON in `rebuild/observability/dashboards/openwebui-rebuild.json` covering the signals listed below, importable into Canva's standard Grafana stack.

## Settings additions

M6 extends the M0 `Settings` class with the production knobs needed for observability, rate limits, security, file upload, and launch comms. The casing convention from M0 (UPPER_SNAKE_CASE attributes matching env var names) applies; access is `settings.OTEL_*`, `settings.RATELIMIT_*`, `settings.TRUSTED_PROXY_CIDRS`, etc. everywhere.

| Field | Type | Default | Notes |
|---|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `str \| None` | `None` | OTLP/gRPC endpoint. Required in `ENV=prod`; the app refuses to start otherwise. |
| `OTEL_SERVICE_NAME` | `str` | `"openwebui-rebuild"` | Resource attribute. |
| `OTEL_RESOURCE_ATTRIBUTES` | `str \| None` | `None` | Comma-separated `k=v` pairs merged into the Resource at bootstrap (e.g. `deployment.environment=prod,service.namespace=ai-platform`). |
| `LOG_FORMAT` | `Literal["json", "text"]` | `"text"` | `json` in prod (line-delimited JSON via `python-json-logger`), `text` in dev for readability. |
| `RATELIMIT_CHAT_TOKENS_PER_MIN` | `int` | `60_000` | Per-user token budget for chat completions across a sliding 60 s window. Enforced by the Redis Lua script in `app/ratelimit/limiter.py`. |
| `RATELIMIT_FILE_UPLOADS_PER_MIN` | `int` | `30` | Per-user file upload count across a sliding 60 s window. |
| `RATELIMIT_WEBHOOK_PER_MIN` | `int` | `60` | Per-webhook token ingress count across a sliding 60 s window. Keyed by webhook `id`, not by user. |
| `TRUSTED_PROXY_CIDRS` | `list[str]` | `[]` | CSV-parsed list of CIDRs for the `TrustedIpMiddleware` allowlist. Required in `ENV=prod`; the app refuses to start otherwise. Empty in dev so local development isn't broken. |
| `ALLOWED_FILE_TYPES` | `list[str]` | `["image/png","image/jpeg","image/gif","image/webp","text/plain","text/markdown","application/pdf"]` | CSV-parsed list of MIME types accepted by the file upload endpoint. Sniffed MIME, declared `Content-Type`, and file extension are cross-checked against this list. |

The launch banner's deactivation date is owned by the **SvelteKit** side as `PUBLIC_LAUNCH_BANNER_UNTIL` (read from `$env/static/public` in the root layout) — the banner is a frontend artefact, FastAPI does not render or know about it, so duplicating the value into the backend `Settings` would be wasted coupling. The Helm chart sets the same ISO-date value on both the FastAPI Deployment (no-op, intentionally absent) and the SvelteKit build (`PUBLIC_LAUNCH_BANNER_UNTIL=2026-05-12` baked into the bundle at build time). After 30 days the legacy archive link in the banner copy is stripped by a code change in the same release, not via env.

Per-route HTTP timeouts are *not* env-driven — they are declared inline at the route via the `timeout(seconds)` dependency factory (`dependencies=[timeout(seconds)]`; see [§ Per-route HTTP timeouts](#per-route-http-timeouts) below) so the value lives next to the route it constrains.

## Observability

The rebuild emits **traces, metrics, and logs** through OpenTelemetry, all exported via OTLP/gRPC to whatever endpoint the platform team injects via `OTEL_EXPORTER_OTLP_ENDPOINT`. The legacy fork already wires up OTel via `backend/open_webui/utils/telemetry/setup.py`; we mine its instrumentor list (FastAPI, SQLAlchemy, Redis, httpx, system metrics) but rewrite the bootstrap on the smaller surface area and against the async stack.

### OpenTelemetry bootstrap

`rebuild/backend/app/observability/otel.py` exposes a single `setup_otel(app, db_engine)` called from `lifespan` before any router is mounted. It:

1. Builds a `Resource` from `OTEL_SERVICE_NAME` (default `openwebui-rebuild`), `service.version` (build-time env `BUILD_HASH`), `deployment.environment` (`staging`/`prod`), and any extra attributes from `OTEL_RESOURCE_ATTRIBUTES` (comma-separated `k=v` pairs, OTel spec format — same syntax as the Settings-table entry above).
2. Configures a `TracerProvider` with a `BatchSpanProcessor` and an `OTLPSpanExporter` (gRPC) pointed at `OTEL_EXPORTER_OTLP_ENDPOINT`. Insecure mode only when `ENV=dev` and explicitly opted in via `OTEL_EXPORTER_OTLP_INSECURE=true`.
3. Configures a `MeterProvider` with a `PeriodicExportingMetricReader` (60 s interval) and an `OTLPMetricExporter`.
4. Configures a `LoggerProvider` with a `BatchLogRecordProcessor` and an `OTLPLogExporter`. The structured-logging handler emits both to stdout (for k8s log collection) and to OTel logs (for trace-correlated views).

### Instrumentation

Per the user's brief: FastAPI, SQLAlchemy, asyncmy, httpx, and python-socketio.

- **FastAPI**: `FastAPIInstrumentor.instrument_app(app, excluded_urls="/healthz,/readyz,/metrics")`. Health probes are excluded so they don't dominate traces.
- **SQLAlchemy / asyncmy**: `SQLAlchemyInstrumentor().instrument(engine=db_engine.sync_engine, enable_commenter=True, commenter_options={"db_driver": True, "opentelemetry_values": True})`. The `enable_commenter` option appends a `/* traceparent='...' */` comment to every emitted SQL statement so that DBA-side tools (slow-query log, performance schema) can be correlated back to a trace ID.
- **httpx**: `HTTPXClientInstrumentor().instrument()` with request/response hooks that set `http.url`, `http.method`, and `http.status_code`. The OpenAI SDK uses httpx under the hood, so this captures every model-gateway call automatically — no extra wiring.
- **python-socketio**: there is no first-party OTel instrumentor for `python-socketio`, so we add a thin custom layer (`rebuild/backend/app/observability/socketio.py`) that wraps the `AsyncServer.on(...)` decorator to start a span per event handler invocation, with attributes `socket.event`, `socket.room`, `socket.user_email_hash` (SHA-256 truncated, never the raw email — see PII below). For Redis pubsub fan-out we add a wrapper around `enter_room`/`emit` that records `socket.fanout.size` (number of recipient SIDs) as a metric.
- **APScheduler**: each scheduled job is wrapped in a span via a job-listener (`scheduler.add_listener(span_listener, EVENT_JOB_SUBMITTED | EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)`), with attributes `automation.id`, `automation.user_id_hash`, `scheduler.tick_age_ms`.
- **Redis**: `RedisInstrumentor().instrument()` — covers both the socket.io adapter and the rate-limit Lua scripts.

### Trace context propagation

Inbound requests already carry a `traceparent` header injected by Canva's edge stack (the OAuth proxy sits behind that). The FastAPI instrumentor extracts it automatically; we just have to make sure the header is preserved through our middleware chain. Two extra propagation paths to wire by hand:

- **APScheduler**: a job that posts back to FastAPI must inject `traceparent` into its outbound httpx call. `automation_run` rows store the originating `traceparent` so a long-running automation can be correlated end-to-end.
- **socket.io events**: client-emitted events carry `traceparent` in the event payload (`{ "traceparent": "...", "data": ... }`). The instrumented decorator extracts it before calling the user handler.

### Structured JSON logs

`rebuild/backend/app/observability/logging.py` configures Python's `logging` with a JSON formatter (`python-json-logger`) when `LOG_FORMAT=json`, plain-text otherwise. Every log line carries:

- `timestamp` (RFC 3339, UTC).
- `level`.
- `logger`.
- `message`.
- `trace_id`, `span_id` (extracted from the current OTel context via `LoggingInstrumentor`).
- `correlation_id` (per-request UUID set by `CorrelationIdMiddleware`; survives across socket.io events for the lifetime of a connection).
- `user_email` and `user_id_hash` only when present (see PII handling below).
- `route` (FastAPI route template, e.g. `/api/chats/{id}/messages`, never the resolved path so dashboards aggregate cleanly).
- Any extra `extra={...}` keys passed by the caller.

### PII handling

`X-Forwarded-Email` is internal-only (every request is authenticated and originates from inside Canva's network), but we still treat it as PII for governance:

- Logs ship the raw email in a top-level `user_email` field tagged with `pii: email` so the log pipeline can drop or redact it at ingest.
- Span attributes use `enduser.id` set to a SHA-256 hash of the email, truncated to 16 hex chars, suitable for cardinality. Raw emails never go on spans.
- Metric labels never include the email or its hash. Per-user dashboards drill from logs, not metrics.
- Webhook tokens and share tokens are explicitly redacted in logs by a regex filter (`token=[\w-]{40,}` → `token=[REDACTED]`).

### Critical signals (dashboards + SLOs)

The Grafana dashboard tracks these 11 signals, each with an explicit target. Targets are starting positions; they will be tightened after a week of baseline data. Burn-rate alerts use multi-window/multi-burn-rate per Google SRE chapter 5.

| # | Signal | Definition | Target / SLO | Alert condition |
|---|---|---|---|---|
| 1 | SSE first-byte latency p95 | `POST /api/chats/{id}/messages` to first `data:` byte | < 800 ms | > 1500 ms for 5 min |
| 2 | SSE stream completion rate | `(streams ending status=ok) / (streams started)` | > 99% rolling 30 min | < 98% for 5 min |
| 3 | socket.io fan-out latency p95 | `channel_post.received_at - channel_post.sent_at` (multi-context measurement via synthetic) | < 200 ms | > 500 ms for 5 min |
| 4 | Scheduler tick latency p95 | Time from `next_run_at <= now()` to `automation_run.created_at` | < 5 s | > 30 s for 10 min |
| 5 | File upload error rate | 5xx + 4xx on `POST /api/files` ÷ total | < 0.5% | > 2% for 5 min |
| 6 | Model gateway error rate | httpx exceptions + 5xx from gateway ÷ total | < 1% | > 5% for 5 min (paging) |
| 7 | MySQL pool utilisation | `pool.in_use / pool.size` | warn > 80%, crit > 95% | crit for 5 min |
| 8 | Redis pubsub round-trip p95 | publish-to-deliver latency, measured via heartbeat probe | < 50 ms | > 200 ms for 5 min |
| 9 | 5xx rate per route | per-route 5xx ÷ per-route requests | < 0.1% | > 1% for 5 min |
| 10 | Automation run success rate | `(runs status=ok) / (runs total)` 1 h window | > 99% | < 95% for 30 min |
| 11 | Websocket disconnect rate | `disconnects / connects` 1 min window | < 5% | > 20% sustained 5 min |

Two extra panels (no SLO, monitoring only): pod CPU/memory utilisation and per-pod request rate. Pages route to the on-call rotation defined in `rebuild/runbooks/oncall.md`.

## Rate limits and timeouts

### Implementation choice: custom middleware over Redis, not `slowapi`

`slowapi`'s default keying is per-IP, which is useless behind the OAuth proxy where every request appears to originate from the proxy's egress IP. We need:

- Per-`X-Forwarded-Email` keying.
- A token-counting bucket (chat completions cost varying tokens, not constant requests).
- Reuse of the Redis instance already present for socket.io and the scheduler.
- Atomic increment-and-check via Lua so that under contention we don't get false-allows.

`slowapi`'s API doesn't model token-counting buckets cleanly, and shoehorning it in costs more than the ~120 lines of code for a minimal sliding-window-counter middleware. We therefore write our own at `rebuild/backend/app/ratelimit/limiter.py`: one Lua script (uploaded once per process) implementing a sliding-window counter, one async wrapper exposing `acquire(key, cost, limit, window_seconds) -> Decision`, one FastAPI dependency factory `rate_limit(bucket: Bucket)` that resolves the bucket config from `Settings`, and one socket.io middleware for ingress events. All three buckets share the same Lua + the same Redis instance.

### Configured buckets

| Bucket | Key | Limit (default) | Cost | Failure mode |
|---|---|---|---|---|
| `chat_tokens` | `rl:chat:{user_email}` | 60 000 tokens / minute (`settings.RATELIMIT_CHAT_TOKENS_PER_MIN`) | tokens estimated by `tiktoken` for the request, then reconciled with actual usage from the gateway response | 429 with `Retry-After`; SSE: 1 frame `{"error":"rate_limited"}` then close |
| `file_uploads` | `rl:upload:{user_email}` | 30 requests / minute (`settings.RATELIMIT_FILE_UPLOADS_PER_MIN`) | 1 per request | 429 with `Retry-After`; multipart form rejected before stream-to-DB |
| `webhook_ingress` | `rl:webhook:{webhook_id}` | 60 requests / minute (`settings.RATELIMIT_WEBHOOK_PER_MIN`) | 1 per request | 429 with `Retry-After`; webhook caller's job to retry |

`Settings` exposes overrides per env var (`RATELIMIT_CHAT_TOKENS_PER_MIN`, etc.) so that production can be raised without a code change once we have baseline numbers.

### Per-route HTTP timeouts

Configured as a **dependency factory** in `app/observability/timeouts.py`, declared at the route declaration site via `dependencies=[timeout(seconds)]`, and backstopped by a single global `TimeoutMiddleware` that enforces a 15 s default for any route that doesn't specify one.

```python
# rebuild/backend/app/observability/timeouts.py
from typing import AsyncIterator
import anyio
from fastapi import Depends, Request


def timeout(seconds: float):
    """Per-route timeout dependency. Use as ``dependencies=[timeout(300)]``."""
    async def _enforce(request: Request) -> AsyncIterator[None]:
        request.state.timeout_seconds = seconds
        with anyio.fail_after(seconds):
            yield
    return Depends(_enforce)
```

```python
# rebuild/backend/app/routers/chats.py
@router.post(
    "/{id}/messages",
    response_model=...,
    dependencies=[timeout(300)],
)
async def post_message(...): ...
```

The dispatch table below documents the project-wide policy; the actual values live as literal `timeout(N)` calls on each affected route. We considered the alternative — a `@route_timeout(seconds)` decorator that mutates a route attribute, paired with a middleware that reads `request.scope["route"].timeout_seconds` — and rejected it: a decorator + middleware split scatters one feature across three files, relies on a slightly awkward `request.scope["route"]` access, and is harder to override per-test. The dependency factory is one file, declarative at the call site, and trivially overridable via `app.dependency_overrides`. The global `TimeoutMiddleware` still exists, but only as the default-15s safety net for routes without an explicit `timeout(...)` dependency; it does not read any route attributes.

| Route shape | Timeout | Rationale |
|---|---|---|
| `GET /healthz`, `GET /readyz` | 1 s | Probe must be cheap; if it isn't, fail. |
| `POST /api/chats/{id}/messages` (SSE) | 300 s hard cap | Long but bounded; matches our SSE stream cap below. |
| `GET/POST /api/chats/*` (non-streaming) | 10 s | Snappy CRUD; anything slower is a query-plan bug. |
| `POST /api/files` (upload) | 30 s | 5 MiB upload over a slow link plus DB write. |
| `GET /api/files/{id}` (download) | 60 s | Streaming read over a slow link. |
| Channel/socket HTTP routes | 10 s | Same shape as chat CRUD. |
| Webhook ingress (`POST /api/webhooks/incoming/{webhook_id}`) | 5 s | Caller is a bot; we are not waiting. Path matches M4's authoritative route shape. |
| Internal scheduler `/test/scheduler/tick` | 5 s | Test-mode only; should be near-instant. |
| Anything else | 15 s default | Catch-all. |

### SSE stream timeout

Defined in code as `SSE_STREAM_TIMEOUT_SECONDS = 300`. Implementation: the streaming generator (M2, `app.services.chat_stream.stream_chat`) wraps the upstream `OpenAICompatibleProvider.stream()` iteration in `async with asyncio.timeout(settings.SSE_STREAM_TIMEOUT_SECONDS)` with a 5-minute deadline. When the deadline trips, the generator catches `asyncio.TimeoutError`, emits the M2-defined `timeout` SSE event (`event: timeout\ndata: {"assistant_message_id": "...", "limit_seconds": 300}\n\n`), persists the assistant message with `cancelled=True, done=True`, and returns. The client renders a "Stream timed out at 5 minutes; click regenerate to continue" inline notice keyed off the `timeout` event. This is the same persistence shape as user-cancellation from M2; M6 only sets the value of the constant, it does not introduce a new event type. The `timeout(300)` route-layer dependency (see § Per-route HTTP timeouts above) is set to the same value as a backstop, but the in-generator deadline is the primary cap so the persist-partial branch always owns the cleanup path.

### APScheduler tick — short statement timeout

The scheduler tick query (`SELECT … FOR UPDATE SKIP LOCKED` from M5) must never stall the app. We pin a per-statement timeout on the scheduler's database session via MySQL's `MAX_EXECUTION_TIME` optimizer hint:

```sql
SELECT /*+ MAX_EXECUTION_TIME(2000) */ ...
```

Two seconds is well above the expected sub-100 ms execution and well below the 30 s tick interval, so we always recover before missing a tick. If the optimizer hint fires, the tick logs a warning (`scheduler.tick.timeout`), increments a counter (`scheduler_tick_timeouts_total`), and proceeds to the next tick. The scheduler's `AsyncEngine` is configured with `pool_recycle=300`, `pool_pre_ping=True`, and a separate pool from the request-handling engine so that scheduler stalls cannot exhaust connections used by HTTP traffic.

## Hardening

### Trusted-header verification

`rebuild/backend/app/security/trusted_ip.py` is a starlette `BaseHTTPMiddleware` that runs **before** the auth dependency. It:

1. Extracts the immediate-peer IP from the ASGI scope (`scope["client"][0]`) — this is whatever k8s/Ingress hands us, which is the OAuth proxy's IP.
2. Compares against `TRUSTED_PROXY_CIDRS` (env var, comma-separated CIDRs, default empty in dev so local development isn't broken).
3. If no match, **strips** every `X-Forwarded-Email` and `X-Forwarded-Name` header from the request before passing it on, and logs a `security.trusted_proxy.miss` event with the source IP.
4. If matched, the headers are left intact for the auth dependency to consume.

The middleware is mounted **first** (outermost) so a misconfigured Ingress can never leak header injection. `Settings` validates that `TRUSTED_PROXY_CIDRS` is non-empty when `ENV=prod`; the app refuses to start otherwise. The CIDR list is the OAuth proxy's pod CIDR plus any explicit fallback IPs Canva's network team provides; this is documented in `rebuild/runbooks/oncall.md` and the values file.

### CORS

`fastapi.middleware.cors.CORSMiddleware` is configured with:

- `allow_origins=settings.CORS_ALLOW_ORIGINS` — typically a single entry in prod, the OAuth proxy's external URL.
- `allow_credentials=True` (the proxy may forward a session cookie from its side, even though we don't use it).
- `allow_methods=["GET","POST","PUT","PATCH","DELETE"]`.
- `allow_headers=["content-type","x-correlation-id","traceparent"]` — explicit allowlist, no wildcards.
- `expose_headers=["x-correlation-id","x-ratelimit-remaining","x-ratelimit-reset"]`.
- `max_age=600`.

In dev (`ENV=dev`) the origin allowlist expands to `http://localhost:5173` (SvelteKit dev server) for ergonomics. Prod refuses to start if `CORS_ALLOW_ORIGINS` is empty. The setting is the same `Settings.CORS_ALLOW_ORIGINS` introduced in M0 (`m0-foundations.md` §Settings); M6 does not add a new env var for the proxy origin.

### SvelteKit CSRF (default-on, kept on)

SvelteKit ships `kit.csrf.checkOrigin = true` by default — every incoming POST/PUT/PATCH/DELETE/OPTIONS to a SvelteKit route is rejected unless its `Origin` header matches the request's origin (see [sveltekit-best-practises.md § 6.5](../best-practises/sveltekit-best-practises.md)). We **leave it on** in `svelte.config.js` even though the rebuild has chosen the "thin SSR shell + direct FastAPI calls" mutation pattern (see [m0-foundations.md § Frontend conventions (cross-cutting)](m0-foundations.md#frontend-conventions-cross-cutting), rule 5) and therefore has zero first-party form actions for the check to protect: the cost of leaving it on is nil (no SvelteKit POST surface to false-positive on), and turning it off would have to be reconsidered the day a SvelteKit form action is introduced. FastAPI handles its own request validation independently — `Origin` and `Referer` are not part of its trust boundary; the trusted-header check lives in `app/security/trusted_ip.py` (above) and the auth dep in `app/core/auth.py` (M0).

### Security headers

A second middleware `SecurityHeadersMiddleware` adds, on every response:

- `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`.
- `X-Content-Type-Options: nosniff`.
- `X-Frame-Options: DENY`.
- `Referrer-Policy: strict-origin-when-cross-origin`.
- `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()`.
- `Content-Security-Policy: default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self' wss: ${CORS_ALLOW_ORIGINS_JOINED}; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'` — `CORS_ALLOW_ORIGINS_JOINED` is the space-joined list from `settings.CORS_ALLOW_ORIGINS`.

CSP includes `'unsafe-inline'` for styles because **SvelteKit's SSR injects inline `<style>` blocks** (for scoped styles, transitions, and arbitrary-value Tailwind classes) into the rendered HTML — `style-src 'self' 'unsafe-inline'` keeps that working without weakening any other directive. Scripts are `'self'` only because `adapter-node` produces a single bundle and we do not inline scripts. Markdown renderer (M2) sanitises via DOMPurify before insertion, so the strict CSP holds even with rich content.

### File upload validation

Reaffirmed from `rebuild.md` section 9. The `POST /api/files` endpoint:

1. Reads `Content-Length`. Rejects > 5 MiB with `413` before any body is consumed.
2. Streams chunks to a temp buffer, hard-stopping if the actual byte count exceeds 5 MiB (defends against a missing or lying `Content-Length`).
3. Sniffs the leading 4 KiB with `python-magic` (libmagic) to determine MIME.
4. Cross-checks sniffed MIME, declared `Content-Type`, and the file extension. Inconsistencies are rejected with `415`. The allowed list lives in `Settings.ALLOWED_FILE_TYPES` (default: images, plain text, common docs, audio for transcription if M4 ever adds it). Executables, archives, and HTML are blocked.
5. Computes SHA-256, persists to `file_blob.data` as `MEDIUMBLOB`, and writes the metadata row to `file`.

MySQL session is initialised with `SET SESSION max_allowed_packet=16M` (defensive — server is also pinned to 16M).

### Webhook tokens

M4 already ships webhook tokens as **hashed-at-rest** (`channel_webhook.token_hash`, SHA-256, unique index; plaintext returned only at creation, no server-side persistence of plaintext). M6 does not change the schema — it confirms the design holds under load and adds the operational verification: the load test asserts that no webhook plaintext appears in any log line, and the `Logging hygiene` section below pins a regex redaction filter for share + webhook tokens. Rotation remains delete-and-create. The same generator (`secrets.token_urlsafe(32)`) is used for share tokens and webhook tokens; both are 43-character URL-safe strings.

### MySQL diagnostics (oncall reference)

The on-call runbook (`rebuild/runbooks/oncall.md`) carries the canonical paste-able queries; this section documents the MySQL 8.0 features they rely on so the design intent is in the plan, not just in the wiki.

**Slow-query triage with `EXPLAIN ANALYZE`.** MySQL 8.0.18+ ships `EXPLAIN ANALYZE`, which actually runs the query and reports per-step `actual time=start..end loops=N rows=N` next to the planner's `cost=...` estimates. First step on any "X is slow" page:

```sql
EXPLAIN ANALYZE
SELECT id, title, updated_at FROM chat
WHERE user_id = ? AND archived = FALSE
ORDER BY updated_at DESC LIMIT 50;
```

Run on the **staging replica** with prod-shape data, never on prod. If the discrepancy between estimated and actual rows is >10×, the optimiser's stats are stale → run `ANALYZE TABLE chat;` (cheap, online) and re-plan. If estimates are accurate but `actual time` is still high, the access path itself is wrong → see "Index lifecycle" below.

**Unused / dead-index audit via `sys` schema.** MySQL 8.0 installs the `sys` schema by default; it ships pre-rolled views over `performance_schema` that answer the questions an ops engineer actually has:

```sql
-- Indexes that have never been read since the server last started.
-- Drop candidates; never drop without first making INVISIBLE — see § Index lifecycle.
SELECT object_schema, object_name, index_name
FROM   sys.schema_unused_indexes
WHERE  object_schema = 'rebuild';

-- Read volume per index. Top of this list = critical path; bottom = waste.
SELECT * FROM sys.schema_index_statistics
WHERE table_schema = 'rebuild'
ORDER BY rows_selected DESC LIMIT 20;

-- Anything blocking on a row lock right now (should always be empty given
-- SKIP LOCKED, but the view is the right place to look first).
SELECT * FROM sys.innodb_lock_waits;

-- Top 10 statements by total latency. Aggregated by digest, so the same
-- statement with different bound parameters folds into one row.
SELECT * FROM sys.statement_analysis
ORDER BY total_latency DESC LIMIT 10;

-- Tables doing the most full scans. A non-trivial spike here usually means
-- a missing index or a regression in a query plan after schema changes.
SELECT * FROM sys.schema_tables_with_full_table_scans;
```

These five queries are pinned at the top of `oncall.md`. The dashboard panels under "MySQL pool utilisation" (signal 7) only tell us that something is wrong; `sys` schema tells us what.

### Index lifecycle (invisible-index pattern)

MySQL 8.0 supports `ALTER TABLE ... ALTER INDEX <name> INVISIBLE` (and `... VISIBLE` to reverse). An invisible index is **physically maintained** on every write and **enforces UNIQUE / FK constraints**, but is hidden from the optimiser, so the planner picks an alternate path. Toggling visibility is a metadata-only operation — instant, no rebuild, no DML stall — which makes it the right tool for two operational scenarios.

**Safe drop** (suspect a `chat` or `channel_message` index has gone unused):

```sql
ALTER TABLE chat ALTER INDEX ix_chat_user_folder_updated INVISIBLE;
-- Wait one full week of representative production traffic.
-- Watch sys.statement_analysis and the slow-query log for regressions.
ALTER TABLE chat ALTER INDEX ix_chat_user_folder_updated VISIBLE;       -- if anything regresses
-- or
ALTER TABLE chat DROP INDEX ix_chat_user_folder_updated;                -- if clean for a week
```

**Staged add** (rolling out a new candidate index off-peak):

```sql
ALTER TABLE channel_message ADD INDEX ix_channel_msg_pinned_created (channel_id, is_pinned, created_at) INVISIBLE;
-- Index is built and maintained on writes but invisible to the planner.
-- Confirm writes are healthy (sys.io_global_by_wait_by_latency on innodb*).
ALTER TABLE channel_message ALTER INDEX ix_channel_msg_pinned_created VISIBLE;
```

**Rules:**

- The visibility toggle is always a separate Alembic revision from the eventual `DROP INDEX`. The first revision lands, observation period runs, second revision drops (or reverts). This keeps the rollback to a single `helm rollback` at any point.
- `INVISIBLE`-then-observe is mandatory before dropping any index that has shipped a release. The only exception is an index that was never deployed (caught in PR review and dropped before merge).
- The Alembic helper `drop_index_if_exists` from M0 is unchanged; the new pattern is an `op.execute("ALTER TABLE ... ALTER INDEX ... INVISIBLE, ALGORITHM=INSTANT, LOCK=NONE")` wrapped in `execute_if(has_index(...), ...)`.

### Configuration changes (`SET PERSIST`)

MySQL 8.0 `SET PERSIST <var> = <value>` writes to `mysqld-auto.cnf` (JSON, with `SET_USER` and `SET_TIME` metadata) and applies the change immediately. `SET PERSIST_ONLY <var> = <value>` writes-but-defers for read-only variables that need a restart. Both survive restart; both are auditable.

**Rules for live tuning the prod MySQL instance:**

1. The on-call uses `SET PERSIST` for any dynamic variable they need to twist (`max_connections`, `innodb_buffer_pool_dump_at_shutdown`, `slow_query_log`, etc.). Inspect with:
   ```sql
   SELECT VARIABLE_NAME, VARIABLE_VALUE, SET_USER, SET_HOST, SET_TIME
   FROM performance_schema.variables_info
   WHERE VARIABLE_SOURCE = 'PERSISTED'
   ORDER BY SET_TIME DESC;
   ```
2. **Every persisted change MUST be mirrored back into the Helm values file (`rebuild/infra/k8s/values-prod.yaml`) in the next deploy** so `mysqld-auto.cnf` doesn't drift from version control. The runbook's incident template includes a "follow-up PR" checkbox for exactly this.
3. Roll back a single variable with `RESET PERSIST <var>;`. Roll back everything (last-resort) with `RESET PERSIST;` — both leave the running value untouched, so a `SET GLOBAL` may be needed to actually revert.
4. For variables outside the runbook's allow-list (e.g. anything that affects replication topology, binlog format, or the data dictionary), the on-call escalates to the platform team before touching `SET PERSIST_ONLY`.

This is intentionally lightweight — the rebuild's MySQL instance is a managed single instance (see `rebuild.md` § 9 and the "MySQL deployment" non-goal below); the heavy operational tooling lives upstream.

### SSE / WebSocket heartbeats and idle disconnect

- **SSE**: every `STREAM_HEARTBEAT_SECONDS` of upstream silence (M0 constant; default 15 s), the streaming generator emits a `: keep-alive\n\n` comment frame (same byte-string as `m2-conversations.md` § SSE streaming and `rebuild/docs/best-practises/FastAPI-best-practises.md` § A.7 Streaming responses (SSE)). Most reverse proxies drop idle connections at 60 s; 15 s is well inside that. The 5-minute hard cap above is the outer bound.
- **WebSocket (socket.io)**: `ping_interval=STREAM_HEARTBEAT_SECONDS`, `ping_timeout=STREAM_HEARTBEAT_SECONDS * 2` (M4 wires both — see [m4-channels.md § Stack](m4-channels.md#stack)). Idle connections (no client events for 30 minutes) are forcibly disconnected by a periodic task that scans the session pool. Channel auto-reply tasks (`@model`) are bounded to 60 s of generation regardless of socket state, with cancellation if the originating user disconnects.

## Deploy pipeline

### Buildkite shape

`rebuild/.buildkite/rebuild.yml` is path-filtered with `if: build.changed_files =~ /^rebuild\//`, mirroring the dual-tree convention from `rebuild.md` section 10. The legacy `.buildkite/pipeline.yaml` keeps shipping the old image for the duration of the build period; on cutover the legacy pipeline is deleted in the sweep PR.

Pipeline stages:

```
lint → test → build → push → deploy-staging → smoke-staging → deploy-prod → smoke-prod
                                  ▲
                                  └── manual unblock between staging and prod
```

- **lint**: `make -C rebuild lint` (ruff, mypy, eslint, svelte-check). 3 min target.
- **test**: `make -C rebuild test` (pytest + Vitest + Playwright CT + Playwright E2E against the deterministic stack). 8 min target. Sharded 4-way.
- **build**: multi-stage Docker build, tagged `${IMAGE_REPO}:rebuild-${BUILDKITE_COMMIT}`. The base image, build args (`BUILD_HASH=${BUILDKITE_COMMIT}`), and the ECR auth plugin block are copied verbatim from the legacy `.buildkite/pipeline.yaml`.
- **push**: `docker push` of the immutable SHA tag, plus a moving `:rebuild-staging` tag on every main commit and `:rebuild-prod` only on a manual promotion.
- **deploy-staging**: `helm upgrade --install openwebui-rebuild rebuild/infra/k8s -f values-staging.yaml --set image.tag=rebuild-${BUILDKITE_COMMIT}`. Includes the Alembic Job (see below).
- **smoke-staging**: runs `rebuild/frontend/tests/smoke/` against the staging URL. Hard-gates promotion.
- **deploy-prod**: same `helm upgrade` against `values-prod.yaml`. Manual unblock step in front of it; an annotation on the build records the promoting user.
- **smoke-prod**: same 5 specs, against prod, plus a 60 s soak watching the dashboards. Failure triggers automatic rollback (`helm rollback openwebui-rebuild 0`).

### Image tag scheme

- `:rebuild-${git_sha}` — immutable, every build.
- `:rebuild-staging` — moving, points at whatever is in staging right now.
- `:rebuild-prod` — moving, points at whatever is in prod right now.
- `:rebuild-prod-previous` — set to the previously-prod tag at the start of every prod deploy. Rollback target.

The legacy fork's `:${BUILDKITE_COMMIT}` tag is left untouched — we don't share tags with the legacy image because deploys go to separate environments until cutover.

### Database migration step

`alembic upgrade head` runs as a Helm `Job` named `openwebui-rebuild-migrate-${git_sha}` with `pre-install,pre-upgrade` hook annotations and `helm.sh/hook-weight: -5`. The Job:

- Uses the same image as the app.
- Runs `alembic -c rebuild/backend/alembic.ini upgrade head`.
- Binds to a dedicated `serviceAccount: openwebui-rebuild-migrate` whose IRSA / Pod Identity binding maps to an IAM role that can mint `rds:GenerateDBAuthToken` for the IAM user named in `DATABASE_IAM_AUTH_MIGRATE_USER`. **Today** that env var resolves to the same single IAM user as `DATABASE_IAM_AUTH_USER` (one IAM user with `ALL PRIVILEGES` on the schema), and the migration `ServiceAccount`'s `eks.amazonaws.com/role-arn` annotation matches the runtime one. The dedicated `ServiceAccount` and the separate `DATABASE_IAM_AUTH_MIGRATE_USER` env var are deliberate seams: the future least-privilege split (runtime user → `SELECT, INSERT, UPDATE, DELETE`; migrate user → `ALL PRIVILEGES`) lands as a values-file change (flip the migration `ServiceAccount`'s role-arn + `DATABASE_IAM_AUTH_MIGRATE_USER`), not an application code change. No DB password is ever rendered into a `Secret`; the M0 IAM auth helper (`app.core.iam_auth.attach_iam_auth_to_engine`) fires inside Alembic's async engine and mints a fresh token for the Job's single physical connection. See [m0-foundations.md § IAM database authentication](m0-foundations.md#iam-database-authentication) for the helper surface and [database-best-practises.md § B.9](../best-practises/database-best-practises.md) for the do/don't list.
- Has `backoffLimit: 0` and `activeDeadlineSeconds: 300` — a migration must succeed within 5 minutes or fail loudly.
- Pods only roll out after the Job completes successfully (Helm hook ordering).

We chose a pre-upgrade Job over an init container because:

- Init containers run on every pod; running migrations N times is at best wasteful and at worst racy if two pods both try to acquire Alembic's lock.
- The Job pattern surfaces migration failure as a deploy failure, not a `CrashLoopBackOff` that gets blamed on the app.
- Rollback is symmetric: a forward migration that fails leaves the previous image still serving (since the Deployment update never happens).

#### Retry safety

`backoffLimit: 0` means **Kubernetes** will not auto-retry a failed migration Job, but operators routinely will: the runbook (`rebuild/runbooks/cutover.md` and `rebuild/runbooks/oncall.md`) instructs the on-call to delete the failed Job and re-run `helm upgrade` after diagnosing. That re-run must always be safe — MySQL DDL auto-commits, so a Job that crashes after creating two of three indexes leaves the schema in a half-state, and a naive `op.create_index(...)` on the second run would explode with `1061 Duplicate key name`. The contract that protects against this is locked at the project level in [rebuild.md § 9 "Robust, idempotent Alembic migrations"](../../../rebuild.md#9-decisions-locked) and shipped in [m0-foundations.md § Migration helpers](m0-foundations.md#migration-helpers): every revision uses only the `*_if_not_exists` / `*_if_exists` wrappers, the M0 CI grep gate fails any PR that introduces a bare `op.create_*` in `backend/alembic/versions/`, and the `tests/test_migrations.py` suite asserts every revision is a re-runnable no-op on a fully-upgraded schema and recovers cleanly from a hand-crafted partial-apply.

The same guarantee underwrites the cutover rollback path: if `helm rollback` triggers a `downgrade` against a partially-downgraded schema (because the previous attempt died mid-way), the inspector-based `*_if_exists` helpers skip already-dropped objects rather than raising. The Job exit code therefore reflects the actual schema-vs-target delta, not the partial-apply history.

The migration Job emits structured JSON logs under the same logger configuration as the app (`LOG_FORMAT=json`), so a Job failure ships full stack + offending DDL to the same log pipeline as a runtime crash. The runbook quotes the exact log query operators paste into Datadog/Loki to fetch the most recent failed-migration logs.

### Deploy targets — uncertainty flag

The legacy pipeline pushes to ECR (`699983977898.dkr.ecr.us-east-1.amazonaws.com/container-build/data-platform/open-webui`), which tells us the image build path and AWS account but not the deploy substrate. This plan **assumes Kubernetes with Helm**, which is the dominant pattern for FastAPI services at Canva and is what the existing `extra_hosts: host.docker.internal:host-gateway` shape in `docker-compose.otel.yaml` won't constrain. **If platform team policy is ECS/Fargate or Argo CD instead of Helm**, the manifests under `rebuild/infra/k8s/` become a kustomize overlay or a Spinnaker pipeline definition, but the surface-area changes are mechanical: same image tag scheme, same migration Job, same `values-*.yaml` shape feeding env vars. See open question 1 below.

## Cutover runbook

Captured in full at `rebuild/runbooks/cutover.md`; this section sketches the spine.

### T-1 week (comms)

- Engineering lead posts in `#openwebui-internal` and `#eng-announcements`: cutover date, what users will lose (chat history, channel scrollback, automations), the read-only archive URL, and a one-line FAQ link.
- Sends an email to the `openwebui-users@canva.com` group with the same content plus rendered banner copy.
- Pins a single in-app banner: "Open WebUI relaunches on {date}. History will be reset; the legacy instance will be available at archive.openwebui.canva-internal.com for 30 days."

### T-1 day (final smoke)

- Run the full E2E suite against staging.
- Run the k6 load script at modelled-peak QPS for 15 minutes; confirm SLOs hold.
- Run a chaos drill: kill a pod mid-stream and a pod mid-automation. Confirm both recover per M2/M5 semantics.
- Tag the staging build that passes as `rebuild-prod-candidate-${date}`.
- Confirm rollback path: `helm rollback` on staging back to the previous good tag completes in under 60 s.
- Final go/no-go in `#openwebui-cutover`. Decision-maker: engineering lead.

### T-0 (cutover day)

Aim for a 30-minute window. All steps tracked in a shared Google Doc with a timestamp column; on-call is in a Zoom bridge.

| T+ | Step | Owner | Verify |
|---|---|---|---|
| 0:00 | Promote `rebuild-prod-candidate-${date}` to `:rebuild-prod` | Releaser | ECR shows new digest |
| 0:01 | `helm upgrade` to prod | Releaser | All pods `Ready`, migration Job `Complete`. |
| 0:05 | Smoke E2E pack against new pod IPs (proxy not flipped yet) | Releaser | 5/5 pass |
| 0:08 | Confirm dashboards show baseline traffic on the new service via synthetic monitor | On-call | All 11 SLO panels green |
| 0:10 | OAuth proxy upstream flipped to point at new k8s `Service` | Platform on-call | `curl https://openwebui.canva-internal.com/healthz` returns 200 from new build (`X-Build-Hash` response header) |
| 0:11 | Banner on legacy instance changes to "This is the legacy read-only archive" | Releaser | Visual check |
| 0:12 | Legacy instance moved to read-only mode (proxy strips `POST/PUT/PATCH/DELETE`); URL changes to `archive.openwebui.canva-internal.com` | Platform on-call | Visual + curl check |
| 0:15 | Post in `#openwebui-internal`: cutover complete. | Releaser | Slack post |
| 0:30 | First go/no-go gate: are dashboards still green and is the synthetic still passing? | On-call | If yes, leave the Zoom bridge on standby for 24 h. If no, rollback. |

### Rollback

Triggered by any of: synthetic monitor failing for 3 consecutive runs, 5xx rate > 5% for 5 min, on-call judgement call. Procedure:

1. Platform on-call flips the OAuth proxy upstream **back to the legacy service**. (~30 s.)
2. Legacy service is taken out of read-only mode (proxy stops stripping mutating verbs).
3. `helm rollback openwebui-rebuild 0` on the new service so we have a known-clean state to debug into.
4. Post in `#openwebui-internal`: rollback complete; investigation in `#openwebui-cutover`.
5. **Empty-slate caveat**: any user activity on the new service during the cutover window (a few minutes max) is lost on rollback. This is acceptable given the empty-slate launch — there's nothing precious yet — and is called out in the comms.

### Decommission (T+30 days)

- Take a final MySQL dump of the legacy DB, store it per Canva's standard data retention policy (compliance hold).
- Delete the legacy k8s Deployment, Service, Ingress, and ConfigMap/Secret.
- Delete the `archive.openwebui.canva-internal.com` DNS record and remove the OAuth proxy route.
- Run the cutover sweep PR (per `rebuild.md` section 10): `git mv rebuild/* .`, delete the legacy tree, tag previous commit `legacy-final`.

### Comms templates

#### Slack post (T-1 week)

> **Open WebUI relaunch — {date}**
> We are switching to a slimmer Open WebUI build on {date}. **Your existing chat history, channel scrollback, and automations will not carry over** — the new instance starts empty. The legacy instance will remain available read-only at archive.openwebui.canva-internal.com for 30 days if you need to refer back. Why we're doing this, what's new, and a short FAQ in this doc: {link}.

#### In-product banner (first 2 weeks)

> History reset on launch. Old chats and channels live read-only at archive.openwebui.canva-internal.com for 30 days.

#### Slack post (T+0)

> **Open WebUI relaunched.** New instance is live at openwebui.canva-internal.com. Old instance is read-only at archive.openwebui.canva-internal.com until {date+30}. Issues → #openwebui-internal.

## Empty-slate launch comms

The empty-slate decision is the single biggest user-visible change of the rebuild, and the plan is explicit (`rebuild.md` sections 5 and 9): no migration, no parallel run, no read-only freeze of legacy data — just deploy, switch, decommission. Comms therefore have to do the work the technical solution refuses to do.

### In-product banner (first 2 weeks)

A single non-dismissible banner at the top of the app shell:

> History was reset when we relaunched on {date}. Old chats are not migrated. The previous instance is read-only at archive.openwebui.canva-internal.com until {date+30}.

After 14 days the banner auto-disables: the SvelteKit root layout reads `PUBLIC_LAUNCH_BANNER_UNTIL` from `$env/static/public` and renders the banner only while `Date.now() < new Date(PUBLIC_LAUNCH_BANNER_UNTIL).getTime()`. The value is set in `values-prod.yaml` and baked into the bundle at build time (per [sveltekit-best-practises.md § 7.1 / § 7.2](../best-practises/sveltekit-best-practises.md): `PUBLIC_*` static env vars are statically replaced and require a rebuild to change — exactly right here, since the cutoff is a known launch-time decision). FastAPI is not involved. After 30 days the archive link inside the banner copy is stripped by a code change in the same release.

### FAQ

Lives at `rebuild/comms/faq.md` and is also the source for an in-app `/help` page.

- **Can I get my old chats back?** No, the legacy instance is read-only at archive.openwebui.canva-internal.com for 30 days. After that the data is retained per Canva's standard policy but no longer accessible via UI.
- **Why didn't you migrate?** Migrating would have added 2–3 weeks and a maintenance burden for a one-off transition. Given how short the average chat lifetime is in this tool, we judged it not worth the cost. Shareable links and chat exports work going forward.
- **Will my automations carry over?** No. You'll need to recreate them; the editor lets you copy-paste prompts and re-pick the same model and schedule.
- **Will my channels carry over?** No. Channel structure (membership, pinned messages, scrollback) is reset. The legacy archive preserves them read-only for 30 days.
- **Will webhooks I set up still work?** No. Tokens are invalidated; you'll need to issue new ones from each channel's webhooks page and update whatever's calling them.
- **Why the `archive.` subdomain?** It's a read-only mirror at the same DB but behind a proxy that blocks mutating requests. Legacy URLs are auto-rewritten by a 301.

### Email

A single email to `openwebui-users@canva.com` at T-1 week, T-1 day, and T+0. Templates live in `rebuild/comms/email-templates.md`.

## Tests gating M6

### Smoke E2E pack (5 specs)

Lives at `rebuild/frontend/tests/smoke/`, runs against staging post-deploy and against prod immediately after the proxy flip. Five specs, one for each of the four user-visible features plus health.

1. `01-health.spec.ts` — `/healthz` returns 200, `/readyz` returns 200, root returns 200 with the SvelteKit shell.
2. `02-chat-stream.spec.ts` — login (header inject), create chat, send message, assert tokens stream, assert the assistant message persists across reload. The OpenAI mock from M0 is **not** used in prod-smoke; a real model gateway call is made and we assert any non-error response of length > 0.
3. `03-share-and-read.spec.ts` — owner creates a share, second BrowserContext reads it. Reused from M3's E2E.
4. `04-channel-realtime.spec.ts` — two contexts, one posts in a channel, the other receives the delta within 1 s. Reused from M4's E2E.
5. `05-automation-tick.spec.ts` — create a `FREQ=MINUTELY` automation, hit `/test/scheduler/tick` (test-only endpoint guarded by `settings.ENV in {"test", "staging"}`), assert the run record appears. Skipped in prod-smoke; staging only.

Smoke runs sequentially (no parallelism) against shared resources, capped at 90 s. Failure aborts the deploy.

### Load test (k6)

`rebuild/backend/tests/load/k6_chat.js` hits `POST /api/chats/{id}/messages` against staging. Modelled-peak QPS comes from the legacy instance's request rate p99 over 30 days, multiplied by 1.5 for headroom — concrete number to be filled in during M6 calibration. The script:

- Ramps from 0 to peak over 2 min, holds for 10 min, ramps down for 1 min.
- Uses a pool of synthetic test users (`X-Forwarded-Email: loadtest-{i}@canva.com`) with the test allowlist enabled.
- Asserts `http_req_duration{phase=first_byte} p(95) < 1500` and `http_req_failed: rate<0.01`.
- Runs nightly on staging via Buildkite scheduled trigger; results posted to `#openwebui-perf`.

### Chaos

Three scenarios, run in staging via pytest fixtures that talk to the cluster API.

- **Kill mid-stream**: client opens an SSE stream; orchestrator kills the pod handling it after 2 s. Assertions: client receives a clean error or reconnect, the partial assistant message in `chat.history` is marked `cancelled`, no zombie streams remain in Redis (verified by counting active stream keys before/after).
- **Kill mid-automation tick**: orchestrator kills the pod that just acquired a row via `FOR UPDATE SKIP LOCKED`. Assertions: the next surviving pod's tick reacquires the row (lock released by transaction abort), the automation runs, the `automation_run` row reflects exactly one success, no duplicate run is created.
- **Kill migration pod mid-apply**: orchestrator (a) drops the schema, (b) launches the migration Job, (c) kills the Job pod after the binlog shows exactly one of M4's eight `CREATE TABLE`s has committed (i.e. mid-revision, not between revisions), (d) re-runs the Job. Assertions: the second Job exits 0, every M0–M5 schema object is present and correct, no `1050 Table already exists` / `1061 Duplicate key name` / `1826 Duplicate foreign key constraint name` errors are logged. This validates the project-wide robust-migration contract from `rebuild.md` §9 end-to-end and covers the M6 acceptance criterion below.

All three scenarios run as a Buildkite scheduled job once per week on staging. They are not gating for individual PRs (too slow, too noisy) but are gating for the cutover-candidate tag.

### Synthetic monitor

A standalone job in Canva's existing synthetics platform (Datadog/Pingdom-shaped), polling every 5 minutes:

- `GET /healthz` — assert 200 in < 500 ms.
- `GET /readyz` — assert 200 in < 1 s.
- A no-op chat send: `POST /api/chats` (creates an empty chat), then `DELETE /api/chats/{id}`. Asserts 200 + 204 in < 2 s round-trip.

Failures page the on-call rotation. Five-minute cadence is balanced against budget; finer granularity comes from the dashboard.

### Visual-regression CI

The visual-regression layer from `rebuild.md` § 8 Layer 4 spans every milestone — M1 ships 15 chrome + smoke baselines under `tests/visual-baselines/m1/`, M2 / M4 / M5 / M6 each add their own — so M6 owns the cross-milestone npm scripts, Makefile targets, and Buildkite wiring rather than each milestone re-inventing the workflow.

**npm scripts (`rebuild/package.json`).** Two new scripts complement the existing `test:e2e:smoke`:

- `test:visual` runs `playwright test --grep @visual` (matches every milestone's `@visual-m{n}` tag — M1's `visual-m1.spec.ts` already authors `@visual-m1`; M2 / M4 / M5 / M6 follow the same convention).
- `test:visual:update` runs `playwright test --grep @visual --update-snapshots` for the manual baseline refresh workflow (Git LFS-tracked PNGs under `tests/visual-baselines/**`).

**Makefile targets (`rebuild/Makefile`).** `make test-visual` and `make test-visual-update` delegate to the two npm scripts so the rebuild's command surface stays consistent with the M0 `test-unit` / `test-component` / `test-e2e-smoke` shape.

**Buildkite wiring.** A new path-filtered `:playwright: visual` step in `rebuild/.buildkite/rebuild.yml` (`if: build.changed_files =~ /^rebuild\/(frontend|backend)\//`) runs `make test-visual` against the deterministic compose stack — same shape as the existing `e2e-smoke` step, separate label so a baseline diff doesn't masquerade as a smoke failure. The step is **gating** for PRs that touch `rebuild/frontend/src/**` or `rebuild/frontend/tests/visual-baselines/**`; it remains informational (non-gating) for backend-only PRs to avoid spurious failures from incidental rendering noise on chrome the change can't have affected.

**Baseline refresh (manual workflow).** Per `rebuild.md` § 8 Layer 4 ("baselines updated via a manual workflow only"), `test:visual:update` is **never** auto-run by CI. The workflow is a Buildkite manual-trigger step (`block: "Refresh visual baselines"` in `rebuild.yml`) that runs `make test-visual-update` inside the CI Linux container image, commits the regenerated PNGs on a feature branch via Git LFS, and opens a PR titled `chore(visual): refresh baselines for {milestone}`. Reviewers diff the PNGs in GitHub's image-diff view; baselines never auto-merge. This same workflow is what M1 uses to backfill the 15 deferred PNGs under `tests/visual-baselines/m1/` (see [m1-theming.md § Visual regression](m1-theming.md)) and what every later milestone uses to refresh its own surfaces.

## Acceptance criteria

- [ ] OTel traces appear in Canva's tracing UI for FastAPI, SQLAlchemy, asyncmy, httpx, python-socketio, and APScheduler events, with `traceparent` correctly propagated across HTTP and through scheduler-originated calls.
- [ ] Logs are JSON-formatted in prod, every line carries `trace_id`, `span_id`, `correlation_id`, and route, and emails are tagged for downstream redaction.
- [ ] Grafana dashboard with all 11 SLO panels is committed, importable, and showing live data on staging.
- [ ] Per-user rate limits enforce against `X-Forwarded-Email`, including the token-counting bucket for chat completions; over-limit responses return `429` with `Retry-After`.
- [ ] All routes have an explicit timeout from the dispatch table; default catch-all is 15 s; SSE has a 5-min hard cap; the scheduler tick uses `MAX_EXECUTION_TIME(2000)`.
- [ ] `TRUSTED_PROXY_CIDRS` is required in prod; a request from outside the allowlist has its `X-Forwarded-Email` header stripped before reaching the auth dependency. Explicitly tested by `tests/integration/test_trusted_proxy.py::test_spoofed_header_outside_cidr_is_stripped` which: (a) sends `X-Forwarded-Email` from an IP inside `TRUSTED_PROXY_CIDRS` and asserts a 200 with the expected `User`, (b) sends the same header from an IP outside the allowlist and asserts the request reaches the route without `request.scope["headers"]` containing `x-forwarded-email`, resulting in a 401. The same test asserts the `security.trusted_proxy.miss` log line is emitted with the source IP redacted.
- [ ] CORS is locked to `settings.CORS_ALLOW_ORIGINS`; security headers (CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy) are present on every response and verified by an E2E.
- [ ] File upload rejects non-allowed MIME types, mismatched declared/sniffed types, and files > 5 MiB.
- [ ] Webhook tokens are stored as SHA-256 hashes; plaintext appears only in the creation response.
- [ ] SSE keep-alive and socket.io `ping_interval` both wired to `STREAM_HEARTBEAT_SECONDS` (M0 constant; default 15 s); socket.io `ping_timeout = 2 * STREAM_HEARTBEAT_SECONDS`; idle disconnect at 30 min. No hard-coded heartbeat cadence anywhere in the codebase (verified by `rg -n "ping_interval=|keep-alive.*15"` returning only the constant import).
- [ ] Buildkite pipeline lints, tests, builds, pushes, and deploys to staging on every main commit; promotes to prod via manual unblock.
- [ ] `alembic upgrade head` runs as a pre-upgrade Helm Job and gates the rollout. The Job is operator-rerunnable: a chaos test that kills the Job pod after exactly one of M4's eight `CREATE TABLE`s has committed, then re-applies the same Helm release, completes the migration on the retry without manual schema repair (covered by an M6 chaos scenario in `rebuild/backend/tests/chaos/test_migration_partial_apply.py`).
- [ ] **No DB password is rendered into a `Secret` in any environment.** Both the runtime `Deployment` and the migration `Job` bind to IRSA / Pod Identity-annotated `ServiceAccount`s; the M0 IAM auth helper mints `rds:GenerateDBAuthToken` per physical connection. Verified by (a) `grep -RIn 'DATABASE_PASSWORD\|MYSQL_PASSWORD' rebuild/infra/k8s/` returning no results, (b) `helm template rebuild/infra/k8s -f values-prod.yaml | yq '.. | select(has("env")) | .env[] | select(.name | test("PASSWORD"))'` returning empty, and (c) a smoke check on staging that `kubectl exec` into a runtime pod and running `python -c "import os; assert 'DATABASE_PASSWORD' not in os.environ"` exits 0.
- [ ] Smoke E2E pack passes against staging and prod post-deploy; failure rolls back automatically.
- [ ] k6 load test holds SLOs at modelled-peak QPS for 10 min on staging.
- [ ] Chaos kill-mid-stream and kill-mid-automation tests pass on staging.
- [ ] Synthetic monitor active, alerting to on-call on failure.
- [ ] Cutover runbook reviewed and dry-run on staging once before cutover day.
- [ ] In-product banner copy ships before T-0 and auto-disables 14 days later.
- [ ] Visual-regression baselines `error-banner.png` and `rate-limited-toast.png` captured under `rebuild/frontend/tests/visual-baselines/m5/` (Git LFS) covering the M6-introduced error/banner surfaces; the smoke pack consumes the same baselines.

## M1 follow-ups

The M1 plan deferred a single UX item that has no good earlier landing zone (M0 ships no command palette, M2 ships no command palette, M3–M5 introduce no global keyboard surface). It lands here as polish, not as a correctness gate.

- **Theme picker command-palette entry.** M1 ships the picker UI in Settings plus the `themeStore.setTheme(id)` / `themeStore.clearChoice()` actions; per [m1-theming.md § Deliverables](m1-theming.md) the picker's docstring carries a `Cmd-K`-shaped TODO awaiting a host palette. If a command palette is introduced in M6 (as part of the polish surface) or in any later milestone, wire it to expose the picker as `Theme: Tokyo Day | Storm | Moon | Night | Match system`, dispatching to the same M1 store actions — no separate code path; the M1 deliverable bullet is already written against this contract. Theme switching from Settings continues to work without it; this is a discoverability improvement, not a correctness gate. If no command palette ships in M6 either, the TODO carries forward into post-M6 polish work and the M1 docstring stays the canonical reminder.

## Out of scope

- **No data migration tool.** The decision is locked: empty-slate. We do not write a chat exporter, a channel-history dumper, an automation-config carrier, or any kind of bridge ETL. (`rebuild.md` section 9.)
- **No read-only freeze of legacy data on cutover** beyond the proxy-level mutation block; the legacy DB is not ALTER'd.
- **No parallel run period.** The new service is not exposed at a peer URL alongside the legacy service before cutover; staging is the only pre-cutover environment.
- **No per-team rollout, no canary by user cohort, no feature flag controlling new-vs-old.** Single big-bang switch at the proxy layer.
- **No blue/green between two prod deployments of the rebuild itself.** Standard rolling update via Helm is enough.
- **No fancy SLO tooling** (Sloth, OpenSLO controllers). Plain Grafana alerts plus PagerDuty paging is the bar.
- **No JWT, API keys, or user-managed tokens** — the trusted-header model from `rebuild.md` section 3 is unchanged. The only token-shaped credentials in the system are share tokens (M3) and webhook tokens (M4).
- **No external object store** for files. MEDIUMBLOB-in-MySQL with the 5 MiB cap holds, per `rebuild.md` section 9.
- **No multi-region deployment.** Single-region prod (us-east-1) until/unless the platform team mandates otherwise.
- **No automated user-facing migration of bookmarks, browser caches, or saved share URLs** from the legacy domain. The 301 redirect from `openwebui.canva-internal.com/...` (legacy URL shape) → `archive.openwebui.canva-internal.com/...` covers GET; mutating verbs hit the read-only proxy and 405.

- **No InnoDB Cluster, Group Replication, or MySQL Router.** The rebuild ships against a **single managed MySQL 8.0 instance** (snapshot backups + binlog-based PITR are the platform team's responsibility, confirmed via `rebuild.md` § 9). HA at internal scale doesn't justify the operational complexity of multi-primary or single-primary group replication, and MySQL Router would add a hop with no payoff for our access pattern. Revisit only if the platform team mandates it.

- **No full-text search via `FULLTEXT` index or the `ngram` parser.** M2's sidebar `?q=` uses `LIKE %q%` on `title` plus `JSON_SEARCH(LOWER(history), ...)`. Benchmarks (`stackoverflow.com/q/72444384`) show the `ngram` parser actually loses to `LIKE` for chat-style substring queries because token overhead grows with query length. Revisit if M6 perf reveals a real bottleneck and the surface is actually used.

- **No `JSON_TABLE`, window functions, hash-join hints, or `LATERAL` derived tables in the application query path.** None of the M0–M6 workloads benefit; the optimiser picks hash join automatically when appropriate. Trust the planner. Revisit only if a concrete query plan demonstrates a need.

- **No multi-valued indexes (`MEMBER OF` / `JSON_CONTAINS`).** They would be relevant if `channel_message.content` collapsed reactions into a JSON array, which it explicitly does not (M4 keeps `channel_message_reaction` as a separate row table). The MVI question is therefore moot until the schema changes, and the schema is not changing.

- **No histograms (`ANALYZE TABLE ... UPDATE HISTOGRAM`).** Useful for low-cardinality columns where indexes don't help, but the rebuild's hot lookups all combine `user_id` (high cardinality) with another column in a composite index. Revisit if `EXPLAIN ANALYZE` shows estimate skew on a low-cardinality column we don't already index.

- **No `BINARY(16)` UUID storage with `UUID_TO_BIN(?, 1)`.** All identifiers stay `VARCHAR(36)` UUIDv7 strings (M0 § ID and time helpers, plus the new `rebuild.md` § 9 decision). The storage halving and InnoDB B-tree locality benefits would be real, but UUIDv7 already provides the locality wins (its leading 48-bit timestamp clusters inserts naturally) and the SQLAlchemy `TypeDecorator` + every-call `BIN_TO_UUID` cost on every log line and JSON payload doesn't pay back at internal scale. Revisit if `chat` exceeds ~10M rows or the M6 hardening benchmarks flag secondary-index bloat as the bottleneck.

## Open questions

1. **Deploy substrate.** This plan assumes Kubernetes + Helm because that is the dominant pattern at Canva for FastAPI services and matches the shape of the existing legacy `Dockerfile` + ECR push. If the actual target is ECS/Fargate, an Argo Rollouts pipeline, or a Spinnaker config, the artefacts under `rebuild/infra/k8s/` are a kustomize overlay or a Spinnaker `pipeline.json` instead — the rest of the plan (image tags, migration Job, smoke gating, rollback flow) is substrate-agnostic. **Owner**: platform on-call to confirm at the start of M6.
2. **Legacy archive duration.** The plan assumes a 30-day read-only archive, after which the legacy DB snapshot is retained per standard policy but the UI is taken down. If compliance or product wants a longer (90-day, 1-year) archive UI, the only delta is keeping the read-only proxy + DB up — no work required from this milestone, but the ops cost lands on whoever owns the budget. **Owner**: data governance, by T-2 weeks.
3. **Whether to retain a DB snapshot for compliance beyond standard retention.** Chat content can include sensitive prompts and outputs; some teams may have compliance/audit reasons to keep the snapshot longer than the default. If yes, store under `s3://canva-data-retention/openwebui-legacy-final-{date}.sql.gz` per the platform team's encryption-at-rest standards. **Owner**: legal + data governance, by T-2 weeks. Default if no answer: standard retention only.
