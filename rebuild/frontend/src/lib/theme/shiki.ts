/**
 * Shiki theme generator. Maps a `ThemePreset`'s syntax / surface tokens
 * to Shiki's TextMate-flavoured theme shape.
 *
 * Pinned by `rebuild/docs/plans/m1-theming.md` § Deliverables. M2's
 * markdown renderer consumes this; M1 only needs the surface to exist
 * and produce a one-off theme for the smoke fenced-codeblock baseline.
 *
 * The TextMate scope strings (`keyword`, `string`, `comment`,
 * `entity.name.function`, `constant.numeric`, `entity.name.tag`) cover
 * the six syntax tokens declared in `presets.ts`. Languages that emit
 * more granular scopes (e.g. `keyword.control.flow`) inherit from the
 * shorter prefix per Shiki's standard scope cascade — no per-language
 * tweaks needed.
 */

import type { ThemePreset, ThemeId } from '$lib/theme/presets';

/**
 * Minimal shape of a Shiki theme registration object. Mirrored from
 * Shiki's own `ThemeRegistrationRaw`, kept narrow so this module owns no
 * version coupling beyond `name` / `type` / `colors` / `tokenColors`.
 */
export interface ShikiTheme {
  name: string;
  type: 'dark' | 'light';
  colors: Record<string, string>;
  tokenColors: Array<{
    scope: string | readonly string[];
    settings: { foreground?: string; background?: string; fontStyle?: string };
  }>;
}

const LIGHT_PRESETS: ReadonlySet<ThemeId> = new Set<ThemeId>(['tokyo-day']);

/**
 * Build a Shiki theme whose surface and syntax colours come from the
 * preset's role tokens directly. Caller passes a `presetId` so the
 * generated theme is named `tokyo-{id}` for cache-key stability between
 * preset switches (Shiki re-uses tokenizations when only the theme
 * changes, per `m1-theming.md` § Open questions (2)).
 */
export function buildShikiTheme(presetId: ThemeId, preset: ThemePreset): ShikiTheme {
  const isLight = LIGHT_PRESETS.has(presetId);
  return {
    name: presetId,
    type: isLight ? 'light' : 'dark',
    colors: {
      'editor.background': preset.backgroundCode,
      'editor.foreground': preset.inkBody,
      'editorLineNumber.foreground': preset.inkMuted,
      'editor.selectionBackground': preset.backgroundElevated,
    },
    tokenColors: [
      {
        scope: ['comment', 'punctuation.definition.comment', 'string.comment'],
        settings: { foreground: preset.syntaxComment, fontStyle: 'italic' },
      },
      {
        scope: ['string', 'string.quoted', 'string.template'],
        settings: { foreground: preset.syntaxString },
      },
      {
        scope: ['constant.numeric', 'constant.language', 'constant.character.numeric'],
        settings: { foreground: preset.syntaxNumber },
      },
      {
        scope: ['keyword', 'storage.type', 'storage.modifier'],
        settings: { foreground: preset.syntaxKeyword },
      },
      {
        scope: ['entity.name.function', 'support.function', 'meta.function-call'],
        settings: { foreground: preset.syntaxFunction },
      },
      {
        scope: [
          'entity.name.tag',
          'punctuation.definition.tag',
          'meta.tag',
          'support.class.component',
        ],
        settings: { foreground: preset.syntaxTag },
      },
    ],
  };
}
