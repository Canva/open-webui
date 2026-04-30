<script lang="ts">
  /**
   * Block-level token renderer. Switches on `token.type` and dispatches
   * each branch to either the matching component (`CodeBlock`,
   * `KatexRenderer`, `AlertRenderer`, `ColonFenceBlock`, `HTMLToken`) or a
   * piece of inline markup (`InlineTokens`). Self-recurses for blockquote,
   * list-item, and details inner content.
   *
   * Token surface intentionally narrower than the legacy fork: every
   * tool-call / reasoning / code-interpreter / citation / source / mention
   * branch is deleted (see m2-conversations.md § Markdown port lines
   * 906-936). Unknown tokens render as their `raw` text rather than being
   * silently swallowed; this keeps streaming-time renderer drift visible
   * to the developer console without breaking the user's view.
   */
  import { marked, type Token, type Tokens as MarkedTokens } from 'marked';

  import { decodeBasicEntities } from '$lib/utils/markdown';
  import Self from './Tokens.svelte';
  import InlineTokens from './InlineTokens.svelte';
  import HTMLToken from './HTMLToken.svelte';
  import CodeBlock from './CodeBlock.svelte';
  import KatexRenderer from './KatexRenderer.svelte';
  import AlertRenderer, { alertComponent } from './AlertRenderer.svelte';
  import ColonFenceBlock from './ColonFenceBlock.svelte';

  /**
   * Custom token shapes the rebuild's marked extensions emit. Marked
   * types these as `Tokens.Generic` (effectively `{ type: string;
   * [k: string]: any }`); we narrow at the dispatch site.
   */
  type DetailsToken = MarkedTokens.Generic & {
    type: 'details';
    summary: string;
    text: string;
    attributes: Record<string, string>;
  };
  type KatexToken = MarkedTokens.Generic & {
    type: 'inlineKatex' | 'blockKatex';
    text: string;
    displayMode: boolean;
  };
  type ColonFenceToken = MarkedTokens.Generic & {
    type: 'colonFence';
    fenceType: 'mermaid';
    text: string;
  };

  interface Props {
    tokens: Token[];
    /** Surfaces to children so streaming-aware renderers (e.g. `text`) can opt in. */
    streaming?: boolean;
    /**
     * Top-of-tree marker. Block-level recursion (list items, blockquotes)
     * passes `top={false}` so loose `text` tokens render inline rather
     * than wrapped in an extra `<p>`.
     */
    top?: boolean;
  }

  let { tokens, streaming = false, top = true }: Props = $props();

  function headingClass(depth: number): string {
    switch (depth) {
      case 1:
        return 'text-ink-strong mt-4 mb-2 text-xl font-semibold';
      case 2:
        return 'text-ink-strong mt-3 mb-2 text-lg font-semibold';
      case 3:
        return 'text-ink-strong mt-3 mb-1 text-base font-semibold';
      default:
        return 'text-ink-strong mt-2 mb-1 text-sm font-semibold';
    }
  }

  function alignStyle(align: 'center' | 'left' | 'right' | null | undefined): string | undefined {
    return align ? `text-align: ${align}` : undefined;
  }
</script>

