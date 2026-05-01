/**
 * E2E: Alice shares a chat, Bob reads the snapshot.
 *
 * Critical path locked by `rebuild/docs/plans/m3-sharing.md`:
 *   - § Tests § E2E (lines 246-249, share-and-read row): "Alice
 *     creates chat → owner sends a message → opens share modal,
 *     clicks Generate → copies URL. Bob (different BrowserContext,
 *     different `X-Forwarded-Email`) opens the URL → asserts the
 *     snapshot matches."
 *   - § User journeys row 1 (Owner shares a chat) and row 4
 *     (Recipient opens shared link).
 *   - § API surface — Bob's `GET /api/shared/{token}` is auth-gated
 *     by the proxy header (any authenticated viewer can read; the
 *     token itself is the share key).
 *
 * Backend coordination
 * --------------------
 * The cassette LLM mock is not yet wired into the docker compose
 * stack (Phase 4a is still deferred — see `send-and-stream.spec.ts`
 * § "Backend coordination" for the same constraint). All three M3
 * endpoints (`POST /api/chats/:id/share`, `DELETE`, `GET
 * /api/shared/:token`) ARE production-ready and exercised by 15
 * backend integration tests against real MySQL — those are the
 * regression anchor for the wire shape. This E2E asserts the
 * frontend's two-context flow against `page.route` mocks for the
 * SHARE endpoints (mirrors how every other M2 E2E mocks the chat
 * endpoints), so the spec is hermetic and deterministic without
 * waiting on Phase 4a.
 *
 * Multi-context contract
 * ----------------------
 * Two BrowserContexts, one per identity. Each context carries its
 * own `X-Forwarded-Email` via `extraHTTPHeaders`. The proxy header
 * is the only auth signal in the rebuild — `BrowserContext` is
 * the unit of isolation that matters for sharing tests (cookies,
 * storage, AND identity all stay scoped to the context).
 */

import { test, expect, type BrowserContext, type Page } from '@playwright/test';

const ALICE_EMAIL = 'alice@canva.com';
const BOB_EMAIL = 'bob@canva.com';
const CHAT_ID = '01900000-0000-7000-8000-000000003a01';
// 43-char URL-safe base64 token (mirrors `secrets.token_urlsafe(32)`).
const SHARE_TOKEN = 'JOURNEYM3sharetokenAAAAAAAAAAAAAAAAAAAAAAAAA';

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
  history: {
    messages: Record<string, unknown>;
    currentId: string | null;
  };
  share_id: string | null;
}

function aliceChatWithMessage(shareId: string | null): ChatStub {
  // hasMessages must be true for the Share button to render; ship a
  // single user/assistant pair so the modal opens.
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
          content: 'Hello',
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
          content: 'Hi there!',
          timestamp: NOW,
          model: 'gpt-4o',
          modelName: 'GPT-4o',
          done: true,
          error: null,
          cancelled: false,
          usage: { prompt_tokens: 8, completion_tokens: 3, total_tokens: 11 },
        },
      },
      currentId: 'a-1',
    },
    share_id: shareId,
  };
}

function snapshotFromAlice(): unknown {
  return {
    token: SHARE_TOKEN,
    title: 'Refactor draft',
    history: aliceChatWithMessage(SHARE_TOKEN).history,
    shared_by: { name: ALICE_EMAIL, email: ALICE_EMAIL },
    created_at: NOW,
  };
}

