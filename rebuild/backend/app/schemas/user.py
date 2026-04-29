"""Response schema for :class:`app.models.user.User`.

``created_at`` is the BIGINT epoch-ms value straight from the row (project-wide
convention from ``rebuild.md`` §4).
"""

from __future__ import annotations

from app.schemas._base import StrictModel


class UserRead(StrictModel):
    id: str
    email: str
    name: str
    timezone: str
    created_at: int  # epoch ms
