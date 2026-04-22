"""Shared pytest fixtures for MySQL integration tests.

Uses pytest-docker to spin up a MySQL 8.0 container, run Alembic migrations,
and provide async sessions for each test.
"""

import os
from pathlib import Path

import pymysql
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

MYSQL_ROOT_PASSWORD = 'testpass'
MYSQL_DATABASE = 'openwebui_test'


# NOTE: We intentionally do NOT define an ``event_loop`` fixture here.
# pytest-asyncio 1.x deprecated overriding ``event_loop`` in favour of the
# ``asyncio_default_fixture_loop_scope`` / ``asyncio_default_test_loop_scope``
# options set in ``pyproject.toml`` (both pinned to ``session``). This keeps
# session-scoped async resources like ``create_async_engine`` valid across
# every test in the session.


@pytest.fixture(scope='session')
def docker_compose_file():
    return str(Path(__file__).parent / 'docker-compose.test.yaml')


def _mysql_ready(host: str, port: int) -> bool:
    try:
        conn = pymysql.connect(
            host=host,
            port=port,
            user='root',
            password=MYSQL_ROOT_PASSWORD,
            database=MYSQL_DATABASE,
        )
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope='session')
def mysql_service(docker_services):
    """Wait for the MySQL container to be connectable and return (host, port)."""
    port = docker_services.port_for('mysql', 3306)
    host = 'localhost'

    # pytest-docker's wait_until_responsive with a generous timeout
    docker_services.wait_until_responsive(
        timeout=60,
        pause=2,
        check=lambda: _mysql_ready(host, port),
    )
    return host, port


@pytest.fixture(scope='session')
def mysql_url(mysql_service):
    host, port = mysql_service
    return f'mysql+pymysql://root:{MYSQL_ROOT_PASSWORD}@{host}:{port}/{MYSQL_DATABASE}'


@pytest.fixture(scope='session')
def mysql_async_url(mysql_url):
    return mysql_url.replace('mysql+pymysql://', 'mysql+aiomysql://', 1)


@pytest.fixture(scope='session')
def mysql_engine(mysql_url):
    engine = create_engine(mysql_url, echo=False)
    yield engine
    engine.dispose()


@pytest.fixture(scope='session')
def mysql_async_engine(mysql_async_url):
    engine = create_async_engine(mysql_async_url, echo=False)
    yield engine
    # Can't call sync dispose in async engine; the event loop fixture handles cleanup.


@pytest.fixture(scope='session')
def run_migrations(mysql_url, mysql_engine):
    """Run the full startup migration chain (peewee + Alembic) on MySQL.

    Mirrors what ``open_webui`` actually does on boot — the legacy peewee
    chain creates the original tables (``tag``, ``user``, …) and then
    Alembic alters/extends them. Several Alembic migrations short-circuit
    when their target tables already exist and silently rely on the peewee
    chain to have created them, so running Alembic in isolation against a
    truly empty database produces a different schema than production. We
    drop everything first to guarantee a clean run regardless of test
    ordering or container reuse between sessions.
    """
    from alembic import command
    from alembic.config import Config
    from open_webui.internal.db import handle_peewee_migration

    alembic_ini = Path(__file__).resolve().parents[1] / 'alembic.ini'
    migrations_dir = Path(__file__).resolve().parents[1] / 'migrations'

    cfg = Config(str(alembic_ini))
    cfg.set_main_option('script_location', str(migrations_dir))
    cfg.set_main_option('sqlalchemy.url', mysql_url.replace('%', '%%'))

    with mysql_engine.connect() as conn:
        conn.execute(text('SET FOREIGN_KEY_CHECKS=0'))
        rows = conn.execute(text('SHOW TABLES')).fetchall()
        for (table_name,) in rows:
            conn.execute(text(f'DROP TABLE IF EXISTS `{table_name}`'))
        conn.execute(text('SET FOREIGN_KEY_CHECKS=1'))
        conn.commit()

    os.environ['DATABASE_URL'] = mysql_url
    handle_peewee_migration(mysql_url)
    command.upgrade(cfg, 'head')

    yield mysql_engine


@pytest.fixture
async def db_session(run_migrations, mysql_async_engine):
    """Provide an async session that rolls back after each test."""
    async_session = async_sessionmaker(mysql_async_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()


@pytest.fixture
def migration_db_url(mysql_service, request):
    """Yield a URL to a freshly created, isolated MySQL database for migration tests.

    Each invocation creates a uniquely named database on the existing MySQL
    container, returns the SQLAlchemy URL to it, then drops it on teardown so
    independent migration runs cannot interfere with one another or with the
    shared fixtures used by the dialect-specific query tests.
    """
    host, port = mysql_service
    safe_name = request.node.name.lower()
    for ch in '[]:- /\\.':
        safe_name = safe_name.replace(ch, '_')
    safe_name = safe_name[:48]
    db_name = f'owui_mig_{safe_name}'

    server_url = f'mysql+pymysql://root:{MYSQL_ROOT_PASSWORD}@{host}:{port}/mysql'
    server_engine = create_engine(server_url, echo=False)
    try:
        with server_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS `{db_name}`'))
            conn.execute(text(f'CREATE DATABASE `{db_name}`'))
            conn.commit()

        yield f'mysql+pymysql://root:{MYSQL_ROOT_PASSWORD}@{host}:{port}/{db_name}'
    finally:
        with server_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS `{db_name}`'))
            conn.commit()
        server_engine.dispose()
