import { handlers } from './handlers';

type BrowserWorker = { start: (options?: unknown) => Promise<unknown>; stop: () => void };

/**
 * No-op default export so SSR imports never resolve `msw/browser`. M0
 * never starts the worker; M2+ that wants client-side mocking calls
 * `startMockWorker()` from a top-level layout effect, gated on
 * `import.meta.env.DEV && PUBLIC_USE_MSW === '1'`.
 */
export const worker: BrowserWorker | null = null;

/**
 * Lazily start the MSW browser worker. Returns `null` in the server
 * runtime, in production builds, or when `PUBLIC_USE_MSW !== '1'`. The
 * dynamic import keeps `msw/browser` out of the server bundle.
 */
export async function startMockWorker(): Promise<BrowserWorker | null> {
  if (typeof window === 'undefined') return null;
  if (!import.meta.env.DEV) return null;
  const flag = (import.meta.env as Record<string, string | undefined>).PUBLIC_USE_MSW;
  if (flag !== '1') return null;
  const { setupWorker } = await import('msw/browser');
  const w = setupWorker(...handlers) as unknown as BrowserWorker;
  await w.start({ onUnhandledRequest: 'bypass' });
  return w;
}
