<!--
  Harness for the M2 Markdown CT spec.

  `Markdown.svelte` itself does not read any context — but the
  recursive subtree (`Tokens` -> `CodeBlock` -> Shiki, `KatexRenderer`,
  `ColonFenceBlock` -> Mermaid) DOES need a `ThemeStore` in scope
  so the M1 Shiki + Mermaid hooks resolve to a known preset.

  Mounting against a deterministic preset (`tokyo-night`) keeps the
  CT bundle's syntax-highlighter rendering stable; without it every
  CT run would re-resolve highlighting against whatever the
  document's `data-theme` happens to be.
-->
<script lang="ts">
  import { setContext, untrack } from 'svelte';
  import { ThemeStore, THEME_CONTEXT_KEY } from '$lib/stores/theme.svelte';
  import Markdown from '$lib/components/chat/Markdown/Markdown.svelte';

  interface Props {
    content: string;
    streaming?: boolean;
  }

  let { content, streaming = false }: Props = $props();

  const contentSnapshot = untrack(() => content);
  const streamingSnapshot = untrack(() => streaming);

  // Pin to tokyo-night so the Shiki + Mermaid pipelines have a
  // known cascade context. Mirrors the visual-m1 spec's setup.
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = 'tokyo-night';
  }

  const themeStore = new ThemeStore({
    initial: 'tokyo-night',
    osDark: true,
    initialSource: 'explicit',
  });
  setContext(THEME_CONTEXT_KEY, themeStore);
</script>

<Markdown content={contentSnapshot} streaming={streamingSnapshot} />
