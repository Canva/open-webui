"""Integration tests for the M3 sharing surface.

Hits ``POST /api/chats/{id}/share``, ``DELETE /api/chats/{id}/share``,
and ``GET /api/shared/{token}`` end-to-end through the FastAPI app via
the ``m2_client`` fixture (``httpx.AsyncClient`` over
``ASGITransport``). The MySQL container is the same session-scoped
testcontainer the rest of the integration suite uses; the
``_truncate_m2_tables`` fixture (extended in this phase to also wipe
``shared_chat``) keeps the suite from bleeding state.

Coverage map (one row per acceptance bullet in
``rebuild/docs/plans/m3-sharing.md`` § Acceptance criteria):

* ``test_post_share_*`` — bullets 3, 4 (POST shape + 404 for missing /
  non-owner).
* ``test_delete_share_*`` — bullet 6 (DELETE clears state, idempotent
  on unshared, 404 for non-owner).
* ``test_get_shared_*`` — bullets 7, 8, 12 (GET shape, 401 over 404
  ordering, snapshot semantics, allowlist).
* ``test_get_chat_exposes_share_id_field`` — belt-and-braces that the
  M2 ``_to_read`` serialiser actually surfaces the new column.

The token-rotation acceptance bullet (the second POST returns a new
token, the previous returns 404) is covered in
``test_rotation.py`` — co-located with this file but split out so the
rotation contract has its own narrative. See that file's module
docstring for the placement rationale.

Style: the cases match ``test_chats_crud.py`` shape — async test
functions (``asyncio_mode=auto`` from pyproject.toml so no marker),
``httpx.AsyncClient`` via the ``m2_client`` fixture, trusted-proxy
headers passed explicitly per request, ORM seeding only when the
HTTP surface can't express the precondition (here: never — every
share precondition is reachable via HTTP).
"""

from __future__ import annotations

from typing import Any

from app.core.ids import new_id


async def _make_chat(
    m2_client: Any,
    headers: dict[str, str],
    *,
    title: str | None = None,
) -> dict[str, Any]:
    """Create a chat via HTTP — same shape as ``test_chats_crud._make_chat``."""
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    response = await m2_client.post("/api/chats", json=body, headers=headers)
    assert response.status_code == 201, response.text
    payload: dict[str, Any] = response.json()
    return payload


# ---------------------------------------------------------------------------
# POST /api/chats/{id}/share
# ---------------------------------------------------------------------------


async def test_post_share_creates_token_and_url_and_updates_chat(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """``POST /share`` returns the locked ``ShareCreateResponse`` shape
    and updates the chat's ``share_id`` back-pointer.

    The response carries:

    * ``token`` — 43-char URL-safe base64 string (matches
      ``shared_chat.id VARCHAR(43)``).
    * ``url`` — relative path ``/s/{token}`` (the FE assembles the
      absolute URL from ``window.location.origin``; backend stays
      base-URL-agnostic).
    * ``created_at`` — BIGINT epoch ms straight off the row.

    The ``chat.share_id`` field round-trips through ``GET /api/chats/{id}``
    (``ChatRead.share_id``) so the FE knows the chat is currently shared
    without a second round-trip.
    """
    chat = await _make_chat(m2_client, alice_headers, title="Refactor draft")

    response = await m2_client.post(f"/api/chats/{chat['id']}/share", headers=alice_headers)
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body.keys()) == {"token", "url", "created_at"}
    assert isinstance(body["token"], str)
    assert len(body["token"]) == 43
    assert body["url"] == f"/s/{body['token']}"
    assert isinstance(body["created_at"], int)
    assert body["created_at"] > 0

    chat_view = await m2_client.get(f"/api/chats/{chat['id']}", headers=alice_headers)
    assert chat_view.status_code == 200
    assert chat_view.json()["share_id"] == body["token"]


