import { defineConfig, devices } from '@playwright/test';

// E2E projects run against the SvelteKit app (default port 5173). The
// trusted-header proxy is simulated by injecting `X-Forwarded-Email` on
// every request; the M0 backend's `get_user` dep upserts the user from
// that header, so a fresh DB still passes the @smoke spec.
//
// `globalSetup` (test-author addition, m0 plan § Tooling § Playwright)
// brings up `infra/docker-compose.yml` so the backend is reachable on
// :8080 before the dev server starts. It returns a teardown function
// (Playwright supports this) that runs `docker compose down -v` after
// the suite finishes. Set `REBUILD_SKIP_COMPOSE=1` to skip when the
// stack is already up (e.g. shared between Buildkite steps).
//
// `webServer` runs `npm run dev` so a fresh checkout can `make
// test-e2e-smoke` without manually starting Vite. Reuses an existing
// dev server when one is already listening on :5173.
export default defineConfig({
  testDir: './frontend/tests/e2e',
  globalSetup: './frontend/tests/globalSetup.ts',
  use: {
    baseURL: 'http://localhost:5173',
    extraHTTPHeaders: { 'X-Forwarded-Email': 'alice@canva.com' },
  },
  webServer: {
    command: 'npm run -s dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],
});
