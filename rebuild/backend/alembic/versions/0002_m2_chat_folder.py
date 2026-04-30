"""m2: create the ``folder`` and ``chat`` tables.

Revision ID: 0002_m2_chat_folder
Revises: 0001_baseline
Create Date: 2026-04-30

The M2 conversation surface (see ``rebuild/docs/plans/m2-conversations.md``
§ Data model and § Alembic revision). Two tables, one MySQL ``GENERATED
ALWAYS AS (...) STORED`` column, five composite indexes, one
self-referential FK and two cross-table FKs.

ON DELETE policy (locked):

* ``folder.user_id → user.id`` — ``CASCADE``. Deleting a user destroys
  their folder tree (the matching cascade on ``chat.user_id`` already
  destroys the chats themselves).
* ``folder.parent_id → folder.id`` (self-FK) — ``CASCADE``. Deleting a
  folder cascades to its descendant folders. Chats inside the deleted
  folders fall back to "no folder" via the FK below; the folder cascade
  does NOT reach across to chats. This is the deliberate UX from the
  M2 plan: deleting a folder should not also delete its conversations.
* ``chat.user_id → user.id`` — ``CASCADE``. Deleting a user destroys
  their chats. There is no anonymous-chat concept in the rebuild.
* ``chat.folder_id → folder.id`` — ``SET NULL``. Deleting a folder
  detaches the chats inside (their ``folder_id`` becomes ``NULL``).

Reserved for M3 (see ``rebuild/docs/plans/m3-sharing.md``):

* ``chat.share_id`` is declared here as ``VARCHAR(43) NULL`` so M3
  doesn't need an ``ALTER ADD COLUMN``. M2 never reads or writes it.
  M3's revision (``0003_m3_sharing``) adds the FK and the unique
  ``ix_chat_share_id`` index via the same M0 helper module.

Both ``upgrade()`` and ``downgrade()`` are written exclusively against
``app.db.migration_helpers`` and are therefore safely re-runnable. Bare
DDL calls against the Alembic ``op`` surface are rejected by the
``test_no_bare_op_calls`` AST gate. The single unavoidable raw-DDL
call — adding the ``GENERATED ALWAYS AS (...) STORED`` column — is
routed through ``execute_if(not has_column(...), <literal SQL>)`` and
pins both ``ALGORITHM=`` and ``LOCK=`` clauses inline so the AST gate
can verify them at the call site (the gate only inspects literal
string arguments, so the SQL is intentionally not factored out into a
module-level constant).
"""

from __future__ import annotations

import sqlalchemy as sa
from app.db.migration_helpers import (
    create_index_if_not_exists,
    create_table_if_not_exists,
    drop_index_if_exists,
    drop_table_if_exists,
    execute_if,
    has_column,
)
from sqlalchemy.dialects import mysql

