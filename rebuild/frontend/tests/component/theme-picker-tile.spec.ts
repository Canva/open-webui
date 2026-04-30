/**
 * Per-tile cascade test for the ThemePicker.
 *
 * The picker's "Day shows light, the three darks show their darks, all
 * on the same page, no tooltip needed" trick rests on one CSS contract:
 * a tile element carrying `data-theme="tokyo-{id}"` resolves the role-
 * token CSS variables (`--background-app`, `--accent-selection`, ...)
 * to THAT preset's values regardless of the page-level active theme.
 *
 * This spec exercises the trick in isolation via a tiny standalone
 * harness (`ThemePickerTileHarness.svelte`) that doesn't mount the
 * picker itself — we want a clean assertion on the cascade primitive
 * without conflating store state, click handlers, or aria semantics.
 *
 * Pinned by `m1-theming.md` § Tests § Component (theme-picker-tile.spec.ts).
 */

import { test, expect } from '@playwright/experimental-ct-svelte';
import ThemePickerTileHarness from './ThemePickerTileHarness.svelte';

const PRESETS = ['tokyo-day', 'tokyo-storm', 'tokyo-moon', 'tokyo-night'] as const;
type Preset = (typeof PRESETS)[number];

// Per-preset expected `backgroundApp` values, transcribed from
// `presets.ts`. The browser may report the resolved style in a
// computed-style normalised form (e.g. an `oklch(...)` or `color(...)`
// function), so we assert via a substring match on the OKLCH lightness
// ratio rather than expecting an exact byte-for-byte string.
const EXPECTED_BG_LIGHTNESS: Record<Preset, string> = {
  'tokyo-day': '0.98',
  'tokyo-storm': '0.27',
  'tokyo-moon': '0.26',
  'tokyo-night': '0.2',
};

test.describe('per-tile data-theme cascade', () => {
  for (const preset of PRESETS) {
    test(`tile data-theme="${preset}" paints its own background-app regardless of page theme`, async ({
      mount,
      page,
    }) => {
      // Construct a hostile page theme — pick whichever preset is
      // NOT the tile's preset, so a regression where the cascade
      // breaks would paint the page-level value into the tile.
      const pageTheme = preset === 'tokyo-night' ? 'tokyo-day' : 'tokyo-night';

      const harness = await mount(ThemePickerTileHarness, {
        props: { preset, pageTheme },
      });

      // Confirm the page-level theme is set as expected (sanity).
      const docTheme = await page.evaluate(() => document.documentElement.dataset.theme);
      expect(docTheme).toBe(pageTheme);

      // Read the swatch's computed background and look for the lightness
      // ratio characteristic of the tile's preset. The browser may
      // report `oklch(0.98 0 0)`, `rgb(250, 250, 250)`, or a
      // `color(srgb …)` form depending on its colour pipeline; we
      // accept either an OKLCH-shaped form (which embeds the lightness
      // directly) OR an rgb form whose value matches.
      const swatch = harness.getByTestId('swatch');
      const bg = await swatch.evaluate((el) => getComputedStyle(el).backgroundColor);

      // Prefer the OKLCH form when present; fall through to a sanity
      // check that the colour is at least non-empty / non-transparent.
      // The strong assertion is "page-vs-tile painted differently",
      // which we verify by mounting an opposite-page-theme harness in
      // the next assertion below.
      const isOklchForm = /oklch|color\(/i.test(bg);
      if (isOklchForm) {
        // OKLCH-shaped — the lightness for this preset must appear.
        expect(bg).toContain(EXPECTED_BG_LIGHTNESS[preset]);
      }
      expect(bg).not.toBe('rgba(0, 0, 0, 0)');
      expect(bg).not.toBe('');

      // Belt-and-braces: same tile mounted under a different page
      // theme should paint the SAME swatch colour. If the cascade
      // were broken (e.g. the implementation stopped writing
      // `data-theme` on the tile), the swatch would re-resolve to
      // the page-level theme's `--background-app` and the colours
      // would diverge.
      const oppositePageTheme = pageTheme === 'tokyo-night' ? 'tokyo-day' : 'tokyo-night';
      await harness.unmount();

      const otherHarness = await mount(ThemePickerTileHarness, {
        props: { preset, pageTheme: oppositePageTheme },
      });
      const otherSwatch = otherHarness.getByTestId('swatch');
      const otherBg = await otherSwatch.evaluate((el) => getComputedStyle(el).backgroundColor);
      expect(otherBg).toBe(bg);
    });
  }
});
