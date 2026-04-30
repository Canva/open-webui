/**
 * Vite plugin: codegens `lib/theme/tokens.css` from `lib/theme/presets.ts`.
 *
 * Pinned by `rebuild/docs/plans/m1-theming.md` § Tailwind 4 wiring. The
 * source of truth is the TypeScript module — one place to edit, one
 * place to typecheck. The CSS is mechanical and committed to the repo
 * so reviewers see the diff when a preset changes.
 *
 * Lifecycle:
 *   - `configResolved`: emit once on dev-server start AND on `vite build`
 *     so production CSS is always fresh from the typed module. We use
 *     `esbuild.transform` directly (esbuild ships with Vite) to load
 *     presets.ts without depending on a running dev server.
 *   - `handleHotUpdate`: re-emit when `presets.ts` is saved. The Tailwind
 *     plugin and SvelteKit pick up the regenerated CSS via their own HMR.
 *
 * The plugin name `theme-emit-tokens` is what surfaces in Vite's plugin
 * timing logs.
 */

import { writeFile, readFile } from 'node:fs/promises';
import { resolve, dirname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { transform } from 'esbuild';
import type { Plugin } from 'vite';

// Relative (not `$lib`) import: this file is loaded by `vite.config.ts`
// directly via Node, NOT through SvelteKit's resolver, so the `$lib`
// alias is not in scope here. Types only — runtime never touches the
// preset module through this import.
import type { ThemeId, ThemePreset } from './presets';

interface PluginOptions {
  /** Absolute path to `presets.ts`. Defaults to the file next to this one. */
  presetsPath?: string;
  /** Absolute path the generated `tokens.css` should be written to. */
  tokensPath?: string;
}

interface LoadedPresets {
  THEME_IDS: readonly ThemeId[];
  THEME_PRESETS: Record<ThemeId, ThemePreset>;
}

const PLUGIN_NAME = 'theme-emit-tokens';

// The 28-token vocabulary, ordered by surface ramp → ink → accents →
// status → syntax. The order shows up in `tokens.css` comments and
// matters for diff-readability when a preset changes.
const ROLE_TOKENS: ReadonlyArray<readonly [keyof ThemePreset, string]> = [
  // Surface ramp
  ['backgroundApp', '--background-app'],
  ['backgroundSidebar', '--background-sidebar'],
  ['backgroundTopbar', '--background-topbar'],
  ['backgroundElevated', '--background-elevated'],
  ['backgroundCode', '--background-code'],
  ['backgroundMention', '--background-mention'],
  // Hairlines and ink
  ['hairline', '--hairline'],
  ['hairlineStrong', '--hairline-strong'],
  ['inkPlaceholder', '--ink-placeholder'],
  ['inkMuted', '--ink-muted'],
  ['inkSecondary', '--ink-secondary'],
  ['inkBody', '--ink-body'],
  ['inkStrong', '--ink-strong'],
  // Accents
  ['accentSelection', '--accent-selection'],
  ['accentSelectionPressed', '--accent-selection-pressed'],
  ['accentMention', '--accent-mention'],
  ['accentHeadline', '--accent-headline'],
  ['accentStream', '--accent-stream'],
  // Status
  ['statusSuccess', '--status-success'],
  ['statusWarning', '--status-warning'],
  ['statusDanger', '--status-danger'],
  ['statusInfo', '--status-info'],
  // Syntax
  ['syntaxKeyword', '--syntax-keyword'],
  ['syntaxString', '--syntax-string'],
  ['syntaxComment', '--syntax-comment'],
  ['syntaxFunction', '--syntax-function'],
  ['syntaxNumber', '--syntax-number'],
  ['syntaxTag', '--syntax-tag'],
];

function defaultPresetsPath(): string {
  // dist/lib/theme/vite-emit-tokens.js when bundled, src/lib/theme/...
  // during dev. Resolve relative to this module.
  const here = dirname(fileURLToPath(import.meta.url));
  return resolve(here, 'presets.ts');
}

function defaultTokensPath(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  return resolve(here, 'tokens.css');
}

/**
 * Load `presets.ts` by transpiling with esbuild and importing via a
 * data URL. The presets module has no external imports, so the data-URL
 * trick works without bundling the whole graph. Returns `null` on
 * failure (caller decides whether to noisily log or silently skip).
 */
async function loadPresetsModule(presetsPath: string): Promise<LoadedPresets | null> {
  const source = await readFile(presetsPath, 'utf-8');
  const transformed = await transform(source, {
    loader: 'ts',
    format: 'esm',
    target: 'es2022',
  });
  const dataUrl = `data:text/javascript;base64,${Buffer.from(transformed.code).toString('base64')}`;
  const mod = (await import(dataUrl)) as Partial<LoadedPresets>;
  if (!mod.THEME_IDS || !mod.THEME_PRESETS) return null;
  return { THEME_IDS: mod.THEME_IDS, THEME_PRESETS: mod.THEME_PRESETS };
}

/**
 * Strip trailing zeros from decimal numerics inside any function-call
 * expression (e.g. `oklch(0.40 0.10 305)` → `oklch(0.4 0.1 305)`). The
 * authored presets in `presets.ts` keep two-decimal alignment for diff
 * readability; Prettier's CSS formatter minifies the same way at lint
 * time, so emitting the minified form here keeps `tokens.css` from
 * dirtying the working tree on the next dev/build cycle.
 */
function normaliseValue(value: string): string {
  return value.replace(/(\d*\.\d*?)0+(?=\D|$)/g, (_match, prefix: string) => {
    // `0.40` → `0.4`; `0.50` → `0.5`; `1.00` → `1.`. Trim a dangling
    // dot so `1.00` collapses to `1`.
    const trimmed = prefix.endsWith('.') ? prefix.slice(0, -1) : prefix;
    return trimmed;
  });
}

/**
 * Project the in-memory presets into a deterministic CSS string. One
 * `[data-theme="…"] { … }` block per preset, role tokens grouped by
 * category with leading comments, trailing newline so editors don't
 * complain about no-newline-at-eof.
 */
export function renderTokensCss(loaded: LoadedPresets): string {
  const HEADER = `/*
 * GENERATED FILE — do not edit by hand.
 *
 * Source of truth: rebuild/frontend/src/lib/theme/presets.ts
 * Regenerated by:  rebuild/frontend/src/lib/theme/vite-emit-tokens.ts
 *
 * This file binds each preset's role-token vocabulary to CSS custom
 * properties that Tailwind 4's @theme inline { ... } block in app.css
 * lifts into utilities (bg-background-app, text-ink-body, ...). When
 * data-theme on the <html> element changes, every utility re-points
 * in one DOM mutation; the browser repaints in one frame.
 *
 * The selector is intentionally [data-theme='X'] (not :root[...]) so a
 * nested element carrying data-theme can override the chrome tokens for
 * its subtree. The M1 ThemePicker uses this to make each tile preview
 * its OWN preset regardless of the page's active theme.
 *
 * To regenerate, save presets.ts during \`vite dev\`, or restart the
 * dev/build server.
 */
`;

  const blocks = loaded.THEME_IDS.map((id) => {
    const preset = loaded.THEME_PRESETS[id];
    const surface = ROLE_TOKENS.slice(0, 6);
    const inkAndHairline = ROLE_TOKENS.slice(6, 13);
    const accents = ROLE_TOKENS.slice(13, 18);
    const status = ROLE_TOKENS.slice(18, 22);
    const syntax = ROLE_TOKENS.slice(22, 28);
    const section = (label: string, slice: typeof ROLE_TOKENS) =>
      [
        `  /* ${label} */`,
        ...slice.map(([key, varName]) => `  ${varName}: ${normaliseValue(preset[key])};`),
      ].join('\n');

    // Selector intentionally unscoped to `:root`: CSS custom properties
    // cascade from ancestors only, and `m1-theming.md` § Deliverables
    // requires the M1 ThemePicker tile to override the chrome tokens by
    // setting `data-theme="tokyo-{id}"` on a non-root element so each
    // tile renders its OWN preset regardless of the page's active theme.
    // `[data-theme='X']` matches BOTH `<html data-theme="X">` (the SSR
    // path) and any nested element carrying the attribute (the picker
    // path); the closer scope wins by inheritance, so nesting Just Works.
    //
    // Single-quoted attribute selector to match the project's Prettier
    // settings; otherwise the next `prettier --check` rewrites the file
    // and the lint step diffs the generated output against itself.
    return [
      `[data-theme='${id}'] {`,
      section('Surface ramp', surface),
      section('Hairlines and ink', inkAndHairline),
      section('Accents', accents),
      section('Status', status),
      section('Syntax', syntax),
      `}`,
    ].join('\n');
  }).join('\n\n');

  return `${HEADER}\n${blocks}\n`;
}

export function themeEmitTokens(options: PluginOptions = {}): Plugin {
  const presetsPath = options.presetsPath ?? defaultPresetsPath();
  const tokensPath = options.tokensPath ?? defaultTokensPath();

  let loggedOnce = false;

  async function emit(reason: string): Promise<void> {
    try {
      const loaded = await loadPresetsModule(presetsPath);
      if (!loaded) {
        if (!loggedOnce) {
          console.warn(`[${PLUGIN_NAME}] presets module did not export THEME_IDS/THEME_PRESETS`);
          loggedOnce = true;
        }
        return;
      }
      const css = renderTokensCss(loaded);
      // Only write when the content actually differs — avoids an HMR
      // ping-pong if a save doesn't change the rendered output.
      try {
        const existing = await readFile(tokensPath, 'utf-8');
        if (existing === css) return;
      } catch {
        // file doesn't exist yet; fall through to write
      }
      await writeFile(tokensPath, css, 'utf-8');
      console.log(`[${PLUGIN_NAME}] regenerated tokens.css (${reason})`);
    } catch (err) {
      // Generation failures must not crash the dev server. The committed
      // tokens.css remains in place.
      console.warn(`[${PLUGIN_NAME}] failed to emit tokens.css:`, err);
    }
  }

  return {
    name: PLUGIN_NAME,
    enforce: 'pre',
    async configResolved() {
      await emit('configResolved');
    },
    async handleHotUpdate(ctx) {
      // Match by basename + parent dir to avoid false positives on
      // unrelated `presets.ts` files in node_modules.
      const file = ctx.file;
      const expected = presetsPath;
      // Normalise both sides to handle Windows `\` vs POSIX `/`.
      const norm = (p: string) => p.split(sep).join('/');
      if (norm(file) === norm(expected)) {
        await emit('handleHotUpdate');
      }
    },
  };
}

// Re-export for tests that want to drive the renderer in isolation.
export { ROLE_TOKENS };
