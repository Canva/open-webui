"""Migration contract tests — gated by the m0 acceptance criteria.

Four contract tests, mandatory for every revision the repo will ever
hold (m0 plan § Alembic helper test gate):

1. ``test_upgrade_head_is_idempotent`` — ``alembic upgrade head`` from a
   fresh DB succeeds; rerun is a no-op (table count unchanged).
2. ``test_downgrade_base_is_idempotent`` — upgrade then double-downgrade;
   the second downgrade is a no-op.
3. ``test_partial_upgrade_recovers`` — half-applied schema (``user``
   table created with a subset of columns, no alembic_version row) +
   ``alembic upgrade head`` completes without error. NB: the M0 baseline
   only ships ``op.create_table_if_not_exists`` for the single ``user``
   table; the helper short-circuits when ``has_table('user')`` is true,
   so the table's column shape is preserved (it does NOT add the missing
   columns). For M1+ when revisions add new columns / indexes via
   ``add_column_if_not_exists`` / ``create_index_if_not_exists``, this
   test grows to assert the missing artefacts get added. See "Deviation
   from dispatch" comment block above ``test_partial_upgrade_recovers``.
4. ``test_no_bare_op_calls`` — AST walk of ``backend/alembic/versions/``;
   bare ``op.create_*`` / ``op.drop_*`` / ``op.add_column`` / etc. are
   forbidden (use the helpers). Also: every ``execute_if(...)`` whose
   SQL begins with ``ALTER TABLE`` must end with ``ALGORITHM=`` and
   ``LOCK=`` clauses so blocking behaviour is explicit at the call site.

Implementation note on driver choice. The conftest's ``database_url``
is the asyncmy form. We deliberately re-use the async engine for the
test-side DDL (drop/create/list) instead of bringing in a sync driver
(``pymysql``/``mysqlclient``) — the project pins ``asyncmy`` only.
``asyncio.run`` is safe here because each test function is sync and no
event loop is owned by the surrounding scope (alembic does its own
``asyncio.run`` inside ``env.py``).
"""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Awaitable
from pathlib import Path
from typing import Any, TypeVar

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
ALEMBIC_DIR = BACKEND_DIR / "alembic"
VERSIONS_DIR = ALEMBIC_DIR / "versions"


T = TypeVar("T")


def _run(coro: Awaitable[T]) -> T:
    """Driver to run a coroutine to completion from sync test code."""
    return asyncio.run(coro)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Direct-DDL helpers (use the asyncmy engine; no sync driver required).
# ---------------------------------------------------------------------------


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    # Pin to absolute path so the tests are cwd-independent.
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    return cfg


async def _async_drop_everything(database_url: str) -> None:
    engine = create_async_engine(database_url, future=True)
    try:
        async with engine.begin() as conn:
            tables = await conn.run_sync(lambda sync_conn: sa.inspect(sync_conn).get_table_names())
            for table in tables:
                await conn.execute(sa.text(f"DROP TABLE IF EXISTS `{table}`"))
    finally:
        await engine.dispose()


async def _async_list_tables(database_url: str) -> list[str]:
    engine = create_async_engine(database_url, future=True)
    try:
        async with engine.connect() as conn:
            return sorted(
                await conn.run_sync(lambda sync_conn: sa.inspect(sync_conn).get_table_names())
            )
    finally:
        await engine.dispose()


async def _async_list_user_columns(database_url: str) -> list[str]:
    engine = create_async_engine(database_url, future=True)
    try:
        async with engine.connect() as conn:

            def _columns(sync_conn: Any) -> list[str]:
                inspector = sa.inspect(sync_conn)
                if not inspector.has_table("user"):
                    return []
                return sorted(c["name"] for c in inspector.get_columns("user"))

            return await conn.run_sync(_columns)
    finally:
        await engine.dispose()


async def _async_exec(database_url: str, sql: str) -> None:
    engine = create_async_engine(database_url, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text(sql))
    finally:
        await engine.dispose()


@pytest.fixture
def fresh_db(engine: Any, database_url: str) -> str:
    """Drop every table in the test DB, then yield the URL.

    ``engine`` is requested so the session-scoped
    ``alembic upgrade head`` from the conftest has already executed once
    against the container (proving the env is wired). We then wipe back
    to virgin and let each test drive its own up/down sequence.
    """
    _run(_async_drop_everything(database_url))
    return database_url


# ---------------------------------------------------------------------------
# Contract test 1: upgrade head is idempotent.
# ---------------------------------------------------------------------------


def test_upgrade_head_is_idempotent(fresh_db: str) -> None:
    cfg = _alembic_config()

    command.upgrade(cfg, "head")
    after_first = _run(_async_list_tables(fresh_db))
    assert "user" in after_first
    assert "alembic_version" in after_first

    command.upgrade(cfg, "head")
    after_second = _run(_async_list_tables(fresh_db))

    assert after_first == after_second


