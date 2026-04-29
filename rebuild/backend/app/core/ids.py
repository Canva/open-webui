"""Project-wide UUIDv7 helper. Every ``id`` column on every table is populated
by :func:`new_id` (RFC 9562). Direct ``uuid.uuid4()`` / ``uuid4()`` calls are
banned via ruff ``flake8-tidy-imports`` (banned-api) — see
``pyproject.toml`` ``[tool.ruff.lint.flake8-tidy-imports.banned-api]``.

UUIDv7 is chosen over UUIDv4 so the leading 48 bits are a millisecond Unix
timestamp, which gives near-monotonic insertion order in the InnoDB clustered
B-tree (and in every secondary index that carries the PK). See
``rebuild.md`` §9 for the full rationale.

Implementation: ``uuid7-standard`` exposes a top-level ``uuid7`` package whose
public API is ``uuid7.create()`` (returns a :class:`uuid.UUID`). In Python 3.13+
this can be swapped for stdlib ``uuid.uuid7`` with no caller change.
"""

from __future__ import annotations

import uuid7  # uuid7-standard package, RFC 9562 backport for Python 3.12


def new_id() -> str:
    """Return a UUIDv7 string in canonical hyphenated 36-char form."""
    return str(uuid7.create())
