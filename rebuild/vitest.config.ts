import { defineConfig } from 'vitest/config';
import { sveltekit } from '@sveltejs/kit/vite';

// Include both colocated specs (`src/**/*.test.ts`) and the dedicated unit
// tree (`frontend/tests/unit/**/*.test.ts`) so the m0 § Tests gating M0
// "Vitest: typed fetch client (de)serializes UserRead from a fixture"
// regression at `frontend/tests/unit/api-client.test.ts` is picked up by
// `npm run test:unit` (test-author addition, m0 § Tooling § Vitest).
export default defineConfig({
  plugins: [sveltekit()],
  test: {
    environment: 'jsdom',
    include: ['frontend/src/**/*.{test,spec}.ts', 'frontend/tests/unit/**/*.{test,spec}.ts'],
    setupFiles: ['./frontend/src/lib/msw/node.ts'],
  },
});
