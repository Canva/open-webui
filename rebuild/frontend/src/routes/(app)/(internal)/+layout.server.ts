import type { LayoutServerLoad } from './$types';

/**
 * Internal route group (`(internal)/`) for visual-regression and
 * pipeline-smoke pages. Reads `event.locals.user` / `locals.theme`
 * / `locals.themeSource` directly (the same shape `(app)/+layout
 * .server.ts` exposes). The `(internal)/+layout@.svelte` sibling
 * uses the SvelteKit `@` layout reset to skip the parent
 * `(app)/+layout.svelte` chrome, and that reset detaches the route
 * from the parent server-load chain too: a `parent()` call here
 * returns `{}` instead of the (app) layout's data. Self-sourcing
 * from `locals` keeps the data contract intact.
 *
 * NO auth bypass: `event.locals.user` is populated for every request
 * by `src/hooks.server.ts` (the M0 trusted-header `getUser` populate
 * via `X-Forwarded-Email`). A request without the proxy header lands
 * here with `data.user = null`, same as anywhere else under `(app)/`.
 * The visual-regression Playwright runner is the only consumer that
 * routinely navigates here; real users hitting these URLs by accident
 * see whatever the upstream proxy lets through.
 *
 * Pinned by `rebuild/docs/plans/m2-conversations.md` § Deliverables
 * (the bullet on promoting the M1 smoke components into dedicated
 * routes under `(internal)/`).
 */
export const load: LayoutServerLoad = ({ locals }) => ({
  user: locals.user,
  theme: locals.theme,
  themeSource: locals.themeSource,
});
