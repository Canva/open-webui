"""``GET /api/agents`` — passthrough of the gateway's ``/v1/models`` list.

The handler reads from the in-process :class:`app.services.agents_cache.AgentsCache`
(5-minute TTL with single-flight refresh — see Phase 2a's
``agents_cache.py``). Provider failures bubble as
:class:`app.providers.openai.ProviderError` and are mapped centrally to
``502 / 504 / 429`` by :func:`app.core.errors.register_exception_handlers`;
this router never wraps ``try/except`` for app-level errors
(``rebuild/docs/best-practises/FastAPI-best-practises.md`` § A.6).

Auth is required even though the response is user-agnostic: every router
in the rebuild requires :func:`app.core.auth.get_user` so the trusted-
header proxy contract is exercised on every authenticated route (no
"is this endpoint behind the proxy?" footnote per route).

The agents catalogue is what the user picks from in the rebuild UI. Each
agent has a preselected underlying model on the agent platform; the
backend never exposes the model id directly. The upstream OpenAI-
compatible URL path stays ``/v1/models`` for wire compatibility, but the
rebuild's API surface is ``/api/agents``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import AgentsCacheDep, CurrentUser
from app.schemas.agent import AgentInfo, AgentList

router = APIRouter(prefix="/api", tags=["agents"])


@router.get("/agents", response_model=AgentList)
async def list_agents(_user: CurrentUser, cache: AgentsCacheDep) -> AgentList:
    """Return the gateway's agent list, cached in-process for 5 minutes."""
    items = await cache.get()
    return AgentList(items=[AgentInfo(id=a.id, label=a.label, owned_by=a.owned_by) for a in items])
