/**
 * Cross-tab theme propagation E2E.
 *
 * Pinned by `rebuild/docs/plans/m1-theming.md` § Tests § E2E
 * (theme-cross-tab.spec.ts) AND § Acceptance criteria.
 *
 * Mechanic: the cookie is the synchronisation surface. Set Tokyo Storm
 * in tab A (via `/settings`); open tab B in the SAME BrowserContext;
 * navigate tab B to `/`; the SvelteKit `hooks.server.ts` reads the
 * cookie on the SSR pass for tab B and emits `<html data-theme=
 * "tokyo-storm">` server-side, so first paint matches without any
 * cross-tab message bus.
 *
 * Cross-tab LIVE propagation (a `storage` event listener that mutates
 * tab B's theme when tab A clicks while both are already open) is
 * descoped by the M1 plan; this test deliberately does NOT assert it.
 */

import { test, expect } from '@playwright/test';

test('cookie set in tab A is honoured on first paint of tab B in the same context', async ({
  context,
}) => {
  // Tab A: set Tokyo Storm via the picker.
  const pageA = await context.newPage();
  await pageA.goto('/settings');

  const stormTile = pageA.locator('button[data-theme="tokyo-storm"]');
  await expect(stormTile, 'expected the Tokyo Storm tile to render').toBeVisible();
  await stormTile.click();

  await expect
    .poll(async () => pageA.evaluate(() => document.documentElement.dataset.theme))
    .toBe('tokyo-storm');

  // Sanity: the cookie is observable on the context.
  const cookies = await context.cookies();
  const themeCookie = cookies.find((c) => c.name === 'theme');
  expect(themeCookie, 'expected the picker click to write the theme cookie').toBeDefined();
  expect(themeCookie!.value).toBe('tokyo-storm');

  // Tab B: open a new page in the SAME context (cookies shared).
  const pageB = await context.newPage();
  await pageB.goto('/');
  await pageB.waitForLoadState('domcontentloaded');

  const themeOnB = await pageB.evaluate(() => document.documentElement.dataset.theme);
  expect(
    themeOnB,
    'tab B in the same BrowserContext should see Storm on first paint via the shared cookie',
  ).toBe('tokyo-storm');

  await pageA.close();
  await pageB.close();
});
