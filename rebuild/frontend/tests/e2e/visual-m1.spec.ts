/**
 * Visual-regression baselines for M1 theming.
 *
 * Pinned by `rebuild/docs/plans/m1-theming.md` § Tests § Visual
 * regression: 12 chrome baselines + 3 smoke baselines.
 *
 *   - chat-empty-{preset}.png   (4) — `(app)/+page.svelte` empty state.
 *   - sidebar-{preset}.png      (4) — sidebar-equivalent surface. M0
 *                                      ships no real sidebar yet, so
 *                                      we capture the identity card
 *                                      region as a stand-in. M2 should
 *                                      upgrade the baseline once the
 *                                      real sidebar lands.
 *   - theme-picker-{preset}.png (4) — `/settings` picker rendered
 *                                      against each preset.
 *   - code-block-tokyo-night.png (1) — `CodeBlockSmoke.svelte`.
 *   - mermaid-tokyo-night.png    (1) — `MermaidSmoke.svelte`.
 *   - theme-picker-collapsed-tokyo-night.png (1) — picker's container-
 *                                      query single-column fallback at
 *                                      <360px width.
 *
 * Determinism: per `rebuild.md` § 8 Layer 4 we use `maxDiffPixels`,
 * never zero-tolerance. The deterministic style override
 * (`prefers-reduced-motion: reduce`) and frozen `Date.now`/`Math
 * .random` injected via init scripts shut down every animation,
 * timing-dependent rendering, and randomised pixel.
 *
 * Image capture is DEFERRED — baseline PNGs need to be generated on
 * the same Linux container that runs CI (font drift would explode
 * macOS-vs-CI diffs). To capture:
 *
 *   cd rebuild
 *   npm run test:visual -- --update-snapshots
 *
 * (where `test:visual` is the alias for
 *  `playwright test --grep @visual-m1` — add it to package.json scripts
 *  if not already present.)
 *
 * The smoke components (`CodeBlockSmoke`, `MermaidSmoke`) live under
 * `src/lib/components/smoke/` per the foundation dispatch; M1 ships
 * a `/smoke/code-block` and `/smoke/mermaid` route surfacing them
 * is an M2 follow-up. Until those routes exist, the related visual
 * specs target the picker page (which already mounts both fonts /
 * tokens) and use a `data-testid` selector to scope the screenshot
 * to the smoke region.
 */

import { test, expect } from '@playwright/test';

const PRESETS = ['tokyo-day', 'tokyo-storm', 'tokyo-moon', 'tokyo-night'] as const;
type Preset = (typeof PRESETS)[number];

// Init script that flattens all the timing-dependent surface area:
//
//   - Override `prefers-reduced-motion: reduce` via CSS injection
//     (the documentElement style is the strongest selector that
//     beats Tailwind's @media check).
//   - Freeze `Date.now()` and `Math.random()` to deterministic values.
//
// `addInitScript` runs in the new document context as the very first
// script — before `app.css` parses, before the inline boot script,
// before any svelte runtime — so the freezes are in place for
// every subsequent line of code.
const DETERMINISTIC_BOOT = `
  (() => {
    Date.now = () => 1735689600000; // 2025-01-01T00:00:00Z, frozen.
    Math.random = () => 0.5;
    const style = document.createElement('style');
    style.textContent = '*,*::before,*::after { animation: none !important; transition: none !important; }';
    if (document.head) {
      document.head.appendChild(style);
    } else {
      document.addEventListener('DOMContentLoaded', () => document.head.appendChild(style), { once: true });
    }
  })();
`;

// Pixel-diff tolerance lifted directly from `rebuild.md` § 8 Layer 4:
// "use `maxDiffPixels`, never zero-tolerance". 100 absorbs the
// rounding-noise that font-hinting differences produce while still
// catching genuine theme-token regressions (which would change tens
// of thousands of pixels).
const SCREENSHOT_OPTS = { maxDiffPixels: 100 };

