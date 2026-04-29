"""Tests for the trusted-header auth surface.

Covers both call shapes documented in the m0 plan § Trusted-header
dependency:

* :func:`app.core.auth.get_user` — invoked via the FastAPI ``GET /api/me``
  route under ``client``.
* :func:`app.core.auth.upsert_user_from_headers` — invoked directly with
  an ``AsyncSession`` (the same call shape M3's socket.io ``connect``
  handler uses).
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select


async def test_missing_header_returns_401(client: Any) -> None:
    """No ``X-Forwarded-Email`` -> 401 from ``get_user``."""
    res = await client.get("/api/me")
    assert res.status_code == 401
    assert res.json()["detail"] == "missing trusted header"


async def test_creates_user_on_first_request(client: Any, db_session: Any) -> None:
    """First hit upserts the user; row exists in the test DB."""
    from app.models.user import User

    res = await client.get(
        "/api/me",
        headers={
            "X-Forwarded-Email": "alice@canva.com",
            "X-Forwarded-Name": "Alice Example",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == "alice@canva.com"
    assert body["name"] == "Alice Example"

    row = await db_session.scalar(select(User).where(User.email == "alice@canva.com"))
    assert row is not None
    assert row.name == "Alice Example"
    assert row.timezone == "UTC"
    assert isinstance(row.created_at, int)


async def test_reuses_user_on_subsequent_requests(client: Any, db_session: Any) -> None:
    """Second hit reuses the row; only one ``user`` row exists."""
    from app.models.user import User

    headers = {
        "X-Forwarded-Email": "bob@canva.com",
        "X-Forwarded-Name": "Bob Example",
    }
    res1 = await client.get("/api/me", headers=headers)
    res2 = await client.get("/api/me", headers=headers)

    assert res1.status_code == 200
    assert res2.status_code == 200
    assert res1.json()["id"] == res2.json()["id"]

    rows = (await db_session.scalars(select(User))).all()
    assert len(rows) == 1
    assert rows[0].email == "bob@canva.com"


async def test_domain_allowlist_rejects(
    client: Any,
    override_settings: Any,
) -> None:
    """When TRUSTED_EMAIL_DOMAIN_ALLOWLIST is set, off-domain -> 401."""
    with override_settings(TRUSTED_EMAIL_DOMAIN_ALLOWLIST=["canva.com"]):
        res = await client.get(
            "/api/me",
            headers={"X-Forwarded-Email": "carol@example.com"},
        )
    assert res.status_code == 401
    assert res.json()["detail"] == "email domain not allowed"


async def test_domain_allowlist_admits_listed_domain(
    client: Any,
    override_settings: Any,
) -> None:
    """Same allowlist accepts an in-list domain (positive sibling)."""
    with override_settings(TRUSTED_EMAIL_DOMAIN_ALLOWLIST=["canva.com"]):
        res = await client.get(
            "/api/me",
            headers={"X-Forwarded-Email": "dan@canva.com"},
        )
    assert res.status_code == 200
    assert res.json()["email"] == "dan@canva.com"


async def test_url_decoded_email_normalised(client: Any, db_session: Any) -> None:
    """URL-encoded ``+`` survives decode and the email is lowercased."""
    from app.models.user import User

    res = await client.get(
        "/api/me",
        headers={"X-Forwarded-Email": "Eve%2Btag%40Canva.com"},
    )
    assert res.status_code == 200
    assert res.json()["email"] == "eve+tag@canva.com"

    rows = (await db_session.scalars(select(User))).all()
    assert len(rows) == 1
    assert rows[0].email == "eve+tag@canva.com"


async def test_upsert_user_from_headers_direct_call(
    db_session: Any,
) -> None:
    """Direct call shape: same shape M3's socket.io connect handler uses."""
    from app.core.auth import upsert_user_from_headers
    from app.models.user import User

    user = await upsert_user_from_headers(
        db_session,
        email="frank@canva.com",
        name="Frank",
    )
    assert user.email == "frank@canva.com"
    assert user.name == "Frank"

    user_again = await upsert_user_from_headers(
        db_session,
        email="frank@canva.com",
        name="Frank",
    )
    assert user_again.id == user.id

    rows = (await db_session.scalars(select(User))).all()
    assert len(rows) == 1


async def test_upsert_user_from_headers_defaults_name_to_email(
    db_session: Any,
) -> None:
    """``name=None`` -> the email is used as the display name."""
    from app.core.auth import upsert_user_from_headers

    user = await upsert_user_from_headers(
        db_session,
        email="grace@canva.com",
        name=None,
    )
    assert user.name == "grace@canva.com"


async def test_upsert_user_from_headers_respects_allowlist(
    db_session: Any,
    override_settings: Any,
) -> None:
    """Allowlist enforcement happens inside the helper, not just get_user."""
    from app.core.auth import upsert_user_from_headers
    from fastapi import HTTPException

    with (
        override_settings(TRUSTED_EMAIL_DOMAIN_ALLOWLIST=["canva.com"]),
        pytest.raises(HTTPException) as exc_info,
    ):
        await upsert_user_from_headers(
            db_session,
            email="harry@example.com",
            name=None,
        )
    assert exc_info.value.status_code == 401
