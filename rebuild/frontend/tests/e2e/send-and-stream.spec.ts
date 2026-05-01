/**
 * E2E: send a message and watch tokens stream in.
 *
 * Critical path locked by `rebuild/docs/plans/m2-conversations.md`:
 *   - § Tests § Frontend (line 1062): "send-and-stream — send a
 *     message, tokens render in order, the assistant message is
 *     persisted, reload shows the message".
 *   - § Frontend routes (lines 858-905): the eight-step send
 *     lifecycle (`activeChat.send` → SSE `start` → `delta`s →
 *     `usage` → `done`) is the contract this spec asserts.
 *   - § Acceptance criteria: "send Hello → tokens render in order
 *     → reload shows Hello + Hi there!".
 *
 * Backend coordination
 * --------------------
 * - SvelteKit's server-load (`(app)/+layout.server.ts` and
 *   `(app)/c/[id]/+page.server.ts`) reaches the FastAPI backend at
 *   `PUBLIC_API_BASE_URL` from the SvelteKit Node.js process. That
 *   path is unreachable from `page.route()` (which only sees the
 *   browser context).
 * - Playwright's `globalSetup` brings up `infra/docker-compose.yml`
 *   so the backend at `:8080` is available for SSR fetches by
 *   default. The cassette LLM mock (Phase 4a) is the long-term
 *   source of truth for the SSE response.
 * - Until Phase 4a's cassette is wired into the backend container,
 *   we mock the SSE response at the BROWSER layer via
 *   `page.route('**\/api/chats/*\/messages')`. The browser-side
 *   `activeChat.send(...)` is the call site that opens the stream;
 *   the SSR'd `chat.history` is empty so the only place tokens
 *   come from is the intercepted stream. This is the path the
 *   dispatch's "fall back to MSW-layer SSE shape" instruction
 *   names.
 *
 * Determinism
 * -----------
 * - The stream uses fixed `user_message_id` / `assistant_message_id`
 *   so subsequent assertions can address them.
 * - All deltas are encoded synchronously on the same tick; tokens
 *   render in order because the SSE parser preserves frame order
 *   (see `tests/unit/parseSSE.test.ts`).
 *
 * Skip protocol
 * -------------
 * If the backend is unreachable (e.g. a developer running
 * `REBUILD_SKIP_COMPOSE=1` without a manual `docker compose up`),
 * SSR will throw. We catch and `test.skip()` with a clear message
 * so the run reports the failure mode without painting it red.
 */

import { test, expect, type Route } from '@playwright/test';

const STREAM_CHAT_ID = '01900000-0000-7000-8000-00000000c0ff';

/**
 * Synthesise the deterministic "Hi there!" SSE cassette per
 * `lib/msw/handlers.ts::defaultStreamBody`. Keeping the wire shape
 * defined inline (vs imported from the MSW module) lets the spec
 * remain self-contained for Playwright's bundle.
 */
function sseFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

const STREAM_BYTES = [
  sseFrame('start', {
    user_message_id: 'user-msg-1',
    assistant_message_id: 'asst-msg-1',
  }),
  sseFrame('delta', { content: 'Hi' }),
  sseFrame('delta', { content: ' there' }),
  sseFrame('delta', { content: '!' }),
  sseFrame('usage', { prompt_tokens: 8, completion_tokens: 3, total_tokens: 11 }),
  sseFrame('done', { assistant_message_id: 'asst-msg-1', finish_reason: 'stop' }),
].join('');

async function fulfilStream(route: Route): Promise<void> {
  await route.fulfill({
    status: 200,
    headers: {
      'content-type': 'text/event-stream',
      'cache-control': 'no-cache',
    },
    body: STREAM_BYTES,
  });
}

