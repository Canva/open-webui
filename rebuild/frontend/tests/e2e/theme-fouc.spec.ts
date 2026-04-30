/**
 * Theme FOUC E2E — the load-bearing M1 acceptance test.
 *
 * Pinned by `rebuild/docs/plans/m1-theming.md` § Tests § E2E
 * (theme-fouc.spec.ts) AND § Acceptance criteria ("no flash to tokyo-
 * night when the cookie says otherwise").
 *
 * Mechanic:
 *
 *   1. Pre-set a `theme=tokyo-{id}` cookie on the BrowserContext via
 *      `context.addCookies(...)` so the SvelteKit `hooks.server.ts`
 *      `theme populate` block reads it and emits `<html data-theme=
 *      "tokyo-{id}">` plus the corresponding `BOOT_SCRIPT_SOURCE`
 *      inlined in `%sveltekit.head%`.
 *
 *   2. Inject a `MutationObserver` via `page.addInitScript(...)` BEFORE
 *      the page navigates, recording every `data-theme` attribute value
 *      the documentElement ever holds during load into `window.
 *      __themeHistory: string[]`. Init scripts run in the new document
 *      context as the very first script, before the inline boot IIFE,
 *      so the observer is live for the boot script's mutation.
 *
 *   3. After navigation settles, read `window.__themeHistory` and
 *      assert every entry is the cookie's preset id. A transient
 *      `null` (cookie miss surfaced as `data-theme=""` or removed
 *      attribute) or a flash through `tokyo-night` (the brand fallback
 *      kicking in before the cookie path resolves) would surface as a
 *      mismatched entry.
 *
 * Parametrised over all four presets so a regression that only
 * affects light themes (e.g. boot script's matchMedia branch
 * mistakenly running before the cookie tier) is caught.
 *
 * Inherits the default `extraHTTPHeaders: { X-Forwarded-Email:
 * alice@canva.com }` from `playwright.config.ts` — every theme
 * navigation runs against an authenticated `(app)` layout, which is
 * the path real users hit.
 */

import { test, expect } from '@playwright/test';

const PRESETS = ['tokyo-day', 'tokyo-storm', 'tokyo-moon', 'tokyo-night'] as const;

// `page.addInitScript` runs before the inline boot script (and before
// the runtime bundle). The observer attaches to documentElement and
// records every attribute mutation on `data-theme`, including the
// "removed" event so a transient null is visible. The history is
// stashed on `window` so the test can read it back via `page.evaluate`
// after navigation.
const INIT_OBSERVER_SOURCE = `
  (() => {
    window.__themeHistory = [];
    const recordCurrent = () => {
      const el = document.documentElement;
      if (!el) {
        return;
      }
      window.__themeHistory.push(el.getAttribute('data-theme'));
    };
    recordCurrent();
    const observer = new MutationObserver((records) => {
      for (const r of records) {
        if (r.attributeName === 'data-theme') {
          window.__themeHistory.push(document.documentElement.getAttribute('data-theme'));
        }
      }
    });
    if (document.documentElement) {
      observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme'],
      });
    } else {
      document.addEventListener('DOMContentLoaded', () => {
        observer.observe(document.documentElement, {
          attributes: true,
          attributeFilter: ['data-theme'],
        });
      });
    }
  })();
`;

for (const preset of PRESETS) {
  test(`no FOUC when the theme cookie says ${preset}`, async ({ page, context }) => {
    // Cookie attribute parity with what `writeChoice` sets in
    // production: `Path=/`, `SameSite=Lax`, `httpOnly: false` (the
    // store mutates from JS land).
    await context.addCookies([
      {
        name: 'theme',
        value: preset,
        url: 'http://localhost:5173',
        path: '/',
        sameSite: 'Lax',
      },
    ]);

    await page.addInitScript(INIT_OBSERVER_SOURCE);

    const response = await page.goto('/');
    expect(response?.status(), 'expected a 2xx for /').toBeLessThan(400);

    // Wait for hydration so the matchMedia $effect has had a chance to
    // re-resolve (it should NOT change anything because the cookie
    // path resolves themeSource to 'explicit'); poll the history a few
    // times to catch any post-hydration flicker too.
    await page.waitForLoadState('domcontentloaded');
    await page.waitForLoadState('networkidle');

    const history: (string | null)[] = await page.evaluate(
      () => (window as unknown as { __themeHistory: (string | null)[] }).__themeHistory,
    );

    // Every observed value must equal the cookie's preset id. A
    // transient null, an empty string, or any other preset would be a
    // FOUC the cookie path was supposed to prevent.
    expect(history.length, 'expected at least one observed data-theme value').toBeGreaterThan(0);
    for (const value of history) {
      expect(
        value,
        `unexpected ${JSON.stringify(value)} in __themeHistory (full: ${JSON.stringify(history)}); ` +
          `cookie path should keep the value at ${preset} for the entire load`,
      ).toBe(preset);
    }

    // And the final live value matches.
    const finalTheme = await page.evaluate(() => document.documentElement.dataset.theme);
    expect(finalTheme).toBe(preset);
  });
}
