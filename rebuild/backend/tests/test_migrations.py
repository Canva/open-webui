"""Migration contract tests — gated by the m0 acceptance criteria.

Four contract tests, mandatory for every revision the repo will ever
hold (m0 plan § Alembic helper test gate):

1. ``test_upgrade_head_is_idempotent`` — ``alembic upgrade head`` from a
   fresh DB succeeds; rerun is a no-op (table count unchanged).
2. ``test_downgrade_base_is_idempotent`` — upgrade then double-downgrade;
   the second downgrade is a no-op.
3. ``test_partial_upgrade_recovers`` — half-applied M0 schema (``user``
   table created with a subset of columns, no alembic_version row) +
   ``alembic upgrade head`` completes without error. NB: the M0 baseline
   only ships ``op.create_table_if_not_exists`` for the single ``user``
   table; the helper short-circuits when ``has_table('user')`` is true,
   so the table's column shape is preserved (it does NOT add the missing
   columns). See "Deviation from dispatch" comment block above
   ``test_partial_upgrade_recovers``.

3b. ``test_partial_upgrade_recovers_m2`` — half-applied M2 schema
   (``user`` + ``folder`` exist, ``alembic_version`` at ``0001_baseline``,
   ``chat`` was never created) + ``alembic upgrade head`` produces ``chat``,
   the ``current_message_id`` ``STORED GENERATED`` column, all five named
   composite indexes, both cross-table FKs, and the M3-reserved
   ``share_id`` column without operator intervention. Asserts the M2
   acceptance-criteria recovery contract from
   ``rebuild/docs/plans/m2-conversations.md``.
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


async def _async_list_columns(database_url: str, table: str) -> list[str]:
    """Return a sorted list of column names on ``table`` (empty if the
    table is absent). Used by the M2 partial-recovery test to confirm
    the chat table picked up every base column plus the
    ``share_id`` reservation and the generated ``current_message_id``.
    """
    engine = create_async_engine(database_url, future=True)
    try:
        async with engine.connect() as conn:

            def _columns(sync_conn: Any) -> list[str]:
                inspector = sa.inspect(sync_conn)
                if not inspector.has_table(table):
                    return []
                return sorted(c["name"] for c in inspector.get_columns(table))

            return await conn.run_sync(_columns)
    finally:
        await engine.dispose()


async def _async_list_index_names(database_url: str, table: str) -> set[str]:
    """Return the set of index names on ``table``. Used by the M2
    partial-recovery test to assert all five chat composite indexes are
    present after a half-applied migration recovers.
    """
    engine = create_async_engine(database_url, future=True)
    try:
        async with engine.connect() as conn:

            def _indexes(sync_conn: Any) -> set[str]:
                inspector = sa.inspect(sync_conn)
                if not inspector.has_table(table):
                    return set()
                return {i["name"] for i in inspector.get_indexes(table) if i["name"]}

            return await conn.run_sync(_indexes)
    finally:
        await engine.dispose()


async def _async_list_fk_names(database_url: str, table: str) -> set[str]:
    """Return the set of foreign-key constraint names on ``table``.
    Used by the M2 partial-recovery test to assert both cross-table FKs
    on chat survive the recovery.
    """
    engine = create_async_engine(database_url, future=True)
    try:
        async with engine.connect() as conn:

            def _fks(sync_conn: Any) -> set[str]:
                inspector = sa.inspect(sync_conn)
                if not inspector.has_table(table):
                    return set()
                return {fk["name"] for fk in inspector.get_foreign_keys(table) if fk["name"]}

            return await conn.run_sync(_fks)
    finally:
        await engine.dispose()


async def _async_column_extra(database_url: str, table: str, column: str) -> str | None:
    """Return the MySQL ``INFORMATION_SCHEMA.COLUMNS.EXTRA`` string for a
    column (or ``None`` if the column is absent). For a STORED generated
    column the value is ``'STORED GENERATED'``; the M2 partial-recovery
    test uses this to confirm ``current_message_id`` was created with
    the correct ``GENERATED ALWAYS AS (...) STORED`` shape rather than
    as a plain nullable ``VARCHAR(36)``.
    """
    engine = create_async_engine(database_url, future=True)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    sa.text(
                        "SELECT EXTRA FROM INFORMATION_SCHEMA.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() "
                        "AND TABLE_NAME = :table "
                        "AND COLUMN_NAME = :column"
                    ),
                    {"table": table, "column": column},
                )
            ).first()
            if row is None:
                return None
            return str(row[0])
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
    # M0 baseline + M2 conversation surface — both must land via the
    # head walk. Asserting on the M2 tables here (rather than only in a
    # separate M2 test) means any future revision that quietly breaks
    # M2's idempotent re-application is caught by this single contract
    # test, in line with the dispatch's "the existing head walk already
    # covers the new revision" requirement.
    assert "user" in after_first
    assert "chat" in after_first
    assert "folder" in after_first
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
    # the version-tracking table around as an empty marker). Every
    # business table from every revision must be gone — the M2 tables
    # are checked here alongside the M0 baseline so the head-walk
    # asymmetry that would slip through (head builds chat, base forgets
    # to drop it) is caught by the contract test rather than by the
    # next milestone's CI run.
    assert "user" not in after_first_down
    assert "chat" not in after_first_down
    assert "folder" not in after_first_down

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
#   `add_column_if_not_exists` helper's job, which M2+ revisions use.
#
#   So for M0 the verifiable contract is: "upgrade head over a partial
#   user table completes without error and the table contents are
#   preserved (no destructive recovery)". For M2+ this test will grow a
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
# Contract test 3b: partial-recovery from a half-applied M2 schema.
# ---------------------------------------------------------------------------
#
# Scenario the M2 plan cares about ("Acceptance criteria" §2 in
# `rebuild/docs/plans/m2-conversations.md`): the M0 baseline ran
# successfully (so `user` and `alembic_version='0001_baseline'` exist),
# the M2 revision started but crashed after creating `folder` and
# before creating `chat`. MySQL DDL implicitly commits, so this is the
# realistic mid-migration crash mode. A retry of `alembic upgrade head`
# must:
#
#   * Notice that `folder` already exists and skip the `create_table`
#     for it (without raising on the inline self-FK / index already
#     being present).
#   * Create `chat` with both cross-table FKs (`fk_chat_user_id_user`,
#     `fk_chat_folder_id_folder`).
#   * Add the `current_message_id` `STORED GENERATED` column out of
#     band via the inline `ALTER TABLE ... ALGORITHM=COPY, LOCK=SHARED`
#     statement.
#   * Add all five named composite indexes on `chat`, including the
#     `ix_chat_current_message` index that targets the generated column.
#   * Leave the `share_id VARCHAR(43) NULL` reservation in place for M3.
#
# We add this as a sibling test rather than extending
# `test_partial_upgrade_recovers` so the M0 contract (the helper is
# non-destructive on a partial table) and the M2 contract (the helper
# fills in everything the missing revision was supposed to add) are
# each testable in isolation.


def test_partial_upgrade_recovers_m2(fresh_db: str) -> None:
    cfg = _alembic_config()

    # Bring M0 to a clean state — `user` table + `alembic_version` row
    # at `0001_baseline`. We use the alembic command rather than raw
    # DDL so the version-tracking row is set correctly; the next
    # `upgrade head` then only needs to advance from M0 to M2.
    command.upgrade(cfg, "0001_baseline")

    # Pre-create `folder` matching exactly what the M2 revision would
    # have created — including the inline self-FK and the
    # `ix_folder_user_parent` composite index — to simulate the M2
    # revision crashing AFTER `folder` landed and BEFORE `chat` did.
    # Column types and FK shape match
    # `alembic/versions/0002_m2_chat_folder.py::upgrade()` step 1 byte-
    # for-byte; if those drift, `chat`'s `fk_chat_folder_id_folder` will
    # fail at FK-creation time (InnoDB checks referenced/referencing
    # column types) and surface here instead of in production.
    _run(
        _async_exec(
            fresh_db,
            "CREATE TABLE `folder` ("
            "  id VARCHAR(36) NOT NULL,"
            "  user_id VARCHAR(36) NOT NULL,"
            "  parent_id VARCHAR(36) NULL,"
            "  name TEXT NOT NULL,"
            "  expanded BOOLEAN NOT NULL DEFAULT 0,"
            "  created_at BIGINT NOT NULL,"
            "  updated_at BIGINT NOT NULL,"
            "  CONSTRAINT pk_folder PRIMARY KEY (id),"
            "  CONSTRAINT fk_folder_user_id_user FOREIGN KEY (user_id) "
            "    REFERENCES `user`(id) ON DELETE CASCADE,"
            "  CONSTRAINT fk_folder_parent_id_folder FOREIGN KEY (parent_id) "
            "    REFERENCES `folder`(id) ON DELETE CASCADE,"
            "  KEY ix_folder_user_parent (user_id, parent_id)"
            ") ENGINE=InnoDB CHARSET=utf8mb4 "
            "COLLATE=utf8mb4_0900_ai_ci",
        )
    )

    # Recovery: a single `alembic upgrade head` must complete the half-
    # applied revision without operator intervention.
    command.upgrade(cfg, "head")

    # 1. `chat` exists alongside the pre-existing `folder`.
    tables = _run(_async_list_tables(fresh_db))
    assert "chat" in tables
    assert "folder" in tables

    # 2. Every base column landed, INCLUDING the M3-reserved `share_id`
    #    placeholder (always NULL in M2; M3 attaches its FK + unique
    #    index via the `0003_m3_sharing` revision).
    chat_columns = set(_run(_async_list_columns(fresh_db, "chat")))
    expected = {
        "id",
        "user_id",
        "title",
        "history",
        "folder_id",
        "archived",
        "pinned",
        "share_id",
        "created_at",
        "updated_at",
        "current_message_id",
    }
    missing = expected - chat_columns
    assert not missing, f"chat is missing columns: {sorted(missing)}"

    # 3. `current_message_id` is a STORED generated column, not a plain
    #    `VARCHAR(36) NULL`. MySQL exposes the generation kind through
    #    `INFORMATION_SCHEMA.COLUMNS.EXTRA`; for a STORED generated
    #    column the value is the literal string `'STORED GENERATED'`.
    extra = _run(_async_column_extra(fresh_db, "chat", "current_message_id"))
    assert (
        extra == "STORED GENERATED"
    ), f"expected current_message_id to be STORED GENERATED, got EXTRA={extra!r}"

    # 4. All five composite indexes on `chat` are present, including
    #    `ix_chat_current_message` which targets the generated column.
    chat_indexes = _run(_async_list_index_names(fresh_db, "chat"))
    expected_indexes = {
        "ix_chat_user_updated",
        "ix_chat_user_pinned_updated",
        "ix_chat_user_archived_updated",
        "ix_chat_user_folder_updated",
        "ix_chat_current_message",
    }
    missing_indexes = expected_indexes - chat_indexes
    assert not missing_indexes, f"chat is missing indexes: {sorted(missing_indexes)}"

    # 5. Both cross-table FKs landed with their named constraints.
    chat_fks = _run(_async_list_fk_names(fresh_db, "chat"))
    assert "fk_chat_user_id_user" in chat_fks
    assert "fk_chat_folder_id_folder" in chat_fks

    # 6. The pre-existing folder is untouched and still carries the
    #    self-FK + composite index it was created with.
    folder_fks = _run(_async_list_fk_names(fresh_db, "folder"))
    assert "fk_folder_user_id_user" in folder_fks
    assert "fk_folder_parent_id_folder" in folder_fks
    folder_indexes = _run(_async_list_index_names(fresh_db, "folder"))
    assert "ix_folder_user_parent" in folder_indexes

    # 7. Re-running `alembic upgrade head` immediately after recovery is
    #    a no-op. Belt-and-braces idempotency check on top of the
    #    head-walk contract test above.
    command.upgrade(cfg, "head")
    assert _run(_async_list_tables(fresh_db)) == tables


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
