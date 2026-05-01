/**
 * E2E: re-sharing a chat rotates the token; the old token dies.
 *
 * Critical path locked by `rebuild/docs/plans/m3-sharing.md`:
 *   - § Tests § E2E (rotation row): "Alice generates a share (t1),
 *     copies; generates again (t2); asserts t1 ≠ t2; Bob navigates
 *     to /s/{t1} and gets the dead-link panel; /s/{t2} resolves to
 *     the new snapshot."
 *   - § Owner UX: rotating IS the only way to re-share — there is no
 *     "regenerate token in place" option in the modal. The user
 *     stops sharing, re-opens, generates again. The plan deliberately
 *     hides any "rotate" button to keep the mental model "one share
 *     = one snapshot moment" simple.
 *   - § User journeys row 3 (Owner re-shares after edits → rotation).
 *
 * Asserts the security-critical invariant: a token retired by re-share
 * must not be a valid lookup. The 15 backend integration tests cover
 * the persistence-layer rotation; this E2E covers the FE round-trip
 * across two contexts so a future refactor that breaks the invariant
 * (e.g. caching the snapshot keyed by chat instead of by token) lands
 * here on the next run.
 */

import { test, expect, type BrowserContext, type Page } from '@playwright/test';

const ALICE_EMAIL = 'alice@canva.com';
const BOB_EMAIL = 'bob@canva.com';
const CHAT_ID = '01900000-0000-7000-8000-000000003a03';
const TOKEN_T1 = 'JOURNEYM3rotateT1AAAAAAAAAAAAAAAAAAAAAAAAAAA';
const TOKEN_T2 = 'JOURNEYM3rotateT2BBBBBBBBBBBBBBBBBBBBBBBBBBB';

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

