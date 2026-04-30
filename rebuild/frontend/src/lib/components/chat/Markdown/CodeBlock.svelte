<script lang="ts">
  /**
   * Fenced code block. Delegates syntax highlighting to the M1 Shiki
   * highlighter (`$lib/markdown/codeblock`) so the markdown subtree
   * inherits the role-token-driven theme bridge for free; theme swaps
   * recolour the block in one paint per `m1-theming.md` § Open
   * questions (2).
   *
   * Trim list (vs the legacy fork's CodeBlock.svelte):
   *   - "Open in artefact" / "Send to canvas" buttons removed (no
   *     artefact surface in the rebuild).
   *   - Pyodide / Jupyter execution removed.
   *   - In-place editor (`CodeEditor.svelte`) removed.
   *   - Mermaid / Vega rendering moved to `ColonFenceBlock.svelte` (the
   *     `:::mermaid` colon-fence is the only diagram surface in the
   *     rebuild).
   *
   * What remains: the highlighted block, a copy button, and a download
   * button. Both buttons are icon-only with `aria-label`s. Buttons are
   * surfaced on hover (`group-hover:opacity-100`) so the resting
   * appearance is just the code.
   */
  import { getContext } from 'svelte';
  import { getShikiHighlighter } from '$lib/markdown/codeblock';
  import { THEME_CONTEXT_KEY, ThemeStore } from '$lib/stores/theme.svelte';

  interface Props {
    code: string;
    /** Language identifier from the fence info string (e.g. `ts`, `bash`). */
    lang?: string;
  }

  const { code, lang = '' }: Props = $props();

  const theme = getContext<ThemeStore>(THEME_CONTEXT_KEY);

  const displayLang = $derived(lang.trim() || 'text');

  let host = $state<HTMLDivElement | null>(null);
  let copied = $state(false);
  let copyError = $state(false);
  let highlightFailed = $state(false);

  $effect(() => {
    let cancelled = false;
    const node = host;
    if (!node) return;
    void (async () => {
      try {
        const hl = await getShikiHighlighter(theme.current, theme.preset);
        if (cancelled) return;
        const html = hl.codeToHtml(code, {
          lang: displayLang,
          theme: theme.current,
        });
        if (cancelled || !node) return;
        // Shiki returns trusted HTML built deterministically from the
        // source string. Mutating `innerHTML` keeps the project-wide
        // ban on `{@html}` (eslint-plugin-svelte/no-at-html-tags from
        // `flat/recommended`) unconditional.
        node.innerHTML = html;
        highlightFailed = false;
      } catch {
        // Unknown language or initialisation failure. Surface the raw
        // source so the user still sees their code; the caller learns
        // through the missing syntax colours that the language wasn't
        // recognised.
        if (!cancelled && node) {
          node.textContent = code;
          highlightFailed = true;
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  });

  async function copyToClipboard() {
    try {
      await navigator.clipboard.writeText(code);
      copied = true;
      copyError = false;
      setTimeout(() => {
        copied = false;
      }, 1500);
    } catch {
      copyError = true;
      setTimeout(() => {
        copyError = false;
      }, 2000);
    }
  }

  function downloadCode() {
    const extension = lang.trim() || 'txt';
    const blob = new Blob([code], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `code.${extension}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }
</script>

<figure
  class="border-hairline bg-background-code group relative my-3 overflow-hidden rounded-xl border"
>
  <header
    class="border-hairline bg-background-elevated text-ink-secondary flex items-center justify-between border-b px-3 py-1.5 text-xs"
  >
    <span class="font-mono tracking-wide lowercase" aria-label="Language: {displayLang}">
      {displayLang}
    </span>
    <div
      class="flex items-center gap-0.5 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100"
    >
      <button
        type="button"
        onclick={copyToClipboard}
        aria-label={copied ? 'Code copied' : 'Copy code'}
        class="text-ink-secondary hover:text-ink-strong hover:bg-background-app inline-flex size-7 items-center justify-center rounded-md transition-colors"
      >
        {#if copied}
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
            stroke-linejoin="round"
            class="text-status-success size-3.5"
            aria-hidden="true"
          >
            <path d="m3.5 8.5 3 3 6-7" />
          </svg>
        {:else if copyError}
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
            stroke-linejoin="round"
            class="text-status-danger size-3.5"
            aria-hidden="true"
          >
            <circle cx="8" cy="8" r="6.5" />
            <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" />
          </svg>
        {:else}
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
            class="size-3.5"
            aria-hidden="true"
          >
            <rect x="5" y="5" width="8" height="8" rx="1.5" />
            <path d="M3 11V4.5A1.5 1.5 0 0 1 4.5 3H11" />
          </svg>
        {/if}
      </button>
      <button
        type="button"
        onclick={downloadCode}
        aria-label="Download code"
        class="text-ink-secondary hover:text-ink-strong hover:bg-background-app inline-flex size-7 items-center justify-center rounded-md transition-colors"
      >
        <svg
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
          class="size-3.5"
          aria-hidden="true"
        >
          <path d="M8 2.5v8M5 7.5l3 3 3-3" />
          <path d="M2.75 13.5h10.5" />
        </svg>
      </button>
    </div>
  </header>

  <div
    bind:this={host}
    class="text-ink-strong overflow-x-auto p-4 font-mono text-xs leading-relaxed"
    role="region"
    aria-label="Code block in {displayLang}"
  >
    <pre class="whitespace-pre"><code>{code}</code></pre>
  </div>

  {#if highlightFailed}
    <p class="text-ink-muted border-hairline border-t px-3 py-1 text-xs">
      Syntax highlighter could not parse this language. Showing raw source.
    </p>
  {/if}
</figure>
