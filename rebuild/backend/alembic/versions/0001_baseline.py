"""baseline: create the ``user`` table.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-04-29

The M0 baseline ships exactly one table — ``user`` — populated by the
trusted-header auth path in ``app.core.auth.upsert_user_from_headers``.
Subsequent milestones (M1 chat/folder, M2 share, M3 channel/file, M4
automation) chain onto this revision via ``down_revision``.

ON DELETE policy: N/A. This revision creates no foreign keys; later
milestones that reference ``user.id`` document their own ``ON DELETE``
choice in their revision docstrings.

Both ``upgrade()`` and ``downgrade()`` are written exclusively against
``app.db.migration_helpers`` and are therefore safely re-runnable. Bare
DDL calls against the Alembic ``op`` surface are rejected here by the
``test_no_bare_op_calls`` AST gate in ``backend/tests/test_migrations.py``.
"""

from __future__ import annotations

import sqlalchemy as sa
from app.db.migration_helpers import (
    create_table_if_not_exists,
    drop_table_if_exists,
)

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    create_table_if_not_exists(
        "user",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("email", name="uq_user_email"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
    )


def downgrade() -> None:
    drop_table_if_exists("user")
