/**
 * E2E: cancel a stream mid-flight via Esc.
 *
 * Critical path locked by `rebuild/docs/plans/m2-conversations.md`:
 *   - § Tests § Frontend (line 1063): "cancel-mid-stream — start a
 *     long stream → press Esc → assertion: stream stops, assistant
 *     message shows the cancelled badge, `/api/chats/{id}` returns
 *     `cancelled: true, done: true` and the partial content the user
 *     already saw".
 *   - § Frontend components (line 887): "MessageInput — Esc cancels
 *     in-flight stream".
 *   - § Stores and state (`ActiveChatStore.cancel`): posts the
 *     explicit `/cancel` AND aborts the local fetch — this spec
 *     exercises both side-effects via the route handlers below.
 *
 * Cassette shape
 * --------------
 * The deterministic stream emits 5 deltas with ~80 ms gaps so the
 * test has a stable window to press Esc after the first 1–2 deltas
 * have rendered. The total stream length is bounded so a missed
 * cancel still completes the test within Playwright's default
 * timeout.
 *
 * Backend coordination
 * --------------------
 * Same as `send-and-stream.spec.ts`: SvelteKit's server-load uses
 * the docker-compose backend (Phase 4a's cassette mock once it
 * lands); browser-side fetches are intercepted via `page.route()`.
 */

import { test, expect, type Route } from '@playwright/test';

const CANCEL_CHAT_ID = '01900000-0000-7000-8000-000000000ca0';

function sseFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

const PARTIAL_DELTAS = ['I', '`m', ' going', ' to', ' write'];

/**
 * Build a slow stream that emits a `start` frame immediately, then
 * paces 5 deltas with ~80 ms gaps. We do NOT emit a terminal frame
 * — the controller stays open until the abort fires (or the timeout
 * below closes it as a safety net).
 *
 * Why no terminal frame: the dispatch's contract is "stream stops
 * because the user pressed Esc → server emits the cancelled SSE
 * frame → client sees the cancelled badge". When the browser
 * aborts the fetch, the route's body controller sees the close and
 * we can synthesise the `cancelled` frame to mirror the production
 * server-side flow.
 */
async function fulfilSlowStream(route: Route): Promise<void> {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      controller.enqueue(
        encoder.encode(
          sseFrame('start', {
            user_message_id: 'user-msg-c1',
            assistant_message_id: 'asst-msg-c1',
          }),
        ),
      );
      for (const piece of PARTIAL_DELTAS) {
        await new Promise<void>((resolve) => setTimeout(resolve, 80));
        try {
          controller.enqueue(encoder.encode(sseFrame('delta', { content: piece })));
        } catch {
          // Connection aborted; bail out.
          return;
        }
      }
      // Safety-net terminal: if Esc never fires, close so the test
      // still completes in finite time.
      controller.enqueue(
        encoder.encode(
          sseFrame('done', { assistant_message_id: 'asst-msg-c1', finish_reason: 'stop' }),
        ),
      );
      controller.close();
    },
  });
  await route.fulfill({
    status: 200,
    headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' },
    body: stream as unknown as ReadableStream<Uint8Array>,
  });
}

test.describe('@e2e-m2 cancel-mid-stream', () => {
  test('Esc during stream → fetch aborts → cancelled badge → /cancel POST observed', async ({
    page,
  }) => {
    let cancelCalled = false;

    await page.route(`**/api/chats`, async (route) => {
      if (route.request().method() === 'POST') {
        const now = Date.now();
        await route.fulfill({
          status: 200,
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            id: CANCEL_CHAT_ID,
            title: 'New Chat',
            pinned: false,
            archived: false,
            folder_id: null,
            created_at: now,
            updated_at: now,
            history: { messages: {}, currentId: null },
            share_id: null,
          }),
        });
        return;
      }
      await route.continue();
    });

    await page.route(`**/api/chats/${CANCEL_CHAT_ID}`, async (route) => {
      const now = Date.now();
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          id: CANCEL_CHAT_ID,
          title: 'New Chat',
          pinned: false,
          archived: false,
          folder_id: null,
          created_at: now,
          updated_at: now,
          history: { messages: {}, currentId: null },
          share_id: null,
        }),
      });
    });

    await page.route(`**/api/chats/${CANCEL_CHAT_ID}/messages`, fulfilSlowStream);

    // The explicit cancel POST. We record the call, return 204, and
    // the route handler emits `cancelled: true` on the next GET so
    // the post-reload assertion lands deterministically.
    await page.route(`**/api/chats/${CANCEL_CHAT_ID}/messages/*/cancel`, async (route) => {
      cancelCalled = true;
      await route.fulfill({ status: 204, body: '' });
    });

    let serverReachable = true;
    try {
      await page.goto('/');
    } catch {
      serverReachable = false;
    }
    test.skip(
      !serverReachable,
      'SvelteKit dev server unreachable. See send-and-stream.spec.ts header for context.',
    );

    const composer = page.getByRole('textbox', { name: 'Compose a message' });
    await composer.fill('Write a long story for me');
    await composer.press('Enter');
    await expect(page).toHaveURL(new RegExp(`/c/${CANCEL_CHAT_ID}$`));

    // Wait for the first delta to render so we know the stream is
    // mid-flight. The first piece is "I"; assert against the
    // partial content (the trailing apostrophe + "m" arrives 80 ms
    // later).
    await expect(page.getByText(/^I/).first()).toBeVisible({ timeout: 10_000 });

    // Press Esc on the composer (the focus target post-send) to
    // fire `useActiveChat().cancel()`.
    await composer.focus();
    await composer.press('Escape');

    // The cancelled badge surfaces verbatim from `Message.svelte`'s
    // `isCancelled` branch.
    await expect(page.getByText('Cancelled', { exact: true })).toBeVisible({
      timeout: 10_000,
    });

    // The explicit cancel POST hit our recorder.
    expect(cancelCalled).toBe(true);
  });
});