async function newIdentityContext(
  // Browser is fully typed by Playwright fixtures; importing the
  // fixture-arg type chain via `Parameters<...>` would couple this
  // helper to a private internal shape. The simplest stable option is
  // to take a pre-resolved factory.
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

test.describe('@e2e-m3 @journey-m3 share-and-read', () => {
  test('Alice shares a chat, Bob (new BrowserContext) opens the URL and reads the snapshot', async ({
    browser,
  }) => {
    // ---- Set up Alice's context. ------------------------------------
    const aliceCtx = await newIdentityContext(browser, ALICE_EMAIL);
    const alicePage = await aliceCtx.newPage();
    await bootDeterministically(alicePage);

    // GET /api/chats/<id> returns Alice's chat with messages so the
    // Share button renders. Initially share_id === null.
    let currentShareId: string | null = null;
    await aliceCtx.route(`**/api/chats/${CHAT_ID}`, async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(aliceChatWithMessage(currentShareId)),
        });
        return;
      }
      await route.continue();
    });

    // POST /api/chats/<id>/share mints the token. The local
    // `currentShareId` flips so subsequent GETs reflect the new state
    // (mirrors what the backend persists on the share row).
    let createCallCount = 0;
    await aliceCtx.route(`**/api/chats/${CHAT_ID}/share`, async (route) => {
      const method = route.request().method();
      if (method === 'POST') {
        createCallCount += 1;
        currentShareId = SHARE_TOKEN;
        await route.fulfill({
          status: 200,
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            token: SHARE_TOKEN,
            url: `/s/${SHARE_TOKEN}`,
            created_at: NOW,
          }),
        });
        return;
      }
      await route.continue();
    });

    // Sidebar list: empty so no extra fixtures intrude on the test.
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

    // The share-modal's `useEffect`-equivalent fires `shares.get` on
    // open in shared phase. Mock that here too — Alice never lands
    // on the public route, but the modal still calls `GET
    // /api/shared/{token}` to render the "Captured" line.
    await aliceCtx.route(`**/api/shared/${SHARE_TOKEN}`, async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(snapshotFromAlice()),
      });
    });

    // ---- Drive Alice's UI. ------------------------------------------
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

    // The Share button only renders when the chat has at least one
    // message — `aliceChatWithMessage(...)` provides that.
    const shareButton = alicePage.getByRole('button', { name: 'Share this chat' });
    await expect(shareButton).toBeVisible();
    await shareButton.click();

    // Modal opens in not-shared state; click Generate.
    await expect(alicePage.getByRole('heading', { name: 'Share this chat' })).toBeVisible();
    await alicePage.getByRole('button', { name: 'Generate share link' }).click();

    // The modal flips to shared state; the URL input shows the
    // absolute URL. Use `toHaveValue` so we assert the field's value
    // (the input is `readonly` so `getByDisplayValue` would also work).
    const urlInput = alicePage.getByRole('textbox', { name: 'Share link' });
    const expectedUrl = await alicePage.evaluate(
      (token) => `${window.location.origin}/s/${token}`,
      SHARE_TOKEN,
    );
    await expect(urlInput).toHaveValue(expectedUrl);
    expect(createCallCount).toBe(1);

    // The token is what Alice would copy and send to Bob — capture
    // it explicitly so the second context navigates to the exact
    // surface Alice would have produced.
    const aliceToken = (await urlInput.inputValue()).split('/').pop();
    expect(aliceToken).toBe(SHARE_TOKEN);

    // ---- Set up Bob's context. --------------------------------------
    const bobCtx = await newIdentityContext(browser, BOB_EMAIL);
    const bobPage = await bobCtx.newPage();
    await bootDeterministically(bobPage);

    // Bob's GET /api/shared/{token} returns the same snapshot Alice
    // generated. The fixture's `shared_by.name` is Alice's email
    // (the backend's snapshot uses the owner's User.name; the test
    // mock uses a stable string to avoid coupling to a User row).
    await bobCtx.route(`**/api/shared/${SHARE_TOKEN}`, async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(snapshotFromAlice()),
      });
    });

    // ---- Drive Bob's UI. --------------------------------------------
    await bobPage.goto(`/s/${SHARE_TOKEN}`);

    // The snapshot title is in the page header.
    await expect(bobPage.getByRole('heading', { name: 'Refactor draft', level: 1 })).toBeVisible();

    // The shared-by subline names Alice.
    await expect(bobPage.getByText(/Shared by alice@canva\.com/)).toBeVisible();

    // The user and assistant messages render.
    await expect(bobPage.getByText('Hello', { exact: true })).toBeVisible();
    await expect(bobPage.getByText('Hi there!', { exact: true })).toBeVisible();

    // Negative containment: the public view never renders the
    // composer, the regen affordances, or the model selector.
    await expect(bobPage.getByRole('textbox', { name: 'Compose a message' })).toHaveCount(0);
    await expect(bobPage.getByRole('button', { name: 'Regenerate message' })).toHaveCount(0);
    await expect(bobPage.getByRole('button', { name: /Model/ })).toHaveCount(0);

    await aliceCtx.close();
    await bobCtx.close();
  });
});
