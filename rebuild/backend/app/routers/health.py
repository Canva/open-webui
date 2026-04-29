"""Liveness + readiness probes. Both are unauthenticated.

* ``GET /healthz`` — pure no-I/O liveness; always 200.
* ``GET /readyz`` — pings MySQL (``SELECT 1``) and Redis (``PING``) inside
  per-call timeouts from ``settings.READYZ_DB_TIMEOUT_MS`` /
  ``settings.READYZ_REDIS_TIMEOUT_MS``. 503 on any failure.

``/readyz`` opens its own ``AsyncSessionLocal`` and Redis client per call
rather than depending on ``get_session`` — these are infra endpoints and must
never trip auth or session-scoped DI machinery.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import settings
from app.core.db import AsyncSessionLocal

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


async def _check_db() -> str:
    async with AsyncSessionLocal() as session:
        await asyncio.wait_for(
            session.execute(text("SELECT 1")),
            timeout=settings.READYZ_DB_TIMEOUT_MS / 1000,
        )
    return "ok"


async def _check_redis() -> str:
    client = Redis.from_url(settings.REDIS_URL)
    try:
        await asyncio.wait_for(
            client.ping(),
            timeout=settings.READYZ_REDIS_TIMEOUT_MS / 1000,
        )
    finally:
        await client.aclose()
    return "ok"


@router.get("/readyz")
async def readyz() -> JSONResponse:
    checks: dict[str, str] = {}
    ok = True

    try:
        checks["db"] = await _check_db()
    except Exception as exc:  # noqa: BLE001 — readiness must catch everything
        checks["db"] = f"error: {exc.__class__.__name__}"
        ok = False

    try:
        checks["redis"] = await _check_redis()
    except Exception as exc:  # noqa: BLE001 — readiness must catch everything
        checks["redis"] = f"error: {exc.__class__.__name__}"
        ok = False

    if ok:
        return JSONResponse({"status": "ready", "checks": checks}, status_code=200)
    return JSONResponse({"status": "unready", "checks": checks}, status_code=503)
