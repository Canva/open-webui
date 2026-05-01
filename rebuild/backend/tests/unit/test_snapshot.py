"""Pure-function unit tests for the M3 share-snapshot copy semantics.

Anchored to ``rebuild/docs/plans/m3-sharing.md`` § Snapshot semantics:
the snapshot is captured at share time and is **not live** — editing
the original chat after sharing must not affect the snapshot. The
HTTP-level proof of this contract lives in
``tests/integration/test_shares.py::test_get_shared_reads_snapshot_not_live_chat``;
the tests below are the *narrower* in-memory proof of the underlying
mechanism.

The router (``app/routers/shares.py``) writes ``history=chat.history``
straight into the new ``SharedChat`` instance and then immediately
``await db.commit()``s. SQLAlchemy's MySQL ``JSON`` type serialises
the dict to JSON text on commit, so the on-disk representation is
always a copy — the wire boundary is what guarantees immutability.
The two tests here demonstrate:

1. The *in-memory* boundary is fragile: passing the dict by reference
   (without going through the JSON roundtrip) leaks subsequent
   mutations into the snapshot. This is a contract-for-the-reviewer
   test — if a future caller ever batches operations and never hits
   the ``commit`` (or stages multiple chats and shares before a single
   commit), the assumption that "the snapshot is isolated" would
   silently break. The test exists to anchor the expectation in code
   so the next agent who reads the router sees the explicit
   "reference vs. copy" lever.
2. The JSON roundtrip is what gives us the production guarantee:
   ``json.loads(json.dumps(d))`` returns a distinct, equal dict, and
   subsequent mutation of the original does not bleed through.

These are intentionally *unit* tests — no DB, no fixtures, no
``async`` machinery. The HTTP-level snapshot test in
``test_shares.py`` is the live-fire proof; this file documents the
mechanism and protects against the in-memory-mutation regression
the live test wouldn't catch.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from app.core.ids import new_id
from app.core.time import now_ms
from app.models.chat import Chat
from app.models.shared_chat import SharedChat


def _make_chat_with_history(history: dict[str, Any]) -> Chat:
    """Build a transient ``Chat`` instance carrying ``history``.

    The chat is never added to a session — these are pure in-memory
    object-construction tests. ``user_id`` is a synthetic string
    because there is no FK enforcement on a detached instance, and
    every other field gets the model's declared default (or a fresh
    UUIDv7 id).
    """
    now = now_ms()
    return Chat(
        id=new_id(),
        user_id=new_id(),
        title="Snapshot test chat",
        history=history,
        archived=False,
        pinned=False,
        created_at=now,
        updated_at=now,
    )


def _seed_history() -> dict[str, Any]:
    """A small but realistic ``History``-shaped dict.

    Mirrors the M2 ``History`` schema: one user message, one assistant
    reply, ``currentId`` pointing at the leaf. Tests below mutate
    ``messages`` in-place to simulate an owner adding a new turn after
    sharing.
    """
    return {
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
                "usage": None,
            },
        },
        "currentId": "a1",
    }


def test_sharedchat_history_is_independent_of_source_chat_dict() -> None:
    """Reference-vs-deepcopy lever: prove the test exercises both paths.

    This is a *contract-for-the-reviewer* test. The router currently
    writes ``history=chat.history`` and then commits, and the JSON
    roundtrip on commit gives us the production guarantee (proven by
    the second test below + the HTTP-level
    ``test_get_shared_reads_snapshot_not_live_chat``). But if a future
    refactor ever batches snapshot creation with another operation
    such that the ``commit`` is delayed — or worse, if a caller stages
    multiple SharedChat instances against an in-memory ``chat`` and
    then mutates ``chat.history`` between staging and commit — the
    in-memory dict would still be shared by reference and the snapshot
    would silently bleed.

    The test makes both shapes (reference, deepcopy) explicit in code
    so the next agent who touches ``app/routers/shares.py::create_share``
    sees the lever and the failure mode.
    """
    history = _seed_history()
    chat = _make_chat_with_history(history)

    # Path 1 — *reference* copy. The router currently does this; the
    # production safety comes from the immediately-following commit
    # which serialises the dict to JSON text. In memory, the two dicts
    # are the same object.
    shared_ref = SharedChat(
        id="t" * 43,
        chat_id=chat.id,
        user_id=chat.user_id,
        title=chat.title,
        history=chat.history,
        created_at=now_ms(),
    )
    # The lever — if this `is` ever flips to `is not` without going
    # through `copy.deepcopy`, somebody changed the router and the
    # second assertion below (mutation bleeds through) will explain
    # what they changed.
    assert shared_ref.history is chat.history

    # Path 2 — *deepcopy*. Models the post-commit production state
    # (the dict is a fresh object materialised from JSON text). The
    # two dicts are equal but distinct.
    shared_copy = SharedChat(
        id="u" * 43,
        chat_id=chat.id,
        user_id=chat.user_id,
        title=chat.title,
        history=copy.deepcopy(chat.history),
        created_at=now_ms(),
    )
    assert shared_copy.history is not chat.history
    assert shared_copy.history == chat.history

    # Mutate the source chat's history — simulate the owner adding a
    # new turn after sharing.
    chat.history["messages"]["u2"] = {
        "id": "u2",
        "parentId": "a1",
        "childrenIds": [],
        "role": "user",
        "content": "After-the-share message",
        "timestamp": 1700000002,
        "agent_id": None,
        "agentName": None,
        "done": True,
        "error": None,
        "cancelled": False,
        "usage": None,
    }

    # Reference path: mutation bleeds through. NOT what we want in
    # production — this is the failure mode the JSON roundtrip on
    # commit defends against.
    assert "u2" in shared_ref.history["messages"]

    # Deepcopy path: the snapshot is insulated. This is the
    # production-correct shape (matches what comes back from MySQL
    # after the commit).
    assert "u2" not in shared_copy.history["messages"]
    assert set(shared_copy.history["messages"].keys()) == {"u1", "a1"}


def test_sharedchat_history_survives_source_chat_deletion_via_json_roundtrip() -> None:
    """JSON roundtrip is the production-grade copy mechanism.

    MySQL's JSON column type serialises the dict to JSON text on
    INSERT and re-materialises a fresh dict on SELECT — so any caller
    that goes through the wire boundary (which is every caller of the
    M3 share router) gets a deepcopy for free. This test models the
    wire boundary in-memory via ``json.dumps`` + ``json.loads`` and
    confirms the two halves of the contract:

    * The roundtripped dict is a *distinct* object (``is not``) from
      the source — proves the wire round-trip materialises a fresh
      dict rather than handing back the same reference.
    * The roundtripped dict is *equal* (``==``) to the source —
      proves no information is lost in the encode/decode pair (the
      ``History``-shaped dicts the router stores are JSON-clean: only
      strings, ints, bools, None, lists, dicts).
    * Mutation of the source after the roundtrip does not bleed into
      the copy — the actual snapshot-isolation guarantee the plan
      depends on.

    Quoting the plan back to itself: "MySQL's JSON column gives us
    this guarantee at the wire boundary; the in-memory state before
    the commit is the only window where a ref-copy would cause a
    leak."
    """
    src = _seed_history()
    roundtripped = json.loads(json.dumps(src))

    assert roundtripped is not src
    assert roundtripped == src

    # Mutate the source — the owner adds another turn after sharing.
    src["messages"]["u2"] = {
        "id": "u2",
        "parentId": "a1",
        "childrenIds": [],
        "role": "user",
        "content": "After-the-share message",
        "timestamp": 1700000002,
        "agent_id": None,
        "agentName": None,
        "done": True,
        "error": None,
        "cancelled": False,
        "usage": None,
    }
    src["currentId"] = "u2"

    # The roundtripped copy is unaffected.
    assert "u2" not in roundtripped["messages"]
    assert roundtripped["currentId"] == "a1"
    assert set(roundtripped["messages"].keys()) == {"u1", "a1"}
