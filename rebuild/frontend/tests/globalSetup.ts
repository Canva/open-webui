import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * Playwright global setup for the M0 @smoke pack (m0 plan § Tests gating
 * M0). Brings up `infra/docker-compose.yml` (mysql + redis + app) with
 * `--wait` so all healthchecks are green before the first browser context
 * opens, and returns a teardown that runs `docker compose down -v` after
 * the entire run finishes (Playwright supports a globalSetup return-as-
 * teardown).
 *
 * Idempotency: skipped when the env var `REBUILD_SKIP_COMPOSE=1` is set
 * (use this when `docker compose up -d --wait` was invoked manually
 * before the run, e.g. from a Buildkite step that needs the stack alive
 * for multiple test commands).
 *
 * Portability: relies on `docker compose` being on PATH. The dispatch
 * authorises this trade-off — the rebuild's local-dev story already
 * requires Docker per `infra/docker-compose.yml` and the Makefile target
 * `make dev`.
 *
 * Dev-server (`webServer`) note: `webServer` is registered in
 * `playwright.config.ts`, not here, because Playwright requires the
 * `webServer` block to be at the top level of the config.
 */

// `__dirname` is not defined in ESM modules; derive from `import.meta.url`
// so this file works whether Playwright runs it via the CommonJS or ESM
// loader (Playwright transpiles globalSetup; the loader pick depends on
// the runner's tsconfig at the time of the run).
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const REBUILD_ROOT = resolve(__dirname, '..', '..');
const COMPOSE_FILE = resolve(REBUILD_ROOT, 'infra', 'docker-compose.yml');

let webServerProcess: ChildProcess | null = null;

export default async function globalSetup(): Promise<() => Promise<void>> {
  if (process.env.REBUILD_SKIP_COMPOSE === '1') {
    console.log('[playwright globalSetup] REBUILD_SKIP_COMPOSE=1; assuming infra is already up.');
    return async () => {
      /* no-op teardown */
    };
  }

  if (!existsSync(COMPOSE_FILE)) {
    throw new Error(
      `[playwright globalSetup] expected compose file at ${COMPOSE_FILE}; ` +
        `is the rebuild/ directory layout intact?`,
    );
  }

  console.log(`[playwright globalSetup] docker compose -f ${COMPOSE_FILE} up -d --wait`);
  const up = spawnSync('docker', ['compose', '-f', COMPOSE_FILE, 'up', '-d', '--wait'], {
    stdio: 'inherit',
    cwd: REBUILD_ROOT,
  });
  if (up.status !== 0) {
    throw new Error(`[playwright globalSetup] docker compose up failed (exit ${up.status})`);
  }

  return async () => {
    console.log(`[playwright globalSetup] docker compose -f ${COMPOSE_FILE} down -v`);
    spawnSync('docker', ['compose', '-f', COMPOSE_FILE, 'down', '-v'], {
      stdio: 'inherit',
      cwd: REBUILD_ROOT,
    });
    // Defensive: kill any vite dev server we spawned earlier so the
    // pid doesn't outlive the test run on local interactive use.
    if (webServerProcess && !webServerProcess.killed) {
      webServerProcess.kill('SIGTERM');
    }
  };
}

// Exported so unit tests / debugging code can reuse the same spawn shape.
export function _internalSpawnVite(): ChildProcess {
  webServerProcess = spawn('npm', ['run', '-s', 'dev'], {
    stdio: 'inherit',
    cwd: REBUILD_ROOT,
    env: { ...process.env },
  });
  return webServerProcess;
}
