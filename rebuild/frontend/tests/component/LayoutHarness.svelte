<!--
  Harness for the +layout.svelte CT spec.

  +layout.svelte requires a `children` snippet (Svelte 5 `{@render children()}`
  pattern). Playwright CT's `mount(...)` API serialises props across a
  worker boundary and cannot pass a Snippet function directly. This wrapper
  declares a no-op `children` snippet inline, then forwards `data` to the
  layout — letting the CT spec drive the layout's actual `data.user`
  branch without a JSON-serialisable workaround for the snippet.

  This is the workaround the m0 dispatch (test-author owner block,
  component/layout.spec.ts) explicitly authorises:
    "If CT cannot mount a +layout.svelte directly (because layouts use
     {@render children()}), pass a small wrapper component and assert
     through it. Document the workaround."
-->
<script lang="ts">
  import Layout from '../../src/routes/+layout.svelte';
  import type { LayoutData } from '../../src/routes/$types';

  let { data }: { data: LayoutData } = $props();
</script>

{#snippet child()}
  <span data-testid="harness-child">child-slot</span>
{/snippet}

<Layout {data} children={child} />
