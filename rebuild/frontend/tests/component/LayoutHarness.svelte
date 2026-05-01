<!--
  Harness for the (app)/+layout.svelte CT spec.

  Phase 3d swapped the M0 identity-demo card for the real M2 chat shell
  (sidebar, conversation slot, toaster, mobile drawer). The (app)
  layout still owns the ThemeStore wiring AND now also constructs every
  M2 store (`provideChats`, `provideFolders`, `provideAgents`,
  `provideActiveChat`, `provideToast`) inline from the `data` prop —
  see `routes/(app)/+layout.svelte` for the canonical setup. This
  harness therefore ONLY needs to forward `data`; the layout itself is
  responsible for setting up every context the sidebar/conversation
  subtree reads.

  Playwright CT's `mount(...)` API serialises props across a worker
  boundary and cannot pass a Snippet function directly, so the harness
  declares a no-op `children` snippet inline and forwards `data`. This
  is the workaround the m0 dispatch (test-author owner block,
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
