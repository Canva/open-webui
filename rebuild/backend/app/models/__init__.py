"""ORM model registry.

Re-exports every concrete ORM model so importing this package alone is
sufficient to populate ``app.db.base.Base.metadata`` (which is what
Alembic's ``env.py`` autogenerate / migration runner consumes).

Each later milestone (M2 chat/folder, M3 share, M4 channel/message/file,
M5 automation/automation_run) appends its model imports to this file.
"""

from __future__ import annotations

from app.models.user import User

__all__ = ["User"]
