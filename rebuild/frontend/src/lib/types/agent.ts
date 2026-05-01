/**
 * Mirror of `app/schemas/agent.py` — the M2 `/api/agents` wire types.
 *
 * Locked by `rebuild/docs/plans/m2-conversations.md` § Agents. The
 * backend caches the upstream agent catalogue (served on
 * `/v1/models` by the OpenAI-compatible gateway) for 5 minutes; the
 * `AgentsStore` triggers a refresh on dropdown open if its local copy
 * is older than 30 s (see `rebuild.md` plan example block).
 */

export interface AgentInfo {
  id: string;
  label: string;
  owned_by: string | null;
}

export interface AgentList {
  items: AgentInfo[];
}
