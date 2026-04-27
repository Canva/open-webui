"""Test MySQL-specific dialect branches against a real MySQL 8.0 container.

Each test inserts data via the async session then exercises the raw SQL
or SQLAlchemy expressions that our dialect branches produce.
"""

import time
import uuid

import pytest
from sqlalchemy import select, text, func, cast, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from open_webui.models.chats import Chat
from open_webui.models.chat_messages import ChatMessage
from open_webui.models.prompts import Prompt
from open_webui.models.users import User


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_user(db: AsyncSession, user_id: str, *, oauth: dict | None = None, scim: dict | None = None) -> None:
    db.add(
        User(
            id=user_id,
            email=f'{user_id}@test.com',
            role='user',
            name='Test User',
            profile_image_url='',
            last_active_at=_now(),
            updated_at=_now(),
            created_at=_now(),
            oauth=oauth,
            scim=scim,
        )
    )
    await db.commit()


async def _seed_chat(
    db: AsyncSession,
    chat_id: str,
    user_id: str,
    *,
    title: str = 'Test Chat',
    messages: list | None = None,
    tags: list | None = None,
) -> None:
    meta = {}
    if tags is not None:
        meta['tags'] = tags
    chat_payload = {'messages': messages or []}
    db.add(
        Chat(
            id=chat_id,
            user_id=user_id,
            title=title,
            chat=chat_payload,
            meta=meta,
            created_at=_now(),
            updated_at=_now(),
        )
    )
    await db.commit()


async def _seed_chat_message(
    db: AsyncSession,
    chat_id: str,
    user_id: str,
    *,
    role: str = 'assistant',
    model_id: str = 'gpt-4',
    usage: dict | None = None,
) -> str:
    msg_id = _uid()
    db.add(
        ChatMessage(
            id=msg_id,
            chat_id=chat_id,
            user_id=user_id,
            role=role,
            model_id=model_id,
            content='hello',
            done=True,
            usage=usage,
            created_at=_now(),
            updated_at=_now(),
        )
    )
    await db.commit()
    return msg_id


