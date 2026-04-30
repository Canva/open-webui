<script lang="ts">
  /**
   * Smoke harness for the Mermaid theme variables. Renders a tiny
   * two-node flowchart so the `mermaid-tokyo-night.png` visual
   * baseline can lock the chrome-token mapping in `mermaid.ts`.
   *
   * Mermaid is dynamically imported on mount so non-diagram routes
   * never pay the bundle cost. The store's `_reapplyMermaid` picks
   * up the loaded global on the next preset switch.
   */
  import { getContext } from 'svelte';
  import { THEME_CONTEXT_KEY, ThemeStore } from '$lib/stores/theme.svelte';
  import { buildMermaidThemeVariables } from '$lib/theme/mermaid';

  const theme = getContext<ThemeStore>(THEME_CONTEXT_KEY);

  let host = $state<HTMLDivElement | null>(null);

  $effect(() => {
    let cancelled = false;
    if (!host) return;

    void (async () => {
      const { default: mermaid } = await import('mermaid');
      // Stash on window so the store's `_reapplyMermaid` can find it
      // on subsequent preset switches without a re-import.
      (window as unknown as { mermaid: typeof mermaid }).mermaid = mermaid;

      mermaid.initialize({
        startOnLoad: false,
        theme: 'base',
        themeVariables: buildMermaidThemeVariables(theme.preset),
      });

      const definition = `flowchart LR\n  A[Workshop] -->|use| B(Agent)\n`;
      const { svg } = await mermaid.render(`mermaid-smoke-${theme.current}`, definition);
      if (!cancelled && host) host.innerHTML = svg;
    })();

    return () => {
      cancelled = true;
    };
  });
</script>

<section class="bg-background-app text-ink-body p-6">
  <h2 class="text-ink-strong mb-3 text-sm font-medium">Mermaid smoke</h2>
  <div bind:this={host} class="border-hairline bg-background-elevated rounded-xl border p-4"></div>
</section>
