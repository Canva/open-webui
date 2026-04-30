import type { LayoutServerLoad } from './$types';

/**
 * Public route group: M3's share view (`/s/{token}`) and any other
 * unauthenticated surface mount under here. M1 only needs the theme
 * resolution to flow through so the recipient of a share link sees
 * the chrome in their picked preset.
 *
 * No `user` field is exposed because public routes deliberately do
 * not run identity through their data prop — that is the M3
 * decision (recipients of a share link should not require auth).
 */
export const load: LayoutServerLoad = ({ locals }) => ({
  theme: locals.theme,
  themeSource: locals.themeSource,
});
