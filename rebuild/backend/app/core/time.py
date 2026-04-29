"""Project-wide epoch-ms timestamp source. Centralised so tests can monkey-patch
a single symbol to freeze time.

Every ``BIGINT`` epoch-ms column in the project (chats, channels, automations,
files, …) takes its value from :func:`now_ms`. ``datetime.datetime.utcnow`` is
banned via ruff ``flake8-tidy-imports``; see ``pyproject.toml``
``[tool.ruff.lint.flake8-tidy-imports.banned-api]`` and ``rebuild.md`` §4.
"""

from __future__ import annotations

import time


def now_ms() -> int:
    """Return current wall-clock time as integer milliseconds since the Unix epoch."""
    return time.time_ns() // 1_000_000
