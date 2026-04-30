/**
 * Mirror of `app/schemas/model.py` — the M2 `/api/models` wire types.
 *
 * Locked by `rebuild/docs/plans/m2-conversations.md` § Models. The
 * backend caches the upstream `/v1/models` list for 5 minutes; the
 * `ModelsStore` triggers a refresh on dropdown open if its local copy
 * is older than 30 s (see `rebuild.md` plan example block).
 */

export interface ModelInfo {
  id: string;
  label: string;
  owned_by: string | null;
}

export interface ModelList {
  items: ModelInfo[];
}
