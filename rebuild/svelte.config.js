import adapter from '@sveltejs/adapter-node';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

// The SvelteKit project root is `rebuild/`, but the source tree (per the m0
// plan layout) lives under `rebuild/frontend/`. Override `kit.files` so
// SvelteKit resolves `app.html`, routes, hooks, lib, params, and static
// assets from `frontend/` instead of the default top-level `src/`.
const config = {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({ out: 'frontend/build' }),
    files: {
      appTemplate: 'frontend/src/app.html',
      assets: 'frontend/static',
      hooks: {
        client: 'frontend/src/hooks.client',
        server: 'frontend/src/hooks.server',
        universal: 'frontend/src/hooks',
      },
      lib: 'frontend/src/lib',
      params: 'frontend/src/params',
      routes: 'frontend/src/routes',
      serviceWorker: 'frontend/src/service-worker',
    },
    outDir: '.svelte-kit',
  },
};

export default config;
