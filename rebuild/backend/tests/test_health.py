"""Tests for ``/healthz`` and ``/readyz``.

* ``/healthz`` is a no-I/O liveness check; one assertion suffices.
* ``/readyz`` requires both MySQL (live testcontainer via ``engine``) and
  Redis (``fake_redis`` patches ``Redis.from_url``). Failure modes are
  covered by simulating each dependency dropping out independently.
"""

from __future__ import annotations

from typing import Any

import pytest


async def test_healthz_ok(client: Any) -> None:
    res = await client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


async def test_readyz_ok(client: Any, fake_redis: Any) -> None:
    """Both checks pass: live MySQL container + fakeredis."""
    res = await client.get("/readyz")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ready"
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["redis"] == "ok"


async def test_readyz_db_down_returns_503(
    client: Any,
    fake_redis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch ``_check_db`` to raise; expect 503 + ``unready``."""
    from app.routers import health as health_module

    async def _broken_db() -> str:
        raise RuntimeError("simulated db outage")

    monkeypatch.setattr(health_module, "_check_db", _broken_db)

    res = await client.get("/readyz")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "unready"
    assert "error" in body["checks"]["db"]
    assert body["checks"]["redis"] == "ok"


async def test_readyz_redis_down_returns_503(
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch ``_check_redis`` to raise; expect 503 + ``unready``."""
    from app.routers import health as health_module

    async def _broken_redis() -> str:
        raise RuntimeError("simulated redis outage")

    monkeypatch.setattr(health_module, "_check_redis", _broken_redis)

    res = await client.get("/readyz")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "unready"
    assert body["checks"]["db"] == "ok"
    assert "error" in body["checks"]["redis"]
