/**
 * Theme preset catalog and the canonical `resolveTheme` precedence helper.
 *
 * Source of truth for the role-token vocabulary used by every component in
 * the rebuild. Each preset declares the SAME twenty-eight role tokens; the
 * Vite plugin at `vite-emit-tokens.ts` mechanically projects this catalog
 * into `tokens.css`, and `app.css` lifts those CSS variables into Tailwind 4
 * utilities via `@theme inline { … }`.
 *
 * Locked by `rebuild/docs/plans/m1-theming.md` § Theme presets and
 * § Resolution order. The four shipping rooms — Tokyo Day, Tokyo Storm,
 * Tokyo Moon, Tokyo Night — are the ONLY theme choices the user ever sees.
 *
 * Hex equivalents are pinned next to each OKLCH value for the visual-
 * regression authoring loop. Round-tripping is approximate; OKLCH is the
 * binding form, hex is informational only.
 */

export const THEME_IDS = ['tokyo-day', 'tokyo-storm', 'tokyo-moon', 'tokyo-night'] as const;

export type ThemeId = (typeof THEME_IDS)[number];

/**
 * The result of `resolveTheme(...)` semantically labels how the active
 * preset was chosen. The store's `source` getter derives this; downstream
 * surfaces (picker reset button, settings copy) read it.
 */
export type ThemeSource = 'explicit' | 'os' | 'default';

/**
 * The role-token vocabulary every preset must declare. Twenty-eight slots,
 * identical key set across the four presets, enforced at the type level
 * (TypeScript will reject a preset that omits a slot).
 *
 * Component code reaches for ROLE tokens, never for a hex value or a preset
 * name. The grep gate in `rebuild/.buildkite/rebuild.yml` enforces this in
 * CI by failing on `#[0-9a-fA-F]{6}` inside any `.svelte` file outside
 * `src/lib/theme/`.
 */
export interface ThemePreset {
  // Surface ramp (6) — every visible chrome surface in priority order
  // (innermost → outermost: code block, mention chip, elevated card,
  // sidebar, topbar, app body).
  backgroundApp: string;
  backgroundSidebar: string;
  backgroundTopbar: string;
  backgroundElevated: string;
  backgroundCode: string;
  backgroundMention: string;
  // Hairlines and ink (7) — strokes and text from the lightest hairline up
  // to the strongest emphasis ink.
  hairline: string;
  hairlineStrong: string;
  inkPlaceholder: string;
  inkMuted: string;
  inkSecondary: string;
  inkBody: string;
  inkStrong: string;
  // Accents (5) — the chrome decorative budget. `accent-selection` is the
  // focus / selection ring; `accent-mention` is the @-mention dot;
  // `accent-headline` is the markdown H1/H2 hue (M2's renderer uses it);
  // `accent-stream` is the live-streaming dot pulse.
  accentSelection: string;
  accentSelectionPressed: string;
  accentMention: string;
  accentHeadline: string;
  accentStream: string;
  // Status hues (4) — semantic only, never adjacent to each other.
  statusSuccess: string;
  statusWarning: string;
  statusDanger: string;
  statusInfo: string;
  // Syntax (6) — fed to the Shiki theme generator at `shiki.ts`. Inside a
  // `background-code` block these step OUTSIDE the one-accent rule because
  // they are content, not chrome.
  syntaxKeyword: string;
  syntaxString: string;
  syntaxComment: string;
  syntaxFunction: string;
  syntaxNumber: string;
  syntaxTag: string;
}

/**
 * Tokyo Night — the brand-canonical dark room. Chrome ink/surface tokens
 * follow the M0 zero-chroma neutral ramp from `app.css`; the accent uses
 * `Mention Sky` per the One-Accent Rule. The syntax palette uses canonical
 * Tokyo Night swatches so a fenced block looks like every other Tokyo
 * Night editor on the planet.
 */
