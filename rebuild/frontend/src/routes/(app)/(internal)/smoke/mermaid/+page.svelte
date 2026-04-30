<script lang="ts">
  /**
   * Visual-regression page mounting the M1 `MermaidSmoke` component
   * verbatim. The smoke component lazy-imports Mermaid on mount and
   * renders a tiny flowchart against the active preset's chrome
   * tokens; this route exists so the `mermaid-tokyo-night.png`
   * Playwright baseline targets a stable URL instead of `/settings`.
   *
   * Pinned by `rebuild/docs/plans/m2-conversations.md` § Deliverables.
   * The `(internal)/+layout@.svelte` reset keeps the M0 identity-demo
   * chrome (and Phase 3d's chat shell, when it lands) out of the
   * screenshot.
   */
  import MermaidSmoke from '$lib/components/smoke/MermaidSmoke.svelte';
</script>

<MermaidSmoke />
