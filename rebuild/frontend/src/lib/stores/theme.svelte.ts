/**
 * Per-request theme store. One instance per render, constructed in
 * `(app)/+layout.svelte` and `(public)/+layout.svelte`, provided to
 * descendants via `setContext('theme', store)`.
 *
 * Pinned by `rebuild/docs/plans/m1-theming.md` § Deliverables AND by
 * the cross-cutting frontend conventions in
 * `rebuild/docs/plans/m0-foundations.md` § Frontend conventions
 * (cross-cutting): module-level `$state` is BANNED for per-user data
 * because the SvelteKit server is shared across requests. The class +
 * `setContext` shape keeps theme preference per-render-tree, SSR-safe.
 *
 * Mermaid is reapplied opportunistically on every preset switch — only
 * if `window.mermaid` is present, no static dependency on the package.
 * M1 ships the smoke component but doesn't import Mermaid eagerly into
 * every route; this keeps the option open for M3's share view to skip
 * loading Mermaid entirely if it doesn't render diagrams.
 */

import { resolveTheme, THEME_PRESETS } from '$lib/theme/presets';
import type { ThemeId, ThemePreset, ThemeSource } from '$lib/theme/presets';
import { writeChoice, clearChoice as clearStoredChoice } from '$lib/theme/persistence';
import { buildMermaidThemeVariables } from '$lib/theme/mermaid';

const CONTEXT_KEY = 'theme';

interface ConstructorArgs {
  /** The server-resolved theme id from `data.theme`. */
  initial: ThemeId;
  /**
   * Result of `matchMedia('(prefers-color-scheme: dark)').matches` if
   * known at construction time. Server constructors pass `null`; the
   * (app) layout calls `setOsDark(...)` from a `$effect` after mount.
   */
  osDark: boolean | null;
  /**
   * Optional override for whether the initial theme came from an
   * explicit user choice (cookie present + valid) vs an OS-fallback
   * resolution. Defaults to a heuristic: explicit iff `initial`
   * differs from `resolveTheme({ osDark })`. Pass `'explicit'`
   * verbatim from `data.themeSource` to remove the heuristic
   * ambiguity (e.g. when explicit choice happens to match OS).
   */
  initialSource?: ThemeSource;
}

interface SetThemeOptions {
  /**
   * When `false`, applies the theme to the DOM but does NOT write to
   * the cookie / localStorage. Used by the matchMedia `$effect` so
   * OS-driven re-resolution doesn't masquerade as an explicit choice.
   */
  persist?: boolean;
}

export class ThemeStore {
  /**
   * `$state.raw` not `$state` — `current` is a string primitive that
   * we only ever reassign; deep proxying buys nothing.
   */
  current: ThemeId = $state.raw('tokyo-night');

  /**
   * Whether the active theme came from an explicit user choice. Drives
   * the `source` derived. Mutated by `setTheme` (true when `persist`
   * is not false) and `clearChoice` (false).
   */
  private _explicit = $state.raw(false);

  /**
   * Last-known OS preference. Updated by `setOsDark` from the
   * matchMedia `$effect` on mount and on change.
   */
  private _osDark: boolean | null = $state.raw(null);

  source: ThemeSource = $derived(
    this._explicit ? 'explicit' : this._osDark === null ? 'default' : 'os',
  );

  constructor({ initial, osDark, initialSource }: ConstructorArgs) {
    this.current = initial;
    this._osDark = osDark;
    if (initialSource) {
      this._explicit = initialSource === 'explicit';
    } else {
      // Heuristic: if the server picked something other than what the
      // OS would have suggested, the cookie must have been present and
      // valid → explicit. Ambiguous only when an explicit choice
      // happens to equal the OS fallback (e.g. user picked tokyo-night
      // on a dark-mode OS) — pass `initialSource` from `data` to
      // disambiguate.
      this._explicit = initial !== resolveTheme({ osDark });
    }
  }

  /**
   * Switch the active theme. Mutates `document.documentElement.dataset
   * .theme` so Tailwind's `@theme inline` utilities re-point in one
   * frame. Persists to cookie + localStorage by default; pass
   * `{ persist: false }` for OS-driven re-resolution.
   */
  setTheme = (id: ThemeId, opts?: SetThemeOptions): void => {
    this.current = id;
    this._explicit = opts?.persist !== false;
    this._applyToDom(id);
    if (opts?.persist !== false) {
      writeChoice(id);
    }
    this._reapplyMermaid();
  };

  /**
   * "Match system" reset. Clears both persistence surfaces and
   * re-resolves to the current OS preference. The active theme may
   * change as a result; the DOM mutation happens in the same tick so
   * the picker's state is unambiguous.
   */
  clearChoice = (): void => {
    clearStoredChoice();
    this._explicit = false;
    const next = resolveTheme({ osDark: this._osDark });
    if (next !== this.current) {
      this.current = next;
      this._applyToDom(next);
    }
    this._reapplyMermaid();
  };

  /**
   * Called by the `(app)`/`(public)` layout's matchMedia `$effect` when
   * `prefers-color-scheme` updates. If the user has an explicit choice,
   * the OS preference is recorded but the theme does NOT change.
   */
  setOsDark = (value: boolean | null): void => {
    this._osDark = value;
    if (this._explicit) return;
    const next = resolveTheme({ osDark: value });
    if (next !== this.current) {
      this.current = next;
      this._applyToDom(next);
      this._reapplyMermaid();
    }
  };

  /** Catalog of all four presets in canonical iteration order. */
  get presets(): readonly ThemePreset[] {
    return Object.values(THEME_PRESETS);
  }

  /** The currently-active preset object (for direct token reads). */
  get preset(): ThemePreset {
    return THEME_PRESETS[this.current];
  }

  private _applyToDom(id: ThemeId): void {
    if (typeof document === 'undefined') return;
    document.documentElement.dataset.theme = id;
  }

  private _reapplyMermaid(): void {
    if (typeof window === 'undefined') return;
    // Opportunistic: only if Mermaid was loaded by some other surface
    // (e.g. M2's chat renderer, or the smoke component). Avoids forcing
    // every route to ship the Mermaid bundle.
    const win = window as unknown as {
      mermaid?: {
        initialize?: (config: {
          startOnLoad?: boolean;
          theme?: string;
          themeVariables?: Record<string, string>;
        }) => void;
      };
    };
    if (!win.mermaid?.initialize) return;
    win.mermaid.initialize({
      startOnLoad: false,
      theme: 'base',
      themeVariables: buildMermaidThemeVariables(THEME_PRESETS[this.current]),
    });
  }
}

export const THEME_CONTEXT_KEY = CONTEXT_KEY;
