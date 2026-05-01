"""m3: create the ``shared_chat`` table and tie ``chat.share_id`` to it.

Revision ID: 0003_m3_sharing
Revises: 0002_m2_chat_folder
Create Date: 2026-05-01

The M3 sharing surface (see ``rebuild/docs/plans/m3-sharing.md``
§ Data model and § Alembic revision). One new table (``shared_chat``),
one cross-table foreign key on the M2-reserved ``chat.share_id``
column, and one unique index enforcing "at most one active share per
chat" at the DB layer.

**M2 already created ``chat.share_id`` at ``VARCHAR(43) NULL``** as
part of ``0002_m2_chat_folder``'s ``create_table_if_not_exists("chat",
...)`` step. This revision adds **only** the foreign key and the
unique index against that pre-existing column. No
``op.add_column("chat", "share_id", ...)`` lands here, and no
``add_column_if_not_exists("chat", sa.Column("share_id", ...))`` lands
here either — ever. The M3 plan calls this out explicitly
(``m3-sharing.md`` § Alembic revision), and the corresponding
M2 revision documents the reservation in its docstring; the two are
deliberately split so M3's downgrade does not touch ``chat.share_id``
(M2 owns the column and any future cleanup belongs to M2's
downgrade).

ON DELETE policy (locked):

* ``shared_chat.chat_id → chat.id`` — ``CASCADE``. Deleting a chat
  destroys its snapshot row; without this the snapshot would outlive
  the underlying chat it was derived from.
* ``shared_chat.user_id → user.id`` — ``CASCADE``. Deleting a user
  destroys their share rows alongside their chats (``chat.user_id``
  cascades from M2).
* ``chat.share_id → shared_chat.id`` — ``SET NULL``. Deleting a
  ``shared_chat`` row clears the back-pointer on the original chat;
  it never leaves a dangling pointer.

The unique index ``ix_chat_share_id`` enforces "at most one active
share per chat" at the storage layer in addition to the application
logic (the share router rotates the token by deleting the previous
``shared_chat`` row before inserting a new one). The M2 ``Chat``
model declares ``share_id`` without a column-level UNIQUE because
uniqueness is owned here, not there.

Deliberate divergence from the dispatch's "Operations, in order" list
(``m3-sharing.md`` § Alembic revision step 2 then step 3):

  The dispatch lists the upgrade as (table → FK → unique index) and
  the downgrade as the strict reverse (drop unique index → drop FK →
  drop table). That ordering is internally inconsistent under MySQL
  8.0 InnoDB:

  * On upgrade with FK-first, MySQL has no existing index on
    ``chat.share_id`` and auto-creates one named after the constraint
    (``fk_chat_share_id``). The subsequent ``CREATE UNIQUE INDEX
    ix_chat_share_id`` adds a *second* index on the same column.
    End-state: two indexes on ``chat.share_id`` (``fk_chat_share_id``
    and ``ix_chat_share_id``), one of them redundant.
  * On the strict-reverse downgrade, dropping ``ix_chat_share_id``
    can fail with error 1553 ("Cannot drop index … needed in a
    foreign key constraint") whenever InnoDB has selected the unique
    index as the FK's backing index — the manual is explicit that
    ``DROP INDEX`` is only permitted if another index can satisfy
    the FK.

  Resolution: create the unique index *before* the FK on upgrade so
  the FK adopts the unique index as its backing index (no duplicate
  auto-index lands), and the strict-reverse downgrade then works
  without triggering 1553. End-state is identical to what the
  dispatch is reaching for; only the ordering shifts. M2 documents
  the same kind of "InnoDB FK-must-be-indexed forces a specific
  drop order" divergence in its own downgrade comment block.

Both ``upgrade()`` and ``downgrade()`` are written exclusively against
``app.db.migration_helpers`` and are therefore safely re-runnable. No
``execute_if`` / raw DDL is needed in this revision — the absence is
deliberate (no MySQL feature in M3 falls outside the helpers' surface,
unlike M2's ``GENERATED ALWAYS AS (...) STORED`` column). Bare DDL
calls against the Alembic ``op`` surface are rejected by the
``test_no_bare_op_calls`` AST gate.
"""

from __future__ import annotations

import sqlalchemy as sa
from app.db.migration_helpers import (
    create_foreign_key_if_not_exists,
    create_index_if_not_exists,
    create_table_if_not_exists,
    drop_constraint_if_exists,
    drop_index_if_exists,
    drop_table_if_exists,
)
from sqlalchemy.dialects import mysql

