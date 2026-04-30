/**
 * Component-level driver for `ThemePicker.svelte`.
 *
 * Mounted via Playwright Component Testing inside a real Chromium —
 * jsdom can't faithfully simulate the matchMedia / cookie / localStorage
 * interplay this picker leans on. The harness (`ThemePickerHarness
 * .svelte`) constructs the per-request `ThemeStore`, provides it via
 * `setContext('theme', store)` per the app's production wiring, and
 * stashes the store on `window.__themeStore` so the spec can introspect
 * reactive state without DOM scraping.
 *
 * Asserts pinned by `m1-theming.md` § Tests § Component:
 *
 *   - All four presets: clicking each tile updates `document
 *     .documentElement.dataset.theme` within one frame.
 *   - Cookie + localStorage co-write in the same call.
 *   - "Match system" reset clears both surfaces AND re-resolves to the
 *     OS preference (via the harness-injected `osDark`).
 *   - Active tile renders with the `accent-selection` outline ring.
 *   - Keyboard navigation: Tab cycles tiles + reset button in order;
 *     Enter / Space activate; aria-pressed flips.
 *   - Only the active tile carries `aria-pressed="true"`.
 */

import { test, expect } from '@playwright/experimental-ct-svelte';
import ThemePickerHarness from './ThemePickerHarness.svelte';

// CT defaults to chromium; force `colorScheme: 'dark'` at the project
// level via `test.use` so the matchMedia path inside the picker (when
// the harness DOESN'T inject `osDark`) reports `dark`. The harness's
// explicit `osDark` prop overrides this for tests where we need the
// store's `_osDark` to be a specific value at construction time, but
// having both layers belt-and-braces means a future svelte-engineer
// rewrite that re-introduces a matchMedia call inside the picker
// doesn't silently change the OS preference under the test.
test.use({ colorScheme: 'dark' });

const PRESETS = ['tokyo-day', 'tokyo-storm', 'tokyo-moon', 'tokyo-night'] as const;

test.describe('ThemePicker — preset switching writes through both surfaces', () => {
  for (const preset of PRESETS) {
    test(`clicking the ${preset} tile updates dataset.theme + cookie + localStorage`, async ({
      mount,
      page,
    }) => {
      const harness = await mount(ThemePickerHarness, {
        props: { initial: 'tokyo-night', osDark: true },
      });

      const tile = harness.locator(`button[data-theme="${preset}"]`);
      await tile.click();

      // 1. dataset.theme reflects the click within a frame.
      await expect
        .poll(async () => page.evaluate(() => document.documentElement.dataset.theme))
        .toBe(preset);

      // 2. cookie carries the same value (URL-encoded; preset ids are
      // safe ASCII so the encoded form equals the literal id).
      const cookies = await page.context().cookies();
      const themeCookie = cookies.find((c) => c.name === 'theme');
      expect(themeCookie, 'expected a theme cookie after picker click').toBeDefined();
      expect(themeCookie!.value).toBe(preset);

      // 3. localStorage mirror.
      const stored = await page.evaluate(() => localStorage.getItem('theme'));
      expect(stored).toBe(preset);

      // 4. The store's reactive `current` matches.
      const current = await page.evaluate(
        () => (window as unknown as { __themeStore: { current: string } }).__themeStore.current,
      );
      expect(current).toBe(preset);
    });
  }
});

test.describe('ThemePicker — aria-pressed reflects the active tile', () => {
  test('only the active tile carries aria-pressed="true"', async ({ mount }) => {
    const harness = await mount(ThemePickerHarness, {
      props: { initial: 'tokyo-storm', initialSource: 'explicit', osDark: false },
    });

    for (const preset of PRESETS) {
      const tile = harness.locator(`button[data-theme="${preset}"]`);
      await expect(tile).toHaveAttribute(
        'aria-pressed',
        preset === 'tokyo-storm' ? 'true' : 'false',
      );
    }

    // Switching activates the new tile and deactivates the old one.
    await harness.locator('button[data-theme="tokyo-moon"]').click();
    for (const preset of PRESETS) {
      const tile = harness.locator(`button[data-theme="${preset}"]`);
      await expect(tile).toHaveAttribute(
        'aria-pressed',
        preset === 'tokyo-moon' ? 'true' : 'false',
      );
    }
  });
});

