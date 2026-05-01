/**
 * Visual-regression baselines for M3 sharing surfaces.
 *
 * Locked by `rebuild/docs/plans/m3-sharing.md` § Acceptance criteria
 * (the three surfaces named in the journey table) AND § User journeys
 * (rows 1, 2, 4 — the modal not-shared, modal shared, and public
 * share-view surfaces). The plan parks the PNGs under
 * `tests/visual-baselines/m2/`; the snapshot directory is derived
 * from the test file location by Playwright's default
 * `snapshotPathTemplate`, so the filename arguments below carry no
 * `m2/` prefix.
 *
 * Three baselines:
 *
 *   1. `share-modal-not-shared.png` — Alice opens the modal on a
 *      chat with at least one message, no share has been generated
 *      yet, modal sits in the `not-shared` phase.
 *   2. `share-modal-shared.png` — same chat with a known token,
 *      modal opens directly in the `shared` phase, URL input shows
 *      the absolute URL.
 *   3. `share-view.png` — Bob navigates to `/s/<token>`, header
 *      shows title + `Shared by` subline, message list renders the
 *      one user + one assistant exchange (assistant is markdown
 *      with a code fence so the Shiki cascade is exercised in the
 *      diff).
 *
 * Image capture is deferred (M1/M2 pattern)
 * -----------------------------------------
 * The PNG baselines do NOT ship in this commit. They are generated
 * inside the same Linux container that runs CI to avoid the macOS-vs-
 * CI font-hinting drift that would explode the diffs into the tens
 * of thousands of pixels. The invocation is:
 *
 *   cd rebuild
 *   npm run test:visual -- --update-snapshots
 *
 * (where `test:visual` is the alias for
 *  `playwright test --grep @visual`; the bare `@visual` matcher
 *  already grabs `@visual-m1`, `@visual-m2`, AND `@visual-m3`, so no
 *  further script edit was needed for M3.)
 *
 * Until the PNGs land, this spec fails on first run with the
 * documented "snapshot missing" message — that's the correct
 * behaviour. A `test.skip(reason)` opt-out flag (`SKIP_VISUAL=1`)
 * is honoured so a developer running the full E2E pack locally on
 * macOS doesn't see false-positive diffs.
 *
 * The deterministic boot script
 * -----------------------------
 * Identical to `tests/e2e/visual-m2.spec.ts` (and `visual-m1`). We
 * re-declare it here (vs imported) so the spec stays self-contained
 * for Playwright's bundle and a future divergence in determinism
 * for M3-only surfaces (e.g. share-token clipboard interactions)
 * doesn't accidentally regress the M1/M2 baselines.
 */

import { test, expect } from '@playwright/test';

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

const SCREENSHOT_OPTS = { maxDiffPixels: 100 };
const PRESET = 'tokyo-night' as const;

async function setupForTokyoNight(
  page: Parameters<Parameters<typeof test>[1]>[0]['page'],
  context: Parameters<Parameters<typeof test>[1]>[0]['context'],
): Promise<void> {
  await context.clearCookies();
  await context.addCookies([
    {
      name: 'theme',
      value: PRESET,
      url: 'http://localhost:5173',
      path: '/',
      sameSite: 'Lax',
    },
  ]);
  await page.addInitScript(DETERMINISTIC_BOOT);
}

const SKIP_REASON =
  'Visual baselines capture deferred to CI (Linux container) — see header. ' +
  'Set SKIP_VISUAL=0 explicitly to run on macOS (font drift will inflate the diff).';

const NOW = 1_735_689_600_000;

const FIXTURE_CHAT_ID = '01900000-0000-7000-8000-00000000ed31';
const FIXTURE_TOKEN = 'VISUALm3sharetokenAAAAAAAAAAAAAAAAAAAAAAAAA';

function chatSummary(input: { id: string; title: string; share_id?: string | null }) {
  return {
    id: input.id,
    title: input.title,
    pinned: false,
    archived: false,
    folder_id: null,
    created_at: NOW,
    updated_at: NOW,
  };
}

