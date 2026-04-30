<script lang="ts">
  /**
   * Stub. The legacy fork collapsed adjacent `<details type="tool_calls">`
   * (and similar reasoning / code-interpreter variants) into a single
   * "Exploring..." panel; the rebuild deletes those branches per
   * m2-conversations.md § Markdown port (`GROUPABLE_DETAIL_TYPES = new
   * Set([])`). Without grouping types, `Tokens.svelte` never produces a
   * `detail_group` token, so this component is functionally unused at
   * the moment.
   *
   * Kept as a named entry point for the day a future feature
   * (multi-step plans, agent traces) reintroduces grouped details. It
   * accepts a `children` snippet so callers can decide what to render
   * inside the group panel.
   */
  import type { Snippet } from 'svelte';

  interface Props {
    children: Snippet;
  }

  const { children }: Props = $props();
</script>

<div class="ds-details-group">
  {@render children()}
</div>