revision: str = "0002_m2_chat_folder"
down_revision: str | None = "0001_baseline"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # 1. ``folder`` first so ``chat.folder_id`` can reference it.
    #    Self-FK on ``parent_id`` is declared inline so it lands
    #    atomically with the table itself; on a re-run, the helper sees
    #    the table already exists and skips the call entirely.
    create_table_if_not_exists(
        "folder",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("parent_id", sa.String(36), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("expanded", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_folder"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name="fk_folder_user_id_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["folder.id"],
            name="fk_folder_parent_id_folder",
            ondelete="CASCADE",
        ),
        sa.Index("ix_folder_user_parent", "user_id", "parent_id"),
    )

    # 2. ``chat`` next, every base column EXCEPT ``current_message_id``
    #    (added out of band as a STORED generated column in step 3).
    #    Both cross-table FKs declared inline so they land with the
    #    table; the M3-reserved ``share_id`` column is declared here so
    #    M3 doesn't need an ``ALTER ADD COLUMN`` later. ``share_id``
    #    carries no FK / unique index in M2 — those are M3's deliverable.
    create_table_if_not_exists(
        "chat",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        # `title` is `TEXT` so MySQL 8.0 forbids a literal DEFAULT on it
        # (error 1101). The "New Chat" fallback lives on the ORM model
        # as a Python-side `default=`, applied at INSERT time by
        # SQLAlchemy — see `app/models/chat.py`. The chat router and
        # streaming pipeline both rely on the Python default; nothing
        # in M2 INSERTs `chat` rows via raw SQL.
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "history",
            mysql.JSON(),
            nullable=False,
            # JSON columns DO support DEFAULT in MySQL 8.0.13+ when the
            # value is an expression wrapped in parentheses. Without
            # this, raw INSERTs that omit `history` would fail; the
            # ORM also writes a fully-validated `History` payload, so
            # this is a defence-in-depth default rather than a load-
            # bearing one.
            server_default=sa.text("(JSON_OBJECT('messages', JSON_OBJECT(), 'currentId', NULL))"),
        ),
        sa.Column("folder_id", sa.String(36), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        # Reserved for M3; declared here to avoid a follow-up ALTER. Width
        # matches ``shared_chat.id`` in M3. Uniqueness + FK are owned by
        # the M3 revision (``0003_m3_sharing``), not by M2.
        sa.Column("share_id", sa.String(43), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_chat"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name="fk_chat_user_id_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["folder_id"],
            ["folder.id"],
            name="fk_chat_folder_id_folder",
            ondelete="SET NULL",
        ),
    )

    # 3. Add the MySQL ``GENERATED ALWAYS AS (...) STORED`` column out of
    #    band. SQLAlchemy 2 has no first-class generated-column support
    #    and MySQL 8.0 has no ``ADD COLUMN IF NOT EXISTS``; routing
    #    through ``execute_if(not has_column(...), <literal SQL>)`` keeps
    #    the migration re-runnable without a stored procedure.
    #
    #    ``ALGORITHM=COPY, LOCK=SHARED``: adding a STORED generated
    #    column needs a table rebuild (the engine has to materialise the
    #    projection for every existing row), which forces ``COPY``.
    #    ``LOCK=SHARED`` keeps reads online during the rebuild and
    #    blocks writes — the right choice for this column on a hot
    #    table. ``add_column_if_not_exists`` is NOT used here because
    #    its INSTANT default is incompatible with STORED generated-column
    #    DDL (MySQL 8.0 fails fast with error 1845). The literal SQL is
    #    inline so the ``test_no_bare_op_calls`` AST gate can verify
    #    both clauses are present at the call site.
    execute_if(
        not has_column("chat", "current_message_id"),
        "ALTER TABLE chat "
        "ADD COLUMN current_message_id VARCHAR(36) "
        "GENERATED ALWAYS AS (JSON_UNQUOTE(JSON_EXTRACT(history, '$.currentId'))) STORED, "
        "ALGORITHM=COPY, LOCK=SHARED",
    )

    # 4. The five composite indexes on ``chat``. Created separately from
    #    ``create_table`` because ``ix_chat_current_message`` references
    #    the generated column added in step 3. MySQL 8.0 has no native
    #    ``CREATE INDEX IF NOT EXISTS``; the helper inspects
    #    ``INFORMATION_SCHEMA.STATISTICS`` first.
    create_index_if_not_exists("ix_chat_user_updated", "chat", ["user_id", "updated_at"])
    create_index_if_not_exists(
        "ix_chat_user_pinned_updated", "chat", ["user_id", "pinned", "updated_at"]
    )
    create_index_if_not_exists(
        "ix_chat_user_archived_updated",
        "chat",
        ["user_id", "archived", "updated_at"],
    )
    create_index_if_not_exists(
        "ix_chat_user_folder_updated",
        "chat",
        ["user_id", "folder_id", "updated_at"],
    )
    create_index_if_not_exists("ix_chat_current_message", "chat", ["current_message_id"])


def downgrade() -> None:
    # Deliberate divergence from the dispatch's "drop all five chat
    # indexes individually before the table" instruction:
    #
    # InnoDB requires every foreign-key column to be backed by an index;
    # if the FK's only candidate index is dropped, MySQL rejects the
    # DROP INDEX with error 1553 ("needed in a foreign key
    # constraint"). The four ``user_id``-leading composite indexes
    # (``ix_chat_user_updated``, ``ix_chat_user_pinned_updated``,
    # ``ix_chat_user_archived_updated``, ``ix_chat_user_folder_updated``)
    # collectively cover ``fk_chat_user_id_user``; InnoDB transparently
    # falls back to the next surviving one as we drop them, but the
    # last surviving one cannot be dropped without first dropping the
    # FK. The dispatch's note that "inline FKs created in step (b) drop
    # automatically with the table" is the resolution: we let
    # ``drop_table_if_exists("chat")`` cascade to every remaining index
    # and FK in one atomic step, and only the index that points at the
    # generated column needs an explicit drop (so the subsequent
    # ``DROP COLUMN`` succeeds — MySQL also rejects DROP COLUMN of a
    # column that is the sole referenced column of an index).
    #
    # The result is symmetric with ``upgrade()``: the table-level
    # artefacts (table, FKs, indexes that aren't on a generated column)
    # land/leave together, and the out-of-band generated column +
    # its index land/leave together. Every step is idempotent so a
    # half-applied downgrade re-runs cleanly.
    drop_index_if_exists("ix_chat_current_message", "chat")

    # ``DROP COLUMN`` of a STORED generated column is also a metadata-
    # plus-rebuild operation in MySQL 8.0; ``ALGORITHM=COPY, LOCK=SHARED``
    # matches the add side. The helper ``drop_column_if_exists`` is not
    # used because it hides ALGORITHM/LOCK behind INPLACE/NONE defaults
    # and the AST gate requires both clauses to surface at the call
    # site for ``ALTER TABLE`` SQL.
    execute_if(
        has_column("chat", "current_message_id"),
        "ALTER TABLE chat DROP COLUMN current_message_id, ALGORITHM=COPY, LOCK=SHARED",
    )

    drop_table_if_exists("chat")
    drop_table_if_exists("folder")
