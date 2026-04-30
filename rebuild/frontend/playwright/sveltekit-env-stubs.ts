/**
 * `$env/static/public` stub for Playwright Component Testing.
 *
 * Why this file exists
 * --------------------
 * `lib/api/client.ts` imports `PUBLIC_API_BASE_URL` from
 * `$env/static/public`. The CT bundler does not run the SvelteKit
 * Vite plugin (see the comment in `playwright-ct.config.ts`), so
 * the virtual module never resolves and the bundle fails.
 *
 * The CT specs do not actually fire HTTP requests (the harnesses
 * stub the store methods that would call `chatsApi.send` etc.), so
 * the value here only has to be a valid URL string. Pin it to
 * `localhost` so a stray real fetch fails loudly with a connection
 * error instead of silently leaking to a real backend.
 *
 * Add new `PUBLIC_*` symbols here as components reach for them.
 */

export const PUBLIC_API_BASE_URL = 'http://localhost:65535';
