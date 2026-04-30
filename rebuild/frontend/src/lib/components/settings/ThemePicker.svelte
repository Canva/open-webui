<script lang="ts">
  /**
   * ThemePicker — the only visually-significant surface in M1.
   *
   * 2x2 grid of "Tokyo room" preview tiles plus a "Match system" reset
   * that only surfaces when the active theme came from an explicit
   * choice. Each tile is a real `<button>` with `aria-pressed`; the
   * tile root carries `data-theme="tokyo-{id}"` so the role-token CSS
   * variables resolve to that preset's values regardless of the page's
   * active theme. Day shows light, the three darks show their darks,
   * all on the same page, no tooltip needed. That trick is what makes
   * the picker self-explanatory at a glance.
   *
   * Pinned by `rebuild/docs/plans/m1-theming.md` § Deliverables (the
   * ThemePicker bullet) and § Acceptance criteria.
   *
   * Reads the per-request `ThemeStore` from context (constructed once
   * in `(app)/+layout.svelte` and `(public)/+layout.svelte` and
   * provided via `setContext('theme', store)`). The store mutates
   * `document.documentElement.dataset.theme` synchronously and writes
   * cookie + localStorage in the same call, so switching is instant
   * with no `transition` on the chrome repaint per the plan.
   *
   * Per-tile chrome (the swatch miniature) is factored into a snippet
   * — same markup for every tile because the per-tile `data-theme`
   * cascade does the visual differentiation upstream of any per-tile
   * markup divergence. The snippet keeps the each-block free of
   * decorative rendering details and uses the Svelte 5 snippet
   * primitive (no slot directive) per
   * `rebuild/docs/best-practises/svelte-best-practises.md` § 8.
   */
  import { getContext } from 'svelte';
  import { THEME_CONTEXT_KEY, ThemeStore } from '$lib/stores/theme.svelte';
  import type { ThemeId } from '$lib/theme/presets';

  const themeStore = getContext<ThemeStore>(THEME_CONTEXT_KEY);

  // Canonical iteration order from THEME_IDS in `presets.ts`. Renders
  // left-to-right, top-to-bottom in the 2x2: Day | Storm / Moon | Night.
  // The order is deliberate: light → progressively darker rooms.
  const TILES: ReadonlyArray<{ id: ThemeId; name: string; aria: string }> = [
    { id: 'tokyo-day', name: 'Tokyo Day', aria: 'Tokyo Day theme' },
    { id: 'tokyo-storm', name: 'Tokyo Storm', aria: 'Tokyo Storm theme' },
    { id: 'tokyo-moon', name: 'Tokyo Moon', aria: 'Tokyo Moon theme' },
    { id: 'tokyo-night', name: 'Tokyo Night', aria: 'Tokyo Night theme' },
  ];
</script>

{#snippet swatch()}
  <!--
    Preview swatch: a literal mini-app rendered with the role tokens of
    THIS tile's preset (the tile's `data-theme` attribute makes the
    cascade resolve to that preset). Pure CSS, no screenshot, no color
    literals. Aria-hidden because the label below carries the semantic
    name; the swatch is decorative pattern.

    Composition is the dispatch-pinned set: `background-app` body,
    `background-sidebar` strip on the inline-start side, `background-
    topbar` bar on top, an `accent-selection` dot in the inline-end
    corner, and a row of accent-mention / accent-headline / accent-
    stream pills along the bottom of the body — five elements that
    tell the chrome story in one read.

    Width is `w-full` so the swatch fills the tile column at every
    viewport (swatches scale with the grid; the height stays fixed at
    100px so the proportions read as "miniature surface" rather than
    "stretched banner").
  -->
  <span
    aria-hidden="true"
    class="bg-background-app border-hairline relative block h-[100px] w-full overflow-hidden rounded-lg border"
  >
    <span class="bg-background-topbar border-hairline absolute inset-x-0 top-0 block h-3 border-b"
    ></span>
    <span
      class="bg-background-sidebar border-hairline absolute start-0 top-3 bottom-0 block w-7 border-e"
    ></span>
    <span class="bg-accent-selection absolute end-3 top-5 block size-1.5 rounded-full"></span>
    <span class="absolute start-10 bottom-3 flex gap-1.5">
      <span class="bg-accent-mention block h-1.5 w-4 rounded-full"></span>
      <span class="bg-accent-headline block h-1.5 w-4 rounded-full"></span>
      <span class="bg-accent-stream block h-1.5 w-4 rounded-full"></span>
    </span>
  </span>
{/snippet}

<div class="@container">
  <!--
    Container query (not a viewport breakpoint) so the picker collapses
    to a single column when its OWN width is narrow — works correctly
    when M2+ embeds the picker in a side-panel under 384px wide. Tiles
    keep their full visual signature in the single-column fallback;
    only the grid topology changes.
  -->
  <div class="grid grid-cols-1 gap-3 @sm:grid-cols-2">
    {#each TILES as tile (tile.id)}
      {@const isActive = themeStore.current === tile.id}
      <button
        type="button"
        aria-pressed={isActive}
        aria-label={tile.aria}
        data-theme={tile.id}
        onclick={() => themeStore.setTheme(tile.id)}
        class={[
          'group relative flex w-full cursor-pointer flex-col items-stretch gap-2',
          'border-hairline rounded-2xl border p-2',
          'focus-visible:outline-accent-selection focus-visible:outline-2 focus-visible:outline-offset-2',
          'motion-safe:ease-out-quart motion-safe:transition-[outline-color] motion-safe:duration-150',
          isActive
            ? 'bg-background-elevated outline-accent-selection outline-2 outline-offset-2'
            : 'bg-background-app motion-safe:hover:outline-hairline-strong motion-safe:hover:outline-2 motion-safe:hover:outline-offset-2',
        ]}
      >
        {@render swatch()}
        <!--
          Label sits below the swatch. Active tile gets a slightly
          stronger weight so the squint test still resolves the
          selected room without relying on the ring alone (per
          `interaction-design.md`: never lean on a single signal).
        -->
        <span
          class={[
            'text-ink-strong block text-xs/[1.4]',
            isActive ? 'font-semibold' : 'font-medium',
          ]}>{tile.name}</span
        >
      </button>
    {/each}
  </div>

  {#if themeStore.source === 'explicit'}
    <!--
      Reset button mirrors DESIGN.json `button-secondary`: pill radius
      (`rounded-3xl`), 8px/16px padding, body typography (`text-sm
      font-medium`), Page-Fill-equivalent fill (`bg-background-
      elevated`), Strong-Ink text. Only surfaces when the active theme
      came from an explicit user pick — when the resolution is OS-
      driven there is nothing to clear.
    -->
    <div class="mt-4 flex justify-end">
      <button
        type="button"
        aria-label="Match system theme"
        onclick={() => themeStore.clearChoice()}
        class={[
          'bg-background-elevated text-ink-strong border-hairline cursor-pointer',
          'rounded-3xl border px-4 py-2 text-sm font-medium',
          'focus-visible:outline-accent-selection focus-visible:outline-2 focus-visible:outline-offset-2',
          'motion-safe:ease-out-quart motion-safe:transition-[border-color] motion-safe:duration-150',
          'motion-safe:hover:border-hairline-strong',
        ]}>Match system</button
      >
    </div>
  {/if}
</div>
