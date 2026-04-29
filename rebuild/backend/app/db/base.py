"""Declarative ORM base + project-wide constraint naming convention.

Every table in the rebuild inherits from :class:`Base`, so every constraint
and index Alembic generates picks up a deterministic name from
``NAMING_CONVENTION``. Deterministic names are mandatory because
``app.db.migration_helpers`` looks up constraints/indexes by name when
deciding whether to skip a re-run of a partially-applied revision.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Project-wide SQLAlchemy 2 declarative base."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
