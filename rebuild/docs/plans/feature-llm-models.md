# Feature — Local dev agent platform (Pydantic AI + Ollama)

> **Authoritative parents:** [rebuild.md](../../../rebuild.md) § 2 (Target architecture) and § Provider abstraction; [rebuild/docs/plans/m2-conversations.md](m2-conversations.md) § Provider abstraction; [rebuild/docs/best-practises/FastAPI-best-practises.md](../best-practises/FastAPI-best-practises.md) § B.4 (Single `OpenAICompatibleProvider` instance). Where this file conflicts with those, those win.
> **Scope:** dev-loop only. Zero changes to the rebuild's runtime backend, runtime image, or production deploy. The deliverable is a new compose service (`agent-platform`) plus a small Ollama sibling that gives `make dev` a working models dropdown and streaming chat without anyone needing to set an OpenAI token.

## Goal

After this lands, a developer who has just cloned the repo runs `make dev`, opens `http://localhost:5173`, and immediately sees a populated model dropdown with one local agent (`dev`, backed by `qwen2.5:0.5b`). They pick it, type "hello", and watch tokens stream into the conversation view exactly as they would with a real internal model gateway. Free-form prompts work. Streaming, cancel, persistence, the SSE event taxonomy, and the model-validation 400 path are all exercised against a real OpenAI-compatible upstream — only the upstream is local Ollama instead of the production gateway.

The runtime backend is **not modified**. `OpenAICompatibleProvider` does not learn about Ollama, Pydantic AI, or any new model id. It continues to talk OpenAI HTTP at `MODEL_GATEWAY_BASE_URL`; the only thing that changes is what's listening on the other end of that URL in the dev compose stack. This preserves the locked single-provider constraint from [rebuild.md § 2](../../../rebuild.md) and [FastAPI-best-practises.md § B.4](../best-practises/FastAPI-best-practises.md).

The agent platform is **not used in tests**. The cassette mock at [rebuild/backend/tests/llm_mock.py](../../backend/tests/llm_mock.py) remains the deterministic upstream for backend integration tests and the MSW handlers in [rebuild/frontend/src/lib/msw/handlers.ts](../../frontend/src/lib/msw/handlers.ts) remain the upstream for frontend unit/component/E2E tests. Mixing real LLM output into CI would make the suite non-deterministic and slow.

The naming (`agent-platform`, not `dev-gateway`) is forward-looking: today the service ships one Pydantic-AI `Agent` per surfaced model id with no system prompt and no tools, but the registry shape (`MODELS: list[ModelDef]` with one Agent per entry) supports multiple personas / tool-using agents on top of the same underlying model id without touching the OpenAI-compat translation layer. M2 ships one agent; future surfaces (M5 dev-mode automations, smoke harnesses) extend the catalog by adding `ModelDef` entries.

## Deliverables

