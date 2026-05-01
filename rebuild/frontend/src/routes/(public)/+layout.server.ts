import type { LayoutServerLoad } from './$types';

/**
 * Public route group: M3's share view (`/s/{token}`) and any other
 * unauthenticated surface mount under here. M1 only needs the theme
 * resolution to flow through so the recipient of a share link sees
 * the chrome in their picked preset.
 *
 * `user` is forwarded from `locals.user` (already populated by the
 * trusted-header `handle` hook) so the typed `App.PageData` contract
 * is satisfied for child pages — but the (public) shell never reads
 * it, and the layout deliberately does NOT call `getUser` itself
 * (per `m1-theming.md` § E2E placeholder for `theme-public-share`).
 * It will be `null` for anonymous requests, which is the correct
 * value to surface for surfaces that aren't auth-gated by SvelteKit
 * (the M3 share view defers auth to the FastAPI router).
 */
export const load: LayoutServerLoad = ({ locals }) => ({
  user: locals.user,
  theme: locals.theme,
  themeSource: locals.themeSource,
});
