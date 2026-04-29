import { setupServer } from 'msw/node';
import { handlers } from './handlers';

/**
 * Node-side MSW server. Used as a Vitest setup file (see `vitest.config.ts`)
 * and as the CT global `beforeMount` hook (see `frontend/playwright/index.ts`)
 * so unit and component tests intercept network at the request layer without
 * touching real HTTP. Production bundles never import this.
 */
export const server = setupServer(...handlers);

// Vitest setup-file lifecycle. Importing the module is enough; the global
// hooks below are picked up because `vitest.config.ts` lists this file in
// `test.setupFiles`.
//
// `globalThis.beforeAll` etc are typed by Vitest at its discretion; cast
// through unknown to avoid pulling Vitest's type surface into the production
// bundle.
type Lifecycle = ((fn: () => void | Promise<void>) => void) | undefined;
const g = globalThis as unknown as {
  beforeAll?: Lifecycle;
  afterEach?: Lifecycle;
  afterAll?: Lifecycle;
};

g.beforeAll?.(() => server.listen({ onUnhandledRequest: 'error' }));
g.afterEach?.(() => server.resetHandlers());
g.afterAll?.(() => server.close());
