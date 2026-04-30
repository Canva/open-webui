/**
 * Unit tests for `src/lib/theme/presets.ts`.
 *
 * Locks the static contract M1's plan binds:
 *
 *   1. THEME_IDS is the four-room canonical iteration order.
 *   2. Every shipping preset declares the SAME 28-key role-token set
 *      (6 surface ramp + 7 hairlines/ink + 5 accents + 4 status + 6 syntax).
 *   3. Every value parses as a valid OKLCH string via culori.
 *
 * Runs in vitest's jsdom environment via the project's vitest.config.ts
 * `frontend/tests/unit/**\/*.{test,spec}.ts` glob. Pure logic, no DOM.
 */

import { describe, expect, it } from 'vitest';
import { parse } from 'culori';
import { THEME_IDS, THEME_PRESETS, type ThemeId, type ThemePreset } from '$lib/theme/presets';

// The canonical 28-key role-token set, transcribed from the M1 plan
// § Theme presets table. Sorted alphabetically inside each group so the
// equality assertion has a deterministic diff on failure.
const SURFACE_RAMP = [
  'backgroundApp',
  'backgroundCode',
  'backgroundElevated',
  'backgroundMention',
  'backgroundSidebar',
  'backgroundTopbar',
] as const;
const HAIRLINES_AND_INK = [
  'hairline',
  'hairlineStrong',
  'inkBody',
  'inkMuted',
  'inkPlaceholder',
  'inkSecondary',
  'inkStrong',
] as const;
const ACCENTS = [
  'accentHeadline',
  'accentMention',
  'accentSelection',
  'accentSelectionPressed',
  'accentStream',
] as const;
const STATUS = ['statusDanger', 'statusInfo', 'statusSuccess', 'statusWarning'] as const;
const SYNTAX = [
  'syntaxComment',
  'syntaxFunction',
  'syntaxKeyword',
  'syntaxNumber',
  'syntaxString',
  'syntaxTag',
] as const;

const EXPECTED_TOKEN_KEYS = [
  ...SURFACE_RAMP,
  ...HAIRLINES_AND_INK,
  ...ACCENTS,
  ...STATUS,
  ...SYNTAX,
].sort();

describe('THEME_IDS', () => {
  it('is the four-room canonical iteration order', () => {
    expect(Array.from(THEME_IDS)).toEqual([
      'tokyo-day',
      'tokyo-storm',
      'tokyo-moon',
      'tokyo-night',
    ]);
  });
});

describe('THEME_PRESETS shape', () => {
  it('exports exactly the four presets THEME_IDS lists', () => {
    expect(Object.keys(THEME_PRESETS).sort()).toEqual([...THEME_IDS].sort());
  });

  it('declares 28 role tokens (6 surface + 7 ink + 5 accents + 4 status + 6 syntax)', () => {
    // Sanity-check the per-group counts so a future plan rewrite that
    // changes the budget is caught at this assertion, not in the deeper
    // equality check below.
    expect(SURFACE_RAMP.length).toBe(6);
    expect(HAIRLINES_AND_INK.length).toBe(7);
    expect(ACCENTS.length).toBe(5);
    expect(STATUS.length).toBe(4);
    expect(SYNTAX.length).toBe(6);
    expect(EXPECTED_TOKEN_KEYS.length).toBe(28);
  });

  it.each(THEME_IDS)('preset %s declares the canonical 28-key set', (id) => {
    const preset = THEME_PRESETS[id as ThemeId];
    const keys = Object.keys(preset).sort();
    expect(keys).toEqual(EXPECTED_TOKEN_KEYS);
  });

  it('all four presets share an identical token-key set (key-set equality)', () => {
    const baseline = Object.keys(THEME_PRESETS['tokyo-night']).sort();
    for (const id of THEME_IDS) {
      const keys = Object.keys(THEME_PRESETS[id as ThemeId]).sort();
      expect(keys, `preset ${id} key set diverged from tokyo-night`).toEqual(baseline);
    }
  });
});

describe('every preset value is a valid OKLCH string', () => {
  for (const id of THEME_IDS) {
    it(`preset ${id} parses every token value via culori`, () => {
      const preset = THEME_PRESETS[id as ThemeId] as Record<keyof ThemePreset, string>;
      const failures: string[] = [];
      for (const [key, value] of Object.entries(preset)) {
        if (typeof value !== 'string' || !value.startsWith('oklch(')) {
          failures.push(`${key}=${JSON.stringify(value)} (not an OKLCH string)`);
          continue;
        }
        const parsed = parse(value);
        if (!parsed || parsed.mode !== 'oklch') {
          failures.push(`${key}=${value} (culori failed to parse)`);
        }
      }
      expect(failures, failures.join('\n')).toEqual([]);
    });
  }
});
