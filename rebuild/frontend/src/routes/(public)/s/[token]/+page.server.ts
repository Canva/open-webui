/**
 * Server-only loader for the M3 public share view at `/s/{token}`.
 *
 * Locked by `rebuild/docs/plans/m3-sharing.md` § Frontend route:
 *   - Loads via `+page.server.ts` (NOT `+page.ts`) so the auth-gated
 *     `GET /api/shared/{token}` runs once with the proxy headers
 *     forwarded by SvelteKit's enhanced `fetch`. A universal load
 *     would also re-run on the client during in-app navigation, which
 *     is wasted work for a snapshot.
 *   - On 404, returns `{ snapshot: null }` so `+page.svelte` can
 *     render the inline "no longer active" panel rather than punting
 *     to the SvelteKit `+error.svelte` chain. The plan calls for a
 *     terminal panel here, not a redirect.
 *   - On 401, lets SvelteKit propagate the framework error so the
 *     proxy interception takes over (the share view never tries to
 *     handle anonymous requests itself).
 *   - On 5xx, surfaces a 502 bad-gateway via the standard `error()`
 *     helper.
 *
 * Placement note (handoff to `plan-keeper`): the plan text says the
 * route lives at `src/routes/s/[token]/+page.svelte`, but the
 * `(public)` route group already exists with the theme-aware layout
 * the plan requires (no sidebar, no header chrome, theme cookie
 * resolved). Putting the new view at
 * `src/routes/(public)/s/[token]/+page.svelte` reuses that layout
 * verbatim. SvelteKit route groups don't appear in the URL, so the
 * path still resolves to `/s/{token}`.
 */

import { error } from '@sveltejs/kit';

import { ApiError, shares } from '$lib/api/client';
import type { SharedChatSnapshot } from '$lib/types/share';

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params, fetch }) => {
  try {
    const snapshot = await shares.get(params.token, fetch);
    return { snapshot };
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.status === 404) {
        // Terminal "no longer active" panel — see component.
        return { snapshot: null as SharedChatSnapshot | null };
      }
      if (err.status === 401) {
        // Bubble the 401 to SvelteKit's error chain so the proxy
        // interception can take over the response. We deliberately
        // do not render a bespoke 401 panel in M3 — the M6 hardening
        // milestone owns the global error chrome.
        error(401, 'authentication required');
      }
      error(err.status >= 500 ? 502 : err.status, err.message);
    }
    throw err;
  }
};
