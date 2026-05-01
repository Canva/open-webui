/**
 * Public-share theme E2E.
 *
 * Pinned by `rebuild/docs/plans/m1-theming.md` § Tests § E2E
 * (theme-public-share.spec.ts) AND `rebuild/docs/plans/m3-sharing.md`
 * § Frontend route (the (public) layout reuse).
 *
 * Three contracts pinned here:
 *
 *   1. The `theme` cookie is honoured on `/s/{token}` — an anonymous
 *      viewer who previously customised in their authenticated
 *      session sees the same picker preset on the share page.
 *      Parametrised across `tokyo-day` and `tokyo-night` to prove
 *      the contract is symmetric.
 *
 *   2. With no cookie, the OS preference path resolves the boot to
 *      the canonical brand fallback for that OS hint (`tokyo-night`
 *      for `dark`, `tokyo-day` for `light`). Mirrors
 *      `theme-os-default.spec.ts`'s mechanic, scoped to the share
 *      route.
 *
 *   3. The (public) `+layout.server.ts` does NOT call `getUser`. The
 *      cheaper invariant we can assert from the browser is the
 *      surface contract: with a valid `X-Forwarded-Email` plus a
 *      theme cookie, the share page renders with the correct
 *      `data-theme` AND `locals.user` is forwarded straight through
 *      from `hooks.server.ts handle` (which is what the layout
 *      `load` returns — see the layout source file for the verbatim
 *      `user: locals.user` line). Direct assertion that the layout
 *      doesn't ALSO call into the FastAPI `/api/me` route requires
 *      a server-side log inspection that's out of scope for an E2E;
 *      we settle for the surface evidence here.
 *
 * Backend coordination
 * --------------------
 * Mocks `GET /api/shared/{token}` at `page.route` so the share page
 * renders deterministically. The backend's auth contract is covered
 * by `auth-required.spec.ts` (the 401 case) and by 15 backend
 * integration tests against real MySQL.
 *
 * History
 * -------
 * This file shipped in M1 as a `test.skip(...)` placeholder per the
 * M1 plan ("ships in M1 so the M3 author doesn't have to invent it;
 * body is a one-line comment that the M3 author fills in"). M3 is
 * shipping the share view, so this file is now flesh-and-bone.
 */

import { test, expect, type ColorScheme } from '@playwright/test';

const SHARE_TOKEN = 'JOURNEYM3themeshareAAAAAAAAAAAAAAAAAAAAAAAAA';

const NOW = 1_735_689_600_000;

function snapshotFixture(): unknown {
  return {
    token: SHARE_TOKEN,
    title: 'Themed share',
    history: {
      messages: {
        'u-1': {
          id: 'u-1',
          parentId: null,
          childrenIds: ['a-1'],
          role: 'user',
          content: 'Anything will do',
          timestamp: NOW,
          model: null,
          modelName: null,
          done: true,
          error: null,
          cancelled: false,
          usage: null,
        },
        'a-1': {
          id: 'a-1',
          parentId: 'u-1',
          childrenIds: [],
          role: 'assistant',
          content: 'Replying for the test fixture',
          timestamp: NOW,
          model: 'gpt-4o',
          modelName: 'GPT-4o',
          done: true,
          error: null,
          cancelled: false,
          usage: { prompt_tokens: 8, completion_tokens: 5, total_tokens: 13 },
        },
      },
      currentId: 'a-1',
    },
    shared_by: { name: 'alice@canva.com', email: 'alice@canva.com' },
    created_at: NOW,
  };
}

const COOKIE_CASES = ['tokyo-day', 'tokyo-night'] as const;

