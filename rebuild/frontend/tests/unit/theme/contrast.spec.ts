/**
 * Unit tests for the M1 accessibility budget (`m1-theming.md`
 * § Accessibility budget).
 *
 * Per the plan this test is a **merge gate** — failing it on a shipping
 * preset blocks the preset (we surface the failing token pair + the
 * actual contrast ratio so a designer can tweak the OKLCH value
 * without re-running the whole suite).
 *
 * The four checks per preset:
 *
 *   - inkBody         vs backgroundApp >= 4.5:1  (body text WCAG AA)
 *   - inkSecondary    vs backgroundApp >= 3.0:1  (secondary text)
 *   - accentSelection vs backgroundApp >= 3.0:1  (focus-ring,
 *     non-text contrast)
 *   - For each status hue (success/warning/danger/info):
 *     status hue at full chroma vs its 20% tinted variant >= 4.5:1
 *
 * Status tints are computed by interpolating in OKLCH between the
 * status hue and pure white at 80% mix (i.e. "20% tint" = the badge
 * fill is 20% of the hue's strength). This mirrors the pattern badge
 * components use elsewhere in the rebuild (M5+'s status badges).
 *
 * Note (per dispatch instruction): if the existing presets do not all
 * pass, the failure is documented in the test output rather than
 * silently fixed by mutating presets.ts. The test asserts the contract;
 * the svelte-engineer owns the colour adjustments if anything fails.
 */

import { describe, expect, it } from 'vitest';
import { parse, formatHex, interpolate, wcagContrast } from 'culori';
import { THEME_IDS, THEME_PRESETS, type ThemeId, type ThemePreset } from '$lib/theme/presets';

/**
 * Compute the WCAG contrast ratio between two OKLCH-formatted strings.
 * Throws (with a useful message) if either side fails to parse — that
 * way the test message names the offending value rather than reporting
 * `NaN` ratios.
 */
function contrast(oklchA: string, oklchB: string): number {
  const a = parse(oklchA);
  const b = parse(oklchB);
  if (!a) throw new Error(`culori: failed to parse ${oklchA}`);
  if (!b) throw new Error(`culori: failed to parse ${oklchB}`);
  // wcagContrast accepts color objects directly.
  return wcagContrast(a, b);
}

/**
 * Build the "20% tint" of a status hue.
 *
 * Interpretation: this is the canonical Tailwind `bg-status-foo/20`
 * convention — 20% opacity of the hue composited over pure white. In
 * sRGB that is `mix(hue, white, 0.8)` (fraction along the gradient,
 * 0 = hue, 1 = white). RGB-space interpolation is used because it
 * matches what the browser actually paints for `bg-color/20` (per the
 * CSS Color Module Level 4 alpha compositing rules); OKLCH-space
 * interpolation produces a different value because OKLCH-shortest-arc
 * hue interpolation rotates through neutral hues for some pairs.
 *
 * Re-emitted as a hex so the diagnostic on failure is human-readable.
 */
function tint20(oklchString: string): string {
  const target = parse(oklchString);
  if (!target) throw new Error(`culori: failed to parse ${oklchString}`);
  const white = parse('oklch(1 0 0)');
  const mix = interpolate([target, white!], 'rgb')(0.8);
  return formatHex(mix);
}

const STATUS_TOKENS: ReadonlyArray<keyof ThemePreset> = [
  'statusSuccess',
  'statusWarning',
  'statusDanger',
  'statusInfo',
];

interface ContrastReport {
  preset: ThemeId;
  pair: string;
  fg: string;
  bg: string;
  ratio: number;
  threshold: number;
}

function check(report: ContrastReport): void {
  expect(
    report.ratio,
    `[${report.preset}] ${report.pair} contrast ${report.ratio.toFixed(2)}:1 ` +
      `< ${report.threshold}:1 (fg=${report.fg} bg=${report.bg})`,
  ).toBeGreaterThanOrEqual(report.threshold);
}

describe('contrast budget — every shipping preset clears the WCAG bar', () => {
  for (const id of THEME_IDS) {
    const preset = THEME_PRESETS[id as ThemeId];
    describe(`preset=${id}`, () => {
      it('inkBody vs backgroundApp >= 4.5 (body-text WCAG AA)', () => {
        const ratio = contrast(preset.inkBody, preset.backgroundApp);
        check({
          preset: id as ThemeId,
          pair: 'inkBody/backgroundApp',
          fg: preset.inkBody,
          bg: preset.backgroundApp,
          ratio,
          threshold: 4.5,
        });
      });

      it('inkSecondary vs backgroundApp >= 3.0 (secondary text)', () => {
        const ratio = contrast(preset.inkSecondary, preset.backgroundApp);
        check({
          preset: id as ThemeId,
          pair: 'inkSecondary/backgroundApp',
          fg: preset.inkSecondary,
          bg: preset.backgroundApp,
          ratio,
          threshold: 3.0,
        });
      });

      it('accentSelection vs backgroundApp >= 3.0 (focus-ring non-text)', () => {
        const ratio = contrast(preset.accentSelection, preset.backgroundApp);
        check({
          preset: id as ThemeId,
          pair: 'accentSelection/backgroundApp',
          fg: preset.accentSelection,
          bg: preset.backgroundApp,
          ratio,
          threshold: 3.0,
        });
      });

      for (const statusKey of STATUS_TOKENS) {
        it(`${statusKey} at full chroma vs 20%-tint(${statusKey}) >= 4.5 (badge text)`, () => {
          const fg = preset[statusKey];
          const bg = tint20(fg);
          const ratio = contrast(fg, bg);
          check({
            preset: id as ThemeId,
            pair: `${statusKey}/tint(${statusKey})`,
            fg,
            bg,
            ratio,
            threshold: 4.5,
          });
        });
      }
    });
  }
});