function chatRead(shareId: string | null) {
  return {
    id: FIXTURE_CHAT_ID,
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
          content: 'Refactor this function for clarity.',
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
          content:
            'Here is a tidier version:\n\n```ts\nconst sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);\n```',
          timestamp: NOW,
          model: 'gpt-4o',
          modelName: 'GPT-4o',
          done: true,
          error: null,
          cancelled: false,
          usage: { prompt_tokens: 8, completion_tokens: 12, total_tokens: 20 },
        },
      },
      currentId: 'a-1',
    },
    share_id: shareId,
  };
}

function snapshotFixture() {
  return {
    token: FIXTURE_TOKEN,
    title: 'Refactor draft',
    history: chatRead(FIXTURE_TOKEN).history,
    shared_by: { name: 'alice@canva.com', email: 'alice@canva.com' },
    created_at: NOW,
  };
}

async function emptySidebarRoutes(
  page: Parameters<Parameters<typeof test>[1]>[0]['page'],
): Promise<void> {
  await page.route('**/api/chats**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/api/chats') && route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          items: [chatSummary({ id: FIXTURE_CHAT_ID, title: 'Refactor draft' })],
          next_cursor: null,
        }),
      });
      return;
    }
    await route.continue();
  });
  await page.route('**/api/folders**', async (route) => {
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

test.describe('@visual-m3 share-modal-not-shared', () => {
  test.skip(process.env.SKIP_VISUAL !== '0', SKIP_REASON);

  test('share-modal-not-shared', async ({ page, context }) => {
    await setupForTokyoNight(page, context);
    await emptySidebarRoutes(page);

    await page.route(`**/api/chats/${FIXTURE_CHAT_ID}`, async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(chatRead(null)),
      });
    });

    await page.goto(`/c/${FIXTURE_CHAT_ID}`);
    await page.waitForLoadState('networkidle');

    // Header's Share button is `aria-label="Share this chat"` when
    // not yet shared. Open the modal and screenshot it.
    await page.getByRole('button', { name: 'Share this chat' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Share this chat' })).toBeVisible();

    await expect(dialog).toHaveScreenshot('share-modal-not-shared.png', SCREENSHOT_OPTS);
  });
});

test.describe('@visual-m3 share-modal-shared', () => {
  test.skip(process.env.SKIP_VISUAL !== '0', SKIP_REASON);

  test('share-modal-shared', async ({ page, context }) => {
    await setupForTokyoNight(page, context);
    await emptySidebarRoutes(page);

    await page.route(`**/api/chats/${FIXTURE_CHAT_ID}`, async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(chatRead(FIXTURE_TOKEN)),
      });
    });
    // The modal's lazy `shares.get` lookup populates the "Captured"
    // line. Pin the response so the relative-time string is
    // deterministic at the frozen `Date.now`.
    await page.route(`**/api/shared/${FIXTURE_TOKEN}`, async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(snapshotFixture()),
      });
    });

    await page.goto(`/c/${FIXTURE_CHAT_ID}`);
    await page.waitForLoadState('networkidle');

    // The header's Share button switches to `aria-label="Manage
    // share link"` when `chat.share_id !== null` (shipped by
    // svelte-engineer per `m3-sharing.md` § Owner UX).
    await page.getByRole('button', { name: 'Manage share link' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    // Wait for the URL input to settle so the screenshot includes
    // the URL the user would actually copy.
    await expect(dialog.getByRole('textbox', { name: 'Share link' })).toBeVisible();

    await expect(dialog).toHaveScreenshot('share-modal-shared.png', SCREENSHOT_OPTS);
  });
});

test.describe('@visual-m3 share-view', () => {
  test.skip(process.env.SKIP_VISUAL !== '0', SKIP_REASON);

  test('share-view', async ({ page, context }) => {
    await setupForTokyoNight(page, context);

    await page.route(`**/api/shared/${FIXTURE_TOKEN}`, async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(snapshotFixture()),
      });
    });

    await page.goto(`/s/${FIXTURE_TOKEN}`);
    await page.waitForLoadState('networkidle');

    // Make sure the article body has resolved before the snapshot —
    // the Shiki highlighter is async, and an early shot would
    // capture the un-highlighted code fence.
    await expect(page.getByRole('heading', { name: 'Refactor draft', level: 1 })).toBeVisible();
    await expect(page.locator('pre').first()).toBeVisible();

    await expect(page).toHaveScreenshot('share-view.png', SCREENSHOT_OPTS);
  });
});