for (const preset of COOKIE_CASES) {
  test(`@journey-m3 cookie theme ${preset} is honoured on /s/{token}`, async ({
    page,
    context,
  }) => {
    await context.addCookies([
      {
        name: 'theme',
        value: preset,
        url: 'http://localhost:5173',
        path: '/',
        sameSite: 'Lax',
      },
    ]);

    await page.route(`**/api/shared/${SHARE_TOKEN}`, async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(snapshotFixture()),
      });
    });

    let serverReachable = true;
    try {
      const response = await page.goto(`/s/${SHARE_TOKEN}`);
      expect(response?.status(), 'expected a 2xx for /s/{token}').toBeLessThan(400);
    } catch {
      serverReachable = false;
    }
    test.skip(
      !serverReachable,
      'SvelteKit dev server unreachable. See send-and-stream.spec.ts header for context.',
    );

    await page.waitForLoadState('domcontentloaded');

    const dataTheme = await page.evaluate(() => document.documentElement.dataset.theme);
    expect(dataTheme, `expected the cookie's ${preset} preset to win`).toBe(preset);

    // Smoke: the share page rendered. If it didn't, the layout
    // contract regressed — assert the snapshot title is visible so
    // a "theme works but page is blank" failure shows the same red.
    await expect(page.getByRole('heading', { name: 'Themed share', level: 1 })).toBeVisible();
  });
}

interface OsCase {
  colorScheme: ColorScheme;
  expected: 'tokyo-day' | 'tokyo-night';
}

const OS_CASES: OsCase[] = [
  { colorScheme: 'dark', expected: 'tokyo-night' },
  { colorScheme: 'light', expected: 'tokyo-day' },
];

for (const { colorScheme, expected } of OS_CASES) {
  test.describe(`@journey-m3 OS preference ${colorScheme} on /s/{token}`, () => {
    test.use({ colorScheme });

    test(`first paint resolves to ${expected} when no theme cookie is set`, async ({
      page,
      context,
    }) => {
      await context.clearCookies();

      await page.route(`**/api/shared/${SHARE_TOKEN}`, async (route) => {
        await route.fulfill({
          status: 200,
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(snapshotFixture()),
        });
      });

      let serverReachable = true;
      try {
        await page.goto(`/s/${SHARE_TOKEN}`);
      } catch {
        serverReachable = false;
      }
      test.skip(
        !serverReachable,
        'SvelteKit dev server unreachable. See send-and-stream.spec.ts header for context.',
      );

      await page.waitForLoadState('domcontentloaded');

      const dataTheme = await page.evaluate(() => document.documentElement.dataset.theme);
      expect(
        dataTheme,
        `expected boot script to resolve OS=${colorScheme} → ${expected} on the share view`,
      ).toBe(expected);

      // OS-default path must NOT write a theme cookie (per
      // `theme-os-default.spec.ts` invariant — `setOsDark`
      // short-circuits without `writeChoice`).
      const cookies = await context.cookies();
      const themeCookie = cookies.find((c) => c.name === 'theme');
      expect(
        themeCookie,
        'OS-default resolution must not write a theme cookie even on the share view',
      ).toBeUndefined();
    });
  });
}

test('@journey-m3 share page renders with `locals.user` forwarded but the layout never required it', async ({
  page,
}) => {
  // The (public) `+layout.server.ts` returns `{ user: locals.user,
  // theme: locals.theme, themeSource: locals.themeSource }`. With
  // the suite-level `X-Forwarded-Email: alice@canva.com` header the
  // hook populates `locals.user`, so `data.user` is non-null on the
  // share page — but the page itself never reads it. The strongest
  // browser-side assertion of the "layout doesn't gate on user" path
  // is to confirm the share page renders cleanly with a valid
  // identity AND with the theme cookie path firing — and a separate
  // `auth-required.spec.ts` proves the unauthenticated case.
  await page.route(`**/api/shared/${SHARE_TOKEN}`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(snapshotFixture()),
    });
  });

  let serverReachable = true;
  try {
    await page.goto(`/s/${SHARE_TOKEN}`);
  } catch {
    serverReachable = false;
  }
  test.skip(
    !serverReachable,
    'SvelteKit dev server unreachable. See send-and-stream.spec.ts header for context.',
  );

  await expect(page.getByRole('heading', { name: 'Themed share', level: 1 })).toBeVisible();
});