const TOKYO_NIGHT: ThemePreset = {
  backgroundApp: 'oklch(0.20 0 0)', // Workshop Dark, ~#2c2c2c
  backgroundSidebar: 'oklch(0.16 0 0)', // Ink Black, ~#1d1d1d
  backgroundTopbar: 'oklch(0.20 0 0)', // Workshop Dark, ~#2c2c2c
  backgroundElevated: 'oklch(0.27 0 0)', // Panel Dark, ~#3f3f3f
  backgroundCode: 'oklch(0.16 0 0)', // Ink Black, ~#1d1d1d
  backgroundMention: 'oklch(0.32 0.04 237)', // Mention Sky tinted neutral, ~#3a4452
  hairline: 'oklch(0.27 0 0)', // Panel Dark, ~#3f3f3f
  hairlineStrong: 'oklch(0.32 0 0)', // Strong Ink, ~#4d4d4d
  inkPlaceholder: 'oklch(0.51 0 0)', // Secondary Ink, ~#7c7c7c
  inkMuted: 'oklch(0.69 0 0)', // Muted Ink, ~#aeaeae
  inkSecondary: 'oklch(0.85 0 0)', // Hairline (used as ink on dark), ~#d6d6d6
  inkBody: 'oklch(0.94 0 0)', // Page Fill, ~#efefef
  inkStrong: 'oklch(0.98 0 0)', // Paper White, ~#fafafa
  accentSelection: 'oklch(0.69 0.17 237)', // Mention Sky, ~#5fb1f6
  accentSelectionPressed: 'oklch(0.55 0.16 237)', // Mention Sky pressed, ~#3287cb
  accentMention: 'oklch(0.69 0.17 237)', // Mention Sky, ~#5fb1f6
  accentHeadline: 'oklch(0.78 0.13 237)', // Mention Sky lifted, ~#88c5f5
  accentStream: 'oklch(0.69 0.17 237)', // Mention Sky, ~#5fb1f6
  // Status hues — tuned to read as legible "deep ink on a 20% tint" badges
  // (per the canonical Info Badge in DESIGN.json: `bg = hue/20` + `text = deep
  // ink variant of hue`). The contrast unit test (`tests/unit/theme/contrast
  // .spec.ts`) holds these to >= 4.5:1 against their own RGB-mix 20%-over-
  // white tint, which is the legibility bar for badge text. We keep maximum
  // chroma within the gamut at the lower L the bar requires; the result still
  // reads as "loud enough to mean something" per DESIGN.md's status-as-
  // semantic rule (deep emerald / amber / crimson / cobalt, not pastel).
  // Identical across the four presets: the badge tint is composited over
  // white per the Tailwind `bg-color/20` convention, so the fg/bg pair is
  // preset-independent.
  statusSuccess: 'oklch(0.45 0.18 149)', // deep emerald, ~#006d02
  statusWarning: 'oklch(0.48 0.16 70)', // deep amber, ~#944600
  statusDanger: 'oklch(0.48 0.21 25)', // deep crimson, ~#b70011
  statusInfo: 'oklch(0.48 0.20 259)', // deep cobalt, ~#0053cb
  syntaxKeyword: 'oklch(0.71 0.16 305)', // ~#bb9af7 magenta
  syntaxString: 'oklch(0.78 0.18 137)', // ~#9ece6a green
  syntaxComment: 'oklch(0.46 0.05 265)', // ~#565f89 muted indigo
  syntaxFunction: 'oklch(0.69 0.13 250)', // ~#7aa2f7 blue
  syntaxNumber: 'oklch(0.78 0.16 50)', // ~#ff9e64 orange
  syntaxTag: 'oklch(0.69 0.18 17)', // ~#f7768e red
};

/**
 * Tokyo Day — light variant. Crisp paper, restrained ink, accents deepened
 * so they clear the WCAG contrast bar against `background-app`. Status
 * hues are unchanged across presets so badge usage stays consistent.
 */
