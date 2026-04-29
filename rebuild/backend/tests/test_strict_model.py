"""Regression for the StrictModel contract from the m0 acceptance criteria.

Mounts a tiny test-local FastAPI app with a single POST endpoint that
accepts a ``StrictModel`` subclass with two string fields. The production
``app.main:app`` is intentionally not used — the contract under test is
the *base class*, not any individual schema.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest_asyncio
from app.schemas._base import StrictModel
from fastapi import FastAPI


class _Echo(StrictModel):
    id: str
    email: str


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.post("/echo")
    async def echo(body: _Echo) -> dict[str, str]:
        return {"id": body.id, "email": body.email}

    return app


@pytest_asyncio.fixture
async def stub_client() -> Any:
    transport = httpx.ASGITransport(app=_make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_extra_field_returns_422(stub_client: Any) -> None:
    """The acceptance-criterion regression: extra fields -> 422."""
    res = await stub_client.post(
        "/echo",
        json={"id": "x", "email": "y", "extra": 1},
    )
    assert res.status_code == 422


async def test_whitespace_is_stripped(stub_client: Any) -> None:
    """``str_strip_whitespace=True`` strips at validation time."""
    res = await stub_client.post(
        "/echo",
        json={"id": "  x  ", "email": " y "},
    )
    assert res.status_code == 200
    assert res.json() == {"id": "x", "email": "y"}


async def test_well_formed_payload_accepted(stub_client: Any) -> None:
    """Sibling positive: no extras, no whitespace -> echo round-trips."""
    res = await stub_client.post(
        "/echo",
        json={"id": "x", "email": "y"},
    )
    assert res.status_code == 200
    assert res.json() == {"id": "x", "email": "y"}
