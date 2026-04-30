"""Response schemas for ``GET /api/models``.

The route handler (Phase 2b dispatch) reads from
:class:`app.services.models_cache.ModelsCache`; this module owns only the
wire shape exposed to the frontend ``ModelsStore``. Locked reference:
``rebuild/docs/plans/m2-conversations.md`` § Models.
"""

from __future__ import annotations

from app.schemas._base import StrictModel


class ModelInfo(StrictModel):
    id: str
    label: str
    owned_by: str | None = None


class ModelList(StrictModel):
    items: list[ModelInfo]