# ---------------------------------------------------------------------------
# Contract test 2: downgrade base is idempotent.
# ---------------------------------------------------------------------------


def test_downgrade_base_is_idempotent(fresh_db: str) -> None:
    cfg = _alembic_config()

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    after_first_down = _run(_async_list_tables(fresh_db))

    # alembic_version may remain after a downgrade-to-base (alembic keeps
    # the version-tracking table around as an empty marker). The user
    # table must be gone.
    assert "user" not in after_first_down

    command.downgrade(cfg, "base")
    after_second_down = _run(_async_list_tables(fresh_db))

    assert after_first_down == after_second_down


# ---------------------------------------------------------------------------
# Contract test 3: partial-recovery from a half-applied schema.
# ---------------------------------------------------------------------------
#
# Deviation from dispatch (documented per the dispatch's explicit
# "Document if your interpretation differs"):
#
#   The dispatch's example asserts the user table has all five columns
#   after upgrade-head over a partially-created table. The M0 baseline's
#   only DDL is `create_table_if_not_exists("user", ...)`, which the
#   helper short-circuits when `has_table("user")` is true. It does NOT
#   reach into the existing table to add missing columns; that is the
#   `add_column_if_not_exists` helper's job, which M1+ revisions use.
#
#   So for M0 the verifiable contract is: "upgrade head over a partial
#   user table completes without error and the table contents are
#   preserved (no destructive recovery)". For M1+ this test will grow a
#   parametrised case asserting missing columns/indexes get filled in.


def test_partial_upgrade_recovers(fresh_db: str) -> None:
    cfg = _alembic_config()

    # Manually create the user table with only id + email columns and
    # no alembic_version row, simulating a crash mid-migration.
    _run(
        _async_exec(
            fresh_db,
            "CREATE TABLE `user` ("
            "  id VARCHAR(36) NOT NULL PRIMARY KEY,"
            "  email VARCHAR(320) NOT NULL,"
            "  UNIQUE KEY uq_user_email (email)"
            ") ENGINE=InnoDB CHARSET=utf8mb4 "
            "COLLATE=utf8mb4_0900_ai_ci",
        )
    )

    # Re-run alembic upgrade head — the helper must short-circuit on the
    # already-existing table without raising.
    command.upgrade(cfg, "head")

    # M0 contract: upgrade succeeded, user table still exists and
    # retains the columns we created. (The helper does not add columns;
    # see the deviation note above.)
    columns = _run(_async_list_user_columns(fresh_db))
    assert "id" in columns
    assert "email" in columns
    assert "user" in _run(_async_list_tables(fresh_db))


# ---------------------------------------------------------------------------
# Contract test 4: AST gate against bare op.* calls in versions/.
# ---------------------------------------------------------------------------


BANNED_OP_CALLS: frozenset[str] = frozenset(
    {
        "create_table",
        "drop_table",
        "create_index",
        "drop_index",
        "add_column",
        "drop_column",
        "alter_column",
        "create_foreign_key",
        "drop_constraint",
        "create_unique_constraint",
        "create_check_constraint",
        "create_primary_key",
    }
)


def _string_arg(node: ast.Call, position: int, kw_name: str) -> str | None:
    """Return the literal string at the given positional or kwarg slot.

    Returns ``None`` when the slot is missing or non-literal (e.g. a
    variable reference); a non-literal SQL string is a separate code-
    review issue and not in scope for this AST gate.
    """
    if len(node.args) > position:
        candidate = node.args[position]
        if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
            return candidate.value
    for kw in node.keywords:
        if (
            kw.arg == kw_name
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        ):
            return kw.value.value
    return None


def test_no_bare_op_calls() -> None:
    assert VERSIONS_DIR.exists(), f"expected alembic/versions/ at {VERSIONS_DIR}"

    offenders: list[str] = []
    for py in sorted(VERSIONS_DIR.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            # `op.<thing>(...)` — bare DDL via the alembic op surface.
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "op"
                and func.attr in BANNED_OP_CALLS
            ):
                offenders.append(
                    f"{py.relative_to(BACKEND_DIR)}:{node.lineno} " f"bare op.{func.attr}(...)"
                )

            # `execute_if(condition, sql)` — allowed, but if SQL begins
            # with ALTER TABLE it must pin both ALGORITHM= and LOCK=.
            if isinstance(func, ast.Name) and func.id == "execute_if":
                sql = _string_arg(node, position=1, kw_name="sql")
                if sql is not None:
                    upper = sql.strip().upper()
                    if upper.startswith("ALTER TABLE") and (
                        "ALGORITHM=" not in upper or "LOCK=" not in upper
                    ):
                        offenders.append(
                            f"{py.relative_to(BACKEND_DIR)}:{node.lineno} "
                            f"execute_if SQL missing ALGORITHM=/LOCK= "
                            f"clauses: {sql!r}"
                        )

    assert not offenders, (
        "Use migration_helpers in alembic/versions/. Offenders:\n  " + "\n  ".join(offenders)
    )
