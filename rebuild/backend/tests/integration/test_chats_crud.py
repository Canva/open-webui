"""Integration tests for the M2 chat CRUD surface.

Hits ``/api/chats`` end-to-end through the FastAPI app via the
``m2_client`` fixture (httpx ``AsyncClient`` over ``ASGITransport``).
The MySQL container is the same session-scoped one the M0 ``client`` /
``engine`` fixtures use; ``_truncate_m2_tables`` (autoloaded by
``m2_client``) wipes ``chat`` / ``folder`` / ``user`` between tests so
the suite doesn't bleed state.

The cassette LLM mock backs ``GET /api/agents`` and the title-helper
endpoint — both via ``cassette_provider`` + ``cassette_agents_cache``
fixtures wired in ``integration/conftest.py``.

Plan reference: ``rebuild/docs/plans/m2-conversations.md`` § Chat CRUD
(line 1037+) and § Tests (line 1066 enumerates ``test_chats_crud.py``).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import sqlalchemy as sa


async def _make_folder(
    m2_client: Any,
    headers: dict[str, str],
    *,
    name: str = "Inbox",
    parent_id: str | None = None,
) -> dict[str, Any]:
    body = {"name": name}
    if parent_id is not None:
        body["parent_id"] = parent_id
    response = await m2_client.post("/api/folders", json=body, headers=headers)
    assert response.status_code == 201, response.text
    folder = response.json()
    assert isinstance(folder, dict)
    return folder


async def _make_chat(
    m2_client: Any,
    headers: dict[str, str],
    *,
    title: str | None = None,
    folder_id: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if folder_id is not None:
        body["folder_id"] = folder_id
    response = await m2_client.post("/api/chats", json=body, headers=headers)
    assert response.status_code == 201, response.text
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


# ---------------------------------------------------------------------------
# POST /api/chats
# ---------------------------------------------------------------------------


async def test_post_chat_creates_with_default_title_and_empty_history(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """A bare POST creates a chat with the canonical default title and
    an empty history tree (``messages={}, currentId=None``).
    """
    response = await m2_client.post("/api/chats", json={}, headers=alice_headers)
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["title"] == "New Chat"
    assert payload["history"] == {"messages": {}, "currentId": None}
    assert payload["folder_id"] is None
    assert payload["pinned"] is False
    assert payload["archived"] is False
    assert payload["share_id"] is None
    assert isinstance(payload["id"], str)
    assert len(payload["id"]) == 36


async def test_post_chat_with_folder_id_validates_ownership(
    m2_client: Any,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    """Posting a chat into another user's folder must 404.

    A 403 would leak the folder's existence; the rebuild's invariant is
    "404 not 403" (FastAPI-best-practises § A.9).
    """
    # Bob's folder. Alice tries to drop a chat into it.
    bobs_folder = await _make_folder(m2_client, bob_headers, name="Bob's stuff")

    response = await m2_client.post(
        "/api/chats",
        json={"folder_id": bobs_folder["id"]},
        headers=alice_headers,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/chats/{id}
# ---------------------------------------------------------------------------


async def test_get_chat_returns_404_for_foreign_owner(
    m2_client: Any,
    alice_headers: dict[str, str],
    bob_headers: dict[str, str],
) -> None:
    chat = await _make_chat(m2_client, alice_headers, title="Alice's chat")
    response = await m2_client.get(f"/api/chats/{chat['id']}", headers=bob_headers)
    assert response.status_code == 404


async def test_get_chat_returns_full_history_after_update(
    m2_client: Any,
    alice_headers: dict[str, str],
    engine: Any,
) -> None:
    """A chat whose ``history`` JSON has been mutated outside the HTTP
    surface (simulating a streaming completion) round-trips back through
    GET as the validated ``History`` shape — every message preserved,
    ``currentId`` honoured.
    """
    chat = await _make_chat(m2_client, alice_headers, title="round-trip")
    # Mutate the row directly to simulate a completed stream having
    # populated the JSON column.
    history_dump = {
        "messages": {
            "u1": {
                "id": "u1",
                "parentId": None,
                "childrenIds": ["a1"],
                "role": "user",
                "content": "Hello",
                "timestamp": 1700000000,
                "agent_id": None,
                "agentName": None,
                "done": True,
                "error": None,
                "cancelled": False,
                "usage": None,
            },
            "a1": {
                "id": "a1",
                "parentId": "u1",
                "childrenIds": [],
                "role": "assistant",
                "content": "Hi there",
                "timestamp": 1700000001,
                "agent_id": "gpt-4o",
                "agentName": "gpt-4o",
                "done": True,
                "error": None,
                "cancelled": False,
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            },
        },
        "currentId": "a1",
    }
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE chat SET history = :h WHERE id = :id"),
            {"h": json.dumps(history_dump), "id": chat["id"]},
        )

    response = await m2_client.get(f"/api/chats/{chat['id']}", headers=alice_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["history"]["currentId"] == "a1"
    assert set(body["history"]["messages"].keys()) == {"u1", "a1"}
    assert body["history"]["messages"]["a1"]["content"] == "Hi there"
    assert body["history"]["messages"]["a1"]["usage"]["total_tokens"] == 3


# ---------------------------------------------------------------------------
# PATCH /api/chats/{id}
# ---------------------------------------------------------------------------


async def test_patch_chat_partial_update_only_changes_provided_fields(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """``model_dump(exclude_unset=True)`` semantics: omitted fields are
    left alone; only the fields that appear in the body change.
    """
    chat = await _make_chat(m2_client, alice_headers, title="Original")
    response = await m2_client.patch(
        f"/api/chats/{chat['id']}",
        json={"title": "Renamed"},
        headers=alice_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Renamed"
    assert body["pinned"] is False
    assert body["archived"] is False
    assert body["folder_id"] is None


async def test_patch_chat_folder_id_null_explicitly_detaches(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """Posting ``folder_id: null`` (vs. omitting the field) must clear
    the chat's folder_id — the writer distinguishes the two via
    ``exclude_unset=True``.
    """
    folder = await _make_folder(m2_client, alice_headers, name="Inbox")
    chat = await _make_chat(m2_client, alice_headers, folder_id=folder["id"])
    assert chat["folder_id"] == folder["id"]

    response = await m2_client.patch(
        f"/api/chats/{chat['id']}",
        json={"folder_id": None},
        headers=alice_headers,
    )
    assert response.status_code == 200
    assert response.json()["folder_id"] is None


async def test_patch_chat_bumps_updated_at(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    chat = await _make_chat(m2_client, alice_headers)
    original_updated_at = chat["updated_at"]
    response = await m2_client.patch(
        f"/api/chats/{chat['id']}",
        json={"pinned": True},
        headers=alice_headers,
    )
    assert response.status_code == 200
    assert response.json()["updated_at"] >= original_updated_at


# ---------------------------------------------------------------------------
# DELETE /api/chats/{id}
# ---------------------------------------------------------------------------


async def test_delete_chat_returns_204_and_chat_is_gone(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    chat = await _make_chat(m2_client, alice_headers)
    response = await m2_client.delete(f"/api/chats/{chat['id']}", headers=alice_headers)
    assert response.status_code == 204
    assert response.content == b""

    follow_up = await m2_client.get(f"/api/chats/{chat['id']}", headers=alice_headers)
    assert follow_up.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/chats — filters, search, pagination
# ---------------------------------------------------------------------------


async def test_list_chats_filters_by_folder_id_none_for_unfoldered(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    folder = await _make_folder(m2_client, alice_headers, name="Inbox")
    foldered = await _make_chat(m2_client, alice_headers, folder_id=folder["id"])
    unfoldered = await _make_chat(m2_client, alice_headers)

    response = await m2_client.get(
        "/api/chats",
        params={"folder_id": "none"},
        headers=alice_headers,
    )
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert unfoldered["id"] in ids
    assert foldered["id"] not in ids


async def test_list_chats_filters_by_archived_pinned(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """``archived=False`` is the implicit default; ``archived=True`` flips
    to the archive view. ``pinned`` filters by exact match when given.
    """
    plain = await _make_chat(m2_client, alice_headers, title="plain")
    pinned = await _make_chat(m2_client, alice_headers, title="pinned")
    archived = await _make_chat(m2_client, alice_headers, title="archived")

    await m2_client.patch(
        f"/api/chats/{pinned['id']}", json={"pinned": True}, headers=alice_headers
    )
    await m2_client.patch(
        f"/api/chats/{archived['id']}", json={"archived": True}, headers=alice_headers
    )

    # default view: live chats only.
    live = await m2_client.get("/api/chats", headers=alice_headers)
    live_ids = {c["id"] for c in live.json()["items"]}
    assert plain["id"] in live_ids
    assert pinned["id"] in live_ids
    assert archived["id"] not in live_ids

    # archived view.
    arch = await m2_client.get("/api/chats", params={"archived": "true"}, headers=alice_headers)
    arch_ids = {c["id"] for c in arch.json()["items"]}
    assert arch_ids == {archived["id"]}

    # pinned filter.
    pinned_only = await m2_client.get(
        "/api/chats", params={"pinned": "true"}, headers=alice_headers
    )
    assert {c["id"] for c in pinned_only.json()["items"]} == {pinned["id"]}


async def test_list_chats_q_param_matches_title_like(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """``?q=`` does case-insensitive ``LIKE %q%`` on title."""
    a = await _make_chat(m2_client, alice_headers, title="Quarterly review")
    b = await _make_chat(m2_client, alice_headers, title="Random thoughts")

    response = await m2_client.get("/api/chats", params={"q": "quarterly"}, headers=alice_headers)
    assert response.status_code == 200
    ids = {c["id"] for c in response.json()["items"]}
    assert a["id"] in ids
    assert b["id"] not in ids


async def test_list_chats_q_param_matches_content_via_json_search(
    m2_client: Any,
    alice_headers: dict[str, str],
    engine: Any,
) -> None:
    """``?q=`` also matches ``JSON_SEARCH(LOWER(history), 'one', LOWER(:q))``
    against the chat body, OR'd with the title match.
    """
    chat = await _make_chat(m2_client, alice_headers, title="boring title")
    history_dump = {
        "messages": {
            "u1": {
                "id": "u1",
                "parentId": None,
                "childrenIds": [],
                "role": "user",
                "content": "Tell me about quokkas",
                "timestamp": 1700000000,
                "agent_id": None,
                "agentName": None,
                "done": True,
                "error": None,
                "cancelled": False,
                "usage": None,
            },
        },
        "currentId": "u1",
    }
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE chat SET history = :h WHERE id = :id"),
            {"h": json.dumps(history_dump), "id": chat["id"]},
        )

    response = await m2_client.get("/api/chats", params={"q": "quokka"}, headers=alice_headers)
    assert response.status_code == 200
    ids = {c["id"] for c in response.json()["items"]}
    assert chat["id"] in ids


async def test_list_chats_q_param_archived_filter_and(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """Filters compose with AND semantics — Phase 2b's choice. A ``q``
    match on a NON-archived chat must NOT appear in the archived view.
    """
    matched_live = await _make_chat(m2_client, alice_headers, title="quarterly review")
    matched_archived = await _make_chat(m2_client, alice_headers, title="quarterly archive")
    await m2_client.patch(
        f"/api/chats/{matched_archived['id']}",
        json={"archived": True},
        headers=alice_headers,
    )

    archived_view = await m2_client.get(
        "/api/chats",
        params={"q": "quarterly", "archived": "true"},
        headers=alice_headers,
    )
    ids = {c["id"] for c in archived_view.json()["items"]}
    assert matched_archived["id"] in ids
    assert matched_live["id"] not in ids


async def test_list_chats_pagination_cursor_round_trips_stably(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """A cursor returned from page N decodes back to a valid filter that
    yields page N+1 on the same shape — no skipped or repeated rows.
    """
    for i in range(5):
        await _make_chat(m2_client, alice_headers, title=f"chat-{i}")

    page1 = await m2_client.get("/api/chats", params={"limit": 2}, headers=alice_headers)
    assert page1.status_code == 200
    p1 = page1.json()
    assert len(p1["items"]) == 2
    assert p1["next_cursor"] is not None

    page2 = await m2_client.get(
        "/api/chats",
        params={"limit": 2, "cursor": p1["next_cursor"]},
        headers=alice_headers,
    )
    assert page2.status_code == 200
    p2 = page2.json()
    assert len(p2["items"]) == 2
    assert p2["next_cursor"] is not None

    seen = {c["id"] for c in p1["items"]} | {c["id"] for c in p2["items"]}
    assert len(seen) == 4  # no duplicates across pages


async def test_list_chats_limit_respected(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    for i in range(5):
        await _make_chat(m2_client, alice_headers, title=f"c{i}")
    response = await m2_client.get("/api/chats", params={"limit": 2}, headers=alice_headers)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 2


# ---------------------------------------------------------------------------
# POST /api/chats/{id}/title (cassette-backed)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("cassette_provider")
async def test_post_chat_title_endpoint_calls_provider_and_persists(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """The title helper POSTs the linear thread upstream and persists
    the returned title against the chat row.

    The cassette mock returns the synthetic ``"Cassette miss"`` envelope
    (see ``llm_mock._replay_json`` fallback) since we don't ship a
    pinned ``.json`` cassette for the title-helper hash; that's
    sufficient to assert "the route round-trips through the provider
    and writes the result back".
    """
    chat = await _make_chat(m2_client, alice_headers)
    response = await m2_client.post(
        f"/api/chats/{chat['id']}/title",
        json={"messages": [{"role": "user", "content": "say hi"}]},
        headers=alice_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Cassette miss"

    follow_up = await m2_client.get(f"/api/chats/{chat['id']}", headers=alice_headers)
    assert follow_up.json()["title"] == "Cassette miss"
