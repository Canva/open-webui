/**
 * Behavioural CT spec for `lib/components/chat/ShareModal.svelte`.
 *
 * Locked by `rebuild/docs/plans/m3-sharing.md`:
 *   - § Tests § Component (line 240): "share-modal.spec.ts — drives
 *     ShareModal.svelte through all three states with MSW handlers
 *     for the three endpoints. Asserts: copy button writes to
 *     `navigator.clipboard`, stop-sharing requires confirmation,
 *     generate-link reflects the returned URL."
 *   - § Owner UX (lines 222-228): three-state machine
 *     (`not-shared` -> `shared` -> `stop-confirm`), Esc + backdrop
 *     close gated on the in-flight lock, copy + stop-sharing both
 *     debounced.
 *   - § User journeys rows 1, 2, 3 — the `not-shared`, `shared`,
 *     and `stop-confirm` surfaces are the Layer A baselines this
 *     spec drives the user-facing behaviour for at Layer B.
 *
 * Layer choice: Playwright Component Testing.
 *   - The modal owns three internal phases plus an inline-confirm
 *     transition; CT mounts the real component against the real
 *     Tailwind cascade at a known viewport, exactly the bug class
 *     CT exists to catch (vs jsdom which would force us to mock
 *     the entire DOM-focus contract).
 *   - The harness monkey-patches `shares.create / .revoke / .get`
 *     with controllable stubs so each test can drive the in-flight
 *     lock cases (Esc is a no-op while pending) deterministically
 *     without inventing a new MSW layer for the CT bundle.
 *
 * No `page.route(...)` is needed — the harness is the network seam
 * (mirrors the established pattern in `MessageInput.spec.ts` and
 * `Sidebar.spec.ts`).
 */

import { test, expect } from '@playwright/experimental-ct-svelte';

import ShareModalHarness from './ShareModalHarness.svelte';
import { TEST_TOKEN, FIXTURE_CHAT_ID, defaultChatFixture } from './share-fixtures';

interface ShareModalWindow {
  __shareModal: {
    controls: {
      holdCreate: boolean;
      holdRevoke: boolean;
      holdGet: boolean;
      pending: {
        create: { resolve: (v: unknown) => void; reject: (e: unknown) => void } | null;
        revoke: { resolve: (v: unknown) => void; reject: (e: unknown) => void } | null;
        get: { resolve: (v: unknown) => void; reject: (e: unknown) => void } | null;
      };
      createResponse: { token: string; url: string; created_at: number };
    };
    apiCalls: { create: string[]; revoke: string[]; get: string[] };
    closeCalls: number[];
    shareChangeCalls: (string | null)[];
    clipboardCalls: string[];
    TEST_TOKEN: string;
    FIXTURE_CHAT_ID: string;
  };
}

test.describe('ShareModal — phase rendering', () => {
  test('opens in not-shared state when chat.share_id is null', async ({ mount }) => {
    const component = await mount(ShareModalHarness, {
      props: { chat: defaultChatFixture({ share_id: null }) },
    });

    // Heading copy is locked by the modal source (`Share this chat`).
    await expect(component.getByRole('heading', { name: 'Share this chat' })).toBeVisible();
    // Snapshot-semantics explainer is verbatim from the M3 plan
    // § Owner UX. Use a partial substring so a copy refresh that
    // rephrases the second sentence doesn't tip the test red on the
    // first sentence's intent.
    await expect(component.getByText('Sharing creates a snapshot')).toBeVisible();
    // The primary CTA is the Generate button.
    await expect(component.getByRole('button', { name: 'Generate share link' })).toBeVisible();
    // Negative containment: the URL input only renders in the shared
    // phase; assert it's NOT in the DOM here.
    await expect(component.getByRole('textbox', { name: 'Share link' })).toHaveCount(0);
  });

  test('opens in shared state when chat.share_id is set', async ({ mount, page }) => {
    const component = await mount(ShareModalHarness, {
      props: { chat: defaultChatFixture({ share_id: TEST_TOKEN }) },
    });

    const urlInput = component.getByRole('textbox', { name: 'Share link' });
    await expect(urlInput).toBeVisible();

    // The component constructs the absolute URL from
    // `window.location.origin` on the client; assert against whatever
    // the CT harness's origin happens to be (defaults to
    // `http://localhost:3100` per the CT config) so we don't couple
    // to a hard-coded port.
    const expectedUrl = await page.evaluate(
      (token) => `${window.location.origin}/s/${token}`,
      TEST_TOKEN,
    );
    await expect(urlInput).toHaveValue(expectedUrl);

    await expect(component.getByRole('button', { name: /Copy link/ })).toBeVisible();
    await expect(component.getByRole('button', { name: 'Stop sharing' })).toBeVisible();
  });
});

