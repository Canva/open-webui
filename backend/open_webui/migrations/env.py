import logging
import os
from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from open_webui.models.auths import Auth
from open_webui.models.calendar import Calendar, CalendarEvent, CalendarEventAttendee  # noqa: F401
from open_webui.env import DATABASE_URL as _ENV_DATABASE_URL, DATABASE_PASSWORD, LOG_FORMAT
from open_webui.internal.db import extract_ssl_mode_from_url, reattach_ssl_mode_to_url
from sqlalchemy import engine_from_config, pool, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.schema import CreateColumn, CreateIndex

# Re-read DATABASE_URL from the environment at every Alembic invocation so
# tests (and any caller that mutates the env var after open_webui has been
# imported) target the database they expect, not the one cached when
# open_webui.env was first imported.
DATABASE_URL = os.environ.get('DATABASE_URL', _ENV_DATABASE_URL)


# ---------------------------------------------------------------------------
# MySQL portability shims
# ---------------------------------------------------------------------------
# A large number of historical Alembic migrations declare primary-key columns
# as ``sa.Text()`` (or its dialect equivalents). MySQL refuses to build an
# index on a ``TEXT``/``BLOB`` column without an explicit prefix length, which
# SQLAlchemy/Alembic do not emit for primary keys. Rather than rewriting
# every migration in-place (and risking churn / merge conflicts), we coerce
# such columns to a bounded ``VARCHAR`` only when the target dialect is MySQL
# — leaving SQLite and PostgreSQL untouched. Identifier lengths up to 255
# characters comfortably accommodate every UUID, OAuth subject, slug, or
# collection name we generate.
_MYSQL_PK_VARCHAR_LEN = 255


def _is_textual_type(type_) -> bool:
    return isinstance(type_, sa.Text) or (isinstance(type_, sa.String) and type_.length is None)


def _column_needs_bounded_string(column) -> bool:
    """Return True for TEXT columns MySQL can't index without a key length.

    MySQL forbids indexes (including unique constraints, primary keys, and
    foreign keys) on TEXT/BLOB columns unless an explicit key length is given.
    Historical migrations declare these columns as ``sa.Text`` for portability,
    so on MySQL we coerce any column that is part of an index — primary key,
    column- or table-level unique constraint, or foreign key — to a bounded
    ``VARCHAR``.
    """
    if not _is_textual_type(column.type):
        return False
    if column.primary_key or column.unique:
        return True
    if getattr(column, 'foreign_keys', None):
        return True
    table = getattr(column, 'table', None)
    if table is not None:
        from sqlalchemy.schema import UniqueConstraint

        for constraint in table.constraints:
            if not isinstance(constraint, UniqueConstraint):
                continue
            for c in constraint.columns:
                if getattr(c, 'name', None) == column.name:
                    return True
        for index in getattr(table, 'indexes', ()):  # pragma: no cover (PK/unique cover the common path)
            for c in index.columns:
                if getattr(c, 'name', None) == column.name:
                    return True
    return False


@compiles(CreateColumn, 'mysql')
def _mysql_create_column(element, compiler, **kw):  # type: ignore[no-untyped-def]
    column = element.element
    # Migrations declare three flavours of textual columns interchangeably:
    #   - ``sa.Text()`` for free-form text
    #   - ``sa.String()`` (no length) intending "short string"
    #   - ``sa.String(length=N)`` when an author already cared about size
    # On MySQL, ``sa.String()`` with no length is a hard compile error and
    # ``sa.Text`` cannot participate in PK/UNIQUE/FK/index constraints
    # without a key prefix length. We coerce both into a bounded
    # ``VARCHAR(255)`` whenever the column is part of a key, leaving free
    # text columns alone.
    if _column_needs_bounded_string(column):
        column.type = sa.String(length=_MYSQL_PK_VARCHAR_LEN)
    elif isinstance(column.type, sa.String) and not isinstance(column.type, sa.Text) and column.type.length is None:
        # Plain ``sa.String()`` -> ``VARCHAR(255)``: matches the historical
        # SQLite/Postgres behaviour where ``sa.String`` defaulted to a
        # short, indexable type and lets later migrations safely add a
        # UNIQUE/index over the column without retroactive type changes.
        column.type = sa.String(length=_MYSQL_PK_VARCHAR_LEN)
    return compiler.visit_create_column(element, **kw)


