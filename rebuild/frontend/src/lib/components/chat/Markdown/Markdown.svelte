<script module lang="ts">
  /**
   * Marked configuration runs once on module evaluation. The extensions
   * are pure functions that mutate `marked`'s global state via
   * `marked.use(...)`; stacking them on every call would compound the
   * tokenizer chain and break the lexer. We guard with a per-process
   * flag stashed on `globalThis` so an HMR reload of this module in dev
   * does not re-register every extension on top of the previous chain.
   *
   * Order matters: KaTeX before details so `$$...$$` inside a
   * `<details>` block is captured by the math tokenizer, not as raw
   * HTML; colon-fence before footnote so `:::mermaid` openers are not
   * mistaken for inline footnote references.
   */
  import { marked } from 'marked';
  import detailsExtension from '$lib/utils/marked/extension';
  import katexExtension from '$lib/utils/marked/katex-extension';
  import colonFenceExtension from '$lib/utils/marked/colon-fence-extension';
  import footnoteExtension from '$lib/utils/marked/footnote-extension';
  import { disableSingleTilde } from '$lib/utils/marked/strikethrough-extension';

  const MARKED_FLAG = '__rebuildMarkdownConfigured__';
  const slot = globalThis as unknown as { [MARKED_FLAG]?: boolean };
  if (!slot[MARKED_FLAG]) {
    marked.setOptions({ breaks: true, gfm: true });
    marked.use(katexExtension());
    marked.use(detailsExtension());
    marked.use(colonFenceExtension());
    marked.use(footnoteExtension());
    marked.use(disableSingleTilde);
    slot[MARKED_FLAG] = true;
  }
</script>

<script lang="ts">
  /**
   * Markdown renderer. Replaces the legacy fork's
   * `chat/Messages/Markdown.svelte` orchestrator. Differences:
   *
   *   - Svelte 5 runes throughout (no `export let`, no `$:`, no event
   *     dispatchers).
   *   - Two pure helpers from `$lib/utils/markdown` replace the legacy
   *     `replaceTokens` + `processResponseContent` pair (citations,
   *     mentions, video / file substitution all dropped).
   *   - Citation, mention, source, and note-link extensions removed;
   *     iframe / file-id / status / video-tag branches in the legacy
   *     `MarkdownTokens.svelte` are not ported.
   *
   * Streaming contract:
   *   - `streaming = true` while the SSE delta loop is running. Closes
   *     dangling triple-backtick / triple-tilde fences so a partial
   *     code block renders as it arrives.
   *   - `streaming = false` once `done` lands; the closed-fence helper
   *     is skipped (the content is already terminal).
   *
   * Phase 3d mounts this as `<Markdown content={msg.content}
   * streaming={msg.streaming} />` inside `Message.svelte`.
   *
   * `marked` is imported in the `<script module>` block above; module-
   * scope bindings are visible from the instance script, so we reach
   * for `marked.lexer` directly without re-importing the value.
   */
  import type { Token } from 'marked';
  import { closeOpenFences, escapeRawAngleBrackets } from '$lib/utils/markdown';
  import Tokens from './Tokens.svelte';

  interface Props {
    content: string;
    streaming?: boolean;
  }

  let { content, streaming = false }: Props = $props();

  const tokens = $derived.by<Token[]>(() => {
    const escaped = escapeRawAngleBrackets(content ?? '');
    const prepared = streaming ? closeOpenFences(escaped) : escaped;
    return marked.lexer(prepared);
  });
</script>

<div class="markdown-body text-ink-body" dir="auto">
  <Tokens {tokens} {streaming} />
</div>

<style>
  /*
   * Typographic resets for the markdown surface. Per m2-conversations.md
   * § Markdown port (line 909) this is the one allowed scoped <style>
   * exception in the rebuild. Tailwind utilities can express most of
   * the rule set, but the descendant cascade for nested HTML elements
   * (paragraphs inside list items, code inside blockquotes, etc.) needs
   * a global selector reach that Tailwind 4 doesn't give us per-utility.
   *
   * Every color / radius / spacing token is sourced from the M0 + M1
   * CSS custom properties (--background-*, --hairline, --ink-*,
   * --radius-*). No literal hex, no ad-hoc gray classes. Font-sizes are
   * rem (root-relative), line-heights are unitless multipliers; both
   * scale through `--app-text-scale` automatically per the
   * Scale-Text-Scale Rule (DESIGN.md § 3).
   */
  .markdown-body :global(p:first-child),
  .markdown-body :global(h1:first-child),
  .markdown-body :global(h2:first-child),
  .markdown-body :global(h3:first-child),
  .markdown-body :global(h4:first-child),
  .markdown-body :global(h5:first-child),
  .markdown-body :global(h6:first-child),
  .markdown-body :global(ul:first-child),
  .markdown-body :global(ol:first-child) {
    margin-block-start: 0;
  }

  .markdown-body :global(p:last-child),
  .markdown-body :global(ul:last-child),
  .markdown-body :global(ol:last-child) {
    margin-block-end: 0;
  }

  .markdown-body :global(li > p) {
    margin: 0;
  }

  .markdown-body :global(li > p + p) {
    margin-block-start: 0.5em;
  }

  .markdown-body :global(details > summary) {
    list-style: none;
  }
  .markdown-body :global(details > summary)::-webkit-details-marker {
    display: none;
  }
  .markdown-body :global(details > summary)::before {
    content: '';
    display: inline-block;
    width: 0.5em;
    height: 0.5em;
    margin-inline-end: 0.5em;
    border-inline-start: 0.35em solid currentColor;
    border-block-start: 0.25em solid transparent;
    border-block-end: 0.25em solid transparent;
    transform: translateY(-1px);
    transition: transform 150ms var(--ease-out-quart);
  }
  .markdown-body :global(details[open] > summary)::before {
    transform: translateY(-1px) rotate(90deg);
  }

  /*
   * Long unbroken strings (URLs, base64, kebab-cased tokens) wrap rather
   * than horizontally pushing the message column. `anywhere` is the
   * unicode-aware variant of `break-word`.
   */
  .markdown-body :global(p),
  .markdown-body :global(li),
  .markdown-body :global(blockquote) {
    overflow-wrap: anywhere;
  }
</style>
