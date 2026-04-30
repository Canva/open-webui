/**
 * Explicit theme persistence E2E.
 *
 * Pinned by `rebuild/docs/plans/m1-theming.md` § Tests § E2E
 * (theme-explicit-persists.spec.ts) AND § Acceptance criteria ("the
 * picker click writes through, survives reload, survives a brand-new
 * BrowserContext on the same persistent storage").
 *
 * Three milestones in one test (per the plan; splitting them would
 * lose the cookie-+-localStorage-+-storage-state continuity):
 *
 *   1. Visit `/settings`, click the Tokyo Moon tile, assert
 *      `data-theme === 'tokyo-moon'`.
 *   2. Full reload (`page.reload()`); assert it survives. The cookie
 *      is the SSR carrier so the server-emitted `<html data-theme>`
 *      should match without the boot script having to do any work.
 *   3. Snapshot the storage state, close the BrowserContext, open a
 *      brand-new BrowserContext from the same storage state,
 *      navigate to `/settings`, assert it survives. This proves the
 *      cookie+localStorage tuple is the durable carrier (not some
 *      in-memory store that gets wiped on context close).
 */

import { test, expect } from '@playwright/test';

test('explicit picker choice persists across reload AND across BrowserContext close', async ({
  page,
  context,
  browser,
}) => {
  // Step 1: visit settings, click Tokyo Moon, assert immediate effect.
  await page.goto('/settings');

  const moonTile = page.locator('button[data-theme="tokyo-moon"]');
  await expect(moonTile, 'expected the Tokyo Moon tile to render').toBeVisible();
  await moonTile.click();

  await expect
    .poll(async () => page.evaluate(() => document.documentElement.dataset.theme))
    .toBe('tokyo-moon');

  // Cookie + localStorage co-write contract.
  const cookiesAfterClick = await context.cookies();
  const themeCookie = cookiesAfterClick.find((c) => c.name === 'theme');
  expect(themeCookie, 'expected the picker click to write the theme cookie').toBeDefined();
  expect(themeCookie!.value).toBe('tokyo-moon');

  const storedAfterClick = await page.evaluate(() => localStorage.getItem('theme'));
  expect(storedAfterClick).toBe('tokyo-moon');

  // Step 2: reload, assert it survives.
  await page.reload();
  await page.waitForLoadState('domcontentloaded');

  const themeAfterReload = await page.evaluate(() => document.documentElement.dataset.theme);
  expect(themeAfterReload, 'theme should survive a full reload').toBe('tokyo-moon');

  // The Moon tile should also render with `aria-pressed="true"` after
  // the reload — proving the SSR-cookie path correctly seeds the store
  // with `themeSource === 'explicit'`.
  await expect(page.locator('button[data-theme="tokyo-moon"]')).toHaveAttribute(
    'aria-pressed',
    'true',
  );

  // Step 3: snapshot storage state, open a NEW BrowserContext with the
  // same state, navigate, assert.
  const storageState = await context.storageState();
  await context.close();

  const newContext = await browser.newContext({
    storageState,
    extraHTTPHeaders: { 'X-Forwarded-Email': 'alice@canva.com' },
  });
  const newPage = await newContext.newPage();
  await newPage.goto('/settings');
  await newPage.waitForLoadState('domcontentloaded');

  const themeInNewContext = await newPage.evaluate(() => document.documentElement.dataset.theme);
  expect(
    themeInNewContext,
    'theme should survive a brand-new BrowserContext on the same persistent storage',
  ).toBe('tokyo-moon');

  // localStorage survives the storage-state round-trip.
  const storedInNewContext = await newPage.evaluate(() => localStorage.getItem('theme'));
  expect(storedInNewContext).toBe('tokyo-moon');

  await newContext.close();
});
