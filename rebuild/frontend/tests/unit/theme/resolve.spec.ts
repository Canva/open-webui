/**
 * Unit tests for `resolveTheme(...)` — the single canonical precedence
 * helper from `src/lib/theme/presets.ts`.
 *
 * Pinned by `m1-theming.md` § Resolution order:
 *
 *   1. Valid `explicit` -> that id.
 *   2. Else `osDark === true` -> 'tokyo-night'.
 *   3. Else `osDark === false` -> 'tokyo-day'.
 *   4. Else (no preference reported) -> 'tokyo-night'.
 *
 * Plus the two edge cases the plan calls out by name:
 *
 *   - explicit value is not a known preset id -> fall through to OS.
 *   - explicit value is the empty string      -> fall through to OS.
 */

import { describe, expect, it } from 'vitest';
import { THEME_IDS, resolveTheme, type ThemeId } from '$lib/theme/presets';

describe('resolveTheme — 12 valid (explicit, osDark) combinations', () => {
  // 4 explicit ids x 3 osDark values (true / false / null) = 12 cases.
  // Every cell asserts the explicit choice wins regardless of osDark.
  const osDarkValues: ReadonlyArray<true | false | null> = [true, false, null];
  for (const explicit of THEME_IDS) {
    for (const osDark of osDarkValues) {
      it(`explicit=${explicit}, osDark=${String(osDark)} -> ${explicit}`, () => {
        expect(resolveTheme({ explicit, osDark })).toBe(explicit);
      });
    }
  }
});

describe('resolveTheme — OS-fallback ladder (no explicit)', () => {
  it('osDark === true -> tokyo-night', () => {
    expect(resolveTheme({ osDark: true })).toBe('tokyo-night');
  });

  it('osDark === false -> tokyo-day', () => {
    expect(resolveTheme({ osDark: false })).toBe('tokyo-day');
  });

  it('osDark === null (no preference reported) -> tokyo-night (brand fallback)', () => {
    expect(resolveTheme({ osDark: null })).toBe('tokyo-night');
  });

  it('osDark omitted (undefined) -> tokyo-night (brand fallback)', () => {
    expect(resolveTheme({})).toBe('tokyo-night');
  });
});

describe('resolveTheme — explicit edge cases the plan calls out', () => {
  // The plan's two explicit-edge cases. Both must fall through to OS so
  // a stale cookie carrying a renamed preset id (or a broken proxy
  // injecting an empty string) degrades to the OS default rather than
  // crashing the boot path.
  const osDarkPairs: ReadonlyArray<{ osDark: true | false | null; expected: ThemeId }> = [
    { osDark: true, expected: 'tokyo-night' },
    { osDark: false, expected: 'tokyo-day' },
    { osDark: null, expected: 'tokyo-night' },
  ];

  for (const { osDark, expected } of osDarkPairs) {
    it(`unknown explicit ("not-a-real-preset"), osDark=${String(osDark)} -> ${expected}`, () => {
      expect(resolveTheme({ explicit: 'not-a-real-preset', osDark })).toBe(expected);
    });

    it(`empty-string explicit, osDark=${String(osDark)} -> ${expected}`, () => {
      expect(resolveTheme({ explicit: '', osDark })).toBe(expected);
    });
  }

  it('explicit=null + osDark=true -> tokyo-night (null is not a valid id)', () => {
    expect(resolveTheme({ explicit: null, osDark: true })).toBe('tokyo-night');
  });

  it('explicit=undefined + osDark=false -> tokyo-day', () => {
    expect(resolveTheme({ explicit: undefined, osDark: false })).toBe('tokyo-day');
  });
});