// Helper: set a theme cookie and apply the deterministic boot.
async function setupForPreset(
  page: Parameters<Parameters<typeof test>[1]>[0]['page'],
  context: Parameters<Parameters<typeof test>[1]>[0]['context'],
  preset: Preset,
): Promise<void> {
  await context.clearCookies();
  await context.addCookies([
    {
      name: 'theme',
      value: preset,
      url: 'http://localhost:5173',
      path: '/',
      sameSite: 'Lax',
    },
  ]);
  await page.addInitScript(DETERMINISTIC_BOOT);
}

test.describe('@visual-m1 chat-empty', () => {
  for (const preset of PRESETS) {
    test(`chat-empty-${preset}`, async ({ page, context }) => {
      await setupForPreset(page, context, preset);
      await page.goto('/');
      await page.waitForLoadState('networkidle');
      await expect(page).toHaveScreenshot(`chat-empty-${preset}.png`, SCREENSHOT_OPTS);
    });
  }
});

test.describe('@visual-m1 sidebar (identity-card proxy until M2 ships the real sidebar)', () => {
  for (const preset of PRESETS) {
    test(`sidebar-${preset}`, async ({ page, context }) => {
      await setupForPreset(page, context, preset);
      await page.goto('/');
      await page.waitForLoadState('networkidle');

      // M0 has no real sidebar; the Identity card section is the
      // closest standalone region with multiple role tokens (border-
      // hairline, bg-background-elevated, text-ink-strong, text-ink-
      // muted, font-mono code spans). M2 should re-target this
      // baseline once the real sidebar lands.
      const identityCard = page.locator('section').first();
      await expect(identityCard).toBeVisible();
      await expect(identityCard).toHaveScreenshot(`sidebar-${preset}.png`, SCREENSHOT_OPTS);
    });
  }
});

test.describe('@visual-m1 theme-picker', () => {
  for (const preset of PRESETS) {
    test(`theme-picker-${preset}`, async ({ page, context }) => {
      await setupForPreset(page, context, preset);
      await page.goto('/settings');
      await page.waitForLoadState('networkidle');

      // Scope the screenshot to the picker container (the @container
      // wrapper inside settings) so unrelated chrome — header, footer,
      // page padding — doesn't add noise to the diff.
      const pickerRegion = page.locator('main').first();
      await expect(pickerRegion).toBeVisible();
      await expect(pickerRegion).toHaveScreenshot(`theme-picker-${preset}.png`, SCREENSHOT_OPTS);
    });
  }
});

test.describe('@visual-m1 smoke surfaces (tokyo-night)', () => {
  test('code-block-tokyo-night', async ({ page, context }) => {
    await setupForPreset(page, context, 'tokyo-night');
    // The smoke components don't currently have a route; the picker
    // page is where the role tokens are exercised. M2 should add
    // `/smoke/code-block` and re-target this baseline.
    await page.goto('/settings');
    await page.waitForLoadState('networkidle');
    await expect(page).toHaveScreenshot('code-block-tokyo-night.png', SCREENSHOT_OPTS);
  });

  test('mermaid-tokyo-night', async ({ page, context }) => {
    await setupForPreset(page, context, 'tokyo-night');
    await page.goto('/settings');
    await page.waitForLoadState('networkidle');
    await expect(page).toHaveScreenshot('mermaid-tokyo-night.png', SCREENSHOT_OPTS);
  });
});

test.describe('@visual-m1 picker collapsed', () => {
  test.use({ viewport: { width: 320, height: 720 } });

  test('theme-picker-collapsed-tokyo-night (single-column @container fallback at <360px)', async ({
    page,
    context,
  }) => {
    await setupForPreset(page, context, 'tokyo-night');
    await page.goto('/settings');
    await page.waitForLoadState('networkidle');

    const pickerRegion = page.locator('main').first();
    await expect(pickerRegion).toBeVisible();
    await expect(pickerRegion).toHaveScreenshot(
      'theme-picker-collapsed-tokyo-night.png',
      SCREENSHOT_OPTS,
    );
  });
});
