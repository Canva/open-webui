/**
 * Mermaid theme-variables generator. Maps a `ThemePreset`'s chrome tokens
 * onto the six-key block Mermaid's `init` accepts as `themeVariables`.
 *
 * Pinned by `rebuild/docs/plans/m1-theming.md` § Deliverables. The store
 * re-applies on every preset switch so visible diagrams re-render with
 * the new chrome.
 *
 * The mapping is intentionally narrow — Mermaid exposes ~50 themable
 * variables but most are surface-derived. Six is the smallest set that
 * makes a flowchart legible (nodes, edges, text, panels) without locking
 * the rebuild into Mermaid's full typography / shadow vocabulary, which
 * we don't use elsewhere.
 */

import type { ThemePreset } from '$lib/theme/presets';

export function buildMermaidThemeVariables(preset: ThemePreset): Record<string, string> {
  return {
    primaryColor: preset.accentSelection,
    lineColor: preset.hairlineStrong,
    textColor: preset.inkBody,
    mainBkg: preset.backgroundElevated,
    secondaryColor: preset.backgroundSidebar,
    tertiaryColor: preset.backgroundTopbar,
  };
}