async def _seed_prompt(
    db: AsyncSession,
    prompt_id: str,
    user_id: str,
    *,
    tags: list | None = None,
) -> None:
    db.add(
        Prompt(
            id=prompt_id,
            command=f'/test-{prompt_id[:8]}',
            user_id=user_id,
            name='Test Prompt',
            content='Do something',
            tags=tags,
            is_active=True,
            created_at=_now(),
            updated_at=_now(),
        )
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures('run_migrations')
@pytest.mark.asyncio
class TestMySQLChatContentSearch:
    """Exercises the MySQL JSON_SEARCH branch in chats.py."""

    async def test_search_finds_chat_by_message_content(self, db_session: AsyncSession):
        user_id = _uid()
        chat_id = _uid()
        await _seed_user(db_session, user_id)
        await _seed_chat(
            db_session,
            chat_id,
            user_id,
            title='Ordinary Title',
            messages=[{'role': 'user', 'content': 'Tell me about quantum computing'}],
        )

        result = await db_session.execute(
            text(
                'SELECT id FROM chat WHERE '
                "JSON_SEARCH(LOWER(chat.chat), 'one', :pattern, NULL, '$.messages[*].content') IS NOT NULL"
            ),
            {'pattern': '%quantum%'},
        )
        rows = result.fetchall()
        assert any(r[0] == chat_id for r in rows)

    async def test_search_finds_chat_by_title(self, db_session: AsyncSession):
        user_id = _uid()
        chat_id = _uid()
        await _seed_user(db_session, user_id)
        await _seed_chat(db_session, chat_id, user_id, title='Quantum Physics Discussion')

        result = await db_session.execute(select(Chat.id).where(Chat.title.ilike('%quantum%'), Chat.id == chat_id))
        assert result.scalar_one_or_none() == chat_id

    async def test_null_byte_safety_filter(self, db_session: AsyncSession):
        """Chats with \\u0000 in JSON are filtered out by our safety clause."""
        user_id = _uid()
        chat_id = _uid()
        await _seed_user(db_session, user_id)
        # Manually insert a chat whose JSON text contains the \\u0000 escape
        # ``archived`` is declared NOT NULL in the chat table on MySQL with no
        # SQL-level default, so an explicit value is required when inserting via
        # raw SQL (the SQLAlchemy ORM otherwise supplies the Python-side
        # default).
        await db_session.execute(
            text(
                'INSERT INTO chat (id, user_id, title, chat, meta, archived, pinned, created_at, updated_at) '
                "VALUES (:id, :uid, 'bad chat', :chat_json, '{}', 0, 0, :now, :now)"
            ),
            {
                'id': chat_id,
                'uid': user_id,
                'chat_json': '{"messages":[{"content":"has \\\\u0000 byte"}]}',
                'now': _now(),
            },
        )
        await db_session.commit()

        result = await db_session.execute(
            text("SELECT id FROM chat WHERE CAST(chat.chat AS CHAR) NOT LIKE '%\\\\u0000%'")
        )
        ids = [r[0] for r in result.fetchall()]
        assert chat_id not in ids


@pytest.mark.usefixtures('run_migrations')
@pytest.mark.asyncio
class TestMySQLTagFilters:
    """Exercises the MySQL JSON_CONTAINS tag filter branch."""

    async def test_filter_chat_by_tag(self, db_session: AsyncSession):
        user_id = _uid()
        chat_id = _uid()
        await _seed_user(db_session, user_id)
        await _seed_chat(db_session, chat_id, user_id, tags=['python', 'ai'])

        result = await db_session.execute(
            text("SELECT id FROM chat WHERE JSON_CONTAINS(JSON_EXTRACT(chat.meta, '$.tags'), JSON_QUOTE(:tag))"),
            {'tag': 'python'},
        )
        assert result.scalar_one_or_none() == chat_id

    async def test_filter_chat_excludes_wrong_tag(self, db_session: AsyncSession):
        user_id = _uid()
        chat_id = _uid()
        await _seed_user(db_session, user_id)
        await _seed_chat(db_session, chat_id, user_id, tags=['python'])

        result = await db_session.execute(
            text("SELECT id FROM chat WHERE JSON_CONTAINS(JSON_EXTRACT(chat.meta, '$.tags'), JSON_QUOTE(:tag))"),
            {'tag': 'rust'},
        )
        assert result.scalar_one_or_none() is None

    async def test_empty_tags_detected(self, db_session: AsyncSession):
        user_id = _uid()
        chat_id = _uid()
        await _seed_user(db_session, user_id)
        await _seed_chat(db_session, chat_id, user_id, tags=[])

        result = await db_session.execute(
            text(
                'SELECT id FROM chat WHERE '
                "(JSON_LENGTH(JSON_EXTRACT(chat.meta, '$.tags')) = 0 "
                "OR JSON_EXTRACT(chat.meta, '$.tags') IS NULL) "
                'AND chat.id = :cid'
            ),
            {'cid': chat_id},
        )
        assert result.scalar_one_or_none() == chat_id


@pytest.mark.usefixtures('run_migrations')
@pytest.mark.asyncio
class TestMySQLPromptTagSearch:
    """Exercises the MySQL JSON_SEARCH branch for prompt tag filtering."""

    async def test_prompt_tag_search(self, db_session: AsyncSession):
        user_id = _uid()
        prompt_id = _uid()
        await _seed_user(db_session, user_id)
        await _seed_prompt(db_session, prompt_id, user_id, tags=['coding', 'python'])

        result = await db_session.execute(
            text("SELECT id FROM prompt WHERE JSON_SEARCH(LOWER(prompt.tags), 'one', :tag) IS NOT NULL"),
            {'tag': 'coding'},
        )
        assert result.scalar_one_or_none() == prompt_id


@pytest.mark.usefixtures('run_migrations')
@pytest.mark.asyncio
class TestMySQLTokenUsage:
    """Exercises the MySQL JSON_EXTRACT branch for token aggregation."""

    async def test_json_extract_token_counts(self, db_session: AsyncSession):
        user_id = _uid()
        chat_id = _uid()
        await _seed_user(db_session, user_id)
        await _seed_chat(db_session, chat_id, user_id)

        usage = {'input_tokens': 100, 'output_tokens': 50}
        await _seed_chat_message(db_session, chat_id, user_id, usage=usage)

        result = await db_session.execute(
            select(
                func.sum(cast(func.json_extract(ChatMessage.usage, '$.input_tokens'), Integer)),
                func.sum(cast(func.json_extract(ChatMessage.usage, '$.output_tokens'), Integer)),
            ).where(ChatMessage.chat_id == chat_id)
        )
        row = result.one()
        assert row[0] == 100
        assert row[1] == 50

    async def test_null_usage_ignored(self, db_session: AsyncSession):
        user_id = _uid()
        chat_id = _uid()
        await _seed_user(db_session, user_id)
        await _seed_chat(db_session, chat_id, user_id)

        await _seed_chat_message(db_session, chat_id, user_id, usage=None)

        result = await db_session.execute(
            select(
                func.sum(cast(func.json_extract(ChatMessage.usage, '$.input_tokens'), Integer)),
            ).where(ChatMessage.chat_id == chat_id)
        )
        assert result.scalar_one_or_none() is None


@pytest.mark.usefixtures('run_migrations')
@pytest.mark.asyncio
class TestMySQLOAuthSCIMLookup:
    """Exercises the MySQL JSON_EXTRACT / JSON_UNQUOTE branch for user lookups."""

    async def test_oauth_lookup_by_provider_sub(self, db_session: AsyncSession):
        user_id = _uid()
        oauth_data = {'google': {'sub': 'google-sub-123'}}
        await _seed_user(db_session, user_id, oauth=oauth_data)

        result = await db_session.execute(
            text('SELECT id FROM `user` WHERE JSON_UNQUOTE(JSON_EXTRACT(`user`.oauth, :path)) = :sub'),
            {'path': '$.google.sub', 'sub': 'google-sub-123'},
        )
        assert result.scalar_one_or_none() == user_id

    async def test_oauth_lookup_wrong_sub_returns_none(self, db_session: AsyncSession):
        user_id = _uid()
        oauth_data = {'google': {'sub': 'google-sub-123'}}
        await _seed_user(db_session, user_id, oauth=oauth_data)

        result = await db_session.execute(
            text('SELECT id FROM `user` WHERE JSON_UNQUOTE(JSON_EXTRACT(`user`.oauth, :path)) = :sub'),
            {'path': '$.google.sub', 'sub': 'wrong-sub'},
        )
        assert result.scalar_one_or_none() is None

    async def test_scim_lookup_by_external_id(self, db_session: AsyncSession):
        user_id = _uid()
        scim_data = {'okta': {'external_id': 'okta-ext-456'}}
        await _seed_user(db_session, user_id, scim=scim_data)

        result = await db_session.execute(
            text('SELECT id FROM `user` WHERE JSON_UNQUOTE(JSON_EXTRACT(`user`.scim, :path)) = :external_id'),
            {'path': '$.okta.external_id', 'external_id': 'okta-ext-456'},
        )
        assert result.scalar_one_or_none() == user_id
