import js from '@eslint/js';
import tsParser from '@typescript-eslint/parser';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import sveltePlugin from 'eslint-plugin-svelte';
import svelteParser from 'svelte-eslint-parser';
import prettierConfig from 'eslint-config-prettier';

// Flat config (ESLint 9). Pinned to enforce the M0 § Frontend conventions
// "Svelte 5 idioms; what to use, what is banned" table:
//
//   - createEventDispatcher     -> banned via no-restricted-imports.
//   - $app/stores               -> banned via no-restricted-imports
//                                  (deprecated since SvelteKit 2.12).
//   - <slot> elements           -> banned via the `lint:grep` npm script
//                                  (see package.json). eslint-plugin-svelte
//                                  2.46 ships `no-dynamic-slot-name` and
//                                  `experimental-require-slot-types` but
//                                  NOT a rule that flags `<slot>` element
//                                  usage as a whole, so the grep gate is
//                                  the only mechanical backstop available
//                                  without bumping the plugin major.
//   - on:click / on:input etc.  -> NOT cleanly catchable with stock plugin
//                                  rules in eslint-plugin-svelte 2.46. The
//                                  m0 plan calls for a grep gate in the lint
//                                  step as the backstop; documented as a
//                                  known limitation here so the gap is
//                                  visible rather than implicit.
//   - use:action directives     -> same as above; covered by the grep gate.
//   - uuid (any) under frontend -> banned defensively (UUIDs are minted
//                                  server-side via app.core.ids.new_id()).
//
// The `lint` npm script chains `eslint . && prettier --check . && lint:grep`
// in that order so a failing grep gate surfaces only after the parser-aware
// checks have passed (cleaner error attribution).
//
const restrictedImports = {
  paths: [
    {
      name: 'svelte',
      importNames: ['createEventDispatcher'],
      message:
        'createEventDispatcher is banned in Svelte 5. Use callback props (onfoo / onclick). See rebuild/docs/plans/m0-foundations.md § Frontend conventions.',
    },
    {
      name: '$app/stores',
      message:
        '$app/stores is deprecated since SvelteKit 2.12. Import from $app/state instead. See rebuild/docs/plans/m0-foundations.md § Frontend conventions.',
    },
    {
      name: 'uuid',
      message:
        'UUIDs are minted server-side via app.core.ids.new_id() (UUIDv7). The frontend never generates IDs. See rebuild/docs/plans/m0-foundations.md § ID and time helpers.',
    },
  ],
  patterns: [
    {
      group: ['uuid/*'],
      message:
        'UUIDs are minted server-side via app.core.ids.new_id() (UUIDv7). The frontend never generates IDs.',
    },
  ],
};

