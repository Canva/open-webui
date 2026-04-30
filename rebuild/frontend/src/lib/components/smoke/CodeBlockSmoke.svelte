<script lang="ts">
  /**
   * Smoke harness for the Shiki + role-token pipeline. Renders one
   * fenced code block through `getShikiHighlighter` against the active
   * preset; exercises every `syntax-*` token on a single page so the
   * `code-block-tokyo-night.png` visual baseline can lock the
   * highlighter contract.
   *
   * NOT for production routes. Mounted by the M1 visual-baseline
   * harness only. M2's markdown renderer subsumes this.
   */
  import { getContext } from 'svelte';
  import { getShikiHighlighter } from '$lib/markdown/codeblock';
  import { THEME_CONTEXT_KEY, ThemeStore } from '$lib/stores/theme.svelte';

  const theme = getContext<ThemeStore>(THEME_CONTEXT_KEY);

  // Exercise: keyword (const, function, return), string (literal),
  // comment (line + jsdoc-ish), function (name + call), number, tag.
  const SOURCE = `// Smoke fixture: every syntax-* role token should be visible.
const greeting = "hello, workshop";

function pulse(count: number) {
  return count + 1;
}

const view = <span className="agent">{pulse(3)}</span>;
`;

  let host = $state<HTMLDivElement | null>(null);

  // Shiki returns trusted HTML built from a fixed source string; we
  // assign via `innerHTML` rather than `{@html}` so the eslint rule
  // banning `@html` stays unconditional and the next reviewer doesn't
  // have to litigate "is this one okay" each time.
  $effect(() => {
    let cancelled = false;
    if (!host) return;
    void (async () => {
      const hl = await getShikiHighlighter(theme.current, theme.preset);
      const out = hl.codeToHtml(SOURCE, {
        lang: 'tsx',
        theme: theme.current,
      });
      if (!cancelled && host) host.innerHTML = out;
    })();
    return () => {
      cancelled = true;
    };
  });
</script>

<section class="bg-background-app text-ink-body p-6">
  <h2 class="text-ink-strong mb-3 text-sm font-medium">Code block smoke</h2>
  <div
    bind:this={host}
    class="border-hairline bg-background-code overflow-x-auto rounded-xl border p-4 font-mono text-xs leading-relaxed"
  ></div>
</section>
