/**
 * Unit tests for `src/lib/theme/shiki.ts`.
 *
 * The implementation signature is `buildShikiTheme(presetId, preset)`
 * (presetId is needed because the cache key for theme reuse is the id,
 * per `m1-theming.md` § Open questions (2)). The plan's prose only
 * names `buildShikiTheme(preset)`; the extra arg is the implementation
 * detail that lets Shiki re-use tokenisation across preset switches.
 *
 * Pinned by `m1-theming.md` § Deliverables (Shiki theme generator) and
 * § Tests § Unit:
 *
 *   - `colors['editor.background'] === preset.backgroundCode`.
 *   - `name === presetId` (`tokyo-{id}` form, since presetId IS that
 *     literal — `tokyo-day`, `tokyo-storm`, etc.).
 *   - tokenColors covers the six syntax scopes the plan calls out.
 *   - Snapshot for tokyo-night; structural invariants for the other 3
 *     (per the dispatch instructions).
 */

import { describe, expect, it } from 'vitest';
import { THEME_IDS, THEME_PRESETS, type ThemeId } from '$lib/theme/presets';
import { buildShikiTheme } from '$lib/theme/shiki';

const SCOPE_TO_PRESET_TOKEN: Record<string, keyof (typeof THEME_PRESETS)['tokyo-night']> = {
  keyword: 'syntaxKeyword',
  string: 'syntaxString',
  comment: 'syntaxComment',
  'entity.name.function': 'syntaxFunction',
  'constant.numeric': 'syntaxNumber',
  'entity.name.tag': 'syntaxTag',
};

function findScopeForeground(
  theme: ReturnType<typeof buildShikiTheme>,
  scope: string,
): string | undefined {
  for (const entry of theme.tokenColors) {
    const scopes = Array.isArray(entry.scope)
      ? (entry.scope as readonly string[])
      : [entry.scope as string];
    if (scopes.includes(scope)) return entry.settings.foreground;
  }
  return undefined;
}

describe('buildShikiTheme — structural invariants (every preset)', () => {
  for (const id of THEME_IDS) {
    const presetId = id as ThemeId;
    const preset = THEME_PRESETS[presetId];

    describe(`preset=${presetId}`, () => {
      const theme = buildShikiTheme(presetId, preset);

      it('name is the presetId verbatim (tokyo-{id})', () => {
        expect(theme.name).toBe(presetId);
        // belt-and-braces: the contract is that the name string starts
        // with `tokyo-` per the plan's `tokyo-{id}` template.
        expect(theme.name.startsWith('tokyo-')).toBe(true);
      });

      it('type is `light` for tokyo-day, `dark` for the other three', () => {
        expect(theme.type).toBe(presetId === 'tokyo-day' ? 'light' : 'dark');
      });

      it("colors['editor.background'] resolves to preset.backgroundCode", () => {
        expect(theme.colors['editor.background']).toBe(preset.backgroundCode);
      });

      it.each(Object.entries(SCOPE_TO_PRESET_TOKEN))(
        'scope %s maps to preset.%s',
        (scope, presetKey) => {
          const fg = findScopeForeground(theme, scope);
          expect(fg, `scope ${scope} missing on ${presetId}`).toBe(preset[presetKey]);
        },
      );
    });
  }
});

describe('buildShikiTheme — tokyo-night snapshot', () => {
  it('matches the committed snapshot (gates surface-mapping drift)', () => {
    const preset = THEME_PRESETS['tokyo-night'];
    const theme = buildShikiTheme('tokyo-night', preset);
    expect(theme).toMatchInlineSnapshot(`
      {
        "colors": {
          "editor.background": "oklch(0.16 0 0)",
          "editor.foreground": "oklch(0.94 0 0)",
          "editor.selectionBackground": "oklch(0.27 0 0)",
          "editorLineNumber.foreground": "oklch(0.69 0 0)",
        },
        "name": "tokyo-night",
        "tokenColors": [
          {
            "scope": [
              "comment",
              "punctuation.definition.comment",
              "string.comment",
            ],
            "settings": {
              "fontStyle": "italic",
              "foreground": "oklch(0.46 0.05 265)",
            },
          },
          {
            "scope": [
              "string",
              "string.quoted",
              "string.template",
            ],
            "settings": {
              "foreground": "oklch(0.78 0.18 137)",
            },
          },
          {
            "scope": [
              "constant.numeric",
              "constant.language",
              "constant.character.numeric",
            ],
            "settings": {
              "foreground": "oklch(0.78 0.16 50)",
            },
          },
          {
            "scope": [
              "keyword",
              "storage.type",
              "storage.modifier",
            ],
            "settings": {
              "foreground": "oklch(0.71 0.16 305)",
            },
          },
          {
            "scope": [
              "entity.name.function",
              "support.function",
              "meta.function-call",
            ],
            "settings": {
              "foreground": "oklch(0.69 0.13 250)",
            },
          },
          {
            "scope": [
              "entity.name.tag",
              "punctuation.definition.tag",
              "meta.tag",
              "support.class.component",
            ],
            "settings": {
              "foreground": "oklch(0.69 0.18 17)",
            },
          },
        ],
        "type": "dark",
      }
    `);
  });
});