export default [
  {
    ignores: [
      '.svelte-kit/**',
      // SvelteKit writes its generated client/server modules into
      // `frontend/.svelte-kit/` on every dev/build (including the typed
      // `$app/*` re-exports and the client app entry under
      // `generated/client/`). Those are auto-generated, not human-authored,
      // and reference identifiers (e.g. `console`) without a matching
      // ESLint globals block — so without this entry they flood `no-undef`.
      'frontend/.svelte-kit/**',
      // adapter-node writes its production artifact to `frontend/build/` per
      // `kit.adapter` in svelte.config.js (co-located with the rest of the
      // frontend tree so the Dockerfile's stage-3 `COPY --from=frontend
      // /work/frontend/build /app/frontend` resolves). The legacy `build/**`
      // entry below is a defensive catch for stray runs from the wrong cwd
      // and stays even though the configured output path is now nested.
      'frontend/build/**',
      'build/**',
      'dist/**',
      'node_modules/**',
      // Python virtual envs bundle JS assets (coverage HTML, urllib3
      // emscripten worker). They are not project code; never lint them.
      '**/.venv/**',
      'frontend/static/mockServiceWorker.js',
      'playwright-report/**',
      'test-results/**',
      // Playwright CT writes its Vite bundle into `<templateDir>/.cache/`
      // on every CT run (templateDir is `frontend/playwright/` per
      // `playwright-ct.config.ts`'s `ctTemplateDir`). Those generated JS
      // files reference Playwright-injected globals (e.g. `__pwRegistry`)
      // that aren't visible to ESLint and would flood `no-undef`.
      'frontend/playwright/.cache/**',
    ],
  },
  js.configs.recommended,
  ...sveltePlugin.configs['flat/recommended'],
  prettierConfig,
  {
    // Includes `frontend/tests/**/*.{ts,js}` so test-author specs (Vitest,
    // Playwright CT, Playwright E2E, the globalSetup runner) lint on the
    // same rules as production source. Without this glob, ESLint flat
    // config refuses to walk those files at all (no matching block).
    files: [
      'frontend/src/**/*.{ts,js}',
      'frontend/tests/**/*.{ts,js}',
      // CT runtime infrastructure: the SvelteKit virtual-module stubs
      // and any other test-only helpers under `frontend/playwright/`
      // (see `playwright-ct.config.ts` for why those exist).
      'frontend/playwright/**/*.{ts,js}',
      '*.config.{ts,js}',
      '*.config.cjs',
    ],
    languageOptions: {
      parser: tsParser,
      parserOptions: { ecmaVersion: 2022, sourceType: 'module' },
      globals: {
        // Browser globals available in client modules.
        window: 'readonly',
        document: 'readonly',
        fetch: 'readonly',
        console: 'readonly',
        // M1 component / E2E specs reach into the page context via
        // `page.evaluate(() => ...)` and `await harness.locator(...)
        // .evaluate(el => getComputedStyle(el)...)`. The callback runs
        // in the browser (where `localStorage` and `getComputedStyle`
        // are obviously defined), but ESLint sees the source as plain
        // TS in the worker context. Allow-list the identifiers so
        // legitimate browser-context evaluate callbacks lint cleanly.
        localStorage: 'readonly',
        getComputedStyle: 'readonly',
        MutationObserver: 'readonly',
        // Browser DOM interface types used as TypeScript annotations
        // (`bind:this={el}` callbacks, MediaQueryList listeners, etc.).
        // ESLint's `no-undef` flags TS interface names the same way it
        // flags runtime identifiers, so the names must be declared here.
        Element: 'readonly',
        HTMLElement: 'readonly',
        HTMLDivElement: 'readonly',
        HTMLInputElement: 'readonly',
        HTMLButtonElement: 'readonly',
        HTMLAnchorElement: 'readonly',
        MediaQueryList: 'readonly',
        MediaQueryListEvent: 'readonly',
        // Document / Location / Storage are referenced by Vitest specs
        // that drive `Document.prototype.cookie` setters, stub
        // `window.location` via `as Location`, and stub `localStorage`
        // via `as Partial<Storage>` (see persistence.spec.ts). Same TS
        // type-position concern as the HTML* names above.
        Document: 'readonly',
        Location: 'readonly',
        Storage: 'readonly',
        // M2 streaming + cancellation primitives. `AbortController` /
        // `AbortSignal` thread through `ActiveChatStore.send()` into
        // the `chats.send` client method; `crypto.randomUUID()` mints
        // optimistic temp ids in chats / folders / toast stores;
        // `ReadableStream` / `TextDecoder` are the Web-Streams API
        // building blocks consumed by `lib/utils/sse.ts`; `DOMException`
        // is the universal `AbortError` shape across browsers and
        // Node's undici.
        AbortController: 'readonly',
        AbortSignal: 'readonly',
        DOMException: 'readonly',
        ReadableStream: 'readonly',
        TextDecoder: 'readonly',
        TextEncoder: 'readonly',
        crypto: 'readonly',
        // Drag-and-drop primitives used by the sidebar specs that
        // synthesise a HTML5 DnD sequence inside `page.evaluate(...)`.
        // The callbacks run in the browser; ESLint sees the source as
        // plain TS in the worker, so the names must be allow-listed.
        DataTransfer: 'readonly',
        DragEvent: 'readonly',
        // Timer + microtask helpers: E2E specs that pace artificial
        // SSE streams (see `tests/e2e/cancel-mid-stream.spec.ts`)
        // need `setTimeout` available at module scope.
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        setInterval: 'readonly',
        clearInterval: 'readonly',
        queueMicrotask: 'readonly',
        // Node globals available in server modules / configs.
        process: 'readonly',
        URL: 'readonly',
        Request: 'readonly',
        Response: 'readonly',
        RequestInit: 'readonly',
        Headers: 'readonly',
        Buffer: 'readonly',
        // Svelte 5 runes — compiler-recognised globals inside `.svelte`
        // and `*.svelte.ts` files. Declared here so `no-undef` doesn't
        // flag them in store modules; the Svelte compiler is the real
        // gate on legitimate use (using `$state` in a plain `.ts` file
        // is a build-time error there, not a lint concern).
        $state: 'readonly',
        $derived: 'readonly',
        $effect: 'readonly',
        $props: 'readonly',
        $bindable: 'readonly',
        $host: 'readonly',
        $inspect: 'readonly',
      },
    },
    plugins: { '@typescript-eslint': tsPlugin },
    rules: {
      'no-restricted-imports': ['error', restrictedImports],
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
    },
  },
  {
    // Also covers `frontend/tests/**/*.svelte` so test-author's CT
    // harnesses (e.g. LayoutHarness.svelte that wraps +layout.svelte
    // with a stub `children` snippet — required because Playwright CT
    // cannot serialise a Snippet across the worker boundary) parse
    // through the svelte parser. Without this glob, eslint falls back
    // to the JS parser on `.svelte` files in tests/ and explodes on
    // the first `{@render}`.
    files: ['frontend/src/**/*.svelte', 'frontend/tests/**/*.svelte'],
    languageOptions: {
      parser: svelteParser,
      parserOptions: { parser: tsParser, ecmaVersion: 2022, sourceType: 'module' },
      globals: {
        // Mirror the .ts globals block — the Svelte parser hands the
        // `<script>` body to the TS parser but the surrounding ESLint
        // rule context is independent, so `no-undef` re-evaluates the
        // identifiers from scratch and needs the same allow-list.
        window: 'readonly',
        document: 'readonly',
        fetch: 'readonly',
        console: 'readonly',
        navigator: 'readonly',
        sessionStorage: 'readonly',
        localStorage: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        setInterval: 'readonly',
        clearInterval: 'readonly',
        queueMicrotask: 'readonly',
        confirm: 'readonly',
        URL: 'readonly',
        Blob: 'readonly',
        // Browser DOM interface types used as TypeScript annotations
        // (`bind:this={el}` callbacks, drag/keyboard handlers, etc.).
        // ESLint's `no-undef` flags TS interface names the same way it
        // flags runtime identifiers, so the names must be declared here.
        HTMLElement: 'readonly',
        HTMLDivElement: 'readonly',
        HTMLSpanElement: 'readonly',
        HTMLInputElement: 'readonly',
        HTMLButtonElement: 'readonly',
        HTMLAnchorElement: 'readonly',
        HTMLTextAreaElement: 'readonly',
        HTMLSelectElement: 'readonly',
        MediaQueryList: 'readonly',
        MediaQueryListEvent: 'readonly',
        // Event types used by inline handler signatures across the M2
        // chat surfaces (drag/drop, keyboard, click, form submit).
        Event: 'readonly',
        KeyboardEvent: 'readonly',
        MouseEvent: 'readonly',
        DragEvent: 'readonly',
        SubmitEvent: 'readonly',
        FocusEvent: 'readonly',
        ClipboardEvent: 'readonly',
        // M2 streaming + cancellation primitives, mirrored from the .ts block.
        AbortController: 'readonly',
        AbortSignal: 'readonly',
        DOMException: 'readonly',
        ReadableStream: 'readonly',
        TextDecoder: 'readonly',
        crypto: 'readonly',
        $state: 'readonly',
        $derived: 'readonly',
        $effect: 'readonly',
        $props: 'readonly',
        $bindable: 'readonly',
        $host: 'readonly',
        $inspect: 'readonly',
      },
    },
    rules: {
      'no-restricted-imports': ['error', restrictedImports],
      // Match the .ts block: the typescript-eslint variant respects
      // type signatures and the `_`-prefix opt-out, which is the
      // signal we use for "param required by the contract but unused
      // in this implementation" (e.g. callback prop type sigs).
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      // `<slot>` element usage is rejected by the `lint:grep` npm script;
      // see the header comment above for why no plugin rule is wired here.
    },
    plugins: { '@typescript-eslint': tsPlugin },
  },
];
