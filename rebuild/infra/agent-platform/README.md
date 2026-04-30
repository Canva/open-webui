# agent-platform

A small FastAPI service that wraps [Pydantic AI](https://ai.pydantic.dev/) in
front of a local [Ollama](https://ollama.com/) daemon and exposes an
OpenAI-compatible HTTP surface (`/v1/models`, `/v1/chat/completions` with SSE
streaming). It exists so the rebuild's `OpenAICompatibleProvider` has a real
upstream to talk to in the dev compose stack — the same wire shape it speaks
to the production internal model gateway.

The full design lives in
[`rebuild/docs/plans/feature-llm-models.md`](../../docs/plans/feature-llm-models.md);
this README is the operational quick reference.

## Why this exists

Without this service, a developer running `make dev` for the first time
sees an empty model dropdown and a 401 from `https://api.openai.com/v1`.
With it, the dropdown is populated by `dev` (backed by `qwen2.5:0.5b`) and
streaming chat works end-to-end against a real LLM — no token, no quota,
no external dependency.

The platform is dev-loop infrastructure, sibling to the MySQL and Redis
compose services. It is **not** part of the rebuild's runtime image and
**never** runs in staging or prod.

## Why it is not used in tests

Backend integration tests use the deterministic cassette mock at
[`rebuild/backend/tests/llm_mock.py`](../../backend/tests/llm_mock.py).
Frontend Vitest / Playwright suites use the MSW handlers at
[`rebuild/frontend/src/lib/msw/handlers.ts`](../../frontend/src/lib/msw/handlers.ts).
Mixing real LLM output into CI would make the suite non-deterministic
and slow; the platform stays out of the test path on purpose.

## How to swap or add models

Two options:

1. **Compose-time override (no rebuild).** Set `MODELS` on the
   `agent-platform` service in `rebuild/infra/docker-compose.yml`
   to a JSON list of `{id, label, ollama_tag, owned_by}` objects.
   Pydantic-Settings parses the JSON automatically. Example:

   ```yaml
   environment:
     MODELS: >-
       [{"id":"dev","label":"Dev (Qwen 2.5, 0.5B)","ollama_tag":"qwen2.5:0.5b"},
        {"id":"dev-coder","label":"Dev Coder (Qwen 2.5 Coder, 1.5B)","ollama_tag":"qwen2.5-coder:1.5b"}]
   ```

   You'll also need to teach the `ollama` service to pull the new tag
   (its entrypoint wrapper hardcodes `qwen2.5:0.5b` today; add another
   `ollama pull <tag>` line and extend the healthcheck `grep`).

2. **Source edit.** Adjust the default `MODELS` list in
   [`app/config.py`](app/config.py). Useful when the new model belongs
   in the canonical default catalog rather than a per-developer override.

## Cold-start cost

The first `make dev` after a clean checkout pulls `qwen2.5:0.5b`
(~400 MB). On a typical home connection that is several minutes;
the ollama service stays unhealthy until the pull completes and the
agent platform's startup gates on ollama-healthy.

Subsequent boots reuse the named volume `ollama_models` and the
service is healthy in seconds.

## Refreshing the model cache

```bash
make dev-rebuild-models
```

Recreates the `ollama` container so its entrypoint wrapper re-runs
`ollama pull` on next boot. `ollama pull` is idempotent on cache hit,
so this is mostly useful when the named volume has been wiped or a
model spec changed.

## Endpoints

- `GET /healthz` — liveness probe (used by the Docker healthcheck and
  by the rebuild's `agent-platform: { condition: service_healthy }`).
- `GET /v1/models` — returns the configured catalog as the OpenAI
  `models.list` shape, with one non-OpenAI extension (`label`) that the
  rebuild reads via `getattr(m, "label", None)`.
- `POST /v1/chat/completions` — accepts the OpenAI request shape;
  `stream=true` returns SSE chunks terminated by `data: [DONE]\n\n`,
  `stream=false` returns a single JSON envelope.

## Pointers

- Plan: [`rebuild/docs/plans/feature-llm-models.md`](../../docs/plans/feature-llm-models.md)
- Compose wiring: [`rebuild/infra/docker-compose.yml`](../docker-compose.yml)
- Rebuild's consumer: [`rebuild/backend/app/providers/openai.py`](../../backend/app/providers/openai.py)
