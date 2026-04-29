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
        'createEventDispatcher is banned in Svelte 5. Use callback props (onfoo / onclick). See rebuild/plans/m0-foundations.md § Frontend conventions.',
    },
    {
      name: '$app/stores',
      message:
        '$app/stores is deprecated since SvelteKit 2.12. Import from $app/state instead. See rebuild/plans/m0-foundations.md § Frontend conventions.',
    },
    {
      name: 'uuid',
      message:
        'UUIDs are minted server-side via app.core.ids.new_id() (UUIDv7). The frontend never generates IDs. See rebuild/plans/m0-foundations.md § ID and time helpers.',
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
        // Node globals available in server modules / configs.
        process: 'readonly',
        URL: 'readonly',
        Request: 'readonly',
        Response: 'readonly',
        RequestInit: 'readonly',
        Headers: 'readonly',
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
    },
    rules: {
      'no-restricted-imports': ['error', restrictedImports],
      // `<slot>` element usage is rejected by the `lint:grep` npm script;
      // see the header comment above for why no plugin rule is wired here.
    },
  },
];
