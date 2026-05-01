"""Response schemas for ``GET /api/agents``.

The route handler (Phase 2b dispatch) reads from
:class:`app.services.agents_cache.AgentsCache`; this module owns only the
wire shape exposed to the frontend ``AgentsStore``. Locked reference:
``rebuild/docs/plans/m2-conversations.md`` § Agents.

In the rebuild's product surface every selectable persona is an
**agent** — the user picks an agent (each with a preselected underlying
model) and the agent platform handles the model lookup. The OpenAI-
compatible upstream still speaks ``/v1/models`` on the wire; the
backend translates that catalogue into the ``Agent`` domain shape here.
"""

from __future__ import annotations

from app.schemas._base import StrictModel


class AgentInfo(StrictModel):
    id: str
    label: str
    owned_by: str | None = None


class AgentList(StrictModel):
    items: list[AgentInfo]
