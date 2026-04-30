<script lang="ts">
  /**
   * `:::mermaid` colon-fence renderer. The legacy fork accepted any
   * `:::<identifier>` block (writing, code_execution, search_results,
   * ...); the rebuild keeps only mermaid (see m2-conversations.md
   * § Markdown port lines 906-936). The colon-fence-extension itself
   * also rejects non-mermaid openers, so this component never sees
   * another fence type.
   *
   * Mermaid is dynamically imported the first time a diagram appears so
   * a no-diagram conversation never pays the ~600 KiB bundle cost. The
   * theme-bridge module (`$lib/theme/mermaid`) maps the active preset's
   * chrome tokens onto Mermaid's `themeVariables`; the M1 ThemeStore's
   * `_reapplyMermaid` picks up the loaded global on subsequent preset
   * switches by reading `window.mermaid`. Matching the smoke component's
   * call shape so the M1 visual baselines (`mermaid-tokyo-night.png`)
   * keep applying once Phase 3c retargets them.
   *
   * Renders by mutating `host.innerHTML` so the project-wide ban on
   * `{@html}` (eslint-plugin-svelte/no-at-html-tags from
   * `flat/recommended`) stays unconditional. Mermaid returns trusted SVG
   * built from the diagram source.
   */
  import { getContext } from 'svelte';
  import { THEME_CONTEXT_KEY, ThemeStore } from '$lib/stores/theme.svelte';
  import { buildMermaidThemeVariables } from '$lib/theme/mermaid';

  interface Props {
    code: string;
  }

  const { code }: Props = $props();
  const uid = $props.id();

  const theme = getContext<ThemeStore>(THEME_CONTEXT_KEY);

  let host = $state<HTMLDivElement | null>(null);
  let renderError = $state<string | null>(null);
  let loading = $state(true);

  $effect(() => {
    let cancelled = false;
    const node = host;
    if (!node) return;
    loading = true;
    void (async () => {
      try {
        const { default: mermaid } = await import('mermaid');
        if (cancelled) return;
        // Stash on window so the ThemeStore's `_reapplyMermaid` can
        // re-theme on preset switch without a second dynamic import.
        (window as unknown as { mermaid: typeof mermaid }).mermaid = mermaid;

        mermaid.initialize({
          startOnLoad: false,
          theme: 'base',
          themeVariables: buildMermaidThemeVariables(theme.preset),
        });

        const { svg } = await mermaid.render(`${uid}-${theme.current}`, code);
        if (cancelled || !node) return;
        node.innerHTML = svg;
        renderError = null;
      } catch (err) {
        if (cancelled || !node) return;
        node.innerHTML = '';
        renderError = err instanceof Error ? err.message : 'Diagram failed to render.';
      } finally {
        if (!cancelled) loading = false;
      }
    })();
    return () => {
      cancelled = true;
    };
  });
</script>

<figure
  class="border-hairline bg-background-elevated my-3 overflow-hidden rounded-xl border"
  aria-label="Mermaid diagram"
>
  <div class="overflow-x-auto p-4">
    <div bind:this={host} class="text-ink-body" aria-live="polite"></div>
    {#if loading && !renderError}
      <p class="text-ink-muted text-xs">Rendering diagram.</p>
    {/if}
    {#if renderError}
      <div class="space-y-1">
        <p class="text-status-danger text-xs font-medium">Diagram failed to render.</p>
        <pre
          class="bg-background-code text-ink-secondary border-hairline overflow-x-auto rounded-md border p-2 font-mono text-xs leading-relaxed">{code}</pre>
      </div>
    {/if}
  </div>
</figure>
