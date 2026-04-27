"""Update user table

Revision ID: b10670c03dd5
Revises: 2f1211949ecc
Create Date: 2025-11-28 04:55:31.737538

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


import open_webui.internal.db
import json
import time

# revision identifiers, used by Alembic.
revision: str = 'b10670c03dd5'
down_revision: Union[str, None] = '2f1211949ecc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {column['name'] for column in inspector.get_columns(table_name)}


def _has_column(table_name: str, column_name: str) -> bool:
    return column_name in _get_columns(table_name)


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def _drop_sqlite_indexes_for_column(table_name, column_name, conn):
    """
    SQLite requires manual removal of any indexes referencing a column
    before ALTER TABLE ... DROP COLUMN can succeed.
    """
    indexes = conn.execute(sa.text(f"PRAGMA index_list('{table_name}')")).fetchall()

    for idx in indexes:
        index_name = idx[1]  # index name
        # SQLite reports internal backing indexes for UNIQUE / PRIMARY KEY
        # constraints here as well (``sqlite_autoindex_*``). Those cannot be
        # dropped explicitly; ``batch_alter_table`` will rebuild the table and
        # remove the constraint-backed index as part of the column drop.
        index_origin = idx[3] if len(idx) > 3 else None
        if index_name.startswith('sqlite_autoindex_') or index_origin in {'u', 'pk'}:
            continue
        # Get indexed columns
        idx_info = conn.execute(sa.text(f"PRAGMA index_info('{index_name}')")).fetchall()

        indexed_cols = [row[2] for row in idx_info]  # col names
        if column_name in indexed_cols:
            conn.execute(sa.text(f'DROP INDEX IF EXISTS {index_name}'))


def _convert_column_to_json(table: str, column: str):
    conn = op.get_bind()
    dialect = conn.dialect.name
    source_column = column
    temp_column = f'{column}_json'

    if not (_has_column(table, source_column) or _has_column(table, temp_column)):
        return

    # SQLite cannot ALTER COLUMN → must recreate column
    if dialect == 'sqlite':
        # 1. Add temporary column
        _add_column_if_missing(table, sa.Column(temp_column, sa.JSON(), nullable=True))

        # 2. Load old data
        if _has_column(table, source_column):
            rows = conn.execute(sa.text(f'SELECT id, {source_column} FROM "{table}"')).fetchall()

            for row in rows:
                uid, raw = row
                if raw is None:
                    parsed = None
                else:
                    try:
                        parsed = json.loads(raw)
                    except Exception:
                        parsed = None  # fallback safe behavior

                conn.execute(
                    sa.text(f'UPDATE "{table}" SET {temp_column} = :val WHERE id = :id'),
                    {'val': json.dumps(parsed) if parsed else None, 'id': uid},
                )

            # 3. Drop old TEXT column
            op.drop_column(table, source_column)

        # 4. Rename new JSON column → original name
        if _has_column(table, temp_column):
            op.alter_column(table, temp_column, new_column_name=source_column)

    elif dialect == 'mysql':
        op.alter_column(table, column, type_=sa.JSON())
    else:
        # PostgreSQL supports direct CAST
        op.alter_column(
            table,
            column,
            type_=sa.JSON(),
            postgresql_using=f'{column}::json',
        )


def _convert_column_to_text(table: str, column: str):
    conn = op.get_bind()
    dialect = conn.dialect.name
    source_column = column
    temp_column = f'{column}_text'

    if not (_has_column(table, source_column) or _has_column(table, temp_column)):
        return

    if dialect == 'sqlite':
        _add_column_if_missing(table, sa.Column(temp_column, sa.Text(), nullable=True))

        if _has_column(table, source_column):
            rows = conn.execute(sa.text(f'SELECT id, {source_column} FROM "{table}"')).fetchall()

            for uid, raw in rows:
                conn.execute(
                    sa.text(f'UPDATE "{table}" SET {temp_column} = :val WHERE id = :id'),
                    {'val': json.dumps(raw) if raw else None, 'id': uid},
                )

            op.drop_column(table, source_column)
        if _has_column(table, temp_column):
            op.alter_column(table, temp_column, new_column_name=source_column)

    elif dialect == 'mysql':
        op.alter_column(table, column, type_=sa.Text())
    else:
        op.alter_column(
            table,
            column,
            type_=sa.Text(),
            postgresql_using=f'to_json({column})::text',
        )


def upgrade() -> None:
    _add_column_if_missing('user', sa.Column('profile_banner_image_url', sa.Text(), nullable=True))
    # ``sa.String()`` (no length) compiles to an unbounded VARCHAR which MySQL
    # rejects ("VARCHAR requires a length on dialect mysql"). Use ``sa.Text``
    # for these short, non-indexed strings; SQLite/Postgres treat the two
    # identically for these purposes.
    _add_column_if_missing('user', sa.Column('timezone', sa.Text(), nullable=True))

    _add_column_if_missing('user', sa.Column('presence_state', sa.Text(), nullable=True))
    _add_column_if_missing('user', sa.Column('status_emoji', sa.Text(), nullable=True))
    _add_column_if_missing('user', sa.Column('status_message', sa.Text(), nullable=True))
    _add_column_if_missing('user', sa.Column('status_expires_at', sa.BigInteger(), nullable=True))

    _add_column_if_missing('user', sa.Column('oauth', sa.JSON(), nullable=True))

    # Convert info (TEXT/JSONField) → JSON
    _convert_column_to_json('user', 'info')
    # Convert settings (TEXT/JSONField) → JSON
    _convert_column_to_json('user', 'settings')

    if not _table_exists('api_key'):
        op.create_table(
            'api_key',
            sa.Column('id', sa.Text(), primary_key=True, unique=True),
            sa.Column('user_id', sa.Text(), sa.ForeignKey('user.id', ondelete='CASCADE')),
            sa.Column('key', sa.Text(), unique=True, nullable=False),
            sa.Column('data', sa.JSON(), nullable=True),
            sa.Column('expires_at', sa.BigInteger(), nullable=True),
            sa.Column('last_used_at', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
            sa.Column('updated_at', sa.BigInteger(), nullable=False),
        )

    conn = op.get_bind()
    # Use the dialect's identifier preparer so reserved words like `user` and
    # `key` are quoted correctly on every backend (backticks for MySQL,
    # double quotes for PostgreSQL/SQLite).
    quote = conn.dialect.identifier_preparer.quote
    user_tbl = quote('user')
    key_col = quote('key')
    if _has_column('user', 'oauth_sub') and _has_column('user', 'oauth'):
        users = conn.execute(
            sa.text(f'SELECT id, oauth_sub FROM {user_tbl} WHERE oauth_sub IS NOT NULL AND oauth IS NULL')
        ).fetchall()

        for uid, oauth_sub in users:
            if oauth_sub:
                # Example formats supported:
                #   provider@sub
                #   plain sub (stored as {"oidc": {"sub": sub}})
                if '@' in oauth_sub:
                    provider, sub = oauth_sub.split('@', 1)
                else:
                    provider, sub = 'oidc', oauth_sub

                oauth_json = json.dumps({provider: {'sub': sub}})
                conn.execute(
                    sa.text(f'UPDATE {user_tbl} SET oauth = :oauth WHERE id = :id'),
                    {'oauth': oauth_json, 'id': uid},
                )

    users_with_keys = []
    if _has_column('user', 'api_key') and _table_exists('api_key'):
        users_with_keys = conn.execute(
            sa.text(f'SELECT id, api_key FROM {user_tbl} WHERE api_key IS NOT NULL')
        ).fetchall()
    now = int(time.time())
    existing_api_key_user_ids = set()
    if _table_exists('api_key') and _has_column('api_key', 'user_id'):
        existing_api_key_user_ids = {
            user_id for (user_id,) in conn.execute(sa.text('SELECT user_id FROM api_key')).fetchall()
        }

    for uid, api_key in users_with_keys:
        if api_key and uid not in existing_api_key_user_ids:
            conn.execute(
                sa.text(f"""
                    INSERT INTO api_key (id, user_id, {key_col}, created_at, updated_at)
                    VALUES (:id, :user_id, :key, :created_at, :updated_at)
                """),
                {
                    'id': f'key_{uid}',
                    'user_id': uid,
                    'key': api_key,
                    'created_at': now,
                    'updated_at': now,
                },
            )

    if conn.dialect.name == 'sqlite':
        if _has_column('user', 'api_key'):
            _drop_sqlite_indexes_for_column('user', 'api_key', conn)
        if _has_column('user', 'oauth_sub'):
            _drop_sqlite_indexes_for_column('user', 'oauth_sub', conn)

    columns_to_drop = [column for column in ('api_key', 'oauth_sub') if _has_column('user', column)]
    if columns_to_drop:
        with op.batch_alter_table('user') as batch_op:
            for column in columns_to_drop:
                batch_op.drop_column(column)


def downgrade() -> None:
    # --- 1. Restore old oauth_sub column ---
    op.add_column('user', sa.Column('oauth_sub', sa.Text(), nullable=True))

    conn = op.get_bind()
    # See _quote_user_table comment in upgrade(): quote reserved identifiers
    # via the dialect's preparer so MySQL backticks / Postgres double quotes
    # are emitted correctly.
    quote = conn.dialect.identifier_preparer.quote
    user_tbl = quote('user')
    key_col = quote('key')
    users = conn.execute(sa.text(f'SELECT id, oauth FROM {user_tbl} WHERE oauth IS NOT NULL')).fetchall()

    for uid, oauth in users:
        try:
            data = json.loads(oauth)
            provider = list(data.keys())[0]
            sub = data[provider].get('sub')
            oauth_sub = f'{provider}@{sub}'
        except Exception:
            oauth_sub = None

        conn.execute(
            sa.text(f'UPDATE {user_tbl} SET oauth_sub = :oauth_sub WHERE id = :id'),
            {'oauth_sub': oauth_sub, 'id': uid},
        )

    op.drop_column('user', 'oauth')

    # --- 2. Restore api_key field ---
    # ``sa.String()`` without length is illegal on MySQL; mirror the upgrade()
    # workaround and store the API key in a TEXT column.
    op.add_column('user', sa.Column('api_key', sa.Text(), nullable=True))

    # Restore values from api_key
    keys = conn.execute(sa.text(f'SELECT user_id, {key_col} FROM api_key')).fetchall()
    for uid, key in keys:
        conn.execute(
            sa.text(f'UPDATE {user_tbl} SET api_key = :key WHERE id = :id'),
            {'key': key, 'id': uid},
        )

    # Drop new table
    op.drop_table('api_key')

    with op.batch_alter_table('user') as batch_op:
        batch_op.drop_column('profile_banner_image_url')
        batch_op.drop_column('timezone')

        batch_op.drop_column('presence_state')
        batch_op.drop_column('status_emoji')
        batch_op.drop_column('status_message')
        batch_op.drop_column('status_expires_at')

    # Convert info (JSON) → TEXT
    _convert_column_to_text('user', 'info')
    # Convert settings (JSON) → TEXT
    _convert_column_to_text('user', 'settings')