- A self-contained Python service at [rebuild/infra/agent-platform/](../../infra/agent-platform/) — own `pyproject.toml`, own `uv.lock`, own `Dockerfile`. **No shared deps with `rebuild/backend/`.** The runtime image MUST NOT pick up `pydantic-ai` or any LLM-related transitives; this directory is built into a separate image that only the dev compose references.
- The platform FastAPI app at [rebuild/infra/agent-platform/app/main.py](../../infra/agent-platform/app/main.py), [app/oai_router.py](../../infra/agent-platform/app/oai_router.py), [app/oai_models.py](../../infra/agent-platform/app/oai_models.py), [app/agents.py](../../infra/agent-platform/app/agents.py), [app/config.py](../../infra/agent-platform/app/config.py).
- Compose additions in [rebuild/infra/docker-compose.yml](../../infra/docker-compose.yml): two new services (`ollama`, `agent-platform`); `app` service gains `MODEL_GATEWAY_BASE_URL=http://agent-platform:8081/v1` and `depends_on: agent-platform`. The `ollama` service uses an entrypoint wrapper that fronts `ollama serve` with a one-shot `ollama pull qwen2.5:0.5b` so model availability and daemon readiness are gated by a single healthcheck — see § Compose wiring for the rationale of folding the pull into the daemon entrypoint instead of running it as a separate init container.
- One Makefile target tweak: `make dev` continues to bring the whole stack up (no new target needed); the existing `make verify-stack` target is extended to curl `/api/models` and assert at least one model is returned. Cold-start `verify-stack` now pays the one-time `qwen2.5:0.5b` pull (~400 MB) so the wall-clock budget for a fresh CI runner grows from ~30 s to ~3-5 minutes; subsequent runs (cached layer + cached `ollama_models` volume) stay at the existing budget. Document this in the Makefile target's leading comment so a future "verify-stack got slower" investigation lands at the right cause.
- One paragraph **appended below** the existing `MODEL_GATEWAY_BASE_URL` / `MODEL_GATEWAY_API_KEY` block in [rebuild/backend/.env.example](../../backend/.env.example) documenting that the dev compose stack provides this automatically and how to override it (e.g. point at a real internal gateway, LM Studio, or vLLM). The existing two-line block stays — it documents the prod sidecar contract and the `SecretStr` semantics on `MODEL_GATEWAY_API_KEY`; the new paragraph adds the dev-loop story without touching the prod documentation.
- Optional standalone `make dev-rebuild-models` target for refreshing the local model cache on demand (recreates the `ollama` container so its entrypoint wrapper re-runs the pull on next boot — `ollama pull` itself is idempotent on cache hit, so this is mostly useful when the named volume has been wiped or a model spec changed).
- Platform-side unit tests at [rebuild/infra/agent-platform/tests/](../../infra/agent-platform/tests/) covering: the OpenAI request → Pydantic AI translation, the SSE chunk emitter, the model registry, and the `/v1/models` shape. **Run independently of the backend pytest suite** via a separate `uv run --project infra/agent-platform pytest` invocation; not wired into `make test-unit`.
- One smoke test at [rebuild/infra/agent-platform/tests/test_smoke_compose.py](../../infra/agent-platform/tests/test_smoke_compose.py), pytest-marked `@pytest.mark.compose`, that brings up the full stack, curls `GET http://localhost:8080/api/models` (through the rebuild's app, not directly), and asserts the configured model ids appear. **Skipped by default**; runs under `make verify-stack`.
- Brief plan-keeper update to [rebuild.md](../../../rebuild.md) § 2 (Target architecture) noting that the dev compose stack ships a local OpenAI-compatible upstream so model discovery works out-of-the-box. The locked sentence ("OpenAI-compatible only, single provider. The internal model gateway is the sole upstream") is unchanged — the agent platform is upstream infra (same category as MySQL and Redis), not a second provider class in the runtime backend.
- One-line `label` plumbing in [rebuild/backend/app/providers/openai.py](../../backend/app/providers/openai.py): change line 110 from `label=m.id` to `label=getattr(m, "label", None) or m.id` so non-id labels emitted by an OpenAI-compatible upstream survive the round trip into the rebuild's `ModelInfo.label` field. The OpenAI Python SDK's `Model` object already accepts arbitrary extra fields and exposes them via attribute access, so the `getattr` shim is forward-compatible with both the agent platform (which emits `label`) and the production internal gateway (which doesn't, today, and falls through cleanly to `m.id`). This is the **only** change the feature plan makes under `rebuild/backend/`; tightly scoped, zero-risk, and required for the friendly label to actually surface in the dropdown — without it the dev user sees `dev` instead of `Dev (Qwen 2.5, 0.5B)`. Covered by a one-line addition to the existing [rebuild/backend/tests/integration/test_models_cache.py](../../backend/tests/integration/test_models_cache.py): a `cassette_mock_app` whose `/v1/models` returns an entry with both `id` and `label` should round-trip the `label` through `cache.get()`.

## Why a separate service (not reuse the test mock, not point straight at Ollama)

Three options were on the table; this plan locks the third.

| Option | Why not |
|---|---|
| **A. Extend the cassette mock** to serve a stub echo on cassette-miss | Couples test fixtures to dev runtime. The mock has no concept of a real model and cannot answer free-form prompts plausibly. Conflates two purposes. |
| **B. Point `MODEL_GATEWAY_BASE_URL` straight at vanilla Ollama's `/v1`** | Ollama already speaks OpenAI HTTP, so this works mechanically. But: model ids are then whatever tag was pulled (e.g. `qwen2.5:0.5b`), the dropdown is polluted with every random model the developer ever pulled into Ollama, and there is no place to land future affordances (per-model system prompts, Pydantic-AI tool wiring, friendly labels, agent-style behaviour). |
| **C. Pydantic-AI agent platform in front of Ollama (this plan)** | One narrow service that owns the curated model list, the friendly labels, the OpenAI wire format, and a Pydantic AI `Agent` per surfaced "model". Future features (M5 dev-mode automations, smoke harnesses) ride on the same surface. Costs one small image and one config file. |

The reference for the Pydantic AI → OpenAI compat translation is [`samreay-agents-platform/packages/ui/src/ui/oai_router.py`](file:///Users/samreay/repos/samreay-agents-platform/packages/ui/src/ui/oai_router.py); we pull the streaming `agent.iter()` shape, the `ChatCompletionChunk` emitter, and the `/v1/models` `ModelObject` shape from there, but we **do not** import that module — it has agent-registry coupling we don't need. Translate the patterns, ship a fresh implementation here.

## Architecture

```
rebuild dev compose
                                  ┌──────────────────────────────────────┐
                                  │          MODEL_GATEWAY_BASE_URL       │
                                  │     http://agent-platform:8081/v1     │
                                  └──────────────┬───────────────────────┘
                                                 │
       ┌────────────┐  /v1/models             ┌──▼─────────────┐  /api/chat       ┌────────────────────┐
       │  app       │  /v1/chat/completions   │ agent-platform │  (Ollama native) │  ollama            │
       │  (FastAPI  │ ──────────────────────► │  (FastAPI +    │ ───────────────► │  entrypoint:       │
       │   rebuild) │ ◄────── SSE stream ──── │   Pydantic AI) │ ◄── SSE stream ─ │   ollama serve     │
       └────────────┘                         └────────────────┘                  │   + initial pull   │
                                                                                  │  (qwen2.5:0.5b)    │
                                                                                  └─────┬──────────────┘
                                                                                        │
                                                                                        │ volume:
                                                                                        │ ollama_models
                                                                                        ▼
                                                                                  (model cache)
```

Locked decisions:

- **Two new compose services**, both marked as dev-only by their dependence on `infra/agent-platform/`:
    - `ollama` — `ollama/ollama:0.5.7` image with an entrypoint wrapper that backgrounds `ollama serve`, waits for the daemon to answer `/api/tags`, runs `ollama pull qwen2.5:0.5b` (no-op when the named volume `ollama_models` already has the layer), then `wait`s on the daemon PID so the container's lifecycle stays tied to the serve process. The healthcheck explicitly grep's the model name out of `/api/tags` so "healthy" means *both* daemon-up *and* model-cached — a single signal the agent platform can `depends_on`.
    - `agent-platform` — our Pydantic-AI wrapper. Built from `infra/agent-platform/Dockerfile`. Listens on container port `8081`. Talks to Ollama at `http://ollama:11434`.
- The rebuild's `app` service gets two changes: `MODEL_GATEWAY_BASE_URL: http://agent-platform:8081/v1` in `environment:`, and `agent-platform: { condition: service_healthy }` added to `depends_on:`.
- **Why the pull lives in the `ollama` entrypoint, not a separate `ollama-pull` init container.** A separate init container would surface a slightly cleaner failure mode for pull errors (a distinct exit code with its own log stream), but it triples the service count and adds a `condition: service_completed_successfully` dependency that compose v2 still warns about. Folding the pull into the daemon entrypoint with a model-name-grep healthcheck collapses both signals (daemon up + model present) into one and makes the topology two services instead of three. Pull failures (network / disk-full) surface as a healthcheck timeout, which prints the daemon's stderr in `docker logs rebuild_ollama` — discoverable, just not as labelled.
- **The model id surfaced through `GET /api/models` is a stable alias** (M2 ships `dev`; future personas land as `dev-pirate`, `dev-coder`, …), not the underlying Ollama tag. The mapping lives in the platform's config and is the only place that knows about `qwen2.5:0.5b`. This shields the rebuild's frontend from "what tag did the developer happen to pull" churn and makes the future "multiple agents, one model" trajectory a config edit, not a code edit.
- **Friendly labels** (`label: "Dev (Qwen 2.5, 0.5B)"`) come from the same platform config and surface through the rebuild's existing `ModelInfo.label` field ([rebuild/backend/app/schemas/model.py](../../backend/app/schemas/model.py)). The provider's `list_models()` currently sets `label = m.id`; this PR ships the one-line `getattr(m, "label", None) or m.id` plumbing alongside the agent-platform service so the friendly label is visible in the dropdown on day one. See the matching Deliverables bullet for the exact diff.
- **Streaming uses Pydantic AI's `agent.iter()` over `agent.run_stream()`** so the full agentic loop is available to future features (tool calls, structured output) without a second rewrite. For M2 there are no tools; the loop just yields text deltas.
- **The platform is stateless.** No conversation store, no per-user history. The rebuild's backend already owns the message tree and sends the full prior history on every turn; the platform just forwards it to Pydantic AI as `message_history`. This keeps the platform tiny and idempotent.

## File and directory layout

Everything new lives under `rebuild/infra/agent-platform/` except the compose edits and the one `.env.example` paragraph.

```
rebuild/
  infra/
    docker-compose.yml                 # MODIFY: add ollama (with pull-on-boot entrypoint), agent-platform services + env on app
    agent-platform/
      README.md                        # one-pager: what this is, how to swap models, why it's not in tests
      Dockerfile                       # multi-stage: uv deps -> slim runtime
      .dockerignore                    # excludes tests/, .venv, __pycache__
      pyproject.toml                   # platform-only deps: fastapi, uvicorn, pydantic-ai==1.88.0, pydantic-settings, httpx
      uv.lock                          # platform-only lock; never shared with backend/
      app/
        __init__.py
        main.py                        # FastAPI factory + lifespan (Ollama health probe + Pydantic AI agent build)
        config.py                      # Settings: OLLAMA_BASE_URL, MODELS (json), HOST, PORT, LOG_LEVEL
        oai_router.py                  # /v1/models, /v1/chat/completions (stream + non-stream)
        oai_models.py                  # ChatCompletionRequest/Response/Chunk + ModelInfo/Object/List
        agents.py                      # Pydantic-AI Agent factory keyed by model alias
      tests/
        __init__.py
        conftest.py                    # bare-FastAPI factory + TestClient; per-test pydantic-ai TestModel/FunctionModel
        test_oai_models.py             # ChatCompletionRequest accepts the OpenAI shape rebuild's SDK sends
        test_oai_router_models.py      # /v1/models returns the configured aliases with the documented shape
        test_oai_router_chat.py        # /v1/chat/completions stream=True yields the OpenAI chunk format
        test_oai_router_nonstream.py   # /v1/chat/completions stream=False returns the non-streaming envelope
        test_agents.py                 # alias->ollama tag mapping, unknown alias raises 404
        test_smoke_compose.py          # @pytest.mark.compose: bring up the stack, curl through rebuild app
  backend/
    .env.example                       # MODIFY: add paragraph under MODEL_GATEWAY_BASE_URL
  Makefile                             # MODIFY: extend verify-stack to curl /api/models and assert non-empty
```

## Component-by-component

### Project-wide conventions (applied to every file below)

[FastAPI-best-practises.md](../best-practises/FastAPI-best-practises.md) formally scopes itself to `rebuild/backend/app/`, but the agent platform follows the same conventions even though it's a separate Python project under `rebuild/infra/`. Specifically:

- Logging via `logging.getLogger(__name__)`. No `print(...)` anywhere.
- Errors via `HTTPException(status_code=...)` for client-facing failures; `raise RuntimeError(...)` only for startup-time invariant violations (the lifespan probe).
- No business logic in dependencies; the dependency layer reads `request.app.state.agents` and that's it.
- `Settings(BaseSettings)` follows the rebuild's UPPER_SNAKE_CASE convention from [m0-foundations.md § Settings(BaseSettings)](m0-foundations.md#settingsbasesettings) "Casing convention (locked)" — every config attribute matches its env var name verbatim.
- No background tasks spawned without a strong local reference (per [FastAPI-best-practises.md § A.8](../best-practises/FastAPI-best-practises.md)). The platform has no long-lived background tasks today; if a future change adds one, hold its handle on `app.state` so the GC doesn't reap it.
- **UUIDv7 everywhere, no `uuid.uuid4()`.** Even though the platform never writes to MySQL (so the InnoDB clustered-PK locality argument from [rebuild.md § 9 Decisions (locked)](../../../rebuild.md#9-decisions-locked) doesn't apply), we mirror the project-wide ban on `uuid4` so a future contributor doesn't reach for it on autocomplete. OpenAI completion ids look like `chatcmpl-{36-char-uuidv7}` (a few chars longer than OpenAI's own opaque ids, but the field is opaque to every caller including the rebuild — `id` is never parsed). The `uuid7-standard` dep + the ruff `banned-api` rule in `pyproject.toml` enforce this.

These are deliberately re-stated here so a future change to the agent platform doesn't drift from the rebuild's conventions on the basis of "the best-practises doc doesn't formally cover us".

### `infra/agent-platform/pyproject.toml`

Self-contained, no `uv.sources` pointing at the backend. The platform is a separate Python project that compose builds in isolation. Pin versions explicitly (rebuild convention from [m0-foundations.md § Dependencies](m0-foundations.md#dependencies-with-versions)):

```toml
[project]
name = "agent-platform"
version = "0.0.0"
requires-python = ">=3.12"
dependencies = [
  # Ranges, not exact pins, because pydantic-ai==1.88.0 transitively requires
  # pydantic>=2.12 + starlette>=0.45.3 — fastapi==0.115.0 (the rebuild backend's
  # pin) caps starlette below that. The locked decision (§ Decisions locked,
  # item 4) keeps pydantic-ai itself exact-pinned; the surrounding stack widens
  # just enough to satisfy its resolver. agent-platform is a self-contained
  # Python project with its own uv.lock, so the wider ranges do NOT leak into
  # rebuild/backend/.
  "fastapi>=0.118,<0.120",
  "uvicorn[standard]>=0.32.0,<0.40",
  "pydantic>=2.12,<3",
  "pydantic-ai==1.88.0",
  "pydantic-settings>=2.6.0,<3",
  "httpx>=0.27.2,<1",
  "uuid7-standard >=1.1,<2",     # UUIDv7 — same dep + version range as rebuild/pyproject.toml
]

[dependency-groups]
dev = ["pytest==8.3.3", "pytest-asyncio==0.24.0", "respx==0.21.1"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = ["compose: smoke test that requires the full docker stack"]

# Mirror the rebuild backend's UUIDv7 ban on uuid.uuid4 so the platform's
# completion id helper can't drift back to v4 on a future contributor's
# autocomplete. The ban is per-project (no shared ruff config inheritance
# from rebuild/pyproject.toml — agent-platform is a self-contained Python
# project) and is the only ruff lint we wire here.
[tool.ruff.lint.flake8-tidy-imports.banned-api]
"uuid.uuid4".msg = "Use uuid7.create() (UUIDv7) instead. Mirrors rebuild/pyproject.toml; see rebuild.md §9."
```

The `pydantic-ai` dep is **platform-local**. It MUST NOT appear in `rebuild/pyproject.toml` (the backend's project file). Add a new grep gate chained off `make lint` (mirroring the frontend `lint:grep` pattern from [m0-foundations.md § Frontend conventions](m0-foundations.md#frontend-conventions-cross-cutting), rule 4): a one-line shell check that `rg "pydantic[-_]ai" rebuild/backend` returns no matches and a non-zero exit. There is no existing backend custom-lint hook today; this PR adds the first one.

### `infra/agent-platform/Dockerfile`

Same multi-stage shape as the rebuild's runtime Dockerfile but slimmer (no frontend stage, no MySQL client headers). Non-root user, healthcheck on `/healthz`.

```dockerfile
FROM python:3.12.7-slim-bookworm AS pydeps
WORKDIR /work
RUN pip install --no-cache-dir uv==0.5.5
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.12.7-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8081
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 app && \
    useradd  --system --uid 10001 --gid app --home-dir /app --shell /bin/false app
WORKDIR /app
COPY --from=pydeps /work/.venv /app/.venv
COPY app /app/app
ENV PATH="/app/.venv/bin:${PATH}" PYTHONPATH="/app"
USER app
EXPOSE 8081
HEALTHCHECK --interval=10s --timeout=3s --retries=10 \
  CMD curl -fsS http://localhost:${PORT}/healthz || exit 1
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081"]
```

Two divergences from the backend Dockerfile worth noting:

- No `default-libmysqlclient-dev` / `build-essential` — platform has no DB driver.
- Python `python -m uvicorn` invocation matches the rebuild's existing decision (the venv shebangs aren't portable across COPY boundaries; see `rebuild/Dockerfile` lines 28-38).

### `infra/agent-platform/app/config.py`

Standard `Settings(BaseSettings)`, mirrored UPPER_SNAKE_CASE per [m0-foundations.md § Settings(BaseSettings) "Casing convention (locked)"](m0-foundations.md#settingsbasesettings).

```python
from __future__ import annotations
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelDef(BaseModel):
    """A surfaced model. ``id`` is the stable alias the rebuild sees;
    ``ollama_tag`` is what the platform pulls + asks Ollama to run."""

    id: str
    label: str
    ollama_tag: str
    owned_by: str = "agent-platform"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    OLLAMA_BASE_URL: str = "http://ollama:11434"
    HOST: str = "0.0.0.0"
    PORT: int = 8081
    LOG_LEVEL: str = "INFO"

    # Default catalog. Override at compose-time via MODELS env var
    # holding a JSON list of ModelDef shapes.
    MODELS: list[ModelDef] = [
        ModelDef(id="dev", label="Dev (Qwen 2.5, 0.5B)", ollama_tag="qwen2.5:0.5b"),
    ]


settings = Settings()
```

`MODELS` is overridable from compose so an individual developer can add e.g. a coder persona without editing the platform's source. Compose default ships exactly one entry; future personas land as additional `ModelDef` entries pointing at the same `qwen2.5:0.5b` tag with different ids and labels (and, when the API surfaces it, different system prompts).

### `infra/agent-platform/app/agents.py`

One Pydantic-AI `Agent` per configured model alias, built once at startup and cached on `app.state.agents`. `pydantic-ai==1.88.0`'s `OpenAIModel` constructor accepts an `OpenAIProvider(base_url=...)` so we point each Agent at the local Ollama daemon's `/v1` endpoint.

```python
from __future__ import annotations
from dataclasses import dataclass

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.config import ModelDef, Settings


@dataclass(slots=True)
class AgentEntry:
    definition: ModelDef
    agent: Agent[None, str]


def build_agents(settings: Settings) -> dict[str, AgentEntry]:
    """Construct one Agent per configured model. Called once from
    ``lifespan``; the result is cached on ``app.state.agents``.
    """
    provider = OpenAIProvider(base_url=f"{settings.OLLAMA_BASE_URL}/v1", api_key="ollama")
    out: dict[str, AgentEntry] = {}
    for defn in settings.MODELS:
        model = OpenAIModel(defn.ollama_tag, provider=provider)
        out[defn.id] = AgentEntry(definition=defn, agent=Agent(model=model, output_type=str))
    return out
```

Locked: **no system prompt is set on the Agent.** The rebuild's streaming pipeline already prepends any `params.system` into `messages[0]` before the HTTP call (see `rebuild/backend/app/providers/openai.py::OpenAICompatibleProvider.stream` lines 121-123); a system prompt baked into the Agent here would double-stack. When future `ModelDef` entries want a persona-style system prompt, the `Agent(...)` constructor takes a `system_prompt=` kwarg — the implementer wires it through then, gated on a new optional `ModelDef.system_prompt` field, with a comment pointing at this paragraph as the rationale for why M2 ships without it.

### `infra/agent-platform/app/oai_models.py`

Pydantic models for the OpenAI wire shape. Crib directly from the reference `oai_models.py` with the slimming pass below — the reference carries `ConfigDict(extra="allow")` because Open WebUI sends extra fields; we accept the same since the OpenAI SDK adds telemetry headers and the occasional `stream_options` field.

```python
from __future__ import annotations
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str = "stop"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: Usage = Usage()


class DeltaContent(BaseModel):
    role: str | None = None
    content: str | None = None


class ChunkChoice(BaseModel):
    index: int = 0
    delta: DeltaContent
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChunkChoice]


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str
    label: str  # non-OpenAI extension; rebuild reads via getattr(m, "label", None) — see § Deliverables


class ModelListResponse(BaseModel):
    object: str = "list"
    data: list[ModelInfo]
```

`ModelInfo.label` is **not** standard OpenAI — the OpenAI public spec for `Model` only defines `id`, `object`, `created`, `owned_by`. The OpenAI Python SDK (which the rebuild's provider uses as transport) still exposes any extra wire fields via attribute access, so the rebuild's `OpenAICompatibleProvider.list_models` reading `getattr(m, "label", None)` (the one-line plumbing change shipped by this PR — see § Deliverables) lights the friendly label up cleanly. The production internal gateway doesn't emit `label` today; the `getattr` shim falls through to `m.id` for that case so existing prod behaviour is unchanged.

### `infra/agent-platform/app/oai_router.py`

The two endpoints. Mirrors the reference [`oai_router.py`](file:///Users/samreay/repos/samreay-agents-platform/packages/ui/src/ui/oai_router.py) but with all the multimodal / image / icon / conversation-store paths stripped (we own none of that here). Key shape:

```python
from __future__ import annotations
import asyncio
import logging
import time
from collections.abc import AsyncIterator

import uuid7
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic_ai.messages import (
    ModelMessage, ModelRequest, ModelResponse,
    PartDeltaEvent, PartStartEvent, TextPart, TextPartDelta,
    UserPromptPart,
)

from app.agents import AgentEntry
from app.oai_models import (
    ChatCompletionChoice, ChatCompletionChunk, ChatCompletionRequest,
    ChatCompletionResponse, ChatMessage, ChunkChoice, DeltaContent,
    ModelInfo, ModelListResponse, Usage,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["openai-compat"])


def _now() -> int:
    return int(time.time())


def _completion_id() -> str:
    # UUIDv7 (not uuid4) per the project-wide rule — see this plan's
    # § Project-wide conventions and rebuild.md §9.
    return f"chatcmpl-{uuid7.create()}"


def _seed_history(messages: list[ChatMessage]) -> tuple[list[ModelMessage], str]:
    """Translate OpenAI messages → Pydantic-AI ``message_history`` + the
    last user prompt (which Pydantic-AI's ``agent.iter()`` takes as a
    separate argument). The system message, if present, is inlined into
    the first user prompt so we don't need a different agent per system
    string. The rebuild's provider already prepends ``params.system``
    into ``messages[0]`` before calling us, so in practice the system
    message arrives as a leading ``user``-role entry containing the
    concatenated prompt; we just need to handle the OpenAI ``system``
    role in case a future caller sends it raw.
    """
    history: list[ModelMessage] = []
    system_prefix = ""
    user_prompt = ""
    for msg in messages:
        if msg.role == "system":
            system_prefix = (system_prefix + "\n\n" + msg.content).strip()
        elif msg.role == "user":
            user_prompt = msg.content
            history.append(ModelRequest(parts=[UserPromptPart(content=msg.content)]))
        elif msg.role == "assistant":
            history.append(ModelResponse(parts=[TextPart(content=msg.content)]))
    if not user_prompt:
        raise HTTPException(status_code=400, detail="no user message in request")
    # Drop the last user message from history — Pydantic-AI's iter() takes
    # it via the user_prompt arg, sending it twice double-stacks the turn.
    if history and isinstance(history[-1], ModelRequest):
        history.pop()
    if system_prefix:
        user_prompt = f"{system_prefix}\n\n{user_prompt}"
    return history, user_prompt


@router.get("/models")
async def list_models(request: Request) -> ModelListResponse:
    agents: dict[str, AgentEntry] = request.app.state.agents
    now = _now()
    return ModelListResponse(
        data=[
            ModelInfo(
                id=entry.definition.id,
                created=now,
                owned_by=entry.definition.owned_by,
                label=entry.definition.label,
            )
            for entry in agents.values()
        ]
    )


@router.post("/chat/completions")
async def chat_completions(body: ChatCompletionRequest, request: Request):
    agents: dict[str, AgentEntry] = request.app.state.agents
    entry = agents.get(body.model)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown model: {body.model}")

    history, user_prompt = _seed_history(body.messages)

    if body.stream:
        return StreamingResponse(
            _stream_response(entry, body.model, user_prompt, history),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    result = await entry.agent.run(user_prompt=user_prompt, message_history=history)
    text: str = result.output
    usage = result.usage()
    return ChatCompletionResponse(
        id=_completion_id(),
        created=_now(),
        model=body.model,
        choices=[ChatCompletionChoice(message=ChatMessage(role="assistant", content=text))],
        usage=Usage(
            prompt_tokens=usage.request_tokens or 0,
            completion_tokens=usage.response_tokens or 0,
            total_tokens=usage.total_tokens or 0,
        ),
    )


async def _stream_response(
    entry: AgentEntry,
    model_id: str,
    user_prompt: str,
    history: list[ModelMessage],
) -> AsyncIterator[str]:
    """Yield SSE-formatted ChatCompletionChunk frames terminated by [DONE].

    Uses agent.iter() not agent.run_stream() so a future tool-using agent
    plugs in without rewriting this function.
    """
    cid = _completion_id()
    created = _now()

    yield (
        "data: "
        + ChatCompletionChunk(
            id=cid, created=created, model=model_id,
            choices=[ChunkChoice(delta=DeltaContent(role="assistant"))],
        ).model_dump_json()
        + "\n\n"
    )

    try:
        async with entry.agent.iter(user_prompt=user_prompt, message_history=history) as run:
            async for node in run:
                from pydantic_ai import Agent  # local import — pydantic-ai only on this path
                if not Agent.is_model_request_node(node):
                    continue
                async with node.stream(run.ctx) as request_stream:
                    async for event in request_stream:
                        text_delta = ""
                        if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                            text_delta = event.part.content or ""
                        elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                            text_delta = event.delta.content_delta or ""
                        if not text_delta:
                            continue
                        yield (
                            "data: "
                            + ChatCompletionChunk(
                                id=cid, created=created, model=model_id,
                                choices=[ChunkChoice(delta=DeltaContent(content=text_delta))],
                            ).model_dump_json()
                            + "\n\n"
                        )
    except asyncio.CancelledError:
        log.info("client disconnected mid-stream for model %s", model_id)
        raise

    yield (
        "data: "
        + ChatCompletionChunk(
            id=cid, created=created, model=model_id,
            choices=[ChunkChoice(delta=DeltaContent(), finish_reason="stop")],
        ).model_dump_json()
        + "\n\n"
    )
    yield "data: [DONE]\n\n"
```

Four things to call out:

- **No `usage` chunk in the streaming path.** OpenAI emits a final usage delta when the request includes `stream_options.include_usage=true` (which the rebuild's provider does — see [rebuild/backend/app/providers/openai.py](../../backend/app/providers/openai.py) line 129). Pydantic-AI's `agent.iter()` doesn't surface per-chunk usage cleanly through the node-stream events today; we accept the rebuild's `usage` event being absent on the dev path. The rebuild handles `delta.usage is None` already (its streaming pipeline gates on `if delta.usage:`), so a missing usage chunk is a no-op there. **Add a comment in the router** documenting this divergence and pointing at the relevant pydantic-ai issue if one exists at implementation time.
- **Cancellation** is handled by Starlette: when the client disconnects, FastAPI raises `CancelledError` inside the generator, which propagates through `agent.iter()`'s `async with` block and closes the upstream Ollama connection. We re-raise so Starlette does its own teardown.
- **No conversation persistence.** The reference saves messages into a `ConversationStore`; we explicitly do not — the rebuild's MySQL-backed `chat.history` is the source of truth, and the platform is stateless.
- **SSE emission is inlined here, not factored into a separate `sse.py` helper.** The leading (role) chunk, per-token deltas, and the final (`finish_reason="stop"` + `[DONE]`) chunks all use the same `"data: " + ChatCompletionChunk(...).model_dump_json() + "\n\n"` literal three times in `_stream_response()`. There is only one stream path and no second consumer of the helper, so the abstraction would be premature; revisit if a second SSE-emitting endpoint lands.

### `infra/agent-platform/app/main.py`

Standard factory + lifespan. Lifespan probes Ollama with a small retry loop so the platform fails its healthcheck if Ollama is genuinely unreachable, surfacing wiring bugs in `make dev` instead of letting them surface as a confused 502 in the rebuild's `/api/models` endpoint. Compose's `depends_on: ollama: { condition: service_healthy }` should make the probe a no-op in steady state, but a cold-start under load can still race the daemon's first-request warmup; the retry loop absorbs that without inflating the steady-state startup time.

```python
from __future__ import annotations
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.agents import build_agents
from app.config import settings
from app.oai_router import router as oai_router


_PROBE_TIMEOUT_SECONDS = 10.0
_PROBE_ATTEMPTS = 5
_PROBE_BACKOFF_SECONDS = 2.0


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Probe Ollama. Failing here surfaces wiring bugs at compose-up
    # time instead of at first /api/models call. Five attempts at 2 s
    # backoff covers Ollama's first-request warmup on a cold compose
    # boot without inflating happy-path startup.
    last_exc: Exception | None = None
    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as c:
        for attempt in range(_PROBE_ATTEMPTS):
            try:
                r = await c.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
                r.raise_for_status()
                last_exc = None
                break
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < _PROBE_ATTEMPTS - 1:
                    await asyncio.sleep(_PROBE_BACKOFF_SECONDS)
    if last_exc is not None:
        raise RuntimeError(
            f"agent-platform could not reach ollama at {settings.OLLAMA_BASE_URL} "
            f"after {_PROBE_ATTEMPTS} attempts: {last_exc}"
        ) from last_exc
    app.state.agents = build_agents(settings)
    yield


app = FastAPI(title="agent-platform", version="0.0.0", lifespan=lifespan)
app.include_router(oai_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

## Compose wiring

The diff to [rebuild/infra/docker-compose.yml](../../infra/docker-compose.yml) — two new top-level services, a new named volume, and two changes to the `app` block. The `ollama` service's healthcheck gates on the configured model being *present in `ollama list`*, not just on the daemon being up — so when `ollama` is reported healthy, the model is already cached and the agent platform can stream against it immediately.

> **Locked: use the in-image `ollama` CLI for both the readiness loop and the healthcheck — never `curl`.** The official `ollama/ollama:0.5.7` image ships **no HTTP client at all** (no `curl`, no `wget`, no `nc`, no `python`). A `curl`-based healthcheck fails immediately with `sh: 1: curl: not found` and the container is marked `unhealthy`; worse, a `curl`-based readiness loop in the entrypoint spins forever, so `ollama pull` never runs and the model is never cached. `ollama list` exits 0 once the daemon's local socket is up and piping it to `grep -q "<tag>"` produces a stable single-signal oracle (daemon-up AND model-cached). Both tools (`ollama`, `grep`) are in-image, so no custom Dockerfile is needed.

```yaml
services:
  # ... existing mysql, redis blocks unchanged ...

  ollama:
    image: ollama/ollama:0.5.7
    container_name: rebuild_ollama
    ports: ['11434:11434']     # exposed to host so a developer can `ollama list` etc.
    volumes:
      - ollama_models:/root/.ollama
    # Background `ollama serve`, wait for the daemon to answer, pull the
    # configured model (no-op on cache hit), then `wait` on the daemon PID
    # so the container's lifecycle stays tied to the serve process.
    # `set -e` makes a failed pull fail the entrypoint, which compose
    # surfaces via the healthcheck timeout below. The daemon's stderr goes
    # to the container log stream as normal.
    #
    # The readiness loop calls `ollama list`, NOT `curl`. The official
    # `ollama/ollama:0.5.7` image ships no HTTP client (see the locked
    # callout above this YAML block). `ollama list` exits 0 once the
    # daemon's local socket is up.
    #
    # Double-dollar (`$$`) escapes Compose's own variable interpolation pass
    # so the shell sees single-`$` correctly. Single-`$pid` would be eaten
    # at compose-render time (`pid` is unset there) and silently break the
    # `wait`. Verify the rendered command with `docker compose config`.
    entrypoint: ['/bin/sh', '-c']
    command:
      - |
        set -e
        ollama serve &
        pid=$$!
        until ollama list >/dev/null 2>&1; do sleep 0.5; done
        ollama pull qwen2.5:0.5b
        wait "$$pid"
    healthcheck:
      # Greps the model id out of `ollama list` so "healthy" implies both
      # daemon-up AND model-cached. The agent platform's depends_on chain
      # then needs only a single condition to gate startup. Uses CMD-SHELL
      # so the pipe is interpreted by sh inside the container; the image
      # has /bin/sh and grep but no curl, so the equivalent CMD-form
      # `['CMD', 'sh', '-c', 'curl ...']` would fail immediately.
      test: ['CMD-SHELL', 'ollama list | grep -q "qwen2.5:0.5b"']
      interval: 5s
      timeout: 3s
      retries: 60       # first-up pull of qwen2.5:0.5b is ~400 MB; 5 min budget at 5 s interval

  agent-platform:
    build:
      context: ./agent-platform
      dockerfile: Dockerfile
    container_name: rebuild_agent_platform
    environment:
      OLLAMA_BASE_URL: http://ollama:11434
      LOG_LEVEL: INFO
    depends_on:
      ollama: { condition: service_healthy }
    ports: ['8081:8081']        # exposed to host for `curl http://localhost:8081/v1/models` debugging
    healthcheck:
      test: ['CMD', 'curl', '-fsS', 'http://localhost:8081/healthz']
      interval: 5s
      timeout: 3s
      retries: 20

  app:
    # ...existing build / container_name unchanged...
    environment:
      ENV: dev
      DATABASE_URL: mysql+asyncmy://rebuild:rebuild@mysql:3306/rebuild?charset=utf8mb4
      REDIS_URL: redis://redis:6379/0
      MODEL_GATEWAY_BASE_URL: http://agent-platform:8081/v1   # <-- NEW
      TRUSTED_EMAIL_HEADER: X-Forwarded-Email
      CORS_ALLOW_ORIGINS: http://localhost:5173
    # ...command / ports unchanged...
    depends_on:
      mysql:           { condition: service_healthy }
      redis:           { condition: service_healthy }
      agent-platform:  { condition: service_healthy }       # <-- NEW

volumes:
  rebuild_mysql_data:
  ollama_models:                                            # <-- NEW
```

The agent-platform service is **always brought up**, even if a developer overrides `MODEL_GATEWAY_BASE_URL` to point at a real internal gateway. The agent-platform image is small and the `qwen2.5:0.5b` pull is a one-time ~400 MB cost; standing it up unconditionally keeps the compose topology static and avoids `--profile` flag wrangling. Document the first-time pull cost in the agent-platform `README.md` so the slow first-up is expected, not surprising.

## Settings additions

The rebuild's `Settings` class is **not** modified — the only change is the value of `MODEL_GATEWAY_BASE_URL` injected by compose. This is exactly the pattern locked in [m0-foundations.md § Settings](m0-foundations.md#settingsbasesettings) for environment-driven config.

The agent platform's own `Settings` class lives entirely under `infra/agent-platform/app/config.py` and is unrelated to the rebuild's settings module. They share zero code.

The one documentation change in [rebuild/backend/.env.example](../../backend/.env.example):

```bash
# ---- Model gateway (M2 streaming + /api/models) ----------------------------
# In dev compose this points at the local agent-platform service
# (Pydantic AI + Ollama, see infra/agent-platform/), which surfaces a
# curated set of small models (`dev`, backed by `qwen2.5:0.5b`) so the
# UI works out of the box with no external token. Override here to
# point at the real internal model gateway, LM Studio, vLLM, or any
# other OpenAI-compatible upstream:
#
#   MODEL_GATEWAY_BASE_URL=https://internal-gateway.canva.io/v1
#   MODEL_GATEWAY_API_KEY=...
#
# When unset, the AsyncOpenAI client falls back to https://api.openai.com/v1,
# which 401s without a real OpenAI key.
# MODEL_GATEWAY_BASE_URL=http://agent-platform:8081/v1
# MODEL_GATEWAY_API_KEY=
```

## API surface (agent platform)

All routes mounted under `/v1`. No auth (the platform is reachable only on the compose network plus the host loopback for debugging). The shapes match the OpenAI public API on every field the rebuild's `OpenAICompatibleProvider` reads (`id`, `owned_by`, the SSE chunk format with `delta.content` / `delta.usage` / `finish_reason`).

### `GET /v1/models`

Returns the configured `ModelDef` list. Each entry carries `id` (the alias) plus a non-standard `label` field the rebuild already understands.

```json
{
  "object": "list",
  "data": [
    { "id": "dev", "label": "Dev (Qwen 2.5, 0.5B)", "object": "model", "created": 1730000000, "owned_by": "agent-platform" }
  ]
}
```

### `POST /v1/chat/completions`

Accepts the OpenAI request shape (`{model, messages, stream, temperature, ...}`). Extra fields are accepted (`extra="allow"`) since the rebuild's provider sends `stream_options` and `temperature` and may add more in M5.

- `stream=true` → SSE stream of `chat.completion.chunk` frames terminated by `data: [DONE]\n\n`. The first chunk carries `delta.role="assistant"`; subsequent chunks carry `delta.content="..."`; the last chunk carries `finish_reason="stop"`.
- `stream=false` → single JSON envelope (`chat.completion`) with the full assistant message.

Errors:

- 404 `unknown model: <id>` — alias not in the configured catalog. The rebuild's `models_cache.contains(...)` check normally prevents this from reaching the platform, but we return a clean 404 anyway.
- 400 `no user message in request` — message list contained no `user` role. Defensive only; the rebuild always sends one.
- 500 / 502 — anything else (Ollama down, model OOM, etc.). The rebuild's provider wraps these into `ProviderError(status_code=502)` already, which surfaces to the SSE stream as a terminal `error` event per [m2-conversations.md § Streaming pipeline](m2-conversations.md#streaming-pipeline).

## Tests

Three layers, all isolated from the backend test suite.

### Unit tests (`infra/agent-platform/tests/`)

- **`test_oai_router_models.py`** — TestClient hits `GET /v1/models`, asserts the JSON shape matches what `OpenAICompatibleProvider.list_models` reads (`data: [{id, owned_by}]`).
- **`test_oai_router_chat.py`** — TestClient hits `POST /v1/chat/completions` with `stream=true`. Mocks the Pydantic AI model driver via `pydantic_ai.models.test.TestModel` (rather than the Ollama HTTP layer via `respx`) so the SSE shape lock survives OpenAI-SDK telemetry / header drift. The router's full `agent.iter()` loop and the `PartStartEvent` / `PartDeltaEvent` event taxonomy still execute unchanged. Asserts the platform emits the OpenAI chunk shape (`{id, object, created, model, choices: [{delta: {content}}]}`) and terminates with `data: [DONE]\n\n`.
- **`test_oai_router_nonstream.py`** — Same, but `stream=false`. Uses `pydantic_ai.models.function.FunctionModel` to stub the assistant response (returns a single `ModelResponse` containing one `TextPart`). Asserts the non-streaming envelope (`object: "chat.completion"`, `choices: [{message: {role, content}, finish_reason}]`).
- **`test_oai_models.py`** — `ChatCompletionRequest.model_validate(payload)` accepts the exact body shape the rebuild's `AsyncOpenAI(...).chat.completions.create(stream=True, stream_options={"include_usage": True}, ...)` emits. Use a captured payload from a real call as the fixture.
- **`test_seed_history.py`** — table-driven test of `_seed_history()` with at least four scenarios: (a) single user message → empty history + the prompt; (b) `[system, user]` → empty history + system-prefixed prompt; (c) `[user, assistant, user]` multi-turn → history of one `ModelRequest` + one `ModelResponse` + the trailing prompt; (d) `[system, user, assistant, system, user]` → both system messages concatenated into the prefix. Locks the "drop the trailing user from history so iter() doesn't double-stack" invariant against future Pydantic-AI API drift.
- **`test_agents.py`** — `build_agents(settings)` returns one entry per `ModelDef`; alias→tag mapping survives. `agents.get("does-not-exist") is None`.
- **`test_smoke_compose.py`** — `@pytest.mark.compose`, skipped by default. Brings up the stack via `docker compose up -d --wait`, curls `http://localhost:8080/api/models` (through the rebuild app, not directly), asserts `{"items": [{"id": "dev", ...}]}` and that a streamed `POST /api/chats/{id}/messages` returns a non-empty assistant message. Run from `make verify-stack` only.

These run via `uv run --project infra/agent-platform pytest`. **Do not add the platform tests to `make test-unit`** — that target is for the rebuild's backend + frontend unit suites and should stay fast.

### Backend tests (unchanged)

The rebuild's existing M2 integration suite continues to use the cassette mock at [rebuild/backend/tests/llm_mock.py](../../backend/tests/llm_mock.py) via the `cassette_provider` fixture in [rebuild/backend/tests/integration/conftest.py](../../backend/tests/integration/conftest.py). The agent platform is **not** wired into any backend test. Adding it would (a) break determinism, (b) require pulling Ollama models in CI, (c) make local `make test-unit` slow.

### Frontend tests (unchanged)

MSW handlers in [rebuild/frontend/src/lib/msw/handlers.ts](../../frontend/src/lib/msw/handlers.ts) keep returning the existing fixed model list; the agent platform is not used by Vitest, Playwright component tests, or Playwright E2E. The model ids in the MSW handler list (`gpt-4o`, `gpt-4o-mini`, `claude-3-5-sonnet`) intentionally differ from the agent platform's (`dev`) — the MSW list represents what the production gateway eventually returns, not what dev ships locally.

## Acceptance criteria

The feature is done when, on a fresh `git clone`, the following sequence works end-to-end with no manual intervention beyond running the documented commands:

- [ ] `make setup && make dev` brings the stack up. First-time boot pulls `qwen2.5:0.5b` (~400 MB; slow, expected); subsequent boots reuse the volume and complete in <30 s.
- [ ] `curl http://localhost:8081/v1/models` returns the configured catalog (`dev`).
- [ ] `curl http://localhost:8081/v1/chat/completions -d '{"model":"dev","messages":[{"role":"user","content":"say hi"}],"stream":false}' -H 'Content-Type: application/json'` returns a non-empty assistant message.
- [ ] `curl -fsS -H "X-Forwarded-Email: dev@canva.com" http://localhost:8080/api/models` (the rebuild's app, *through* the agent platform) returns `{"items": [{"id": "dev", ...}]}`.
- [ ] After `npm run dev`, `http://localhost:5173` renders the model selector with one entry whose visible label reads `Dev (Qwen 2.5, 0.5B)` (not the bare alias `dev`) — proving the one-line `label` plumbing in `app/providers/openai.py` actually rounds the friendly label through to the dropdown.
- [ ] Picking the model, typing "hello", and pressing send streams an assistant response into the conversation view; the response persists across page reload.
- [ ] Clicking cancel mid-stream stops the stream cleanly and persists the partial assistant message with the cancelled badge.
- [ ] `make verify-stack` passes (existing `/healthz` + `/readyz` + `/api/me` checks plus the new `/api/models` non-empty assertion).
- [ ] Backend `make test-unit` completes in ≤ same wall-time as before the feature lands (agent platform is not in the test path).
- [ ] `make lint` fails if `pydantic-ai` or `pydantic_ai` is imported anywhere under `rebuild/backend/`.
- [ ] The runtime image (`make build`) does not include `pydantic-ai` or any LLM-related transitives — verified by `docker run --rm open-webui-rebuild:dev pip list | grep -i pydantic-ai` returning empty.

## Out of scope

Explicitly deferred to follow-up PRs (each tiny, none blocking):

- **Per-model system prompts**, agent tool wiring, or any non-trivial Pydantic AI usage. The plan deliberately ships agents with no system prompt and no tools — just a transport for completions. Future personas (`dev-pirate`, `dev-coder`, …) extend `agents.py` by reading an optional `ModelDef.system_prompt` field, without touching the OpenAI compat layer.
- **Recording the agent platform's outputs as cassettes.** The cassette workflow in [rebuild/backend/tests/fixtures/llm/README.md](../../backend/tests/fixtures/llm/README.md) hand-crafts cassettes today; building a `LLM_RECORD=1` proxy mode (already mentioned as deferred there) is its own surface and not blocked by this work.
- **Automatic model swap on hardware constraints.** If `qwen2.5:0.5b` OOMs on a developer's tiny machine, they edit the `MODELS` env block in compose. We do not auto-detect.
- **Production replacement.** The internal model gateway in production stays the upstream for staging + prod (`MODEL_GATEWAY_BASE_URL` is injected by Helm). The agent platform never ships in the runtime image and never appears in any non-`infra/` path.
- **Auth on the agent platform.** The platform is exposed only on the compose network and host loopback. If a developer wants to expose it externally for some reason (shared dev box), they add their own basic-auth proxy in front; we don't bake it in.
- **GPU acceleration.** Ollama uses CPU on most developer machines; on Apple Silicon it auto-detects Metal. We do not configure CUDA / ROCm passthrough in compose.
- **Pydantic-AI 1.88.0 deprecations.** The as-shipped 1.88.0 emits 7 `DeprecationWarning`s the platform's tests surface but do not error on: `OpenAIModel` is renamed to `OpenAIChatModel` (5 sites in `app/agents.py` + tests), and `RequestUsage.request_tokens` / `.response_tokens` are renamed to `.input_tokens` / `.output_tokens` (2 sites in `app/oai_router.py`'s non-streaming path). Migrating is a one-PR follow-up; deferred so this PR stays scoped to "land the dev compose service" rather than "land the dev compose service AND chase a deprecation churn." When the migration lands it should also bump the locked-pin in § Decisions locked → item 4 to `pydantic-ai==<next>` with a fresh changelog scan.
- **Optional `--profile` to skip the agent platform.** Even when `MODEL_GATEWAY_BASE_URL` is overridden to point at a real upstream, compose still stands up `ollama` and `agent-platform`. Locked here to keep the topology static; a developer who finds the boot cost annoying can `docker compose stop agent-platform ollama` after one `make dev`.

## Decisions locked from review

The plan's first draft raised five open questions. All five are now locked:

1. **Model defaults.** Single model: `qwen2.5:0.5b`, surfaced as alias `dev`. No `dev-quality` second tier.
2. **Compose service naming.** `agent-platform` (chosen over `gateway`/`dev-gateway`/`llm-gateway`) — forward-looking name that supports future personas without a rename.
3. **Directory placement.** `rebuild/infra/agent-platform/` — matches the compose service name; keeps it adjacent to `infra/mysql/` and `infra/redis/` so dev-only nature is obvious.
4. **`pydantic-ai` version pin.** Exact pin `==1.88.0`. Upgrade is a deliberate PR; ranged-pinning would let a transitive minor-version bump break the streaming router silently.
5. **Optional profile to skip the agent platform.** Not added — the agent platform is always brought up. Topology stays static; developers who prefer a real upstream override `MODEL_GATEWAY_BASE_URL` and (optionally) `docker compose stop` the unused services.

No open questions remain that gate implementation start.
