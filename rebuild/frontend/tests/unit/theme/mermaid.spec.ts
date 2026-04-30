/**
 * Unit tests for `src/lib/theme/mermaid.ts`.
 *
 * Pinned by `m1-theming.md` § Deliverables (Mermaid theme generator):
 *
 *   primaryColor    -> accentSelection
 *   lineColor       -> hairlineStrong
 *   textColor       -> inkBody
 *   mainBkg         -> backgroundElevated
 *   secondaryColor  -> backgroundSidebar
 *   tertiaryColor   -> backgroundTopbar
 *
 * Snapshot for tokyo-night, structural invariants for the other three.
 */

import { describe, expect, it } from 'vitest';
import { THEME_IDS, THEME_PRESETS, type ThemeId } from '$lib/theme/presets';
import { buildMermaidThemeVariables } from '$lib/theme/mermaid';

const KEY_TO_PRESET_TOKEN: Record<string, keyof (typeof THEME_PRESETS)['tokyo-night']> = {
  primaryColor: 'accentSelection',
  lineColor: 'hairlineStrong',
  textColor: 'inkBody',
  mainBkg: 'backgroundElevated',
  secondaryColor: 'backgroundSidebar',
  tertiaryColor: 'backgroundTopbar',
};

describe('buildMermaidThemeVariables — structural invariants (every preset)', () => {
  for (const id of THEME_IDS) {
    const presetId = id as ThemeId;
    const preset = THEME_PRESETS[presetId];
    describe(`preset=${presetId}`, () => {
      const vars = buildMermaidThemeVariables(preset);

      it('returns exactly the six expected keys', () => {
        expect(Object.keys(vars).sort()).toEqual(Object.keys(KEY_TO_PRESET_TOKEN).sort());
      });

      it.each(Object.entries(KEY_TO_PRESET_TOKEN))(
        '%s -> preset.%s',
        (mermaidKey, presetTokenKey) => {
          expect(vars[mermaidKey]).toBe(preset[presetTokenKey]);
        },
      );
    });
  }
});

describe('buildMermaidThemeVariables — tokyo-night snapshot', () => {
  it('matches the committed snapshot (gates the chrome-token mapping)', () => {
    const vars = buildMermaidThemeVariables(THEME_PRESETS['tokyo-night']);
    expect(vars).toMatchInlineSnapshot(`
      {
        "lineColor": "oklch(0.32 0 0)",
        "mainBkg": "oklch(0.27 0 0)",
        "primaryColor": "oklch(0.69 0.17 237)",
        "secondaryColor": "oklch(0.16 0 0)",
        "tertiaryColor": "oklch(0.20 0 0)",
        "textColor": "oklch(0.94 0 0)",
      }
    `);
  });
});
