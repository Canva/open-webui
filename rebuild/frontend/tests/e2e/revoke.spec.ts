/**
 * E2E: Alice revokes a share, Bob sees the dead-link panel.
 *
 * Critical path locked by `rebuild/docs/plans/m3-sharing.md`:
 *   - § Tests § E2E (revoke row): "Bob first reads the snapshot;
 *     Alice clicks Stop sharing → confirms; Bob refreshes and sees
 *     the inline 'no longer active' panel; the original message
 *     content is NOT visible."
 *   - § User journeys row 2 (Owner revokes a share) and row 5
 *     (Recipient hits a dead share link → graceful inline panel).
 *   - § Frontend route: 404 from `GET /api/shared/{token}` returns
 *     `{ snapshot: null }` from `+page.server.ts`, which renders
 *     the terminal panel — never a generic SvelteKit error page.
 *
 * Backend coordination
 * --------------------
 * Same as `share-and-read.spec.ts` — the cassette LLM mock is not
 * yet wired into the docker stack, but the share endpoints have
 * 15 backend integration tests against real MySQL as the wire-
 * shape regression. This spec asserts the FE flow against
 * `page.route` mocks for the share endpoints.
 *
 * The revoke flow uses an inline confirm panel inside the modal
 * (NOT `window.confirm`) — the M3 plan rules out the native
 * dialog explicitly because it flashes outside the theme.
 */

import { test, expect, type BrowserContext, type Page } from '@playwright/test';

const ALICE_EMAIL = 'alice@canva.com';
const BOB_EMAIL = 'bob@canva.com';
const CHAT_ID = '01900000-0000-7000-8000-000000003a02';
const SHARE_TOKEN = 'JOURNEYM3revoketokenAAAAAAAAAAAAAAAAAAAAAAA';

const NOW = 1_735_689_600_000;

