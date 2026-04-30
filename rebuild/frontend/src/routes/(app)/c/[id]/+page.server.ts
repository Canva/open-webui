import { error } from '@sveltejs/kit';

import type { PageServerLoad } from './$types';

import { ApiError, chats } from '$lib/api/client';

/**
 * Server-load the full chat (including the JSON history tree) so the
 * `/c/[id]` deep-link paints with content on first response, before
 * the SSE stream or any client-side hydration kicks in.
 *
 * Locked by `rebuild/docs/plans/m2-conversations.md`:
 *   - § Frontend routes (line 880): "loads the full chat for SSR,
 *     then SPA takes over".
 *   - § Stores and state (line 1022): "`activeChat` is hydrated
 *     separately by `c/[id]/+page.server.ts` on direct deep-links";
 *     `useActiveChat().load(id)` then re-validates from the
 *     `+page.svelte`'s `$effect` so the in-memory store matches the
 *     SSR'd markup.
 *
 * Errors:
 *   - 404 -> SvelteKit `error(404)` so `+error.svelte` renders.
 *   - 401 / 403 -> map to 404 too: leaking "this chat exists but
 *     belongs to someone else" would defeat the trusted-header
 *     ownership check. The backend returns 404 in both cases anyway;
 *     this is defence-in-depth.
 *   - Anything else surfaces as a 500 via SvelteKit's default
 *     `+error.svelte` chain.
 */
export const load: PageServerLoad = async ({ params, fetch }) => {
  try {
    const chat = await chats.get(params.id, fetch);
    return { chat };
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.status === 404 || err.status === 401 || err.status === 403) {
        error(404, 'Chat not found');
      }
      error(err.status >= 500 ? 502 : 500, err.message);
    }
    throw err;
  }
};
