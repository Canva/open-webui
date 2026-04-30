/**
 * OS-default theme E2E.
 *
 * Pinned by `rebuild/docs/plans/m1-theming.md` § Tests § E2E
 * (theme-os-default.spec.ts) AND § Acceptance criteria ("OS preference
 * resolves correctly when there is no cookie / no localStorage").
 *
 * Three sub-cases driven via Playwright's `colorScheme` per-test
 * override (`test.use({ colorScheme: ... })`):
 *
 *   - dark           → first paint is `tokyo-night`.
 *   - light          → first paint is `tokyo-day`.
 *   - no-preference  → first paint is `tokyo-night` (brand-canonical
 *                       fallback when the matchMedia query reports no
 *                       preference).
 *
 * Each sub-test opens a fresh BrowserContext (no cookie, no
 * localStorage), navigates to `/`, and asserts the document-level
 * `data-theme` attribute set by the inline boot script. This is the
 * strongest evidence that the boot script's matchMedia tier resolves
 * correctly — the server fallback is always `tokyo-night` regardless
 * of OS, so any deviation from `tokyo-night` here is the boot script
 * doing its job.
 */

import { test, expect, type ColorScheme } from '@playwright/test';

interface OsDefaultCase {
  colorScheme: ColorScheme;
  expected: 'tokyo-night' | 'tokyo-day';
  rationale: string;
}

const CASES: OsDefaultCase[] = [
  {
    colorScheme: 'dark',
    expected: 'tokyo-night',
    rationale: "matchMedia('(prefers-color-scheme: dark)').matches === true → tokyo-night",
  },
  {
    colorScheme: 'light',
    expected: 'tokyo-day',
    rationale: "matchMedia('(prefers-color-scheme: dark)').matches === false → tokyo-day",
  },
  {
    colorScheme: 'no-preference',
    expected: 'tokyo-night',
    rationale: 'matchMedia returns false for "no preference" → boot fallback to tokyo-night',
  },
];

for (const { colorScheme, expected, rationale } of CASES) {
  test.describe(`OS preference: ${colorScheme}`, () => {
    test.use({ colorScheme });

    test(`first paint resolves to ${expected} (${rationale})`, async ({ page, context }) => {
      // Pre-flight: belt-and-braces. The dispatch context is fresh
      // per-test, but defensively clear cookies + localStorage so a
      // cassette run can't leak state across cases.
      await context.clearCookies();

      await page.goto('/');

      // Wait for hydration to settle so the matchMedia $effect has had
      // a chance to fire; the boot script wins the FOUC race but the
      // $effect is the durable signal.
      await page.waitForLoadState('domcontentloaded');

      const dataTheme = await page.evaluate(() => document.documentElement.dataset.theme);
      expect(dataTheme, `expected boot script to resolve OS=${colorScheme} → ${expected}`).toBe(
        expected,
      );

      // Sanity: no cookie was written by the OS-default path (the
      // store should NOT persist OS-driven resolution; that's what the
      // `setOsDark` short-circuit guards against — it only updates
      // `current` when the user has NOT made an explicit choice, and
      // does so without calling `writeChoice`).
      const cookies = await context.cookies();
      const themeCookie = cookies.find((c) => c.name === 'theme');
      expect(themeCookie, 'OS-default resolution must not write a theme cookie').toBeUndefined();
    });
  });
}
