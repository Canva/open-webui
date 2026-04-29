import { test, expect } from '@playwright/test';

// Tagged @smoke (m0 plan § Tests gating M0). `playwright.config.ts`
// declares chromium + firefox + webkit projects, so this file gives us
// browser-matrix coverage of the M0 round-trip:
//
//   - GET /  with X-Forwarded-Email -> the email appears in the DOM AND
//     the network call to /api/me returned 200.
//   - GET /  without headers        -> graceful "Sign in via the proxy"
//     fallback copy (NOT a 500 page).
//
// The default `extraHTTPHeaders: { X-Forwarded-Email: alice@canva.com }`
// from playwright.config.ts is inherited by the first test. The negative
// case opens its own browser context with no extra headers.

test('@smoke trusted-header round-trip surfaces the email and hits /api/me', async ({ page }) => {
  const apiMeStatuses: number[] = [];
  page.on('response', (response) => {
    if (response.url().endsWith('/api/me')) {
      apiMeStatuses.push(response.status());
    }
  });

  await page.goto('/');

  // The trusted-header email must appear on the rendered page.
  await expect(page.getByText('alice@canva.com', { exact: true })).toBeVisible();

  // And the network call to /api/me must have returned 200. The actual
  // request happens server-side (hooks.server.ts handle calls
  // event.fetch('/api/me')); when SvelteKit's enhanced fetch replays
  // into the SSR page, the response shows up on the page network log.
  // If the request is never observed by `page.on('response')` because
  // it stayed entirely server-side, we fall back to a fresh client-side
  // fetch via `page.request` to assert the same contract.
  if (apiMeStatuses.length === 0) {
    const r = await page.request.get('/api/me');
    expect(r.status()).toBe(200);
  } else {
    expect(apiMeStatuses).toContain(200);
  }
});

test('@smoke no-header context falls back to the recovery copy without a 500', async ({
  browser,
}) => {
  const context = await browser.newContext({ extraHTTPHeaders: {} });
  const page = await context.newPage();

  const response = await page.goto('/');
  // SvelteKit returns 200 with the layout's fallback copy when the
  // trusted header is absent — `hooks.server.ts handle` sets
  // `locals.user = null`, and `+layout.svelte` renders the recovery
  // branch. A 500 here would indicate the layout / load chain blew up
  // on `data.user === null`.
  expect(response?.status()).toBeLessThan(500);
  await expect(page.getByText(/proxy header/i)).toBeVisible();
  await expect(page.getByText('X-Forwarded-Email', { exact: true })).toBeVisible();

  await context.close();
});
