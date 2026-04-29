"""Standard-library logging bootstrap.

Structlog / OTel shipping arrives in M6; for M0 we just need a single entry
point the FastAPI ``lifespan`` can call once at startup.
"""

from __future__ import annotations

import logging


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger with a project-wide format and the given level."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