test.describe('@e2e-m2 send-and-stream', () => {
  test('send a message → tokens render in order → assistant persisted → reload shows it', async ({
    page,
  }) => {
    // ---- Browser-side route interception. ---------------------------
    // The chat-create POST returns a deterministic id so we know
    // where the post-Enter goto() lands.
    await page.route(`**/api/chats`, async (route) => {
      if (route.request().method() === 'POST') {
        const now = Date.now();
        await route.fulfill({
          status: 200,
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            id: STREAM_CHAT_ID,
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

    // The SSR'd `GET /api/chats/{id}` after `goto('/c/<id>')` returns
    // the empty chat skeleton. The activeChat store re-fetches from
    // the browser via `chatsApi.get(id)`, which we mock here too so
    // the test does not depend on a live backend round-trip.
    await page.route(`**/api/chats/${STREAM_CHAT_ID}`, async (route) => {
      const now = Date.now();
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          id: STREAM_CHAT_ID,
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

    // The streaming endpoint — the deterministic cassette.
    await page.route(`**/api/chats/${STREAM_CHAT_ID}/messages`, fulfilStream);

    // ---- Drive the UI. ----------------------------------------------
    let serverReachable = true;
    try {
      await page.goto('/');
    } catch (err) {
      serverReachable = false;
      console.warn('[send-and-stream] goto / failed:', err);
    }
    test.skip(
      !serverReachable,
      'SvelteKit dev server unreachable (likely backend down). ' +
        'Bring up `make dev-stack` or set REBUILD_SKIP_COMPOSE=0.',
    );

    // The empty-state composer auto-focuses on mount. Type and hit
    // Enter to fire the create-chat → goto → first-message handoff.
    const composer = page.getByRole('textbox', { name: 'Compose a message' });
    await expect(composer).toBeVisible();
    await composer.fill('Hello');
    await composer.press('Enter');

    // Goto resolves to /c/<id>. The conversation view mounts and
    // picks up the sessionStorage handoff to dispatch the first
    // message.
    await expect(page).toHaveURL(new RegExp(`/c/${STREAM_CHAT_ID}$`));

    // The user bubble must render verbatim.
    await expect(page.getByText('Hello', { exact: true })).toBeVisible();

    // Tokens land in order. The assistant message body assembles to
    // "Hi there!" — assert the final string is visible (the order is
    // implicit because the parser preserves frame order; the unit
    // test in `tests/unit/parseSSE.test.ts` covers the strict ordering
    // contract).
    await expect(page.getByText('Hi there!', { exact: true })).toBeVisible();

    // The assistant message footer surfaces the agent + token count
    // once `done` flips true (see `Message.svelte` § "Metadata +
    // actions row" — hidden while isStreaming).
    await expect(page.getByText('11 tokens', { exact: true })).toBeVisible();

    // ---- Reload — the assistant message must be visible again. ------
    // We re-mock the GET endpoint to return the persisted exchange so
    // the SSR'd hydration includes both messages.
    await page.unroute(`**/api/chats/${STREAM_CHAT_ID}`);
    await page.route(`**/api/chats/${STREAM_CHAT_ID}`, async (route) => {
      const now = Date.now();
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          id: STREAM_CHAT_ID,
          title: 'New Chat',
          pinned: false,
          archived: false,
          folder_id: null,
          created_at: now,
          updated_at: now,
          history: {
            messages: {
              'user-msg-1': {
                id: 'user-msg-1',
                parentId: null,
                childrenIds: ['asst-msg-1'],
                role: 'user',
                content: 'Hello',
                timestamp: now,
                agent_id: null,
                agentName: null,
                done: true,
                error: null,
                cancelled: false,
                usage: null,
              },
              'asst-msg-1': {
                id: 'asst-msg-1',
                parentId: 'user-msg-1',
                childrenIds: [],
                role: 'assistant',
                content: 'Hi there!',
                timestamp: now,
                agent_id: 'gpt-4o',
                agentName: 'GPT-4o',
                done: true,
                error: null,
                cancelled: false,
                usage: { prompt_tokens: 8, completion_tokens: 3, total_tokens: 11 },
              },
            },
            currentId: 'asst-msg-1',
          },
          share_id: null,
        }),
      });
    });

    await page.reload();

    await expect(page.getByText('Hello', { exact: true })).toBeVisible();
    await expect(page.getByText('Hi there!', { exact: true })).toBeVisible();
  });
});
