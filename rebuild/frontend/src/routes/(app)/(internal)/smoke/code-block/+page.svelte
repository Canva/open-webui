<script lang="ts">
  /**
   * Visual-regression page mounting the M1 `CodeBlockSmoke` component
   * verbatim. The smoke component owns its own visual surface (Shiki
   * highlighter against the active preset's `--syntax-*` role tokens);
   * this route exists so the `code-block-tokyo-night.png` Playwright
   * baseline targets a stable URL instead of `/settings`.
   *
   * Pinned by `rebuild/docs/plans/m2-conversations.md` § Deliverables.
   * The `(internal)/+layout@.svelte` reset keeps the M0 identity-demo
   * chrome (and Phase 3d's chat shell, when it lands) out of the
   * screenshot.
   */
  import CodeBlockSmoke from '$lib/components/smoke/CodeBlockSmoke.svelte';
</script>

<CodeBlockSmoke />
