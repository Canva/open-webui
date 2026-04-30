"""``GET /api/models`` — passthrough of the gateway's ``/v1/models`` list.

The handler reads from the in-process :class:`app.services.models_cache.ModelsCache`
(5-minute TTL with single-flight refresh — see Phase 2a's
``models_cache.py``). Provider failures bubble as
:class:`app.providers.openai.ProviderError` and are mapped centrally to
``502 / 504 / 429`` by :func:`app.core.errors.register_exception_handlers`;
this router never wraps ``try/except`` for app-level errors
(``rebuild/docs/best-practises/FastAPI-best-practises.md`` § A.6).

Auth is required even though the response is user-agnostic: every router
in the rebuild requires :func:`app.core.auth.get_user` so the trusted-
header proxy contract is exercised on every authenticated route (no
"is this endpoint behind the proxy?" footnote per route).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentUser, ModelsCacheDep
from app.schemas.model import ModelInfo, ModelList

router = APIRouter(prefix="/api", tags=["models"])


@router.get("/models", response_model=ModelList)
async def list_models(_user: CurrentUser, cache: ModelsCacheDep) -> ModelList:
    """Return the gateway's model list, cached in-process for 5 minutes."""
    items = await cache.get()
    return ModelList(items=[ModelInfo(id=m.id, label=m.label, owned_by=m.owned_by) for m in items])
