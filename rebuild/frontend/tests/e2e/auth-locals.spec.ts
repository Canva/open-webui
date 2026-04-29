import { test, expect } from '@playwright/test';
import type { User } from '../../src/lib/types/user';

// Placement choice (m0 acceptance criterion regression):
//
//   The dispatch lists `tests/component/auth-locals.spec.ts` as the
//   default location, with E2E as the explicit fallback when CT cannot
//   drive `event.locals.user`. Playwright Component Testing only mounts
//   the component — it does not run `hooks.server.ts`, where the rebuild
//   actually populates `locals.user` from the trusted-header proxy. So
//   the regression for the m0 acceptance criterion ("a route handler
//   reading event.locals.user sees the same value the client receives in
//   data.user") MUST run against the real SvelteKit server. This test
//   therefore lives in `tests/e2e/`.
//
// Assertion strategy:
//
//   `+layout.server.ts` is a one-liner returning `{ user: locals.user }`,
//   so by construction `data.user === locals.user`. The shipped layout
//   renders the value through `JSON.stringify(data.user, null, 2)` into a
//   `<pre>` debug block (kept in the m0 layout precisely as the smoke
//   anchor for this regression). We:
//
//     1. Hit `/api/me` directly to capture what the server believes the
//        trusted-header user is.
//     2. Hit `/` (which goes through `hooks.server.ts handle` → populate
//        `locals.user` → `+layout.server.ts load` → `data.user`) and
//        parse the rendered debug JSON.
//     3. Assert (1) and (2) match. If they ever drift, either the layout
//        load is no longer a one-liner forwarding `locals.user`, or
//        `hooks.server.ts` is doing something different from the route
//        handler — either way, an m0-acceptance regression.

test('@smoke locals.user matches data.user under the trusted-header path', async ({ browser }) => {
  const context = await browser.newContext({
    extraHTTPHeaders: { 'X-Forwarded-Email': 'alice@canva.com' },
  });
  const page = await context.newPage();

  // (1) capture the server's view of the trusted-header user
  const meResponse = await page.request.get('/api/me');
  expect(meResponse.ok()).toBe(true);
  const apiUser = (await meResponse.json()) as User;
  expect(apiUser.email).toBe('alice@canva.com');

  // (2) load the page and parse the rendered data.user debug block
  await page.goto('/');
  const debugBlock = page.locator('pre').filter({ hasText: '"email"' });
  await expect(debugBlock).toBeVisible();
  const debugText = (await debugBlock.textContent()) ?? '';
  const dataUser = JSON.parse(debugText) as User;

  // (3) the m0 invariant
  expect(dataUser).toEqual(apiUser);

  await context.close();
});
