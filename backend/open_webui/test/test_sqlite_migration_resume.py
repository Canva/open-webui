"""Regression tests for resuming partially applied SQLite migrations."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def _alembic_config(sqlite_url: str) -> Config:
    alembic_ini = Path(__file__).resolve().parents[1] / 'alembic.ini'
    migrations_dir = Path(__file__).resolve().parents[1] / 'migrations'

    cfg = Config(str(alembic_ini))
    cfg.set_main_option('script_location', str(migrations_dir))
    cfg.set_main_option('sqlalchemy.url', sqlite_url.replace('%', '%%'))
    return cfg


def test_sqlite_upgrade_resumes_after_partial_b10670c03dd5(monkeypatch, tmp_path):
    """A drifted SQLite DB with one pre-added column should still reach head."""
    db_path = tmp_path / 'resume-partial-b106.sqlite3'
    sqlite_url = f'sqlite:///{db_path}'

    monkeypatch.setenv('DATABASE_URL', sqlite_url)

    from open_webui.internal.db import handle_peewee_migration

    handle_peewee_migration(sqlite_url)

    engine = create_engine(sqlite_url, echo=False)
    try:
        with engine.begin() as conn:
            conn.execute(text('ALTER TABLE user ADD COLUMN profile_banner_image_url TEXT'))
    finally:
        engine.dispose()

    command.upgrade(_alembic_config(sqlite_url), 'head')

    engine = create_engine(sqlite_url, echo=False)
    try:
        inspector = inspect(engine)
        user_columns = {column['name'] for column in inspector.get_columns('user')}

        assert {
            'profile_banner_image_url',
            'timezone',
            'presence_state',
            'status_emoji',
            'status_message',
            'status_expires_at',
            'oauth',
        } <= user_columns
        assert 'oauth_sub' not in user_columns
        assert 'api_key' not in user_columns

        with engine.connect() as conn:
            version = conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
        assert version
    finally:
        engine.dispose()