revision: str = "0003_m3_sharing"
down_revision: str | None = "0002_m2_chat_folder"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 1. ``shared_chat`` first so the M2 ``chat.share_id → shared_chat.id``
    #    FK below has a referent. Both cross-table FKs and both
    #    secondary indexes are declared inline so they land atomically
    #    with the table on a fresh run; on a re-run the helper sees
    #    ``has_table("shared_chat")`` is true and short-circuits the
    #    whole step (table + FKs + indexes), which is exactly the
    #    behaviour the M3 partial-recovery contract test
    #    (``test_partial_upgrade_recovers_m3``) exercises.
    #
    #    Width 43 on ``id`` matches ``secrets.token_urlsafe(32)``'s
    #    output length and the M2-owned ``chat.share_id VARCHAR(43)``
    #    column byte-for-byte; if those drift, MySQL InnoDB will reject
    #    the cross-table FK below with a type-mismatch error. Width 36
    #    on ``chat_id`` / ``user_id`` matches the project-wide UUIDv7
    #    PK shape (``rebuild.md`` §9). ``mysql.JSON()`` is the dialect-
    #    native ``JSON`` column type (same as ``chat.history`` in M2).
    create_table_if_not_exists(
        "shared_chat",
        sa.Column("id", sa.String(43), nullable=False),
        sa.Column("chat_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("history", mysql.JSON(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_shared_chat"),
        sa.ForeignKeyConstraint(
            ["chat_id"],
            ["chat.id"],
            name="fk_shared_chat_chat_id_chat",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name="fk_shared_chat_user_id_user",
            ondelete="CASCADE",
        ),
        sa.Index("ix_shared_chat_chat_id", "chat_id"),
        sa.Index("ix_shared_chat_user_id", "user_id"),
    )

    # 2. The unique index enforcing "at most one active share per
    #    chat" at the DB layer. The M2 ``chat`` table does not declare
    #    a column-level UNIQUE on ``share_id`` (the column is reserved
    #    nullable in M2; uniqueness is M3's deliverable). Created
    #    BEFORE the FK below so the FK adopts this index as its
    #    backing index — see the divergence note in the module
    #    docstring for why this differs from the dispatch's stated
    #    "FK then index" order. MySQL 8.0 has no native ``CREATE INDEX
    #    IF NOT EXISTS``; the helper inspects
    #    ``INFORMATION_SCHEMA.STATISTICS`` first.
    create_index_if_not_exists(
        "ix_chat_share_id",
        "chat",
        ["share_id"],
        unique=True,
    )

    # 3. The cross-table FK on the M2-owned ``chat.share_id`` column.
    #    M2 reserved the column at ``VARCHAR(43) NULL``; M3 backfills
    #    the FK + uniqueness. ``ON DELETE SET NULL`` keeps the chat
    #    alive when the share row is deleted (revoke / token rotation)
    #    and clears the back-pointer atomically. With
    #    ``ix_chat_share_id`` already in place from step 2, MySQL
    #    adopts it as the FK's backing index and does NOT auto-create
    #    a duplicate index named after the constraint.
    #
    #    MySQL 8.0 has no native ``ADD CONSTRAINT IF NOT EXISTS``; the
    #    helper inspects ``INFORMATION_SCHEMA`` (via SQLAlchemy
    #    ``inspect()``) before emitting the underlying ``op.create_
    #    foreign_key`` call.
    create_foreign_key_if_not_exists(
        "fk_chat_share_id",
        "chat",
        "shared_chat",
        ["share_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Strict reverse of ``upgrade()``: drop the FK first (so the
    # unique index it backs onto can be dropped without InnoDB
    # rejecting it with error 1553 "needed in a foreign key
    # constraint"), then the unique index, then the table. Every step
    # is idempotent so a half-applied downgrade re-runs cleanly.
    #
    # We deliberately do NOT drop ``chat.share_id`` here — that
    # column is M2's property (created by ``0002_m2_chat_folder``)
    # and any cleanup belongs to M2's downgrade, not M3's. Dropping
    # it here would silently break the M2 contract that
    # ``alembic downgrade -1`` from M3 leaves the M2 schema intact.
    drop_constraint_if_exists("fk_chat_share_id", "chat", type_="foreignkey")
    drop_index_if_exists("ix_chat_share_id", "chat")
    drop_table_if_exists("shared_chat")
