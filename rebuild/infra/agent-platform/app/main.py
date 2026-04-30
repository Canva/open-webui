from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.agents import build_agents
from app.config import settings
from app.oai_router import router as oai_router

# Probe budget for the lifespan-time Ollama health check. Compose's
# ``depends_on: ollama: { condition: service_healthy }`` should make
# the probe a no-op in steady state, but a cold-start under load can
# still race the daemon's first-request warmup; the retry loop
# absorbs that without inflating the steady-state startup time.
_PROBE_TIMEOUT_SECONDS = 10.0
_PROBE_ATTEMPTS = 5
_PROBE_BACKOFF_SECONDS = 2.0


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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
