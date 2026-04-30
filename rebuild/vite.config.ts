import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';
import { themeEmitTokens } from './frontend/src/lib/theme/vite-emit-tokens';

export default defineConfig({
  // Order matters: themeEmitTokens regenerates `lib/theme/tokens.css`
  // BEFORE the Tailwind plugin scans it (`enforce: 'pre'` and explicit
  // ordering both backstop this). Without that ordering the first dev
  // boot would scan a stale (or missing) tokens.css.
  plugins: [themeEmitTokens(), tailwindcss(), sveltekit()],
  server: {
    port: 5173,
    host: true,
    // SvelteKit's `kit.files` overrides put the source tree under
    // `rebuild/frontend/src/`, but Vite's default fs allowlist only adds
    // `lib/` and `routes/` (plus the conventional `<root>/src`). That
    // leaves bare files like `frontend/src/app.css` and `frontend/src/
    // app.html` outside the allowlist, so the dev server 404s on the
    // global stylesheet import. Allow the whole `frontend/` subtree so
    // top-level entrypoints resolve.
    fs: {
      allow: ['frontend'],
    },
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: false,
      },
    },
  },
});