test.describe('ThemePicker — "Match system" reset', () => {
  test('reset button is hidden until the source becomes explicit', async ({ mount }) => {
    // Construct with the OS-fallback path (no initialSource, osDark=true
    // → resolves to tokyo-night which equals the heuristic OS pick → the
    // store flags source as 'os', not 'explicit').
    const harness = await mount(ThemePickerHarness, {
      props: { initial: 'tokyo-night', osDark: true },
    });

    await expect(harness.getByRole('button', { name: /match system/i })).toHaveCount(0);

    // Click a non-OS tile to make the source 'explicit'; the reset
    // button should appear.
    await harness.locator('button[data-theme="tokyo-storm"]').click();
    await expect(harness.getByRole('button', { name: /match system/i })).toBeVisible();
  });

  test('clicking reset clears both surfaces AND re-resolves to the OS preference', async ({
    mount,
    page,
  }) => {
    // OS pref is 'dark' → expected reset target is tokyo-night.
    const harness = await mount(ThemePickerHarness, {
      props: { initial: 'tokyo-storm', initialSource: 'explicit', osDark: true },
    });

    // Sanity: the picker starts in the explicit branch (tokyo-storm).
    await expect
      .poll(async () => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe('tokyo-storm');

    const reset = harness.getByRole('button', { name: /match system/i });
    await expect(reset).toBeVisible();
    await reset.click();

    // After reset the resolved theme is the OS preference (dark → tokyo-night).
    await expect
      .poll(async () => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe('tokyo-night');

    // The cookie was deleted (Max-Age=0 wipes it from the context).
    const cookies = await page.context().cookies();
    const themeCookie = cookies.find((c) => c.name === 'theme');
    expect(themeCookie, 'cookie should be cleared after reset').toBeUndefined();

    // localStorage was cleared.
    const stored = await page.evaluate(() => localStorage.getItem('theme'));
    expect(stored).toBeNull();

    // The store's source became non-'explicit' so the reset button
    // hides itself again.
    await expect(reset).toHaveCount(0);
  });
});

test.describe('ThemePicker — active tile carries the accent-selection ring', () => {
  test('the active tile has a non-transparent outline that resolves to its preset accent', async ({
    mount,
  }) => {
    const harness = await mount(ThemePickerHarness, {
      props: { initial: 'tokyo-night', initialSource: 'explicit', osDark: true },
    });

    const activeTile = harness.locator('button[data-theme="tokyo-night"]');
    await expect(activeTile).toHaveAttribute('aria-pressed', 'true');

    const outline = await activeTile.evaluate((el) => {
      const computed = getComputedStyle(el);
      return {
        outlineColor: computed.outlineColor,
        outlineStyle: computed.outlineStyle,
        outlineWidth: computed.outlineWidth,
      };
    });

    // Non-empty outline of any visible style + non-transparent colour
    // is the contract — the exact rgb() value comes from the resolved
    // accent-selection token (which depends on the chromium colour
    // pipeline and would be brittle to assert by literal value).
    //
    // CONTRACT BUG (surfaced by this assertion):
    //   The active tile is currently styled
    //   `... outline-none ... outline-accent-selection outline-2
    //   outline-offset-2`. Tailwind v4 generates:
    //     .outline-none { --tw-outline-style: none; outline-style: none; }
    //     .outline-2    { outline-style: var(--tw-outline-style); outline-width: 2px; }
    //   The base-class `outline-none` writes --tw-outline-style: none,
    //   which then carries through into the active state's outline-2
    //   resolution → outline-style ends up `none` and the ring is
    //   invisible. The picker needs to either drop `outline-none` from
    //   the base, replace `outline-2` with `outline outline-2` (which
    //   resets --tw-outline-style: solid), or add an explicit
    //   `outline-solid` to the active branch.
    //
    // Surface the actual computed values in the failure message so the
    // svelte-engineer fix has all the evidence in-hand.
    expect(
      outline.outlineStyle,
      `expected non-'none' outline-style on active tile (computed: ${JSON.stringify(outline)}); ` +
        "see CONTRACT BUG note in this test — `outline-none` on the picker's base class is " +
        "clobbering --tw-outline-style and the active tile's `outline-2` reads back 'none'.",
    ).not.toBe('none');
    expect(outline.outlineWidth).not.toBe('0px');
    expect(outline.outlineColor).not.toBe('rgba(0, 0, 0, 0)');
  });
});

test.describe('ThemePicker — keyboard navigation', () => {
  test('Tab cycles through tiles in canonical order, then reaches the reset button', async ({
    mount,
    page,
  }) => {
    // Need source='explicit' so the reset button is part of the tab
    // order; otherwise it's not rendered.
    const harness = await mount(ThemePickerHarness, {
      props: { initial: 'tokyo-storm', initialSource: 'explicit', osDark: true },
    });

    // The body is the focusable root; first Tab lands on the first tile.
    // The harness reference disappears after this evaluate; access via
    // the page locator to keep it in scope for the keyboard checks.
    void harness;
    await page.evaluate(() => document.body.focus());
    await page.keyboard.press('Tab');

    const orderedSelectors = [
      'button[data-theme="tokyo-day"]',
      'button[data-theme="tokyo-storm"]',
      'button[data-theme="tokyo-moon"]',
      'button[data-theme="tokyo-night"]',
    ];

    for (const sel of orderedSelectors) {
      // Each Tab moves focus forward through the picker DOM; assert the
      // currently-focused element matches the next selector in canonical
      // order.
      const matches = await page.evaluate((s) => document.activeElement?.matches(s) ?? false, sel);
      expect(matches, `expected focus on ${sel}`).toBe(true);
      await page.keyboard.press('Tab');
    }

    // The next Tab should land on the reset button.
    const onReset = await page.evaluate(
      () => document.activeElement?.getAttribute('aria-label') === 'Match system theme',
    );
    expect(onReset, 'expected focus on the Match system reset button').toBe(true);
  });

  test('Enter and Space both activate the focused tile', async ({ mount, page }) => {
    const harness = await mount(ThemePickerHarness, {
      props: { initial: 'tokyo-night', initialSource: 'explicit', osDark: true },
    });

    // Focus the Day tile and press Enter.
    await harness.locator('button[data-theme="tokyo-day"]').focus();
    await page.keyboard.press('Enter');
    await expect
      .poll(async () => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe('tokyo-day');
    await expect(harness.locator('button[data-theme="tokyo-day"]')).toHaveAttribute(
      'aria-pressed',
      'true',
    );

    // Focus Moon tile and press Space.
    await harness.locator('button[data-theme="tokyo-moon"]').focus();
    await page.keyboard.press('Space');
    await expect
      .poll(async () => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe('tokyo-moon');
    await expect(harness.locator('button[data-theme="tokyo-moon"]')).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  test('Shift+Tab moves focus backwards', async ({ mount, page }) => {
    const harness = await mount(ThemePickerHarness, {
      props: { initial: 'tokyo-night', initialSource: 'explicit', osDark: true },
    });

    // Focus the third tile, then shift+tab → second.
    await harness.locator('button[data-theme="tokyo-moon"]').focus();
    await page.keyboard.press('Shift+Tab');
    const onStorm = await page.evaluate(
      () => document.activeElement?.matches('button[data-theme="tokyo-storm"]') ?? false,
    );
    expect(onStorm, 'expected focus on tokyo-storm after Shift+Tab').toBe(true);
  });
});
