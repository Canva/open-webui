"""Idempotent wrappers around the ``alembic.op`` DDL surface.

Every Alembic revision in the rebuild — from the M0 baseline through the M4
automations — calls ONLY the helpers in this module. Bare ``op.create_*``,
``op.drop_*``, ``op.add_column``, etc. are forbidden in
``backend/alembic/versions/`` and gated by the ``test_no_bare_op_calls``
AST test.

The helpers split into two camps:

1. Wrappers that map onto a MySQL-native ``IF NOT EXISTS`` /
   ``IF EXISTS`` clause (CREATE/DROP TABLE, DROP INDEX on MySQL 8.0.29+).
2. Wrappers that introspect the live schema with SQLAlchemy ``inspect()``
   and skip the underlying ``op.*`` call when the object already exists or
   has already been removed. MySQL 8.0 does NOT support ``IF NOT EXISTS``
   on ``CREATE INDEX``, ``ALTER TABLE ADD COLUMN``, ``ADD CONSTRAINT``, or
   ``ADD FOREIGN KEY``, so the inspect-then-emit pattern is mandatory for
   those.

Both ``upgrade()`` and ``downgrade()`` of every revision must be safely
re-runnable: a retry on a half-applied migration must complete the rest
and no-op the parts that already landed.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.functions import Function


def _inspector() -> sa.engine.reflection.Inspector:
    return sa.inspect(op.get_bind())


def has_table(name: str) -> bool:
    return _inspector().has_table(name)


def has_column(table: str, column: str) -> bool:
    if not has_table(table):
        return False
    return any(c["name"] == column for c in _inspector().get_columns(table))


def has_index(table: str, name: str) -> bool:
    if not has_table(table):
        return False
    return any(i["name"] == name for i in _inspector().get_indexes(table))


def has_unique_constraint(table: str, name: str) -> bool:
    if not has_table(table):
        return False
    return any(u["name"] == name for u in _inspector().get_unique_constraints(table))


def has_foreign_key(table: str, name: str) -> bool:
    if not has_table(table):
        return False
    return any(fk["name"] == name for fk in _inspector().get_foreign_keys(table))


def has_check_constraint(table: str, name: str) -> bool:
    if not has_table(table):
        return False
    return any(cc["name"] == name for cc in _inspector().get_check_constraints(table))


def create_table_if_not_exists(name: str, *columns: Any, **kw: Any) -> None:
    """Idempotent ``op.create_table``.

    The Python-level ``has_table`` guard provides idempotency. SQLAlchemy's
    MySQL dialect does NOT have a ``mysql_create_if_not_exists`` table-arg
    (despite some third-party docs suggesting otherwise); attempting to set
    one renders bogus DDL and raises a ``TypeError`` inside the dialect's
    table-options compiler. The serial M5 migration Job
    (``backoffLimit: 0``) means concurrent racing migrators are functionally
    impossible, so the Python guard alone is sufficient.
    """
    if has_table(name):
        return
    kw.setdefault("mysql_engine", "InnoDB")
    kw.setdefault("mysql_charset", "utf8mb4")
    kw.setdefault("mysql_collate", "utf8mb4_0900_ai_ci")
    op.create_table(name, *columns, **kw)


def drop_table_if_exists(name: str) -> None:
    if has_table(name):
        op.drop_table(name)


def create_index_if_not_exists(
    name: str,
    table: str,
    columns: Sequence[str | sa.Column[Any]],
    *,
    unique: bool = False,
    **kw: Any,
) -> None:
    if has_index(table, name):
        return
    # Alembic types `columns` narrowly as Sequence[str | TextClause | Function],
    # but its runtime accepts sa.Column too — cast keeps the helper's input
    # surface ergonomic for callers that pass Column objects directly.
    op.create_index(
        name,
        table,
        cast(Sequence[str | TextClause | Function[Any]], columns),
        unique=unique,
        **kw,
    )


def drop_index_if_exists(name: str, table: str) -> None:
    if has_index(table, name):
        op.drop_index(name, table_name=table)


def add_column_if_not_exists(
    table: str,
    column: sa.Column[Any],
    *,
    algorithm: str = "INSTANT",
    lock: str = "DEFAULT",
) -> None:
    """Idempotent ``op.add_column`` that pins the MySQL DDL algorithm.

    Defaults to ``ALGORITHM=INSTANT, LOCK=DEFAULT`` (MySQL 8.0.12+) so the
    operation is metadata-only and runtime is independent of table size. If
    the column type/position is incompatible with INSTANT, MySQL fails fast
    with 1845 (instead of silently downgrading to ``ALGORITHM=COPY`` and
    locking the table for hours). Callers that genuinely need INPLACE/COPY
    pass the explicit override and justify it in a comment in the revision
    file.
    """
    if has_column(table, column.name):
        return
    if algorithm.upper() == "INSTANT" and lock.upper() == "DEFAULT":
        # SQLAlchemy doesn't render ALGORITHM/LOCK on ADD COLUMN, so emit
        # raw DDL with the same column definition the dialect would
        # produce.
        ddl = sa.schema.CreateColumn(column).compile(dialect=op.get_bind().dialect)
        op.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}, ALGORITHM=INSTANT, LOCK=DEFAULT")
    else:
        op.add_column(table, column)


def drop_column_if_exists(table: str, column: str) -> None:
    if has_column(table, column):
        # DROP COLUMN cannot use ALGORITHM=INSTANT (MySQL 8.0); INPLACE is
        # the best we can do. Tables that would block on this are
        # explicitly called out in the revision's comment block.
        op.execute(f"ALTER TABLE {table} DROP COLUMN {column}, ALGORITHM=INPLACE, LOCK=NONE")


def create_foreign_key_if_not_exists(
    name: str,
    source_table: str,
    referent_table: str,
    local_cols: list[str],
    remote_cols: list[str],
    **kw: Any,
) -> None:
    if has_foreign_key(source_table, name):
        return
    op.create_foreign_key(name, source_table, referent_table, local_cols, remote_cols, **kw)


def drop_constraint_if_exists(name: str, table: str, *, type_: str) -> None:
    """Drop a constraint by name+type if present.

    ``type_`` ∈ ``{"foreignkey", "unique", "check", "primary"}``.
    """
    found = {
        "foreignkey": has_foreign_key,
        "unique": has_unique_constraint,
        "check": has_check_constraint,
    }.get(type_, lambda _t, _n: True)(table, name)
    if found:
        op.drop_constraint(name, table, type_=type_)


def create_check_constraint_if_not_exists(
    name: str,
    table: str,
    condition: str | sa.sql.elements.ColumnElement[bool],
) -> None:
    if not has_check_constraint(table, name):
        op.create_check_constraint(name, table, condition)


def execute_if(condition: bool, sql: str) -> None:
    """Escape hatch for raw DDL (e.g. MySQL generated columns) guarded by
    an application-level predicate the caller has already evaluated against
    ``_inspector()``.
    """
    if condition:
        op.execute(sql)
