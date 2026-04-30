<script lang="ts">
  /**
   * Root layout: imports the global stylesheet (app.css → tokens.css →
   * Tailwind base) and renders whichever route group is active. The
   * theme store is constructed PER ROUTE GROUP — `(app)/+layout.svelte`
   * for authenticated chrome, `(public)/+layout.svelte` for share-style
   * surfaces — so each render tree gets its own per-request instance
   * (the M0 cross-cutting frontend convention rules out module-level
   * `$state` for per-user data).
   *
   * No identity demo here; that lives in `(app)/+layout.svelte`.
   */
  import '../app.css';
  import type { Snippet } from 'svelte';

  let { children }: { children: Snippet } = $props();
</script>

{@render children()}
