import type { PageServerLoad } from './$types';

/**
 * Settings page server load.
 *
 * Returns only what the page needs: the trusted-header user (so the
 * page can render the auth-gated guard from `m1-theming.md` § Open
 * questions / "Match system" reset path), nothing else. The active
 * theme is already on `event.locals.theme` AND mirrored in the per-
 * request ThemeStore via the layout, so the picker never asks for it
 * here.
 *
 * Auth gating is layered: `(app)/+layout.server.ts` already surfaces
 * `locals.user` to every child page, and `(app)/+layout.svelte` owns
 * the M0 "no proxy header" empty state. This page additionally guards
 * its own render in `+page.svelte` with `if (data.user)` per the M1
 * dispatch instruction (the layout doesn't currently hide children
 * for unauthenticated requests).
 */
export const load: PageServerLoad = ({ locals }) => ({
  user: locals.user,
});
