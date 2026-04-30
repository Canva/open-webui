/**
 * SvelteKit virtual-module stubs for Playwright Component Testing.
 *
 * Why this file exists
 * --------------------
 * The CT bundler (`playwright-ct.config.ts`) loads the bare
 * `@sveltejs/vite-plugin-svelte` plugin so a single Svelte 5 runtime
 * is on the module graph. It deliberately does NOT load the
 * `sveltekit()` plugin (which would pull in the full Kit dev-server
 * pipeline). Without that plugin, the `$app/...` virtual modules
 * never resolve and any `.svelte` file that imports them at module
 * scope (e.g. the M2 `(app)/+layout.svelte`'s
 * `import { afterNavigate } from '$app/navigation'`) fails to
 * bundle with a Rollup "failed to resolve" error.
 *
 * The fix here is the smallest possible: a stub module that exports
 * harmless no-ops + a frozen page object whose URL points at `/`.
 * Specs that need to drive navigation can still call the exposed
 * `afterNavigate` callback synchronously through the harness, but in
 * practice every M2 component test cares about the rendered DOM,
 * not about Kit lifecycle.
 *
 * Three virtual paths share the same stub via the alias declared in
 * `playwright-ct.config.ts`:
 *   - `$app/navigation` (afterNavigate, beforeNavigate, goto, ...)
 *   - `$app/state`      (page reactive state)
 *   - `$app/stores`     (legacy page/getStores; banned by lint:grep
 *                        in source but kept here for completeness so
 *                        a stray import doesn't break the bundle).
 */

type NavCallback = (...args: unknown[]) => unknown;

/** No-op lifecycle hooks. */
export function afterNavigate(_cb: NavCallback): void {
  /* CT runtime: no Kit router, so nothing to call. */
}
export function beforeNavigate(_cb: NavCallback): void {
  /* CT runtime: no Kit router, so nothing to call. */
}
export function onNavigate(_cb: NavCallback): void {
  /* CT runtime: no Kit router, so nothing to call. */
}

/** No-op imperative navigation. Returns a resolved Promise so `await goto(...)` works. */
export async function goto(_href: string, _opts?: unknown): Promise<void> {
  /* CT runtime: no Kit router. The harness controls the URL via
   * window.history when a spec genuinely needs it. */
}

/** Resolve a route to a Kit-style URL string. CT just returns the input. */
export function resolveRoute(href: string): string {
  return href;
}

export function invalidate(_dep: unknown): Promise<void> {
  return Promise.resolve();
}
export function invalidateAll(): Promise<void> {
  return Promise.resolve();
}
export function preloadCode(..._urls: string[]): Promise<void> {
  return Promise.resolve();
}
export function preloadData(_href: string): Promise<unknown> {
  return Promise.resolve(null);
}
export function disableScrollHandling(): void {
  /* CT runtime: no Kit router. */
}
export function pushState(_url: string, _state: unknown): void {
  /* CT runtime: noop. */
}
export function replaceState(_url: string, _state: unknown): void {
  /* CT runtime: noop. */
}

/**
 * Reactive page stub. Components that read `page.url.pathname` get
 * a sane root URL; components that read `page.params` / `page.data`
 * get empty objects. Mutating these from a spec is harmless because
 * no consumer subscribes via Kit's stores layer in CT.
 *
 * The shape mirrors `import { page } from '$app/state'` from
 * SvelteKit 2.x — a plain reactive object, not a writable store.
 */
const pageStub = {
  url: new URL('http://localhost:3100/'),
  params: {} as Record<string, string>,
  route: { id: null as string | null },
  status: 200,
  error: null as Error | null,
  data: {} as Record<string, unknown>,
  form: null as unknown,
  state: {} as Record<string, unknown>,
};

export const page = pageStub;

/**
 * Allow specs to override the page URL via the harness without
 * having to know about `import.meta` plumbing. Exposed at the
 * module level so a test can `setPagePath('/c/abc')` to drive
 * `Sidebar`'s `activeId = page.url.pathname.match(...)` derivation.
 */
export function setPagePath(pathname: string): void {
  pageStub.url = new URL(pathname, 'http://localhost:3100');
}

/** Legacy `$app/stores` shape (banned in source by lint:grep but stubbed
 *  here for completeness so a stray legacy import doesn't break the bundle). */
function readableStub<T>(value: T) {
  return {
    subscribe(run: (v: T) => void): () => void {
      run(value);
      return () => {
        /* unsubscribe */
      };
    },
  };
}

export const navigating = readableStub<null>(null);
export const updated = {
  ...readableStub<boolean>(false),
  check(): Promise<boolean> {
    return Promise.resolve(false);
  },
};

export function getStores(): {
  page: typeof pageStub;
  navigating: ReturnType<typeof readableStub<null>>;
  updated: typeof updated;
} {
  return { page: pageStub, navigating, updated };
}
