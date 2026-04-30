import type { LayoutServerLoad } from './$types';

/**
 * Authenticated route group: surfaces the M0 trusted-header user and
 * the M1 theme resolution from `event.locals` (populated by the
 * `handle` hook in `src/hooks.server.ts`) onto every child page's
 * `data` prop.
 *
 * Per the M1 plan § Persistence and `m0-foundations.md` § Auth populate,
 * the cookie/header reads happen in `handle`, not in this load — that
 * way layout `load` caching across navigations cannot leak a stale
 * user or theme value.
 */
export const load: LayoutServerLoad = ({ locals }) => ({
  user: locals.user,
  theme: locals.theme,
  themeSource: locals.themeSource,
});