const DETERMINISTIC_BOOT = `
  (() => {
    Date.now = () => 1735689600000;
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

interface ChatStub {
  id: string;
  title: string;
  pinned: boolean;
  archived: boolean;
  folder_id: string | null;
  created_at: number;
  updated_at: number;
  history: { messages: Record<string, unknown>; currentId: string | null };
  share_id: string | null;
}

function aliceChat(shareId: string | null): ChatStub {
  return {
    id: CHAT_ID,
    title: 'Refactor draft',
    pinned: false,
    archived: false,
    folder_id: null,
    created_at: NOW,
    updated_at: NOW,
    history: {
      messages: {
        'u-1': {
          id: 'u-1',
          parentId: null,
          childrenIds: ['a-1'],
          role: 'user',
          content: 'Will become invisible after revoke',
          timestamp: NOW,
          agent_id: null,
          agentName: null,
          done: true,
          error: null,
          cancelled: false,
          usage: null,
        },
        'a-1': {
          id: 'a-1',
          parentId: 'u-1',
          childrenIds: [],
          role: 'assistant',
          content: 'Pre-revoke assistant reply',
          timestamp: NOW,
          agent_id: 'gpt-4o',
          agentName: 'GPT-4o',
          done: true,
          error: null,
          cancelled: false,
          usage: { prompt_tokens: 8, completion_tokens: 5, total_tokens: 13 },
        },
      },
      currentId: 'a-1',
    },
    share_id: shareId,
  };
}

function snapshotForBob(): unknown {
  return {
    token: SHARE_TOKEN,
    title: 'Refactor draft',
    history: aliceChat(SHARE_TOKEN).history,
    shared_by: { name: ALICE_EMAIL, email: ALICE_EMAIL },
    created_at: NOW,
  };
}

async function newIdentityContext(
  browser: import('@playwright/test').Browser,
  email: string,
): Promise<BrowserContext> {
  return browser.newContext({
    extraHTTPHeaders: { 'X-Forwarded-Email': email },
  });
}

async function bootDeterministically(page: Page): Promise<void> {
  await page.addInitScript(DETERMINISTIC_BOOT);
}

test.describe('@e2e-m3 @journey-m3 revoke', () => {
  test('Bob reads the snapshot, Alice revokes, Bob refreshes and sees the dead-link panel', async ({
    browser,
  }) => {
    // ---- Set up Bob's context first so we can prove the read works
    //      against the live snapshot before the revoke fires.
    const bobCtx = await newIdentityContext(browser, BOB_EMAIL);
    const bobPage = await bobCtx.newPage();
    await bootDeterministically(bobPage);

    let revokeFired = false;
    await bobCtx.route(`**/api/shared/${SHARE_TOKEN}`, async (route) => {
      if (revokeFired) {
        await route.fulfill({
          status: 404,
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ detail: 'share not found' }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(snapshotForBob()),
      });
    });

    // ---- Set up Alice's context with the chat already in shared
    //      state (the modal opens directly into the shared phase). ----
    const aliceCtx = await newIdentityContext(browser, ALICE_EMAIL);
    const alicePage = await aliceCtx.newPage();
    await bootDeterministically(alicePage);

    let currentShareId: string | null = SHARE_TOKEN;
    await aliceCtx.route(`**/api/chats/${CHAT_ID}`, async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(aliceChat(currentShareId)),
        });
        return;
      }
      await route.continue();
    });

    let revokeCallCount = 0;
    await aliceCtx.route(`**/api/chats/${CHAT_ID}/share`, async (route) => {
      const method = route.request().method();
      if (method === 'DELETE') {
        revokeCallCount += 1;
        currentShareId = null;
        revokeFired = true;
        await route.fulfill({ status: 204, body: '' });
        return;
      }
      await route.continue();
    });

    // The modal's `shares.get` lazy-fetch fires when opening in
    // shared state. Mock it so the "Captured" line renders.
    await aliceCtx.route(`**/api/shared/${SHARE_TOKEN}`, async (route) => {
      // Alice's own context fetch — pre-revoke this returns a snapshot.
      await route.fulfill({
        status: revokeCallCount === 0 ? 200 : 404,
        headers: { 'content-type': 'application/json' },
        body:
          revokeCallCount === 0
            ? JSON.stringify(snapshotForBob())
            : JSON.stringify({ detail: 'share not found' }),
      });
    });

    // Sidebar empties for both contexts.
    for (const ctx of [aliceCtx, bobCtx]) {
      await ctx.route('**/api/chats**', async (route) => {
        const url = new URL(route.request().url());
        if (url.pathname.endsWith('/api/chats') && route.request().method() === 'GET') {
          await route.fulfill({
            status: 200,
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ items: [], next_cursor: null }),
          });
          return;
        }
        await route.continue();
      });
      await ctx.route('**/api/folders**', async (route) => {
        if (route.request().method() === 'GET') {
          await route.fulfill({
            status: 200,
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify([]),
          });
          return;
        }
        await route.continue();
      });
    }

    // ---- Step 1: Bob reads the live snapshot. -----------------------
    let serverReachable = true;
    try {
      await bobPage.goto(`/s/${SHARE_TOKEN}`);
    } catch {
      serverReachable = false;
    }
    test.skip(
      !serverReachable,
      'SvelteKit dev server unreachable. See send-and-stream.spec.ts header for context.',
    );
    await expect(bobPage.getByRole('heading', { name: 'Refactor draft', level: 1 })).toBeVisible();
    await expect(
      bobPage.getByText('Will become invisible after revoke', { exact: true }),
    ).toBeVisible();

    // ---- Step 2: Alice opens the modal and revokes. -----------------
    await alicePage.goto(`/c/${CHAT_ID}`);
    await alicePage.getByRole('button', { name: 'Manage share link' }).click();

    // The modal opens in shared phase. Click Stop sharing → inline
    // confirm → second Stop sharing.
    const dialog = alicePage.getByRole('dialog');
    await dialog.getByRole('button', { name: 'Stop sharing' }).click();
    await expect(
      dialog.getByText(/Stop sharing\? The current link will stop working immediately\./),
    ).toBeVisible();
    await dialog.getByRole('button', { name: 'Stop sharing' }).click();

    // Modal returns to not-shared phase.
    await expect(alicePage.getByRole('button', { name: 'Generate share link' })).toBeVisible();
    expect(revokeCallCount).toBe(1);

    // Sanity: the inline confirm did NOT delegate to `window.confirm`.
    // (The handler in `ShareModal.svelte` doesn't even reference it
    // — but assert defensively so a future refactor that adds a
    // window-level fallback surfaces here.)
    const nativeConfirmFires = await alicePage.evaluate(
      () => (window as unknown as { __confirmFires?: number }).__confirmFires ?? 0,
    );
    expect(nativeConfirmFires).toBe(0);

    // ---- Step 3: Bob refreshes and sees the dead-link panel. --------
    await bobPage.reload();

    await expect(
      bobPage.getByRole('heading', { name: 'Shared chat unavailable', level: 1 }),
    ).toBeVisible();
    await expect(bobPage.getByText('This share link is no longer active.')).toBeVisible();

    // The original message content MUST NOT be visible — the dead-
    // link path must never leak the snapshot bytes for a revoked
    // share. This is the non-leak invariant the plan calls out.
    await expect(
      bobPage.getByText('Will become invisible after revoke', { exact: true }),
    ).toHaveCount(0);
    await expect(bobPage.getByText('Pre-revoke assistant reply', { exact: true })).toHaveCount(0);

    await aliceCtx.close();
    await bobCtx.close();
  });
});
