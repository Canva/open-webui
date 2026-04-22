"""Add oauth_session table

Revision ID: 38d63c18f30f
Revises: 3af16a1c9fb6
Create Date: 2025-09-08 14:19:59.583921

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '38d63c18f30f'
down_revision: Union[str, None] = '3af16a1c9fb6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure 'id' column in 'user' table is unique and primary key (ForeignKey constraint)
    inspector = sa.inspect(op.get_bind())
    columns = inspector.get_columns('user')

    pk_columns = inspector.get_pk_constraint('user')['constrained_columns']
    id_column = next((col for col in columns if col['name'] == 'id'), None)

    if id_column and not id_column.get('unique', False):
        unique_constraints = inspector.get_unique_constraints('user')
        unique_columns = {tuple(u['column_names']) for u in unique_constraints}

        with op.batch_alter_table('user') as batch_op:
            # If primary key is wrong, drop it
            if pk_columns and pk_columns != ['id']:
                batch_op.drop_constraint(inspector.get_pk_constraint('user')['name'], type_='primary')

            # Add unique constraint if missing
            if ('id',) not in unique_columns:
                batch_op.create_unique_constraint('uq_user_id', ['id'])

            # Re-create correct primary key
            batch_op.create_primary_key('pk_user_id', ['id'])

    # Create oauth_session table
    op.create_table(
        'oauth_session',
        sa.Column('id', sa.Text(), primary_key=True, nullable=False, unique=True),
        sa.Column(
            'user_id',
            sa.Text(),
            sa.ForeignKey('user.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('provider', sa.Text(), nullable=False),
        sa.Column('token', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.BigInteger(), nullable=False),
        sa.Column('updated_at', sa.BigInteger(), nullable=False),
    )

    # Create indexes for better performance.
    #
    # ``user_id``, ``provider`` and ``token`` are declared as ``sa.Text`` for
    # cross-dialect portability, but MySQL refuses to index TEXT columns
    # without an explicit prefix length. ``mysql_length`` is silently ignored
    # by SQLite and PostgreSQL.
    PREFIX = 255
    op.create_index(
        'idx_oauth_session_user_id', 'oauth_session', ['user_id'],
        mysql_length={'user_id': PREFIX},
    )
    op.create_index('idx_oauth_session_expires_at', 'oauth_session', ['expires_at'])
    op.create_index(
        'idx_oauth_session_user_provider', 'oauth_session', ['user_id', 'provider'],
        mysql_length={'user_id': PREFIX, 'provider': PREFIX},
    )


def downgrade() -> None:
    # Dropping the table also drops every secondary index. Trying to drop
    # ``idx_oauth_session_user_id`` first fails on MySQL with error 1553 —
    # the index is needed by the FK on ``user_id``. ``DROP TABLE`` cleanly
    # removes both, so just drop the table.
    op.drop_table('oauth_session')