# Connection currently in use by the migration run, captured in
# run_migrations_online() so the CreateIndex compile hook can probe the live
# schema for column types — the hook can otherwise only see what the migration
# author put in the in-memory ``Index`` object.
_ACTIVE_MIGRATION_CONN = None


def _probe_text_columns(table_name: str) -> set[str]:
    if _ACTIVE_MIGRATION_CONN is None:
        return set()
    try:
        inspector = sa.inspect(_ACTIVE_MIGRATION_CONN)
        return {c['name'] for c in inspector.get_columns(table_name) if _is_textual_type(c['type'])}
    except Exception:  # pragma: no cover — best-effort schema probe
        return set()


@compiles(CreateIndex, 'mysql')
def _mysql_create_index(element, compiler, **kw):  # type: ignore[no-untyped-def]
    """Inject prefix lengths for indexes that touch TEXT/BLOB columns.

    MySQL refuses to index a TEXT column without an explicit prefix length.
    Many of our migrations declare slug/UUID columns as ``sa.Text`` and then
    add an index across them; we transparently set ``mysql_length`` for any
    such column so the same migration text works on every dialect.

    ``op.create_index('idx', 'table', ['col'])`` builds an Index whose column
    expressions are unresolved string names, so we probe the live MySQL
    schema for column types using the connection captured by
    ``run_migrations_online``.
    """
    index = element.element
    text_cols: set[str] = set()

    for col in index.columns:
        col_type = getattr(col, 'type', None)
        if _is_textual_type(col_type):
            col_name = getattr(col, 'name', None) or str(col)
            text_cols.add(col_name)

    text_cols |= _probe_text_columns(index.table.name)
    indexed_names = {getattr(col, 'name', None) or str(col) for col in index.columns}
    text_cols &= indexed_names

    if text_cols:
        existing = index.dialect_options['mysql'].get('length') or {}
        if isinstance(existing, int):
            existing = {name: existing for name in indexed_names}
        else:
            existing = dict(existing)
        for name in text_cols:
            existing.setdefault(name, _MYSQL_PK_VARCHAR_LEN)
        index.dialect_options['mysql']['length'] = existing
    return compiler.visit_create_index(element, **kw)


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Re-apply JSON formatter after fileConfig replaces handlers.
if LOG_FORMAT == 'json':
    from open_webui.env import JSONFormatter

    for handler in logging.root.handlers:
        handler.setFormatter(JSONFormatter())

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Auth.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

DB_URL = DATABASE_URL

# Normalize SSL query params for psycopg2 (Alembic uses psycopg2, not asyncpg).
url_without_ssl, ssl_mode = extract_ssl_mode_from_url(DB_URL)
DB_URL = reattach_ssl_mode_to_url(url_without_ssl, ssl_mode) if ssl_mode else DB_URL

if DB_URL:
    config.set_main_option('sqlalchemy.url', DB_URL.replace('%', '%%'))


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option('sqlalchemy.url')
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # Handle SQLCipher URLs
    if DB_URL and DB_URL.startswith('sqlite+sqlcipher://'):
        if not DATABASE_PASSWORD or DATABASE_PASSWORD.strip() == '':
            raise ValueError('DATABASE_PASSWORD is required when using sqlite+sqlcipher:// URLs')

        # Extract database path from SQLCipher URL
        db_path = DB_URL.replace('sqlite+sqlcipher://', '')
        if db_path.startswith('/'):
            db_path = db_path[1:]  # Remove leading slash for relative paths

        # Create a custom creator function that uses sqlcipher3
        def create_sqlcipher_connection():
            import sqlcipher3

            conn = sqlcipher3.connect(db_path, check_same_thread=False)
            conn.execute(f"PRAGMA key = '{DATABASE_PASSWORD}'")
            return conn

        connectable = create_engine(
            'sqlite://',  # Dummy URL since we're using creator
            creator=create_sqlcipher_connection,
            echo=False,
        )
    else:
        # Standard database connection (existing logic)
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix='sqlalchemy.',
            poolclass=pool.NullPool,
        )

    global _ACTIVE_MIGRATION_CONN
    with connectable.connect() as connection:
        _ACTIVE_MIGRATION_CONN = connection
        try:
            context.configure(connection=connection, target_metadata=target_metadata)

            with context.begin_transaction():
                context.run_migrations()
        finally:
            _ACTIVE_MIGRATION_CONN = None


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