const TOKYO_DAY: ThemePreset = {
  backgroundApp: 'oklch(0.98 0 0)', // Paper White, ~#fafafa
  backgroundSidebar: 'oklch(0.94 0 0)', // Page Fill, ~#efefef
  backgroundTopbar: 'oklch(0.98 0 0)', // Paper White, ~#fafafa
  backgroundElevated: 'oklch(0.94 0 0)', // Page Fill, ~#efefef
  backgroundCode: 'oklch(0.94 0 0)', // Page Fill, ~#efefef
  backgroundMention: 'oklch(0.96 0.03 237)', // Mention Sky tint, ~#e8f1fb
  hairline: 'oklch(0.92 0 0)', // Divider, ~#e8e8e8
  hairlineStrong: 'oklch(0.85 0 0)', // Hairline, ~#d2d2d2
  inkPlaceholder: 'oklch(0.77 0 0)', // Placeholder, ~#bcbcbc
  inkMuted: 'oklch(0.69 0 0)', // Muted Ink, ~#a7a7a7
  inkSecondary: 'oklch(0.51 0 0)', // Secondary Ink, ~#7a7a7a
  inkBody: 'oklch(0.42 0 0)', // Body Ink, ~#626262
  inkStrong: 'oklch(0.16 0 0)', // Ink Black, ~#252525
  accentSelection: 'oklch(0.55 0.16 237)', // Deepened Sky for 3:1 against paper, ~#3989d2
  accentSelectionPressed: 'oklch(0.45 0.14 237)', // ~#2470b6
  accentMention: 'oklch(0.55 0.16 237)', // ~#3989d2
  accentHeadline: 'oklch(0.45 0.14 237)', // ~#2470b6, body-text contrast
  accentStream: 'oklch(0.55 0.16 237)', // ~#3989d2
  // Status hues — see Tokyo Night's preset for the rationale; values are
  // intentionally identical across the four presets so a badge's fg/bg
  // pair is preset-independent (the tint is composited over white).
  statusSuccess: 'oklch(0.45 0.18 149)', // deep emerald, ~#006d02
  statusWarning: 'oklch(0.48 0.16 70)', // deep amber, ~#944600
  statusDanger: 'oklch(0.48 0.21 25)', // deep crimson, ~#b70011
  statusInfo: 'oklch(0.48 0.20 259)', // deep cobalt, ~#0053cb
  syntaxKeyword: 'oklch(0.40 0.10 305)', // ~#5a4a78 plum
  syntaxString: 'oklch(0.42 0.10 137)', // ~#485e30 olive
  syntaxComment: 'oklch(0.51 0.01 270)', // ~#6c6e75 stone
  syntaxFunction: 'oklch(0.40 0.15 257)', // ~#2959aa cobalt
  syntaxNumber: 'oklch(0.45 0.14 50)', // ~#965027 burnt sienna
  syntaxTag: 'oklch(0.45 0.13 17)', // ~#8c4351 terracotta
};

/**
 * Tokyo Storm — slate-blue dark, less saturated than Night. Surface ramp
 * carries a small chroma shift (~0.025) toward 264° so the room feels
 * cooler without breaking the zero-chroma chrome rule (the chroma is
 * intentional and documented; `prefers-reduced-motion` users still see it
 * as a stable, non-shifting tone).
 */
const TOKYO_STORM: ThemePreset = {
  backgroundApp: 'oklch(0.27 0.025 264)', // ~#24283b
  backgroundSidebar: 'oklch(0.24 0.025 264)', // ~#1f2335
  backgroundTopbar: 'oklch(0.27 0.025 264)', // ~#24283b
  backgroundElevated: 'oklch(0.32 0.025 264)', // ~#2c3148
  backgroundCode: 'oklch(0.24 0.025 264)', // ~#1f2335
  backgroundMention: 'oklch(0.32 0.04 237)', // ~#2c3a4f
  hairline: 'oklch(0.32 0.025 264)', // ~#2c3148
  hairlineStrong: 'oklch(0.40 0.025 264)', // ~#3a405e
  inkPlaceholder: 'oklch(0.55 0.02 264)', // ~#5a6079
  inkMuted: 'oklch(0.65 0.02 264)', // ~#7077a0
  inkSecondary: 'oklch(0.78 0.02 264)', // ~#9aa1c5
  inkBody: 'oklch(0.83 0.05 264)', // ~#a9b1d6
  inkStrong: 'oklch(0.90 0.04 264)', // ~#c0c8e6
  accentSelection: 'oklch(0.69 0.13 250)', // ~#7aa2f7 blue
  accentSelectionPressed: 'oklch(0.60 0.13 250)', // ~#5b87dc
  accentMention: 'oklch(0.78 0.13 237)', // ~#88c5f5
  accentHeadline: 'oklch(0.78 0.13 237)', // ~#88c5f5
  accentStream: 'oklch(0.71 0.16 305)', // ~#bb9af7 magenta pulse
  // Status hues — see Tokyo Night's preset for the rationale.
  statusSuccess: 'oklch(0.45 0.18 149)', // deep emerald, ~#006d02
  statusWarning: 'oklch(0.48 0.16 70)', // deep amber, ~#944600
  statusDanger: 'oklch(0.48 0.21 25)', // deep crimson, ~#b70011
  statusInfo: 'oklch(0.48 0.20 259)', // deep cobalt, ~#0053cb
  syntaxKeyword: 'oklch(0.71 0.16 305)', // ~#bb9af7
  syntaxString: 'oklch(0.78 0.18 137)', // ~#9ece6a
  syntaxComment: 'oklch(0.45 0.05 264)', // ~#525a7c
  syntaxFunction: 'oklch(0.69 0.13 250)', // ~#7aa2f7
  syntaxNumber: 'oklch(0.78 0.16 50)', // ~#ff9e64
  syntaxTag: 'oklch(0.69 0.18 17)', // ~#f7768e
};

