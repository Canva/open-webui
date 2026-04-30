<script lang="ts">
  /**
   * KaTeX wrapper. Lazy-imports `katex` + `mhchem` + the stylesheet on
   * first mount so a no-math conversation never pays the ~250 KiB bundle
   * cost. Subsequent re-renders share the cached module promise.
   *
   * Renders by mutating `host.innerHTML` rather than `{@html}` so the
   * project-wide ban on `{@html}` (eslint-plugin-svelte/no-at-html-tags
   * shipped via `flat/recommended`) stays unconditional. KaTeX returns
   * trusted HTML built deterministically from the TeX source, so this is
   * a controlled exception narrower than a blanket `{@html}` allow-list.
   *
   * `throwOnError: false` mirrors the legacy fork's behaviour: a
   * malformed expression renders as the original red-tinted fallback that
   * KaTeX produces, which is a useful affordance for the user spotting
   * their own typo mid-stream.
   */
  import type { renderToString as KatexRenderToString } from 'katex';

  interface Props {
    tex: string;
    displayMode?: boolean;
  }

  const { tex, displayMode = false }: Props = $props();

  let host = $state<HTMLSpanElement | null>(null);
  let renderToString = $state<typeof KatexRenderToString | null>(null);

  $effect(() => {
    let cancelled = false;
    void (async () => {
      if (renderToString === null) {
        const [katex] = await Promise.all([
          import('katex'),
          // mhchem extends KaTeX with `\ce{}` / `\pu{}` chemistry macros.
          // Module declared as untyped in `app.d.ts`; this import is
          // for its side effect on the KaTeX prototype.
          import('katex/contrib/mhchem'),
          // The stylesheet attaches to <head> as a side-effect module
          // import; KaTeX's HTML output assumes the CSS is present.
          import('katex/dist/katex.min.css'),
        ]);
        if (cancelled) return;
        renderToString = katex.renderToString;
      }
      const node = host;
      if (!node || renderToString === null) return;
      try {
        node.innerHTML = renderToString(tex, { displayMode, throwOnError: false });
      } catch {
        // KaTeX throws on extremely malformed input even with throwOnError
        // off; surface a fallback so the UI doesn't blank out.
        node.textContent = tex;
      }
    })();
    return () => {
      cancelled = true;
    };
  });
</script>

{#if displayMode}
  <span bind:this={host} class="katex-display-host my-1 block overflow-x-auto">
    <code class="text-ink-secondary font-mono text-[0.92em]">{tex}</code>
  </span>
{:else}
  <span bind:this={host} class="katex-inline-host">
    <code class="text-ink-secondary font-mono text-[0.92em]">{tex}</code>
  </span>
{/if}
