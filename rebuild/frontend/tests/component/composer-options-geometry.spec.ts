/**
 * Geometric invariants for `MessageInput.svelte` with the `+ Options`
 * disclosure expanded.
 *
 * Pinned by `rebuild/docs/best-practises/visual-qa-best-practises.md`
 * § Layer B (geometric invariants) and referenced from the M2 acceptance
 * criteria in `rebuild/docs/plans/m2-conversations.md` § Acceptance
 * criteria ("Every user journey in § User journeys has (a) a visual
 * baseline, (b) a geometric-invariant spec, (c) a signed-off impeccable
 * design review").
 *
 * Why Component Testing, not E2E
 * ------------------------------
 * The bug is purely geometric: at `≥ sm` (640 px) the composer's
 * advanced-knobs `<div>` lays out as `grid-cols-[120px_1fr]`, but the
 * first column holds a flex row with `<span>Temperature</span> + <input
 * class="w-20">` whose intrinsic width is ~172 px and spills into column
 * 2, colliding with the `<span>System</span>` label sitting there.
 *
 * This is a single-component concern — no routing, no SSR, no backend.
 * CT mounts the real component against the real Tailwind CSS at a
 * deterministic viewport, which is the cheapest reliable way to catch it.
 * E2E `@journey-m{n}` specs are reserved for multi-surface transitions
 * that CT cannot express.
 *
 * This spec is the template every other component-level geometric
 * invariant follows: mount the harness → drive UI → assert via the
 * helpers in `../e2e/helpers/geometry.ts`. CT uses `@playwright/
 * experimental-ct-svelte` which exposes the same `expect` / locator API
 * as the full Playwright runner, so the helpers work verbatim.
 */

import { test, expect } from '@playwright/experimental-ct-svelte';

import MessageInputHarness from './MessageInputHarness.svelte';
import {
  expectContains,
  expectMinContentWidth,
  expectNoOverlap,
  expectNoTextClipping,
} from '../e2e/helpers/geometry';

// Deterministic viewports. The `sm:grid-cols-[120px_1fr]` breakpoint
// activates at ≥ 640 px, which is where the bug manifests. Narrow-viewport
// behaviour (`grid-cols-1`, rows stacked) is covered separately so a
// future refactor can't break the mobile path while the desktop one
// stays green.
const DESKTOP_VIEWPORT = { width: 1280, height: 720 } as const;
const NARROW_VIEWPORT = { width: 520, height: 720 } as const;

test.describe('MessageInput — Options panel geometric invariants (desktop viewport)', () => {
  test.use({ viewport: DESKTOP_VIEWPORT });

  test("open Options → Temperature and System don't collide, stay inside the composer, nothing is clipped", async ({
    mount,
    page,
  }) => {
    const component = await mount(MessageInputHarness, {
      props: { initialModel: 'gpt-4o' },
    });

    // Type a character so `canSend` is true and the send button lights up
    // — matches the state a user actually reaches before opening Options.
    const composer = component.getByRole('textbox', { name: 'Compose a message' });
    await composer.fill('hello');

    // Expand the advanced knobs. The button label flips `+ Options` →
    // `− Options` on click; we target via accessible name so the spec
    // survives copy changes.
    const optionsBtn = component.getByRole('button', { name: /\+ Options/ });
    await expect(optionsBtn).toBeVisible();
    await optionsBtn.click();

    const tempInput = component.getByLabel('Temperature');
    const systemInput = component.getByLabel('System');
    await expect(tempInput).toBeVisible();
    await expect(systemInput).toBeVisible();

    // -- Invariant 1: Temperature and System don't overlap. ---------------
    // This is the whole reason the spec exists. If the flex row inside
    // the grid's first column spills past 120 px, the number input
    // collides with the System label's rectangle.
    await expectNoOverlap(tempInput, systemInput, ['Temperature input', 'System textarea']);

    // Also check the literal `<span>System</span>` label — the label span
    // is what the user sees overlapped in the screenshot, not the
    // textarea rectangle.
    const systemLabel = component
      .locator('label')
      .filter({ hasText: 'System' })
      .locator('span')
      .first();
    await expectNoOverlap(tempInput, systemLabel, ['Temperature input', 'System label']);

    // -- Invariant 2: both controls stay inside the composer card. --------
    // The `MessageInput.svelte` component's root element IS the `<form>`.
    // CT wraps the mount in an `#root > internal:control=component` anchor,
    // so `component.locator('form')` searches for a *nested* form and
    // misses; we reach the form directly at the page level instead.
    const composerCard = page.locator('form').first();
    await expectContains(composerCard, tempInput, ['composer card', 'Temperature input']);
    await expectContains(composerCard, systemInput, ['composer card', 'System textarea']);

    // -- Invariant 3: Temperature input has enough width for `default`. ---
    // Placeholder is `"default"` at `text-xs` (~12 px), 7 chars × ~6 px +
    // 16 px padding = ~56 px of content-box. The helper subtracts the
    // Chromium number-stepper chrome for `type="number"` inputs so the
    // assertion reflects actual text space.
    await expectMinContentWidth(tempInput, 56, 'Temperature input');

    // -- Invariant 4: no text clipping on the label spans. ----------------
    // Catches `"default"` → `"defa"` truncation at the CSS level, and
    // protects against future i18n regressions where "Temperature" gets
    // translated to a longer word and starts hiding behind its sibling.
    for (const label of ['Temperature', 'System']) {
      const span = component.locator('label').filter({ hasText: label }).locator('span').first();
      await expectNoTextClipping(span, `${label} label text`);
    }
  });
});

test.describe('MessageInput — Options panel geometric invariants (narrow viewport)', () => {
  test.use({ viewport: NARROW_VIEWPORT });

  test('grid stacks, same invariants hold', async ({ mount, page }) => {
    // Same invariants on the `grid-cols-1` branch — regression guard so
    // a future refactor to the disclosure layout can't quietly break
    // the mobile path while the desktop one stays green.
    const component = await mount(MessageInputHarness, {
      props: { initialModel: 'gpt-4o' },
    });

    await component.getByRole('textbox', { name: 'Compose a message' }).fill('hi');
    await component.getByRole('button', { name: /\+ Options/ }).click();

    const tempInput = component.getByLabel('Temperature');
    const systemInput = component.getByLabel('System');
    await expect(tempInput).toBeVisible();
    await expect(systemInput).toBeVisible();

    const composerCard = page.locator('form').first();
    await expectContains(composerCard, tempInput, ['composer card', 'Temperature input']);
    await expectContains(composerCard, systemInput, ['composer card', 'System textarea']);
    await expectMinContentWidth(tempInput, 56, 'Temperature input');
    // At narrow viewports the two rows stack — no-overlap is trivially
    // true (vertical gap ≥ `gap-3` = 12 px). We still assert so a
    // future "same row at all widths" refactor surfaces.
    await expectNoOverlap(tempInput, systemInput, ['Temperature input', 'System textarea']);
  });
});