async def test_post_share_404_for_missing_chat(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """``POST /share`` against a non-existent chat returns 404, not 500.

    A fabricated UUIDv7 (real shape, never inserted) lets the
    ``_load_owned_chat`` lookup fail cleanly through the central
    handler.
    """
    fake_chat_id = new_id()
    response = await m2_client.post(f"/api/chats/{fake_chat_id}/share", headers=alice_headers)
    assert response.status_code == 404


async def test_post_share_404_for_non_owner_not_403(
    m2_client: Any,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    """Non-owners get ``404`` (not ``403``) — the plan is explicit
    that we don't leak existence (``rebuild/docs/plans/m3-sharing.md``
    § API surface, ``FastAPI-best-practises.md`` § A.9).

    A 403 would tell Bob "this chat exists, you just can't share it" —
    information leak. A 404 says "no such chat to you", which is
    indistinguishable from "this UUID was never used".
    """
    chat = await _make_chat(m2_client, alice_headers, title="Alice's chat")

    response = await m2_client.post(f"/api/chats/{chat['id']}/share", headers=bob_headers)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/chats/{id}/share
# ---------------------------------------------------------------------------


async def test_delete_share_clears_share_id_and_deletes_row(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """``DELETE /share`` clears ``chat.share_id`` and makes the URL dead.

    The three assertions correspond to the three observable effects of
    revocation per § API surface ``DELETE``:

    1. The endpoint returns ``204 No Content``.
    2. ``GET /api/chats/{id}`` shows ``share_id`` cleared back to
       ``null`` (the FE uses this to update its local share state).
    3. ``GET /api/shared/{old_token}`` returns ``404`` — the URL stops
       working immediately, no grace period.
    """
    chat = await _make_chat(m2_client, alice_headers)
    share = await m2_client.post(f"/api/chats/{chat['id']}/share", headers=alice_headers)
    token = share.json()["token"]

    delete = await m2_client.delete(f"/api/chats/{chat['id']}/share", headers=alice_headers)
    assert delete.status_code == 204
    assert delete.content == b""

    chat_view = await m2_client.get(f"/api/chats/{chat['id']}", headers=alice_headers)
    assert chat_view.status_code == 200
    assert chat_view.json()["share_id"] is None

    dead = await m2_client.get(f"/api/shared/{token}", headers=alice_headers)
    assert dead.status_code == 404


async def test_delete_share_is_idempotent_on_unshared_chat(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """``DELETE /share`` on a never-shared chat is a 204 no-op, NOT 404.

    The plan locks idempotency on the DELETE so the FE can fire-and-
    forget without tracking server-side share state. The second
    DELETE call confirms the no-op also holds after the first DELETE
    has cleared any state — calling DELETE twice in a row is safe.
    """
    chat = await _make_chat(m2_client, alice_headers)

    first = await m2_client.delete(f"/api/chats/{chat['id']}/share", headers=alice_headers)
    assert first.status_code == 204
    assert first.content == b""

    second = await m2_client.delete(f"/api/chats/{chat['id']}/share", headers=alice_headers)
    assert second.status_code == 204
    assert second.content == b""


async def test_delete_share_404_for_non_owner(
    m2_client: Any,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    """Non-owners get ``404`` on DELETE too — same non-leak rule as POST."""
    chat = await _make_chat(m2_client, alice_headers)
    await m2_client.post(f"/api/chats/{chat['id']}/share", headers=alice_headers)

    response = await m2_client.delete(f"/api/chats/{chat['id']}/share", headers=bob_headers)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/shared/{token}
# ---------------------------------------------------------------------------


async def test_get_shared_returns_snapshot_with_shared_by(
    m2_client: Any,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    """Any authenticated user can read a snapshot — including users who
    are NOT the original sharer. The response carries the locked
    ``SharedChatResponse`` shape and the sharer's name + email.

    Bob (a different authenticated proxy user) opens Alice's share
    here — proves the access model is "any valid trusted-header" not
    "only the original sharer". The plan locks this as the entire
    M3 access contract.
    """
    chat = await _make_chat(m2_client, alice_headers, title="Refactor draft")
    share = await m2_client.post(f"/api/chats/{chat['id']}/share", headers=alice_headers)
    token = share.json()["token"]

    response = await m2_client.get(f"/api/shared/{token}", headers=bob_headers)
    assert response.status_code == 200, response.text
    body = response.json()

    # Shape lock — every documented field is present and no extras.
    assert set(body.keys()) == {"token", "title", "history", "shared_by", "created_at"}
    assert body["token"] == token
    assert body["title"] == "Refactor draft"
    # Empty history on a fresh chat round-trips through the History
    # validator without losing the shape.
    assert body["history"] == {"messages": {}, "currentId": None}
    assert body["created_at"] == share.json()["created_at"]

    assert set(body["shared_by"].keys()) == {"name", "email"}
    assert body["shared_by"]["name"] == "Alice"
    assert body["shared_by"]["email"] == "alice@canva.com"


async def test_get_shared_404_for_unknown_token(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """A made-up but well-shaped token returns ``404``.

    We use a 43-char URL-safe-base64-shaped value so the path
    parameter matches the regex the route would accept; the 404
    comes from the ``db.get(SharedChat, token)`` returning ``None``,
    not from a path-parsing reject.
    """
    fake_token = "z" * 43
    response = await m2_client.get(f"/api/shared/{fake_token}", headers=alice_headers)
    assert response.status_code == 404


async def test_get_shared_404_after_revoke(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """``GET`` on a revoked token returns ``404`` — same status as
    "unknown token", so an attacker can't distinguish the two.
    """
    chat = await _make_chat(m2_client, alice_headers)
    share = await m2_client.post(f"/api/chats/{chat['id']}/share", headers=alice_headers)
    token = share.json()["token"]

    delete = await m2_client.delete(f"/api/chats/{chat['id']}/share", headers=alice_headers)
    assert delete.status_code == 204

    response = await m2_client.get(f"/api/shared/{token}", headers=alice_headers)
    assert response.status_code == 404


async def test_get_shared_401_without_trusted_email(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """No ``X-Forwarded-Email`` → ``401`` even when the token is valid.

    The auth gate is at the dependency level (``get_user`` runs
    before the handler), so a request that omits the trusted header
    never reaches the ``db.get(SharedChat, token)`` call. This is the
    critical security backstop: a leaked share URL is useless to
    anyone the proxy doesn't authenticate.

    We assert two things:

    * The status is ``401`` (the auth dep wins over the token lookup
      that would have returned ``200``).
    * The response body does NOT contain the token or any snapshot
      data — i.e. ``401`` truly precedes ``404`` in dependency
      resolution order, and we don't leak "this token would have
      been valid" through the error message.
    """
    chat = await _make_chat(m2_client, alice_headers)
    share = await m2_client.post(f"/api/chats/{chat['id']}/share", headers=alice_headers)
    token = share.json()["token"]

    # Explicit empty headers dict — the m2_client fixture sets no
    # default headers, so this exercises the "no X-Forwarded-Email"
    # path even though we're using a token that would otherwise be
    # valid for an authenticated request.
    response = await m2_client.get(f"/api/shared/{token}", headers={})
    assert response.status_code == 401

    # Defence-in-depth: the 401 envelope must not contain the token
    # or any snapshot field. The handler never ran, so the only
    # thing in the body should be the standard "missing trusted
    # header" detail from `get_user`.
    assert response.json() == {"detail": "missing trusted header"}


async def test_get_shared_401_for_disallowed_email_domain(
    m2_client: Any,
    alice_headers: dict[str, str],
    override_settings: Any,
) -> None:
    """An ``X-Forwarded-Email`` outside the allowlist returns ``401``.

    Mirrors ``test_auth.py::test_domain_allowlist_rejects`` — the
    M3 share endpoint is gated by ``get_user`` so the same allowlist
    enforcement applies. We use a deny-all-but-canva.com allowlist
    and present an off-domain header; the response is ``401`` from
    the auth dep, not ``200`` from the handler.

    Setting up the share itself uses Alice (allowlisted) so we know
    the token is valid; the failure is then proved to come from the
    auth dep not the lookup, by checking the response detail matches
    ``upsert_user_from_headers``'s allowlist message.
    """
    chat = await _make_chat(m2_client, alice_headers)
    share = await m2_client.post(f"/api/chats/{chat['id']}/share", headers=alice_headers)
    token = share.json()["token"]

    with override_settings(trusted_email_domain_allowlist=["canva.com"]):
        response = await m2_client.get(
            f"/api/shared/{token}",
            headers={"X-Forwarded-Email": "eve@attacker.com"},
        )
    assert response.status_code == 401
    assert response.json() == {"detail": "email domain not allowed"}


async def test_get_shared_reads_snapshot_not_live_chat(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """The snapshot is captured at share time and is **not live**.

    Plan § Snapshot semantics, restated as one HTTP-level test:

    1. Share a chat with title "Before".
    2. PATCH the chat title to "After".
    3. GET ``/api/shared/{token}`` — the response title is "Before".

    This is the focused belt-and-braces version of the half of
    ``test_rotation.py::test_rotation_preserves_snapshot_title_and_history_copy``
    that asserts snapshot immutability under live edits. Co-locating
    it here means a regression in the snapshot semantics fails one
    very narrowly-scoped test name in the share suite, not a longer
    rotation narrative.
    """
    chat = await _make_chat(m2_client, alice_headers, title="Before")
    share = await m2_client.post(f"/api/chats/{chat['id']}/share", headers=alice_headers)
    token = share.json()["token"]

    patch = await m2_client.patch(
        f"/api/chats/{chat['id']}",
        json={"title": "After"},
        headers=alice_headers,
    )
    assert patch.status_code == 200
    assert patch.json()["title"] == "After"

    response = await m2_client.get(f"/api/shared/{token}", headers=alice_headers)
    assert response.status_code == 200
    assert response.json()["title"] == "Before"


# ---------------------------------------------------------------------------
# Belt-and-braces: GET /api/chats/{id} surfaces share_id
# ---------------------------------------------------------------------------


async def test_get_chat_exposes_share_id_field(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """``ChatRead`` (the GET response) must surface ``share_id`` so the
    frontend knows the chat is currently shared without a second
    round-trip.

    The M2 schema reserved the ``share_id`` field as ``str | None``
    with a default of ``None``; M3 is the first milestone that ever
    populates it. This test pins the contract that the M2 ``_to_read``
    serialiser actually wires the ORM column through to the response —
    a regression where ``share_id`` quietly drops would silently
    break the share modal's "this chat is currently shared" state
    without breaking any other test in this file.
    """
    chat = await _make_chat(m2_client, alice_headers)
    pre = await m2_client.get(f"/api/chats/{chat['id']}", headers=alice_headers)
    assert pre.status_code == 200
    assert pre.json()["share_id"] is None

    share = await m2_client.post(f"/api/chats/{chat['id']}/share", headers=alice_headers)
    token = share.json()["token"]

    post = await m2_client.get(f"/api/chats/{chat['id']}", headers=alice_headers)
    assert post.status_code == 200
    assert post.json()["share_id"] == token