{#each tokens as token, idx (idx)}
  {#if token.type === 'space'}
    <div aria-hidden="true" class="my-2"></div>
  {:else if token.type === 'hr'}
    <hr class="border-hairline my-4" />
  {:else if token.type === 'heading'}
    {@const h = token as MarkedTokens.Heading}
    <svelte:element
      this={`h${Math.min(Math.max(h.depth, 1), 6)}`}
      dir="auto"
      class={headingClass(h.depth)}
    >
      <InlineTokens tokens={h.tokens} {streaming} />
    </svelte:element>
  {:else if token.type === 'code'}
    {@const c = token as MarkedTokens.Code}
    <CodeBlock code={c.text ?? ''} lang={c.lang ?? ''} />
  {:else if token.type === 'table'}
    {@const tbl = token as MarkedTokens.Table}
    <div class="border-hairline my-3 overflow-hidden rounded-lg border">
      <div class="overflow-x-auto">
        <table class="text-ink-body w-full text-sm" dir="auto">
          <thead class="bg-background-elevated text-ink-strong">
            <tr>
              {#each tbl.header as cell, ci (ci)}
                <th
                  scope="col"
                  class="border-hairline border-b px-3 py-1.5 text-start font-medium"
                  style={alignStyle(tbl.align[ci])}
                >
                  <InlineTokens tokens={cell.tokens} {streaming} />
                </th>
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each tbl.rows as row, ri (ri)}
              <tr class={ri < tbl.rows.length - 1 ? 'border-hairline border-b' : ''}>
                {#each row as cell, ci (ci)}
                  <td class="px-3 py-1.5 align-top" style={alignStyle(tbl.align[ci])}>
                    <InlineTokens tokens={cell.tokens} {streaming} />
                  </td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {:else if token.type === 'blockquote'}
    {@const bq = token as MarkedTokens.Blockquote}
    {@const alert = alertComponent(bq)}
    {#if alert}
      <AlertRenderer {alert} />
    {:else}
      <blockquote dir="auto" class="border-hairline text-ink-secondary my-2 border-s ps-3.5">
        <Self tokens={bq.tokens} {streaming} top={false} />
      </blockquote>
    {/if}
  {:else if token.type === 'list'}
    {@const list = token as MarkedTokens.List}
    {#if list.ordered}
      <ol
        start={typeof list.start === 'number' ? list.start : 1}
        dir="auto"
        class="my-2 ps-6 [list-style:decimal]"
      >
        {#each list.items as item, ii (ii)}
          <li class="my-1 text-start">
            {#if item.task}
              <input
                type="checkbox"
                checked={item.checked}
                disabled
                class="me-1 align-middle"
                aria-label={item.checked ? 'Completed task' : 'Open task'}
              />
            {/if}
            <Self tokens={item.tokens} {streaming} top={list.loose} />
          </li>
        {/each}
      </ol>
    {:else}
      <ul dir="auto" class="my-2 ps-6 [list-style:disc]">
        {#each list.items as item, ii (ii)}
          <li class="my-1 text-start">
            {#if item.task}
              <input
                type="checkbox"
                checked={item.checked}
                disabled
                class="me-1 align-middle"
                aria-label={item.checked ? 'Completed task' : 'Open task'}
              />
            {/if}
            <Self tokens={item.tokens} {streaming} top={list.loose} />
          </li>
        {/each}
      </ul>
    {/if}
  {:else if token.type === 'paragraph'}
    {@const p = token as MarkedTokens.Paragraph}
    <p dir="auto" class="my-2 leading-relaxed">
      <InlineTokens tokens={p.tokens} {streaming} />
    </p>
  {:else if token.type === 'text'}
    {@const t = token as MarkedTokens.Text}
    {#if top}
      <p dir="auto" class="my-2 leading-relaxed">
        {#if t.tokens}
          <InlineTokens tokens={t.tokens} {streaming} />
        {:else}
          {decodeBasicEntities(t.text)}
        {/if}
      </p>
    {:else if t.tokens}
      <InlineTokens tokens={t.tokens} {streaming} />
    {:else}
      {decodeBasicEntities(t.text)}
    {/if}
  {:else if token.type === 'details'}
    {@const d = token as DetailsToken}
    <details class="border-hairline bg-background-elevated my-2 rounded-lg border px-3 py-2">
      <summary class="text-ink-strong cursor-pointer font-medium select-none"
        >{decodeBasicEntities(d.summary)}</summary
      >
      {#if d.text && d.text.trim().length > 0}
        <div class="text-ink-body mt-2">
          <Self tokens={marked.lexer(d.text)} {streaming} />
        </div>
      {/if}
    </details>
  {:else if token.type === 'html'}
    <HTMLToken token={token as MarkedTokens.HTML | MarkedTokens.Tag} />
  {:else if token.type === 'inlineKatex' || token.type === 'blockKatex'}
    {@const k = token as KatexToken}
    {#if k.text}
      <KatexRenderer tex={k.text} displayMode={k.displayMode} />
    {/if}
  {:else if token.type === 'colonFence'}
    {@const cf = token as ColonFenceToken}
    {#if cf.fenceType === 'mermaid'}
      <ColonFenceBlock code={cf.text} />
    {/if}
  {/if}
{/each}
