<script lang="ts">
  /**
   * Inline-level token renderer. Mirror of `Tokens.svelte` but for the
   * inline subset of marked's token surface (`em`, `strong`, `link`,
   * `image`, `codespan`, `br`, `del`, inline `html`, inline `inlineKatex`,
   * `text`, `escape`, `footnote`).
   *
   * The legacy fork's `mention`, `citation`, `iframe`, and note-link
   * branches are deleted (see m2-conversations.md § Markdown port lines
   * 906-936). M4 reintroduces channels and may add a mention extension
   * back; this file is the integration site for that future work.
   *
   * Self-recurses into `link.tokens`, `strong.tokens`, `em.tokens`,
   * `del.tokens` so nested inline markup (a strong inside a link, a
   * codespan inside an em) renders correctly.
   */
  import { type Token, type Tokens as MarkedTokens } from 'marked';

  import { decodeBasicEntities } from '$lib/utils/markdown';
  import Self from './InlineTokens.svelte';
  import HTMLToken from './HTMLToken.svelte';
  import KatexRenderer from './KatexRenderer.svelte';
  import TextToken from './TextToken.svelte';
  import CodespanToken from './CodespanToken.svelte';

  type FootnoteToken = MarkedTokens.Generic & {
    type: 'footnote';
    text: string;
    escapedText: string;
  };
  type KatexToken = MarkedTokens.Generic & {
    type: 'inlineKatex';
    text: string;
    displayMode: boolean;
  };

  interface Props {
    tokens: Token[];
    /** Forwarded so descendant renderers can opt into streaming-aware UI. */
    streaming?: boolean;
  }

  let { tokens, streaming = false }: Props = $props();
</script>

{#each tokens as token, idx (idx)}
  {#if token.type === 'escape'}
    <TextToken token={token as MarkedTokens.Escape} />
  {:else if token.type === 'html'}
    <HTMLToken token={token as MarkedTokens.HTML | MarkedTokens.Tag} />
  {:else if token.type === 'link'}
    {@const link = token as MarkedTokens.Link}
    <a
      href={link.href}
      title={link.title ?? undefined}
      target="_blank"
      rel="nofollow noopener noreferrer"
      class="text-accent-selection hover:text-accent-selection-pressed underline underline-offset-2"
    >
      {#if link.tokens && link.tokens.length > 0}
        <Self tokens={link.tokens} {streaming} />
      {:else}
        {decodeBasicEntities(link.text)}
      {/if}
    </a>
  {:else if token.type === 'image'}
    {@const img = token as MarkedTokens.Image}
    <img
      src={img.href}
      alt={img.text ?? ''}
      title={img.title ?? undefined}
      loading="lazy"
      class="border-hairline my-2 h-auto max-w-full rounded-lg border"
    />
  {:else if token.type === 'strong'}
    {@const s = token as MarkedTokens.Strong}
    <strong class="text-ink-strong font-semibold">
      <Self tokens={s.tokens} {streaming} />
    </strong>
  {:else if token.type === 'em'}
    {@const em = token as MarkedTokens.Em}
    <em class="italic">
      <Self tokens={em.tokens} {streaming} />
    </em>
  {:else if token.type === 'codespan'}
    <CodespanToken token={token as MarkedTokens.Codespan} />
  {:else if token.type === 'br'}
    <br />
  {:else if token.type === 'del'}
    {@const d = token as MarkedTokens.Del}
    <del class="text-ink-muted">
      <Self tokens={d.tokens} {streaming} />
    </del>
  {:else if token.type === 'inlineKatex'}
    {@const k = token as KatexToken}
    {#if k.text}
      <KatexRenderer tex={k.text} displayMode={k.displayMode ?? false} />
    {/if}
  {:else if token.type === 'footnote'}
    {@const fn = token as FootnoteToken}
    <sup class="text-accent-mention text-[0.75em]">
      <a href={`#fn-${fn.text}`} aria-label={`Footnote ${fn.text}`} class="hover:underline">
        {fn.text}
      </a>
    </sup>
  {:else if token.type === 'text'}
    {@const t = token as MarkedTokens.Text}
    {#if t.tokens && t.tokens.length > 0}
      <Self tokens={t.tokens} {streaming} />
    {:else}
      <TextToken token={t} />
    {/if}
  {/if}
{/each}