/**
 * Tokyo Moon — warmer dark, softest ramp. Surface ramp drifts to ~270° for
 * a faintly violet undertone; same trade-off as Storm — the chroma is
 * deliberate and documented in PROJECT.md as an exempted preset deviation.
 */
const TOKYO_MOON: ThemePreset = {
  backgroundApp: 'oklch(0.26 0.025 270)', // ~#222436
  backgroundSidebar: 'oklch(0.23 0.025 270)', // ~#1e2030
  backgroundTopbar: 'oklch(0.26 0.025 270)', // ~#222436
  backgroundElevated: 'oklch(0.31 0.025 270)', // ~#2b2d44
  backgroundCode: 'oklch(0.23 0.025 270)', // ~#1e2030
  backgroundMention: 'oklch(0.32 0.04 237)', // ~#2d394f
  hairline: 'oklch(0.31 0.025 270)', // ~#2b2d44
  hairlineStrong: 'oklch(0.40 0.025 270)', // ~#3a3c5a
  inkPlaceholder: 'oklch(0.55 0.02 270)', // ~#5b5e7a
  inkMuted: 'oklch(0.65 0.02 270)', // ~#7174a0
  inkSecondary: 'oklch(0.78 0.02 270)', // ~#9b9ec5
  inkBody: 'oklch(0.84 0.04 270)', // ~#c8d3f5
  inkStrong: 'oklch(0.92 0.03 270)', // ~#dadcec
  accentSelection: 'oklch(0.74 0.14 250)', // ~#82aaff softer blue
  accentSelectionPressed: 'oklch(0.65 0.14 250)', // ~#608ee0
  accentMention: 'oklch(0.78 0.13 237)', // ~#88c5f5
  accentHeadline: 'oklch(0.80 0.10 195)', // ~#86d3da cyan-leaning headline
  accentStream: 'oklch(0.72 0.16 305)', // ~#c099ff
  // Status hues — see Tokyo Night's preset for the rationale.
  statusSuccess: 'oklch(0.45 0.18 149)', // deep emerald, ~#006d02
  statusWarning: 'oklch(0.48 0.16 70)', // deep amber, ~#944600
  statusDanger: 'oklch(0.48 0.21 25)', // deep crimson, ~#b70011
  statusInfo: 'oklch(0.48 0.20 259)', // deep cobalt, ~#0053cb
  syntaxKeyword: 'oklch(0.74 0.15 305)', // ~#c099ff
  syntaxString: 'oklch(0.80 0.16 137)', // ~#c3e88d
  syntaxComment: 'oklch(0.50 0.05 270)', // ~#636da6 muted
  syntaxFunction: 'oklch(0.74 0.14 250)', // ~#82aaff
  syntaxNumber: 'oklch(0.80 0.15 50)', // ~#ffc777
  syntaxTag: 'oklch(0.71 0.18 17)', // ~#ff757f
};

export const THEME_PRESETS: Record<ThemeId, ThemePreset> = {
  'tokyo-day': TOKYO_DAY,
  'tokyo-storm': TOKYO_STORM,
  'tokyo-moon': TOKYO_MOON,
  'tokyo-night': TOKYO_NIGHT,
};

/**
 * Type-narrowing predicate. Cookie / localStorage / query strings are
 * untrusted; this is the single chokepoint that promotes a candidate
 * string to `ThemeId`.
 */
export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === 'string' && (THEME_IDS as readonly string[]).includes(value);
}

/**
 * Canonical theme-resolution precedence. Stated once, locked in
 * `m1-theming.md` § Resolution order:
 *
 *   1. Valid `explicit` wins.
 *   2. `osDark === true`  → "tokyo-night".
 *   3. `osDark === false` → "tokyo-day".
 *   4. Anything else      → "tokyo-night" (brand-canonical fallback).
 *
 * The same algorithm runs on the server (in `hooks.server.ts` for the SSR
 * cookie path) and on the client (in `boot.ts`'s pre-hydration IIFE).
 * Keeping it pure and dependency-free is what makes the two paths
 * impossible to disagree.
 */
export function resolveTheme(input: {
  explicit?: ThemeId | string | null | undefined;
  osDark?: boolean | null;
}): ThemeId {
  if (isThemeId(input.explicit)) return input.explicit;
  if (input.osDark === true) return 'tokyo-night';
  if (input.osDark === false) return 'tokyo-day';
  return 'tokyo-night';
}
