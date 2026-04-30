"""Integration tests for the M2 folder CRUD surface.

Exercises ``POST/GET/PATCH/DELETE /api/folders`` end-to-end through the
``m2_client`` fixture. The two recursive-CTE shapes
(:func:`assert_no_cycle`, :func:`collect_descendants`) are tested via
their HTTP entry points — the cycle case fires from PATCH, the
descendant case from DELETE.

Plan reference: ``rebuild/docs/plans/m2-conversations.md`` § Folder
CRUD, § Cycle detection and descendant computation, and § Tests
("Coverage gate" line 1075 — every CRUD endpoint must have at least
one integration test).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa


async def _make_folder(
    m2_client: Any,
    headers: dict[str, str],
    *,
    name: str,
    parent_id: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"name": name}
    if parent_id is not None:
        body["parent_id"] = parent_id
    response = await m2_client.post("/api/folders", json=body, headers=headers)
    assert response.status_code == 201, response.text
    payload: dict[str, Any] = response.json()
    return payload


async def _make_chat(
    m2_client: Any,
    headers: dict[str, str],
    *,
    title: str = "chat",
    folder_id: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"title": title}
    if folder_id is not None:
        body["folder_id"] = folder_id
    response = await m2_client.post("/api/chats", json=body, headers=headers)
    assert response.status_code == 201, response.text
    payload: dict[str, Any] = response.json()
    return payload


# ---------------------------------------------------------------------------
# POST /api/folders
# ---------------------------------------------------------------------------


async def test_post_folder_creates_with_no_parent(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    response = await m2_client.post("/api/folders", json={"name": "Inbox"}, headers=alice_headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Inbox"
    assert body["parent_id"] is None
    assert body["expanded"] is False
    assert isinstance(body["id"], str)
    assert len(body["id"]) == 36


async def test_post_folder_with_parent_validates_existence(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    parent = await _make_folder(m2_client, alice_headers, name="Parent")
    child = await _make_folder(m2_client, alice_headers, name="Child", parent_id=parent["id"])
    assert child["parent_id"] == parent["id"]


async def test_post_folder_404_on_missing_parent(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """A non-existent parent (or one that belongs to another user) must
    return ``404`` (the recursive-CTE empty-anchor branch).
    """
    response = await m2_client.post(
        "/api/folders",
        json={"name": "orphan", "parent_id": "11111111-1111-1111-1111-111111111111"},
        headers=alice_headers,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/folders/{id}
# ---------------------------------------------------------------------------


async def test_patch_folder_rename_only_succeeds(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    folder = await _make_folder(m2_client, alice_headers, name="Old name")
    response = await m2_client.patch(
        f"/api/folders/{folder['id']}",
        json={"name": "New name"},
        headers=alice_headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "New name"


async def test_patch_folder_move_succeeds_when_no_cycle(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """Moving a folder under a sibling — no ancestor relationship — must
    succeed."""
    a = await _make_folder(m2_client, alice_headers, name="A")
    b = await _make_folder(m2_client, alice_headers, name="B")
    response = await m2_client.patch(
        f"/api/folders/{a['id']}",
        json={"parent_id": b["id"]},
        headers=alice_headers,
    )
    assert response.status_code == 200
    assert response.json()["parent_id"] == b["id"]


async def test_patch_folder_move_409_on_cycle(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """A → B → C, then PATCH A.parent_id = C must produce ``409`` —
    moving A under one of its own descendants would cycle the tree.
    """
    a = await _make_folder(m2_client, alice_headers, name="A")
    b = await _make_folder(m2_client, alice_headers, name="B", parent_id=a["id"])
    c = await _make_folder(m2_client, alice_headers, name="C", parent_id=b["id"])
    response = await m2_client.patch(
        f"/api/folders/{a['id']}",
        json={"parent_id": c["id"]},
        headers=alice_headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "cycle"


async def test_patch_folder_move_to_self_409(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """Pointing a folder's ``parent_id`` at itself is a degenerate cycle
    — the ancestor walk hits the moved folder on the very first hop.
    """
    a = await _make_folder(m2_client, alice_headers, name="A")
    response = await m2_client.patch(
        f"/api/folders/{a['id']}",
        json={"parent_id": a["id"]},
        headers=alice_headers,
    )
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# DELETE /api/folders/{id}
# ---------------------------------------------------------------------------


async def test_delete_folder_cascades_to_descendants_via_db_cascade(
    m2_client: Any,
    alice_headers: dict[str, str],
    engine: Any,
) -> None:
    """The descendant CTE returns the full ``[target, ...descendants]``
    list and the DELETE removes every row in the tree."""
    a = await _make_folder(m2_client, alice_headers, name="A")
    b = await _make_folder(m2_client, alice_headers, name="B", parent_id=a["id"])
    c = await _make_folder(m2_client, alice_headers, name="C", parent_id=b["id"])

    response = await m2_client.delete(f"/api/folders/{a['id']}", headers=alice_headers)
    assert response.status_code == 200
    body = response.json()
    assert set(body["deleted_folder_ids"]) == {a["id"], b["id"], c["id"]}

    async with engine.begin() as conn:
        result = await conn.execute(
            sa.text("SELECT id FROM folder WHERE id IN (:a, :b, :c)"),
            {"a": a["id"], "b": b["id"], "c": c["id"]},
        )
        remaining = [row[0] for row in result.all()]
    assert remaining == []


async def test_delete_folder_detaches_chats_via_set_null(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """Chats inside a deleted folder survive with ``folder_id = NULL``
    (the column is ``ON DELETE SET NULL``; the router's UPDATE issues
    the same effect proactively so the response payload is accurate)."""
    folder = await _make_folder(m2_client, alice_headers, name="To delete")
    chat = await _make_chat(m2_client, alice_headers, title="survivor", folder_id=folder["id"])

    response = await m2_client.delete(f"/api/folders/{folder['id']}", headers=alice_headers)
    assert response.status_code == 200
    assert chat["id"] in response.json()["detached_chat_ids"]

    follow_up = await m2_client.get(f"/api/chats/{chat['id']}", headers=alice_headers)
    assert follow_up.status_code == 200
    assert follow_up.json()["folder_id"] is None


async def test_delete_folder_returns_descendant_ids_and_detached_chat_ids(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """The DELETE response payload is the union of the descendant CTE
    + the chat-detach UPDATE — both populated for the frontend store.
    """
    a = await _make_folder(m2_client, alice_headers, name="A")
    b = await _make_folder(m2_client, alice_headers, name="B", parent_id=a["id"])
    chat_in_a = await _make_chat(m2_client, alice_headers, title="in A", folder_id=a["id"])
    chat_in_b = await _make_chat(m2_client, alice_headers, title="in B", folder_id=b["id"])

    response = await m2_client.delete(f"/api/folders/{a['id']}", headers=alice_headers)
    assert response.status_code == 200
    body = response.json()
    assert set(body["deleted_folder_ids"]) == {a["id"], b["id"]}
    assert set(body["detached_chat_ids"]) == {chat_in_a["id"], chat_in_b["id"]}


# ---------------------------------------------------------------------------
# GET /api/folders
# ---------------------------------------------------------------------------


async def test_get_folders_returns_flat_list_ordered_by_created_at(
    m2_client: Any,
    alice_headers: dict[str, str],
) -> None:
    """The list is flat (parent/child are reconstructed client-side from
    ``parent_id``) and ordered by ``created_at`` ascending — older
    folders first so the sidebar tree renders deterministically.
    """
    first = await _make_folder(m2_client, alice_headers, name="first")
    second = await _make_folder(m2_client, alice_headers, name="second")
    third = await _make_folder(m2_client, alice_headers, name="third")

    response = await m2_client.get("/api/folders", headers=alice_headers)
    assert response.status_code == 200
    items = response.json()
    ids = [f["id"] for f in items]
    assert ids == [first["id"], second["id"], third["id"]]
