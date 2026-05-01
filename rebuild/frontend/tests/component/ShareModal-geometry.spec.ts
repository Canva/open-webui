/**
 * Geometric invariants for `lib/components/chat/ShareModal.svelte`
 * across the three phases (`not-shared`, `shared`, `stop-confirm`).
 *
 * Pinned by `rebuild/docs/best-practises/visual-qa-best-practises.md`
 * § Layer B (geometric invariants), and called out by name in
 * `rebuild/docs/plans/m3-sharing.md` § User journeys (rows 1, 2, 3
 * — the modal-not-shared, modal-shared, and stop-confirm states).
 *
 * Why Component Testing, not E2E
 * ------------------------------
 * The modal is a single component with three internal phases — no
 * routing, no SSR, no backend. CT mounts the real component against
 * the real Tailwind cascade at deterministic viewports, the cheapest
 * reliable way to catch overlap / clipping / overflow bugs at a
 * known size. Any future regression where the URL input shrinks
 * past the visible token, the action-row buttons collide, or the
 * panel overflows the viewport surfaces here on the first run.
 *
 * Spec shape mirrors `composer-options-geometry.spec.ts` byte-for-
 * byte: deterministic viewports as `const`, two top-level
 * `test.describe` blocks (one per viewport), each with `test.use`
 * pinning the viewport and a single `test(...)` driving the modal
 * along the user's exact path.
 */

import { test } from '@playwright/experimental-ct-svelte';

import ShareModalHarness from './ShareModalHarness.svelte';
import { TEST_TOKEN, defaultChatFixture } from './share-fixtures';
import {
  expectContains,
  expectMinContentWidth,
  expectNoOverlap,
  expectNoTextClipping,
} from '../e2e/helpers/geometry';

// Deterministic viewports. Desktop is the default M2 chat surface;
// narrow exercises the responsive path so a future refactor that
// over-tightens `max-w-md` doesn't quietly regress the small-screen
// path while the desktop one stays green. Both are top-level
// describes (NOT nested), per `visual-qa-best-practises.md` § Layer B
// — CT's viewport fixture doesn't always propagate cleanly into
// nested describes.
const DESKTOP_VIEWPORT = { width: 1280, height: 720 } as const;
const NARROW_VIEWPORT = { width: 520, height: 720 } as const;

// The URL input must hold a 43-char base64 token at the modal's
// `text-xs` font size. 200 px is the conservative floor — at the
// modal's `max-w-md` (28rem = 448 px) minus `p-7` (28 px each side)
// minus the Copy-link button's content, the input has ~280–300 px
// available. Setting the threshold below the worst-case avoids
// false-positives if the future Copy-link copy lengthens; setting
// it above 100 catches any regression where the input collapses
// (`flex-1` losing because of a sibling growing past its share).
const URL_INPUT_MIN_PX = 200;

