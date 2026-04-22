"""Shared pytest fixtures for MySQL integration tests.

Uses pytest-docker to spin up a MySQL 8.0 container, run Alembic migrations,
and provide async sessions for each test.
"""

import asyncio
import os
from pathlib import Path

import pymysql
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

MYSQL_ROOT_PASSWORD = 'testpass'
MYSQL_DATABASE = 'openwebui_test'


@pytest.fixture(scope='session')
def event_loop():
    """Create a single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


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
    """Run the full Alembic migration chain against the MySQL container."""
    from alembic import command
    from alembic.config import Config

    alembic_ini = Path(__file__).resolve().parents[1] / 'alembic.ini'
    migrations_dir = Path(__file__).resolve().parents[1] / 'migrations'

    cfg = Config(str(alembic_ini))
    cfg.set_main_option('script_location', str(migrations_dir))
    cfg.set_main_option('sqlalchemy.url', mysql_url.replace('%', '%%'))

    # Patch DATABASE_URL in the env module so migrations/env.py picks it up
    os.environ['DATABASE_URL'] = mysql_url
    command.upgrade(cfg, 'head')

    yield mysql_engine


@pytest.fixture
async def db_session(run_migrations, mysql_async_engine):
    """Provide an async session that rolls back after each test."""
    async_session = async_sessionmaker(mysql_async_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()