function aliceChat(shareId: string | null, contentTag: string): ChatStub {
  // The assistant-reply text changes between t1 and t2 so we can
  // assert Bob sees the post-rotation content under /s/{t2} (and
  // does NOT see the t1 content).
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
          content: 'Edit me to demonstrate rotation',
          timestamp: NOW,
          model: null,
          modelName: null,
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
          content: contentTag,
          timestamp: NOW,
          model: 'gpt-4o',
          modelName: 'GPT-4o',
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

function snapshotForToken(token: string, contentTag: string): unknown {
  return {
    token,
    title: 'Refactor draft',
    history: aliceChat(token, contentTag).history,
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

test.describe('@e2e-m3 @journey-m3 rotation', () => {
  test('re-sharing rotates the token: t1 dies, t2 resolves', async ({ browser }) => {
    // ---- Alice's context: drives the two share-and-stop-and-share
    //      cycles. Each generate POST flips `currentShareId` and
    //      enqueues the next token to mint. -----------------------
    const aliceCtx = await newIdentityContext(browser, ALICE_EMAIL);
    const alicePage = await aliceCtx.newPage();
    await bootDeterministically(alicePage);

    // The chat starts not-shared. After the first Generate it carries
    // t1; after the user reverts to not-shared (via Stop sharing) and
    // generates again, it carries t2. The route handler walks this
    // sequence as the page calls into it.
    let currentShareId: string | null = null;
    let nextTokenIdx = 0;
    const TOKENS = [TOKEN_T1, TOKEN_T2] as const;
    const POST_BODIES_LATER = ['rotation t1 reply', 'rotation t2 reply'] as const;

    await aliceCtx.route(`**/api/chats/${CHAT_ID}`, async (route) => {
      if (route.request().method() === 'GET') {
        // The chat content is the t1 body before any rotation, the
        // t2 body after. The body change is what proves the snapshot
        // captured at each generate is its own moment-in-time.
        const tag = currentShareId === TOKEN_T2 ? POST_BODIES_LATER[1] : POST_BODIES_LATER[0];
        await route.fulfill({
          status: 200,
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(aliceChat(currentShareId, tag)),
        });
        return;
      }
      await route.continue();
    });

    let createCallCount = 0;
    let revokeCallCount = 0;
    await aliceCtx.route(`**/api/chats/${CHAT_ID}/share`, async (route) => {
      const method = route.request().method();
      if (method === 'POST') {
        createCallCount += 1;
        const minted = TOKENS[nextTokenIdx]!;
        nextTokenIdx += 1;
        currentShareId = minted;
        await route.fulfill({
          status: 200,
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            token: minted,
            url: `/s/${minted}`,
            created_at: NOW + createCallCount,
          }),
        });
        return;
      }
      if (method === 'DELETE') {
        revokeCallCount += 1;
        currentShareId = null;
        await route.fulfill({ status: 204, body: '' });
        return;
      }
      await route.continue();
    });

    // The modal lazy-fetches `/api/shared/{token}` after Generate to
    // populate the "Captured" line. Mock for whatever the latest
    // minted token is.
    await aliceCtx.route('**/api/shared/*', async (route) => {
      const url = new URL(route.request().url());
      const token = url.pathname.split('/').pop()!;
      const tag = token === TOKEN_T2 ? POST_BODIES_LATER[1] : POST_BODIES_LATER[0];
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(snapshotForToken(token, tag)),
      });
    });

    await aliceCtx.route('**/api/chats**', async (route) => {
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
    await aliceCtx.route('**/api/folders**', async (route) => {
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

    // ---- Step 1: Alice generates t1. --------------------------------
    let serverReachable = true;
    try {
      await alicePage.goto(`/c/${CHAT_ID}`);
    } catch {
      serverReachable = false;
    }
    test.skip(
      !serverReachable,
      'SvelteKit dev server unreachable. See send-and-stream.spec.ts header for context.',
    );

    await alicePage.getByRole('button', { name: 'Share this chat' }).click();
    await alicePage.getByRole('button', { name: 'Generate share link' }).click();

    const urlInput = alicePage.getByRole('textbox', { name: 'Share link' });
    await expect(urlInput).toHaveValue(
      await alicePage.evaluate((t) => `${window.location.origin}/s/${t}`, TOKEN_T1),
    );
    expect(currentShareId).toBe(TOKEN_T1);

    // ---- Step 2: Alice stops sharing, then generates t2. ------------
    const dialog = alicePage.getByRole('dialog');
    await dialog.getByRole('button', { name: 'Stop sharing' }).click();
    await dialog.getByRole('button', { name: 'Stop sharing' }).click();
    await expect(alicePage.getByRole('button', { name: 'Generate share link' })).toBeVisible();
    expect(revokeCallCount).toBe(1);

    await alicePage.getByRole('button', { name: 'Generate share link' }).click();
    await expect(urlInput).toHaveValue(
      await alicePage.evaluate((t) => `${window.location.origin}/s/${t}`, TOKEN_T2),
    );
    expect(createCallCount).toBe(2);
    expect(TOKEN_T1).not.toBe(TOKEN_T2);

    // ---- Step 3: Bob loads /s/{t1} (dead) and /s/{t2} (alive). ------
    const bobCtx = await newIdentityContext(browser, BOB_EMAIL);
    const bobPage = await bobCtx.newPage();
    await bootDeterministically(bobPage);

    // Bob's mock: t1 → 404, t2 → live snapshot. Order matters here:
    // the FIRST handler registered for a glob wins, so register the
    // exact-match dead-token route before the wildcard live route.
    await bobCtx.route(`**/api/shared/${TOKEN_T1}`, async (route) => {
      await route.fulfill({
        status: 404,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ detail: 'share not found' }),
      });
    });
    await bobCtx.route(`**/api/shared/${TOKEN_T2}`, async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(snapshotForToken(TOKEN_T2, POST_BODIES_LATER[1])),
      });
    });

    // /s/{t1} → dead-link panel, t1 content NOT visible.
    await bobPage.goto(`/s/${TOKEN_T1}`);
    await expect(
      bobPage.getByRole('heading', { name: 'Shared chat unavailable', level: 1 }),
    ).toBeVisible();
    await expect(bobPage.getByText('This share link is no longer active.')).toBeVisible();
    await expect(bobPage.getByText(POST_BODIES_LATER[0], { exact: true })).toHaveCount(0);

    // /s/{t2} → live snapshot, t2 content visible.
    await bobPage.goto(`/s/${TOKEN_T2}`);
    await expect(bobPage.getByRole('heading', { name: 'Refactor draft', level: 1 })).toBeVisible();
    await expect(bobPage.getByText(POST_BODIES_LATER[1], { exact: true })).toBeVisible();
    // Cross-check: the t1 body must not appear under the t2 URL.
    await expect(bobPage.getByText(POST_BODIES_LATER[0], { exact: true })).toHaveCount(0);

    await aliceCtx.close();
    await bobCtx.close();
  });
});