test.describe('ShareModal — generate transition', () => {
  test('clicking Generate transitions to shared state and calls onShareChange with the token', async ({
    mount,
    page,
  }) => {
    const component = await mount(ShareModalHarness, {
      props: { chat: defaultChatFixture({ share_id: null }) },
    });

    await component.getByRole('button', { name: 'Generate share link' }).click();

    // Phase flips: the URL input materialises with the test token.
    const expectedUrl = await page.evaluate(
      (token) => `${window.location.origin}/s/${token}`,
      TEST_TOKEN,
    );
    await expect(component.getByRole('textbox', { name: 'Share link' })).toHaveValue(expectedUrl);

    // The harness records `onShareChange` invocations + the chat id
    // the modal POSTed against. Both are asserted via `page.evaluate`.
    const result = await page.evaluate(() => {
      const w = window as unknown as ShareModalWindow;
      return {
        createCalls: w.__shareModal.apiCalls.create,
        shareChangeCalls: w.__shareModal.shareChangeCalls,
      };
    });
    expect(result.createCalls).toEqual([FIXTURE_CHAT_ID]);
    expect(result.shareChangeCalls).toEqual([TEST_TOKEN]);
  });
});

test.describe('ShareModal — copy link', () => {
  test('clicking Copy link writes the absolute URL to navigator.clipboard', async ({
    mount,
    page,
  }) => {
    const component = await mount(ShareModalHarness, {
      props: { chat: defaultChatFixture({ share_id: TEST_TOKEN }) },
    });

    await component.getByRole('button', { name: /Copy link/ }).click();

    const expectedUrl = await page.evaluate(
      (token) => `${window.location.origin}/s/${token}`,
      TEST_TOKEN,
    );
    const clipboardCalls = await page.evaluate(
      () => (window as unknown as ShareModalWindow).__shareModal.clipboardCalls,
    );
    expect(clipboardCalls).toEqual([expectedUrl]);
  });
});

test.describe('ShareModal — inline stop-confirm flow', () => {
  test('Stop sharing reveals an inline confirm scoped to the dialog (never window.confirm)', async ({
    mount,
    page,
  }) => {
    const component = await mount(ShareModalHarness, {
      props: { chat: defaultChatFixture({ share_id: TEST_TOKEN }) },
    });

    // Guard: assert window.confirm is NOT invoked at any point in this
    // flow. The plan rules out `window.confirm` because it flashes
    // outside the theme; the inline confirm must do all the work.
    await page.evaluate(() => {
      const w = window as unknown as { __confirmCalls: string[]; confirm: (m?: string) => boolean };
      w.__confirmCalls = [];
      w.confirm = (m?: string): boolean => {
        w.__confirmCalls.push(m ?? '');
        return true;
      };
    });

    await component.getByRole('button', { name: 'Stop sharing' }).click();

    // The inline confirm panel is scoped to the dialog (role="dialog").
    const dialog = component.getByRole('dialog');
    await expect(dialog).toContainText('Stop sharing? The current link will stop working');
    // Cancel returns to shared.
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(component.getByRole('button', { name: /Copy link/ })).toBeVisible();

    // Re-enter and confirm: second click triggers the DELETE.
    await component.getByRole('button', { name: 'Stop sharing' }).click();
    await dialog.getByRole('button', { name: 'Stop sharing' }).click();

    // Modal is back at not-shared phase.
    await expect(component.getByRole('button', { name: 'Generate share link' })).toBeVisible();

    const result = await page.evaluate(() => {
      const w = window as unknown as ShareModalWindow & { __confirmCalls: string[] };
      return {
        revokeCalls: w.__shareModal.apiCalls.revoke,
        shareChangeCalls: w.__shareModal.shareChangeCalls,
        confirmCalls: w.__confirmCalls,
      };
    });
    expect(result.revokeCalls).toEqual([FIXTURE_CHAT_ID]);
    // Last shareChange call should be `null` (revoked).
    expect(result.shareChangeCalls.at(-1)).toBeNull();
    expect(result.confirmCalls).toEqual([]);
  });
});

