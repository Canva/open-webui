/**
 * Geometric invariants for the M3 public share view at `/s/{token}`.
 *
 * Pinned by `rebuild/docs/best-practises/visual-qa-best-practises.md`
 * § Layer B (geometric invariants), and called out by name in
 * `rebuild/docs/plans/m3-sharing.md` § User journeys row 4 (the
 * "no composer / model-selector / regen affordances" negative-
 * containment check, plus the read-only thread fitting inside the
 * public-layout shell).
 *
 * Why Component Testing, not E2E
 * ------------------------------
 * The share view is a single route page with a small amount of
 * markup wrapping `MessageList` in `readonly` mode. The invariants
 * here are about what is and isn't on the surface (negative
 * containment) and the shape of the read-only column. CT mounts
 * the harness mirror of the route's markup against the real
 * Tailwind cascade; an E2E would add the cost of booting the Kit
 * dev server and a backend round-trip without strengthening any
 * assertion.
 */

import { test, expect } from '@playwright/experimental-ct-svelte';

import SharedViewHarness from './SharedViewHarness.svelte';
import { defaultSnapshotFixture, longHistoryFixture } from './share-fixtures';
import { expectContains, expectNoTextClipping } from '../e2e/helpers/geometry';

const DESKTOP_VIEWPORT = { width: 1280, height: 720 } as const;
const NARROW_VIEWPORT = { width: 520, height: 720 } as const;

test.describe('SharedView — geometric invariants (desktop viewport)', () => {
  test.use({ viewport: DESKTOP_VIEWPORT });

  test('negative containment: no composer, no model-selector, no regen affordances render', async ({
    mount,
  }) => {
    const component = await mount(SharedViewHarness, {
      props: { snapshot: defaultSnapshotFixture() },
    });

    // The compose textbox is the M2 user-input affordance — explicitly
    // suppressed on the share view per the M3 plan.
    await expect(component.getByRole('textbox', { name: 'Compose a message' })).toHaveCount(0);
    // Model selector buttons (in M2 they appear as `aria-label` / role
    // matching `Model`). The share view never instantiates one.
    await expect(component.getByRole('button', { name: /Model/ })).toHaveCount(0);
    // Per-message regen / copy / retry buttons are suppressed by the
    // readonly mode on `Message.svelte`.
    await expect(component.getByRole('button', { name: 'Regenerate message' })).toHaveCount(0);
    await expect(component.getByRole('button', { name: 'Copy message' })).toHaveCount(0);
    await expect(component.getByRole('button', { name: 'Retry' })).toHaveCount(0);
  });

  test("the thread column matches the M2 conversation view's max-width", async ({ mount }) => {
    const component = await mount(SharedViewHarness, {
      props: { snapshot: defaultSnapshotFixture() },
    });

    // The route wraps the thread in `<article class="... max-w-3xl ...">`
    // — same clamp the M2 ConversationView uses. Assert via
    // `boundingBox` (Tailwind's `max-w-3xl` resolves to 48rem = 768 px).
    const article = component.locator('article').first();
    const box = await article.boundingBox();
    expect(box, 'thread article boundingBox').not.toBeNull();
    // Allow a small slack for browser sub-pixel rounding; reject any
    // explosion past `max-w-3xl + 1px`.
    expect(box!.width).toBeLessThanOrEqual(768 + 1);
  });

  test('header title and subline stay inside the article column', async ({ mount }) => {
    const component = await mount(SharedViewHarness, {
      props: {
        snapshot: defaultSnapshotFixture({
          title: 'Refactor draft',
          shared_by: { name: 'Alice Example', email: 'alice@canva.com' },
        }),
      },
    });

    const article = component.locator('article').first();
    const heading = component.getByRole('heading', { level: 1 });
    const subline = component.getByText(/Shared by Alice Example/);

    await expectContains(article, heading, ['thread column', 'Shared chat title']);
    await expectContains(article, subline, ['thread column', 'shared-by subline']);
  });

  test('long history (100 pairs) renders a thread that stays within the column', async ({
    mount,
  }) => {
    // A long thread shouldn't blow out the column width — the
    // virtualisation path keeps painting cheap, but the layout
    // contract is the same.
    test.setTimeout(60_000);
    const component = await mount(SharedViewHarness, {
      props: { snapshot: longHistoryFixture(100) },
    });

    const article = component.locator('article').first();
    const box = await article.boundingBox();
    expect(box!.width).toBeLessThanOrEqual(768 + 1);
  });
});

test.describe('SharedView — geometric invariants (narrow viewport)', () => {
  test.use({ viewport: NARROW_VIEWPORT });

  test('header title is not text-clipped at narrow widths', async ({ mount }) => {
    const component = await mount(SharedViewHarness, {
      props: {
        snapshot: defaultSnapshotFixture({
          title: 'A reasonably long shared-chat title that exercises wrap',
        }),
      },
    });

    // `expectNoTextClipping` checks `scrollWidth <= clientWidth`,
    // which catches a regression where the heading gets a fixed
    // width and starts clipping. The heading allows wrapping by
    // default, so a normal title fits even at 520 px.
    const heading = component.getByRole('heading', { level: 1 });
    await expectNoTextClipping(heading, 'Shared chat title');
  });

  test('dead-link panel stays inside the viewport', async ({ mount }) => {
    const component = await mount(SharedViewHarness, { props: { snapshot: null } });

    const heading = component.getByRole('heading', { name: 'Shared chat unavailable' });
    // `component` is the harness's outermost wrapper (the
    // `min-h-svh` div) — that's the closest visible-and-rect-able
    // viewport proxy. (`page.locator('html')` is not reliably
    // `toBeVisible` inside the CT iframe.)
    await expectContains(component, heading, ['shared-view shell', 'dead-link heading']);
  });
});