test.describe('ShareModal — geometric invariants (desktop viewport)', () => {
  test.use({ viewport: DESKTOP_VIEWPORT });

  test('not-shared phase: modal stays inside viewport, action-row buttons do not collide, explainer is not clipped', async ({
    mount,
  }) => {
    const component = await mount(ShareModalHarness, {
      props: { chat: defaultChatFixture({ share_id: null }) },
    });

    const modal = component.getByRole('dialog');
    const generate = component.getByRole('button', { name: 'Generate share link' });
    const cancel = component.getByRole('button', { name: 'Cancel' });
    const explainer = component.getByText(/Sharing creates a snapshot/);
    // The backdrop (`role="presentation"`) is the harness's root —
    // `ShareModal.svelte`'s outermost element is the `fixed inset-0`
    // div, which CT mounts directly. So `component` itself IS the
    // backdrop and stands in as the viewport-spanning rect.
    // (`page.locator('html')` is not reliably `toBeVisible` inside
    // the CT iframe, hence the local proxy.)
    const backdrop = component;

    // Invariant 1: the modal stays inside the visible viewport
    // (backdrop spans `inset-0`).
    await expectContains(backdrop, modal, ['viewport (backdrop)', 'modal panel']);

    // Invariant 2: the two action-row buttons don't overlap each other.
    await expectNoOverlap(generate, cancel, ['Generate share link', 'Cancel']);
    // And both stay inside the modal panel.
    await expectContains(modal, generate, ['modal panel', 'Generate share link']);
    await expectContains(modal, cancel, ['modal panel', 'Cancel']);

    // Invariant 3: the snapshot-semantics explainer is not text-
    // clipped. Catches an i18n regression that lengthens the copy
    // past the modal's content-box.
    await expectNoTextClipping(explainer, 'snapshot-semantics explainer');
  });

  test('shared phase: URL input has enough content-box width for a 43-char token, copy + stop buttons do not collide', async ({
    mount,
  }) => {
    const component = await mount(ShareModalHarness, {
      props: { chat: defaultChatFixture({ share_id: TEST_TOKEN }) },
    });

    const modal = component.getByRole('dialog');
    const urlInput = component.getByRole('textbox', { name: 'Share link' });
    const copyBtn = component.getByRole('button', { name: /Copy link/ });
    const stopBtn = component.getByRole('button', { name: 'Stop sharing' });
    const doneBtn = component.getByRole('button', { name: 'Done' });
    // `component` is the backdrop — see the not-shared test for the
    // explanation.
    const backdrop = component;

    // Invariant 1: the URL input has enough content-box width to
    // hold the 43-char token. The threshold is conservative; tighten
    // when the design hardens.
    await expectMinContentWidth(urlInput, URL_INPUT_MIN_PX, 'Share URL input');

    // Invariant 2: the URL input + Copy-link button live in the
    // same flex row; Copy-link must not overlap the input itself.
    await expectNoOverlap(urlInput, copyBtn, ['Share URL input', 'Copy link']);

    // Invariant 3: the destructive Stop-sharing CTA and the primary
    // Done CTA share the modal's footer; they sit at opposite ends
    // (`justify-between`) and must not collide.
    await expectNoOverlap(stopBtn, doneBtn, ['Stop sharing', 'Done']);

    // Invariant 4: every footer control stays inside the modal panel.
    for (const [ctrl, label] of [
      [urlInput, 'Share URL input'],
      [copyBtn, 'Copy link'],
      [stopBtn, 'Stop sharing'],
      [doneBtn, 'Done'],
    ] as const) {
      await expectContains(modal, ctrl, ['modal panel', label]);
    }

    // Invariant 5: the modal panel itself stays inside the visible
    // viewport (backdrop spans `inset-0`).
    await expectContains(backdrop, modal, ['viewport (backdrop)', 'modal panel']);
  });

  test('stop-confirm phase: inline confirm panel stays inside the modal and its two buttons do not collide', async ({
    mount,
  }) => {
    const component = await mount(ShareModalHarness, {
      props: { chat: defaultChatFixture({ share_id: TEST_TOKEN }) },
    });
    await component.getByRole('button', { name: 'Stop sharing' }).click();

    const modal = component.getByRole('dialog');
    const confirmCopy = component.getByText(
      /Stop sharing\? The current link will stop working immediately\./,
    );
    // Two buttons named 'Stop sharing' would normally exist after the
    // transition (one is the destructive CTA, one was the previous
    // entry-point), but the previous-phase button is unmounted by
    // the {#if} branch. Within the dialog there's exactly one
    // `Cancel` and one `Stop sharing`.
    const cancel = modal.getByRole('button', { name: 'Cancel' });
    const stop = modal.getByRole('button', { name: 'Stop sharing' });

    await expectNoTextClipping(confirmCopy, 'stop-confirm prompt copy');
    await expectNoOverlap(cancel, stop, ['Cancel', 'Stop sharing (confirm)']);
    await expectContains(modal, cancel, ['modal panel', 'Cancel']);
    await expectContains(modal, stop, ['modal panel', 'Stop sharing (confirm)']);
  });
});

test.describe('ShareModal — geometric invariants (narrow viewport)', () => {
  test.use({ viewport: NARROW_VIEWPORT });

  test('shared phase still fits the URL input + buttons inside a 520px viewport', async ({
    mount,
  }) => {
    const component = await mount(ShareModalHarness, {
      props: { chat: defaultChatFixture({ share_id: TEST_TOKEN }) },
    });

    const modal = component.getByRole('dialog');
    const urlInput = component.getByRole('textbox', { name: 'Share link' });
    const copyBtn = component.getByRole('button', { name: /Copy link/ });
    const stopBtn = component.getByRole('button', { name: 'Stop sharing' });
    const doneBtn = component.getByRole('button', { name: 'Done' });
    // `component` is the backdrop — see the not-shared test for the
    // explanation.
    const backdrop = component;

    // The modal still stays inside the visible viewport at a narrow
    // width — the backdrop spans the viewport via `fixed inset-0`,
    // and `p-4` insets the modal naturally.
    await expectContains(backdrop, modal, ['viewport (backdrop)', 'modal panel']);
    // Sibling controls don't overlap.
    await expectNoOverlap(urlInput, copyBtn, ['Share URL input', 'Copy link']);
    await expectNoOverlap(stopBtn, doneBtn, ['Stop sharing', 'Done']);
    // The URL input still has enough room for the token at this
    // viewport — `max-w-md` clamps to 448 px, so the floor here is
    // the same as the desktop case.
    await expectMinContentWidth(urlInput, URL_INPUT_MIN_PX, 'Share URL input');
  });
});
