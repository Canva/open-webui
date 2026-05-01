import type { LayoutServerLoad } from './$types';

import { ApiError, agents, chats, folders } from '$lib/api/client';
import type { AgentInfo } from '$lib/types/agent';
import type { ChatList } from '$lib/types/chat';
import type { FolderRead } from '$lib/types/folder';

/**
 * Authenticated route group: surfaces the M0 trusted-header user, the
 * M1 theme resolution, and the M2 sidebar/folder/agent payloads from
 * the FastAPI backend onto every child page's `data` prop.
 *
 * Pinned by `rebuild/docs/plans/m2-conversations.md`:
 *   - § Frontend routes and components (line 875): "loads sidebar list
 *     + folder list once per navigation".
 *   - § Stores and state (line 1015): "The `(app)/+layout.server.ts`
 *     `load` returns `{ chats, folders, agents }`" — server-rendered
 *     into HTML and re-used as the stores' initial values during
 *     hydration so the first paint has the sidebar populated without
 *     an extra round-trip.
 *
 * The cookie/header reads happen in `handle`, not here, so layout
 * `load` caching across navigations cannot leak a stale user or
 * theme value (per the M1 plan § Persistence).
 *
 * Fail-soft: when the backend is degraded each backend call falls
 * back to its empty shape so the auth card and chat shell still
 * render. Phase 3d's `<Toaster>` surfaces these so the user knows the
 * sidebar / agent selector are stale; the layout itself does not
 * surface anything because the store error fields are reactive and
 * components that consume them already render the right empty-state
 * affordances (per `rebuild/docs/plans/m0-foundations.md` § Frontend
 * conventions cross-cutting, rule 1: errors live on the store, not
 * the layout).
 */
export const load: LayoutServerLoad = async ({ locals, fetch }) => {
  const base = {
    user: locals.user,
    theme: locals.theme,
    themeSource: locals.themeSource,
  } as const;

  if (locals.user === null) {
    return base;
  }

  const [chatsResult, foldersResult, agentsResult] = await Promise.all([
    chats.list({ limit: 50 }, fetch).catch((err: unknown) => {
      logBackendError('chats.list', err);
      return EMPTY_CHATS;
    }),
    folders.list(fetch).catch((err: unknown) => {
      logBackendError('folders.list', err);
      return EMPTY_FOLDERS;
    }),
    agents.list(fetch).catch((err: unknown) => {
      logBackendError('agents.list', err);
      return EMPTY_AGENTS;
    }),
  ]);

  return {
    ...base,
    chats: chatsResult,
    folders: foldersResult,
    agents: agentsResult.items,
  };
};

const EMPTY_CHATS: ChatList = { items: [], next_cursor: null };
const EMPTY_FOLDERS: FolderRead[] = [];
const EMPTY_AGENTS: { items: AgentInfo[] } = { items: [] };

function logBackendError(label: string, err: unknown): void {
  const status = err instanceof ApiError ? ` (${err.status})` : '';
  const message = err instanceof Error ? err.message : String(err);
  console.warn(`[layout.server] ${label}${status}: ${message}`);
}
