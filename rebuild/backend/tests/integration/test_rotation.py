"""Integration tests for the M3 share-token rotation contract.

The plan places this under ``tests/unit/test_rotation.py`` (see
``rebuild/docs/plans/m3-sharing.md`` § Tests § Unit), but the
rotation semantics inherently involve two ``INSERT``s, a ``DELETE``,
and the ``ix_chat_share_id`` unique-index invariant on the M3-owned
back-pointer column. A realistic test needs MySQL's actual unique-
index behaviour and the FK ``ON DELETE`` cascades that the M3 Alembic
revision installs — neither of which an in-memory SQLite engine or a
synthetic in-process setup can model. Co-locating the rotation test
with ``test_shares.py`` (same fixtures, same MySQL container, same
truncation) keeps the test infrastructure single-purpose and avoids
the maintenance overhead of a parallel "fake DB just for one file".

The deviation from the plan's directory choice is **deliberate** and
called out in the test-author handoff (``placement_decisions``). The
narrower "the router calls ``secrets.token_urlsafe(32)`` and gets a
43-char URL-safe string" half of the rotation contract is covered by
the pure-Python ``tests/unit/test_token.py`` — the rotation tests
below cover what only a real DB can prove.

Reference: ``rebuild/docs/plans/m3-sharing.md`` § Snapshot semantics
("re-share is delete + create … treating re-share as delete + insert
means the token is the unit of disclosure"), § API surface
``POST /api/chats/{chat_id}/share`` step 2 ("if ``chat.share_id`` is
already set, **delete the old ``shared_chat`` row and clear the
back-pointer first** — token rotation"), and § Acceptance criteria
("a second ``POST`` on the same chat rotates the token; the previous
token returns ``404``").
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa


async def _make_chat(
    m2_client: Any,
    headers: dict[str, str],
    *,
    title: str | None = None,
) -> dict[str, Any]:
    """Create a chat via the HTTP surface — same shape as ``test_chats_crud``."""
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    response = await m2_client.post("/api/chats", json=body, headers=headers)
    assert response.status_code == 201, response.text
    payload: dict[str, Any] = response.json()
    return payload


async def _seed_history(engine: Any, *, chat_id: str) -> dict[str, Any]:
    """Seed a non-trivial ``chat.history`` directly on the row.

    The plan calls for "a chat with at least one message" so the
    snapshot assertion exercises a real history payload, but the M2
    ``/messages`` endpoint opens an SSE stream and is too heavy for
    a share test (it would also pull in the cassette + StreamRegistry
    paths, which the share router is independent of). A direct
    ``UPDATE`` mirrors what ``test_get_chat_returns_full_history_after_update``
    in ``test_chats_crud.py`` does for the same reason.

    Returns the dict we wrote so callers can assert on it.
    """
    history_dump: dict[str, Any] = {
        "messages": {
            "u1": {
                "id": "u1",
                "parentId": None,
                "childrenIds": ["a1"],
                "role": "user",
                "content": "Tell me about quokkas",
                "timestamp": 1700000000,
                "model": None,
                "modelName": None,
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
                "content": "They are small marsupials native to Western Australia.",
                "timestamp": 1700000001,
                "model": "gpt-4o",
                "modelName": "gpt-4o",
                "done": True,
                "error": None,
                "cancelled": False,
                "usage": None,
            },
        },
        "currentId": "a1",
    }
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE chat SET history = :h WHERE id = :id"),
            {"h": json.dumps(history_dump), "id": chat_id},
        )
    return history_dump


async def test_second_post_rotates_token(
    m2_client: Any,
    alice_headers: dict[str, str],
    engine: Any,
) -> None:
    """A second ``POST /share`` on the same chat mints a fresh token,
    invalidates the previous one, and updates the chat's ``share_id``
    back-pointer to the new token.

    The five assertions below correspond, in order, to the five
    bullet points the plan locks under § API surface step 2 + the
    § Acceptance criteria "second POST … rotates" gate:

    1. The two responses carry distinct tokens.
    2. The previous token returns ``404`` on ``GET /api/shared/...``
       (the stale URL is dead immediately, no grace period).
    3. The new token returns ``200`` with the same captured title +
       history (rotation does not corrupt the snapshot).
    4. The chat's ``share_id`` field (surfaced via ``GET /api/chats/{id}``
       to keep this test off the ORM) equals the new token.
    5. Both the old + new tokens have the canonical 43-char shape.
    """
    chat = await _make_chat(m2_client, alice_headers, title="Quokka primer")
    history = await _seed_history(engine, chat_id=chat["id"])

    res1 = await m2_client.post(f"/api/chats/{chat['id']}/share", headers=alice_headers)
    assert res1.status_code == 200, res1.text
    t1 = res1.json()["token"]
    assert isinstance(t1, str)
    assert len(t1) == 43

    res2 = await m2_client.post(f"/api/chats/{chat['id']}/share", headers=alice_headers)
    assert res2.status_code == 200, res2.text
    t2 = res2.json()["token"]
    assert isinstance(t2, str)
    assert len(t2) == 43

    # Assertion 1: tokens are distinct (the rotation actually rotated).
    assert t1 != t2

    # Assertion 2: the old token is dead — a stale URL returns 404
    # immediately, no grace period.
    dead = await m2_client.get(f"/api/shared/{t1}", headers=alice_headers)
    assert dead.status_code == 404

    # Assertion 3: the new token returns the snapshot, with title +
    # history matching what the chat held at re-share time. The
    # snapshot is captured from the current chat state (which we
    # never mutated between the two POSTs in this test), so the
    # rotated snapshot equals the originally-snapshotted content.
    live = await m2_client.get(f"/api/shared/{t2}", headers=alice_headers)
    assert live.status_code == 200, live.text
    body = live.json()
    assert body["token"] == t2
    assert body["title"] == "Quokka primer"
    assert body["history"]["currentId"] == history["currentId"]
    assert set(body["history"]["messages"].keys()) == set(history["messages"].keys())

    # Assertion 4: the chat's back-pointer was updated to the NEW
    # token, fetched through the HTTP surface so we don't reach into
    # the ORM here. ``ChatRead.share_id`` is the M2 _to_read field.
    chat_view = await m2_client.get(f"/api/chats/{chat['id']}", headers=alice_headers)
    assert chat_view.status_code == 200
    assert chat_view.json()["share_id"] == t2


async def test_rotation_preserves_snapshot_title_and_history_copy(
    m2_client: Any,
    alice_headers: dict[str, str],
    engine: Any,
) -> None:
    """A live PATCH between two shares does NOT bleed into the first
    snapshot, and the second share captures the post-PATCH state.

    Two interlocking properties of the rotation contract:

    * **Snapshot immutability** (plan § Snapshot semantics):
      "Editing the original chat after sharing — adding messages,
      regenerating, renaming — does not update the share." We assert
      this by PATCHing the chat title between two ``GET /api/shared``
      calls on the *same* token and confirming the snapshot is
      unchanged. ``test_shares.py::test_get_shared_reads_snapshot_not_live_chat``
      is the focused belt-and-braces version of just this half.

    * **Re-share snapshots fresh** (plan § Snapshot semantics):
      "To publish a fresh version the owner must explicitly re-share."
      We assert this by re-sharing AFTER the PATCH and confirming the
      new snapshot reflects the new title.

    A note on dispatch fidelity: the dispatch instructions for this
    case place "assert the old token is dead (404)" *before* the
    re-share, which would imply PATCH alone kills the share. That
    contradicts the plan's snapshot-semantics section ("editing the
    original chat … does not update the share") and is impossible
    against the M3 router (``patch_chat`` does not touch
    ``chat.share_id``). The order below — PATCH → assert snapshot
    unchanged → re-share → assert old token now dead → assert new
    snapshot has the new title — is the only sequence consistent
    with the plan, and is what's actually tested. The handoff's
    ``deferred_or_refused`` field calls this out.
    """
    chat = await _make_chat(m2_client, alice_headers, title="Before")
    await _seed_history(engine, chat_id=chat["id"])

    res1 = await m2_client.post(f"/api/chats/{chat['id']}/share", headers=alice_headers)
    assert res1.status_code == 200, res1.text
    t1 = res1.json()["token"]

    # Confirm baseline: the first snapshot reflects the "Before" title.
    pre = await m2_client.get(f"/api/shared/{t1}", headers=alice_headers)
    assert pre.status_code == 200
    assert pre.json()["title"] == "Before"

    # Mutate the underlying chat title — the snapshot must NOT change.
    patch = await m2_client.patch(
        f"/api/chats/{chat['id']}",
        json={"title": "After"},
        headers=alice_headers,
    )
    assert patch.status_code == 200
    assert patch.json()["title"] == "After"

    # Snapshot semantics: t1 still reads "Before" — live edits do
    # not bleed into the existing share.
    after_patch = await m2_client.get(f"/api/shared/{t1}", headers=alice_headers)
    assert after_patch.status_code == 200
    assert after_patch.json()["title"] == "Before"

    # Now re-share. The new snapshot captures the CURRENT state
    # (post-PATCH), and the old token rotates to dead.
    res2 = await m2_client.post(f"/api/chats/{chat['id']}/share", headers=alice_headers)
    assert res2.status_code == 200, res2.text
    t2 = res2.json()["token"]
    assert t2 != t1

    # The old token is now 404 — re-share is delete + insert.
    dead = await m2_client.get(f"/api/shared/{t1}", headers=alice_headers)
    assert dead.status_code == 404

    # The new token reflects the NEW title (re-share snapshots the
    # current state, not the original-share state).
    fresh = await m2_client.get(f"/api/shared/{t2}", headers=alice_headers)
    assert fresh.status_code == 200
    assert fresh.json()["title"] == "After"
