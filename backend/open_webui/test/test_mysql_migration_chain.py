"""End-to-end migration tests against a real MySQL 8.0 container.

Production startup runs the peewee migration chain first (see
``open_webui.internal.db.handle_peewee_migration``) followed by the Alembic
chain via ``alembic upgrade head``. The dialect-specific tests in
``test_mysql_migrations.py`` only verify that Alembic alone reaches HEAD on
a database that some other fixture brought up. That left two gaps:

1. The legacy peewee migrations were never executed against MySQL by CI, so
   regressions like the recent ``007_add_user_last_active_at`` /
   ``017_add_user_oauth_sub`` failures slipped through.
2. The Alembic downgrade path was never exercised on MySQL, so a buggy
   ``downgrade()`` could break disaster-recovery rollbacks without being
   noticed.

These tests close both gaps by spinning up a fresh, isolated MySQL database
per test, running the *full* startup migration sequence, and — for the
round-trip case — downgrading every Alembic revision back to base and
asserting the schema is empty.
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

# Tables created/destroyed only by Alembic. The peewee chain creates a
# ``migratehistory`` table that lives outside Alembic's purview, so it is
# expected to remain after a full Alembic downgrade.
PEEWEE_BOOKKEEPING_TABLES = {'migratehistory'}
ALEMBIC_BOOKKEEPING_TABLES = {'alembic_version'}


def _alembic_config(mysql_url: str):
    from alembic.config import Config

    alembic_ini = Path(__file__).resolve().parents[1] / 'alembic.ini'
    migrations_dir = Path(__file__).resolve().parents[1] / 'migrations'

    cfg = Config(str(alembic_ini))
    cfg.set_main_option('script_location', str(migrations_dir))
    cfg.set_main_option('sqlalchemy.url', mysql_url.replace('%', '%%'))
    return cfg


def _run_full_migration_chain(mysql_url: str) -> None:
    """Run peewee + Alembic migrations the same way ``open_webui`` does on boot."""
    from alembic import command
    from open_webui.internal.db import handle_peewee_migration

    os.environ['DATABASE_URL'] = mysql_url
    handle_peewee_migration(mysql_url)

    cfg = _alembic_config(mysql_url)
    command.upgrade(cfg, 'head')


@pytest.mark.slow
class TestMySQLMigrationChain:
    def test_peewee_then_alembic_reaches_head(self, migration_db_url):
        """Full startup chain (peewee + Alembic) succeeds on an empty MySQL DB.

        This guards against MySQL-specific failures inside individual peewee
        migrations (identifier quoting, TEXT-column unique indexes, etc.) and
        verifies they compose cleanly with the Alembic chain — exactly the
        sequence ``open_webui`` executes when it starts against a fresh DB.
        """
        _run_full_migration_chain(migration_db_url)

        engine = create_engine(migration_db_url, echo=False)
        try:
            inspector = inspect(engine)
            tables = set(inspector.get_table_names())

            assert 'alembic_version' in tables, 'Alembic head was not reached'
            assert 'migratehistory' in tables, 'Peewee chain did not run'

            # Spot-check columns. ``oauth_sub`` is added by Peewee 017 and
            # later dropped by Alembic ``b10670c03dd5`` once OAuth identities
            # move into a JSON ``oauth`` column, so it must NOT be present at
            # HEAD. The other columns are added by Peewee 007 / Alembic
            # b10670c03dd5 respectively and stay forever.
            user_columns = {c['name'] for c in inspector.get_columns('user')}
            assert {'created_at', 'updated_at', 'last_active_at', 'oauth'} <= user_columns
            assert 'oauth_sub' not in user_columns, 'b10670c03dd5_update_user_table should have dropped oauth_sub'

            with engine.connect() as conn:
                version = conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
            assert version, 'alembic_version row should not be empty'
        finally:
            engine.dispose()

    def test_alembic_round_trip_to_base(self, migration_db_url):
        """Upgrade to head, then downgrade every Alembic revision back to base.

        After downgrading to ``base`` the only tables left should be the
        peewee bookkeeping table (``migratehistory``) since peewee migrations
        run before Alembic and are not unwound by ``alembic downgrade``.
        Anything else means a ``downgrade()`` is broken on MySQL.
        """
        from alembic import command

        _run_full_migration_chain(migration_db_url)

        cfg = _alembic_config(migration_db_url)
        command.downgrade(cfg, 'base')

        engine = create_engine(migration_db_url, echo=False)
        try:
            inspector = inspect(engine)
            remaining = set(inspector.get_table_names())

            leftover = remaining - PEEWEE_BOOKKEEPING_TABLES - ALEMBIC_BOOKKEEPING_TABLES
            assert not leftover, (
                f'Tables remaining after full Alembic downgrade: {sorted(leftover)}. '
                'A downgrade() somewhere in the migration chain is incomplete on MySQL.'
            )

            if 'alembic_version' in remaining:
                with engine.connect() as conn:
                    rows = conn.execute(text('SELECT version_num FROM alembic_version')).fetchall()
                assert rows == [], f'alembic_version still tracks revisions: {rows}'
        finally:
            engine.dispose()
