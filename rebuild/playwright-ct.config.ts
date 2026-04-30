import { defineConfig, devices } from '@playwright/experimental-ct-svelte';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import tailwindcss from '@tailwindcss/vite';

// Resolve the EXACT same `@sveltejs/vite-plugin-svelte` copy that
// Playwright CT vendors under its own node_modules and import its
// ESM entry point by file URL. CT's framework-plugin auto-inject
// (in `node_modules/@playwright/experimental-ct-core/lib/viteUtils.js`
// createConfig) is gated behind `!baseAndUserConfig.plugins?.length`
// — adding a Tailwind plugin (which we MUST do for the role-token
// utilities to materialise during CT runs) trips that gate and the
// framework's svelte plugin is silently dropped. The project's own
// `@sveltejs/vite-plugin-svelte` is v4 and emits `.svelte` output
// that's *not* on the same module graph as svelte 5.55.x's runtime
// inside CT's bundler, which surfaces as `lifecycle_outside_component`
// from any `setContext(...)` call. Pinning the v5 vendored plugin
// keeps every `.svelte` import on the single svelte runtime CT loads.
const ctSveltePluginEntry = resolve(
  import.meta.dirname,
  'node_modules/@playwright/experimental-ct-svelte/node_modules/@sveltejs/vite-plugin-svelte/src/index.js',
);
const { svelte, vitePreprocess } = (await import(
  pathToFileURL(ctSveltePluginEntry).href
)) as typeof import('@sveltejs/vite-plugin-svelte');

// Playwright CT bundles components with its own Vite (currently v6),
// independent of the SvelteKit dev/build pipeline, so the SvelteKit
// `$lib` alias is NOT in scope here. Components that import from
// `$lib/...` (the M1 (app)/+layout.svelte constructs the ThemeStore via
// `$lib/stores/theme.svelte`) need the alias plumbed explicitly. Mirror
// what `kit.files.lib` declares in `svelte.config.js`.
const LIB_DIR = resolve(import.meta.dirname, 'frontend/src/lib');

// SvelteKit virtual-module stubs. The CT bundler does not load the
// `sveltekit()` Vite plugin (which would pull in the full Kit dev
// server), so any `.svelte` file that imports `$app/navigation` /
// `$app/state` / `$app/stores` (e.g. the M2 `(app)/+layout.svelte`'s
// `afterNavigate` and `Sidebar.svelte`'s `page.url.pathname`) fails
// to bundle with a Rollup "failed to resolve" error.
//
// The stubs at `frontend/playwright/sveltekit-stubs.ts` re-export the
// Kit lifecycle / nav helpers as no-ops and expose a frozen `page`
// object whose URL points at `/`. This is the smallest viable patch
// — and the long-term option (run the Kit plugin inside CT) trips the
// duplicate-Svelte-runtime gate documented above.
const SVELTEKIT_STUBS = resolve(import.meta.dirname, 'frontend/playwright/sveltekit-stubs.ts');
const SVELTEKIT_ENV_STUBS = resolve(
  import.meta.dirname,
  'frontend/playwright/sveltekit-env-stubs.ts',
);

export default defineConfig({
  testDir: './frontend/tests/component',
  use: {
    ctPort: 3100,
    ctTemplateDir: './frontend/playwright',
    ctViteConfig: {
      // Tailwind 4 scans for utility usage at bundle time. M1's
      // ThemePicker (and the M1 component specs that read computed
      // styles to verify per-tile cascade) depend on `bg-background-
      // app`, `outline-accent-selection`, ... existing as real CSS
      // rules — without the Tailwind plugin those classes silently
      // become no-ops. The svelte plugin is loaded from CT's vendored
      // copy (see top-of-file note) so we stay on a single svelte
      // runtime.
      // Cast through `any[]` because CT's `ctViteConfig` is typed against
      // CT's vendored vite, while `tailwindcss()` and `svelte()` return
      // plugins typed against the project's own vite — same module, two
      // type identities. The runtime is fine; the type error is just
      // duplicate-package noise.
      plugins: [tailwindcss(), svelte({ preprocess: vitePreprocess() })] as any[],
      resolve: {
        alias: {
          $lib: LIB_DIR,
          // Stub SvelteKit virtual modules (see SVELTEKIT_STUBS comment
          // above). Order matters: more specific paths first so vite
          // doesn't accidentally swallow `$app` itself before the
          // sub-path matchers run.
          '$app/navigation': SVELTEKIT_STUBS,
          '$app/state': SVELTEKIT_STUBS,
          '$app/stores': SVELTEKIT_STUBS,
          '$env/static/public': SVELTEKIT_ENV_STUBS,
          '$env/dynamic/public': SVELTEKIT_ENV_STUBS,
        },
      },
    },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
