"""Test that the full Alembic migration chain runs to HEAD on MySQL 8.0."""

import pytest
from sqlalchemy import inspect, text


@pytest.mark.usefixtures('run_migrations')
class TestMySQLMigrations:
    def test_migrations_reach_head(self, mysql_engine):
        """All Alembic revisions applied without error."""
        with mysql_engine.connect() as conn:
            result = conn.execute(text('SELECT version_num FROM alembic_version'))
            rows = result.fetchall()
            assert len(rows) == 1, 'Expected exactly one alembic_version row'
            assert rows[0][0], 'version_num should not be empty'

    def test_core_tables_exist(self, mysql_engine):
        """Key application tables were created by migrations."""
        inspector = inspect(mysql_engine)
        tables = set(inspector.get_table_names())
        expected = {
            'user',
            'auth',
            'chat',
            'chat_message',
            'prompt',
            'model',
            'file',
            'folder',
            'tag',
            'knowledge',
            'function',
            'tool',
            'group',
            'channel',
            'message',
            'note',
            'feedback',
            'access_grant',
            'config',
            'automation',
            'automation_run',
        }
        missing = expected - tables
        assert not missing, f'Missing tables after migration: {missing}'

    def test_chat_table_columns(self, mysql_engine):
        """The chat table has all expected columns including later migrations."""
        inspector = inspect(mysql_engine)
        columns = {c['name'] for c in inspector.get_columns('chat')}
        expected = {
            'id',
            'user_id',
            'title',
            'chat',
            'created_at',
            'updated_at',
            'share_id',
            'archived',
            'pinned',
            'meta',
            'folder_id',
            'tasks',
            'summary',
            'last_read_at',
        }
        missing = expected - columns
        assert not missing, f'Missing columns on chat: {missing}'
