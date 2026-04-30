/**
 * Markdown code-block highlighting surface.
 *
 * M1 stub: gives the smoke component (`CodeBlockSmoke.svelte`) and any
 * future markdown renderer a single place to ask for "the active
 * Shiki highlighter." M2's full markdown pipeline expands this into
 * caching, lazy-language loading, and the Mermaid block detector.
 *
 * The Shiki highlighter is built lazily and cached per-process. Theme
 * swaps reuse the existing tokenisation (per `m1-theming.md` § Open
 * questions (2)) — calling `loadTheme` on a new preset is O(1) for the
 * theme registration and does NOT re-tokenise visible code blocks.
 */

import { createHighlighter, type Highlighter, type ThemeInput } from 'shiki';

import { buildShikiTheme, type ShikiTheme } from '$lib/theme/shiki';
import type { ThemeId, ThemePreset } from '$lib/theme/presets';

let highlighterPromise: Promise<Highlighter> | null = null;
const registeredThemes = new Set<ThemeId>();

const SMOKE_LANGUAGES = ['javascript', 'typescript', 'tsx', 'json', 'bash'] as const;

/**
 * Coerce our stable `ShikiTheme` shape into the `ThemeInput` Shiki
 * accepts. Shiki's runtime parser handles our shape directly; the cast
 * exists only because Shiki's `ThemeRegistrationRaw` extends a
 * TextMate `IRawTheme` we don't want to leak into the rebuild's API
 * surface.
 */
function toThemeInput(theme: ShikiTheme): ThemeInput {
  return theme as unknown as ThemeInput;
}

/**
 * Returns a Shiki highlighter primed for `presetId`. Concurrent callers
 * during the same tick share a single in-flight initialisation; later
 * callers either find the cached instance or re-register the new theme
 * without rebuilding the engine.
 *
 * Caller-side typical pattern:
 *
 *   const hl = await getShikiHighlighter('tokyo-night', preset);
 *   const html = hl.codeToHtml(src, { lang: 'typescript', theme: 'tokyo-night' });
 */
export async function getShikiHighlighter(
  presetId: ThemeId,
  preset: ThemePreset,
): Promise<Highlighter> {
  if (!highlighterPromise) {
    highlighterPromise = createHighlighter({
      langs: [...SMOKE_LANGUAGES],
      themes: [toThemeInput(buildShikiTheme(presetId, preset))],
    });
    registeredThemes.add(presetId);
    return highlighterPromise;
  }
  const hl = await highlighterPromise;
  if (!registeredThemes.has(presetId)) {
    await hl.loadTheme(toThemeInput(buildShikiTheme(presetId, preset)));
    registeredThemes.add(presetId);
  }
  return hl;
}
