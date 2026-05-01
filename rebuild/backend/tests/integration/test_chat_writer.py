"""Unit tests for :func:`app.services.chat_writer.append_assistant_message`.

The writer is the single chat-history append surface shared between the
M2 streaming pipeline (``chat_stream.py``) and the M5 automation
executor's chat-target writes — it has to handle the
``status="complete"|"cancelled"|"error"`` triple consistently and
enforce :data:`MAX_CHAT_HISTORY_BYTES` on every write.

Plan reference: ``rebuild/docs/plans/m2-conversations.md`` § Deliverables
(``append_assistant_message`` signature on line 17), § History-size
enforcement (lines 850-863), and the dispatch-named ``test_chat_writer.py``
target.

These tests touch the DB (the writer's contract is "load the chat row
with FOR UPDATE, mutate the JSON, commit"), so they live in the
integration suite alongside the chat / folder CRUD tests that share the
``alice`` + DB session fixtures.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.core.constants import MAX_CHAT_HISTORY_BYTES
from app.core.ids import new_id
from app.core.time import now_ms
from app.models.chat import Chat
from app.schemas.history import History, HistoryMessage
from app.services.chat_writer import HistoryTooLargeError, append_assistant_message


async def _seed_chat(
    db_session: Any,
    *,
    user_id: str,
    history: History | None = None,
) -> Chat:
    """Persist a minimal chat row owned by ``user_id`` and return it."""
    now = now_ms()
    chat = Chat(
        id=new_id(),
        user_id=user_id,
        title="New Chat",
        history=(history or History()).model_dump(),
        folder_id=None,
        archived=False,
        pinned=False,
        created_at=now,
        updated_at=now,
    )
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)
    return chat


# ---------------------------------------------------------------------------
# status flag wiring
# ---------------------------------------------------------------------------


async def test_append_assistant_message_status_complete_sets_done_true_no_error_no_cancel(
    db_session: Any,
    alice: Any,
) -> None:
    chat = await _seed_chat(db_session, user_id=alice.id)
    new_id_returned = await append_assistant_message(
        db_session,
        chat_id=chat.id,
        parent_message_id=None,
        agent_id="gpt-4o",
        content="hello",
        status="complete",
    )
    await db_session.refresh(chat)
    history = History.model_validate(chat.history)
    msg = history.messages[new_id_returned]
    assert msg.done is True
    assert msg.cancelled is False
    assert msg.error is None
    assert msg.content == "hello"


async def test_append_assistant_message_status_cancelled_sets_done_true_cancelled_true(
    db_session: Any,
    alice: Any,
) -> None:
    chat = await _seed_chat(db_session, user_id=alice.id)
    new = await append_assistant_message(
        db_session,
        chat_id=chat.id,
        parent_message_id=None,
        agent_id="gpt-4o",
        content="partial",
        status="cancelled",
    )
    await db_session.refresh(chat)
    msg = History.model_validate(chat.history).messages[new]
    assert msg.done is True
    assert msg.cancelled is True
    assert msg.error is None
    assert msg.content == "partial"


async def test_append_assistant_message_status_error_sets_done_true_error_payload(
    db_session: Any,
    alice: Any,
) -> None:
    """The Phase 2a writer's chosen error envelope is the literal
    ``{"message": "execution error"}`` short-form (locked in
    ``app/services/chat_writer.py::_status_flags``). Asserted here so a
    future refactor can't silently change the M5 chat-target shape.
    """
    chat = await _seed_chat(db_session, user_id=alice.id)
    new = await append_assistant_message(
        db_session,
        chat_id=chat.id,
        parent_message_id=None,
        agent_id="gpt-4o",
        content="halfway",
        status="error",
    )
    await db_session.refresh(chat)
    msg = History.model_validate(chat.history).messages[new]
    assert msg.done is True
    assert msg.cancelled is False
    assert msg.error == {"message": "execution error"}


# ---------------------------------------------------------------------------
# id + missing-chat contract
# ---------------------------------------------------------------------------


async def test_append_assistant_message_returns_new_message_id(
    db_session: Any,
    alice: Any,
) -> None:
    """Returned id is a UUIDv7 string in the canonical 36-char form."""
    chat = await _seed_chat(db_session, user_id=alice.id)
    new = await append_assistant_message(
        db_session,
        chat_id=chat.id,
        parent_message_id=None,
        agent_id="gpt-4o",
        content="hi",
        status="complete",
    )
    assert isinstance(new, str)
    assert len(new) == 36
    assert new.count("-") == 4  # canonical UUID hyphenation


async def test_append_assistant_message_raises_on_missing_chat(
    db_session: Any,
    alice: Any,  # noqa: ARG001 — fixture sets up the DB in a clean state
) -> None:
    """Phase 2a chose :class:`LookupError` for the missing-chat case."""
    with pytest.raises(LookupError) as exc_info:
        await append_assistant_message(
            db_session,
            chat_id="nonexistent-id",
            parent_message_id=None,
            agent_id="gpt-4o",
            content="hi",
            status="complete",
        )
    assert "nonexistent-id" in str(exc_info.value)


# ---------------------------------------------------------------------------
# history-cap enforcement on every write
# ---------------------------------------------------------------------------


async def test_append_assistant_message_enforces_history_cap_413(
    db_session: Any,
    alice: Any,
) -> None:
    """Pre-seed a chat with a history close to the 1 MiB cap, then
    append a final message large enough to push it over. The writer
    must raise :class:`HistoryTooLargeError` BEFORE the commit lands —
    the row's previous history is preserved.
    """
    big_user_msg = HistoryMessage(
        id=new_id(),
        parentId=None,
        childrenIds=[],
        role="user",
        content="x" * (MAX_CHAT_HISTORY_BYTES - 4096),
        timestamp=now_ms(),
    )
    history = History(messages={big_user_msg.id: big_user_msg}, currentId=big_user_msg.id)
    chat = await _seed_chat(db_session, user_id=alice.id, history=history)
    chat_id = chat.id
    pre_append_history_dump = dict(chat.history)

    with pytest.raises(HistoryTooLargeError) as exc_info:
        await append_assistant_message(
            db_session,
            chat_id=chat_id,
            parent_message_id=big_user_msg.id,
            agent_id="gpt-4o",
            content="y" * 8192,
            status="complete",
        )
    assert exc_info.value.cap == MAX_CHAT_HISTORY_BYTES
    assert exc_info.value.size > MAX_CHAT_HISTORY_BYTES

    # The writer raised AFTER mutating the chat ORM instance but BEFORE
    # commit. Roll the session back so subsequent reads on it see a
    # clean state, then verify the pre-existing history survived on the
    # row by issuing a fresh SELECT through a brand-new session — the
    # current ``db_session`` may still be holding the FOR UPDATE lock
    # from the failed write.
    await db_session.rollback()

    from app.core.db import AsyncSessionLocal

    async with AsyncSessionLocal() as fresh_session:
        fresh = await fresh_session.get(Chat, chat_id)
        assert fresh is not None
        assert fresh.history == pre_append_history_dump
