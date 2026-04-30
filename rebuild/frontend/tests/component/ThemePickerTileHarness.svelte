<!--
  Standalone preview-tile harness for `theme-picker-tile.spec.ts`.

  Renders a minimal "swatch" element wrapped in a container carrying
  `data-theme="tokyo-{id}"` so the per-tile CSS-variable cascade trick
  the picker relies on is exercised in isolation. The swatch's
  background colour is the role token `--background-app`, lifted into
  Tailwind via the project `@theme inline { --color-background-app:
  var(--background-app); }` block — meaning the painted colour for
  any tile is THAT preset's `backgroundApp`, regardless of the page's
  active theme.

  This harness deliberately does NOT mount the full ThemePicker; we
  want a clean assertion that the cascade primitive works without
  conflating store state, click handlers, or aria-pressed semantics.
-->
<script lang="ts">
  import { untrack } from 'svelte';
  import type { ThemeId } from '$lib/theme/presets';

  interface Props {
    /** The preset id to preview on this tile. */
    preset: ThemeId;
    /** The page-level active theme (so the test can confirm isolation). */
    pageTheme?: ThemeId;
  }

  let { preset, pageTheme = 'tokyo-night' }: Props = $props();

  // Mirror what hooks.server.ts emits: the page-level data-theme on
  // <html>. The tile inside should still resolve to its OWN preset
  // because the per-tile data-theme attribute trumps cascade.
  // `untrack` matches the production `(app)/+layout.svelte` snapshot
  // pattern and silences `svelte/state_referenced_locally`.
  const pageThemeSnapshot: ThemeId = untrack(() => pageTheme);
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = pageThemeSnapshot;
  }
</script>

<div data-testid="tile-wrapper" data-theme={preset} class="border-hairline rounded-2xl border p-2">
  <span
    data-testid="swatch"
    aria-hidden="true"
    class="bg-background-app block h-[100px] w-[160px] rounded-lg"
  ></span>
  <span data-testid="label" class="text-ink-strong text-xs">{preset}</span>
</div>
