<!--
  Harness for the (app)/+layout.svelte CT spec.

  M1 moved the identity demo from `routes/+layout.svelte` (now just an
  app.css importer that renders {@render children()}) into
  `routes/(app)/+layout.svelte`, which also constructs the ThemeStore
  and provides it via `setContext`. The CT spec therefore mounts the
  (app) layout via this harness; the data shape is expanded with
  `theme` / `themeSource` fields the (app) layout reads to seed the
  store.

  Playwright CT's `mount(...)` API serialises props across a worker
  boundary and cannot pass a Snippet function directly, so the harness
  declares a no-op `children` snippet inline and forwards `data`.

  This is the workaround the m0 dispatch (test-author owner block,
  component/layout.spec.ts) explicitly authorises.
-->
<script lang="ts">
  import Layout from '../../src/routes/(app)/+layout.svelte';
  import type { LayoutData } from '../../src/routes/(app)/$types';

  let { data }: { data: LayoutData } = $props();
</script>

{#snippet child()}
  <span data-testid="harness-child">child-slot</span>
{/snippet}

<Layout {data} children={child} />