test.describe('ShareModal — close affordances respect the in-flight lock', () => {
  test('Escape closes the modal when no request is in flight', async ({ mount, page }) => {
    await mount(ShareModalHarness, {
      props: { chat: defaultChatFixture({ share_id: null }) },
    });
    await page.keyboard.press('Escape');

    const closes = await page.evaluate(
      () => (window as unknown as ShareModalWindow).__shareModal.closeCalls.length,
    );
    expect(closes).toBe(1);
  });

  test('Escape is a no-op while a request is in flight, then fires once the request resolves', async ({
    mount,
    page,
  }) => {
    const component = await mount(ShareModalHarness, {
      props: { chat: defaultChatFixture({ share_id: null }) },
    });

    // Hold the next `shares.create` call open.
    await page.evaluate(() => {
      (window as unknown as ShareModalWindow).__shareModal.controls.holdCreate = true;
    });

    await component.getByRole('button', { name: 'Generate share link' }).click();
    // The modal flips the disabled state on the close button while
    // the POST is open; assert the visual signal so the test isn't
    // a pure race condition on the first Escape.
    await expect(component.getByRole('button', { name: 'Close' })).toBeDisabled();

    // Esc while in flight: the handler short-circuits.
    await page.keyboard.press('Escape');
    let closes = await page.evaluate(
      () => (window as unknown as ShareModalWindow).__shareModal.closeCalls.length,
    );
    expect(closes).toBe(0);

    // Release the held create. Resolve with the harness default.
    await page.evaluate(() => {
      const w = window as unknown as ShareModalWindow;
      const pending = w.__shareModal.controls.pending.create;
      pending?.resolve(w.__shareModal.controls.createResponse);
    });

    // After the resolve lands the modal is in the shared phase and
    // unlocked — Esc now closes.
    await expect(component.getByRole('textbox', { name: 'Share link' })).toBeVisible();
    await page.keyboard.press('Escape');
    closes = await page.evaluate(
      () => (window as unknown as ShareModalWindow).__shareModal.closeCalls.length,
    );
    expect(closes).toBe(1);
  });

  test('Backdrop click is a no-op while in flight, then closes once the request resolves', async ({
    mount,
    page,
  }) => {
    const component = await mount(ShareModalHarness, {
      props: { chat: defaultChatFixture({ share_id: null }) },
    });
    await page.evaluate(() => {
      (window as unknown as ShareModalWindow).__shareModal.controls.holdCreate = true;
    });
    await component.getByRole('button', { name: 'Generate share link' }).click();
    await expect(component.getByRole('button', { name: 'Close' })).toBeDisabled();

    // The backdrop is the outer `role="presentation"` div. Click it
    // outside the dialog rectangle to make sure the handler's
    // `event.target !== event.currentTarget` guard still passes.
    // Use a corner click so we land on the backdrop, not the modal.
    await page.evaluate(() => {
      const backdrop = document.querySelector('[role="presentation"]') as HTMLElement | null;
      backdrop?.click(); // direct click on the backdrop element itself
    });
    let closes = await page.evaluate(
      () => (window as unknown as ShareModalWindow).__shareModal.closeCalls.length,
    );
    expect(closes).toBe(0);

    await page.evaluate(() => {
      const w = window as unknown as ShareModalWindow;
      w.__shareModal.controls.pending.create?.resolve(w.__shareModal.controls.createResponse);
    });
    await expect(component.getByRole('textbox', { name: 'Share link' })).toBeVisible();

    // Now backdrop click closes.
    await page.evaluate(() => {
      const backdrop = document.querySelector('[role="presentation"]') as HTMLElement | null;
      backdrop?.click();
    });
    closes = await page.evaluate(
      () => (window as unknown as ShareModalWindow).__shareModal.closeCalls.length,
    );
    expect(closes).toBe(1);
  });
});
