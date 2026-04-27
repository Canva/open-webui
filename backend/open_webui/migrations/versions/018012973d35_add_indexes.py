"""Add indexes

Revision ID: 018012973d35
Revises: d31026856c01
Create Date: 2025-08-13 03:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = '018012973d35'
down_revision = 'd31026856c01'
branch_labels = None
depends_on = None


def upgrade():
    # Many of the columns being indexed here were originally declared as
    # TEXT/sa.Text. MySQL cannot index a TEXT column without an explicit key
    # prefix length, so we pass ``mysql_length`` for any potentially TEXT
    # column. SQLite and PostgreSQL ignore this kwarg.
    PREFIX = 255
    op.create_index(
        'folder_id_idx',
        'chat',
        ['folder_id'],
        mysql_length={'folder_id': PREFIX},
    )
    op.create_index(
        'user_id_pinned_idx',
        'chat',
        ['user_id', 'pinned'],
        mysql_length={'user_id': PREFIX},
    )
    op.create_index(
        'user_id_archived_idx',
        'chat',
        ['user_id', 'archived'],
        mysql_length={'user_id': PREFIX},
    )
    op.create_index(
        'updated_at_user_id_idx',
        'chat',
        ['updated_at', 'user_id'],
        mysql_length={'user_id': PREFIX},
    )
    op.create_index(
        'folder_id_user_id_idx',
        'chat',
        ['folder_id', 'user_id'],
        mysql_length={'folder_id': PREFIX, 'user_id': PREFIX},
    )

    op.create_index(
        'user_id_idx',
        'tag',
        ['user_id'],
        mysql_length={'user_id': PREFIX},
    )

    op.create_index('is_global_idx', 'function', ['is_global'])


def downgrade():
    # Chat table indexes
    op.drop_index('folder_id_idx', table_name='chat')
    op.drop_index('user_id_pinned_idx', table_name='chat')
    op.drop_index('user_id_archived_idx', table_name='chat')
    op.drop_index('updated_at_user_id_idx', table_name='chat')
    op.drop_index('folder_id_user_id_idx', table_name='chat')

    # Tag table index
    op.drop_index('user_id_idx', table_name='tag')

    # Function table index

    op.drop_index('is_global_idx', table_name='function')
