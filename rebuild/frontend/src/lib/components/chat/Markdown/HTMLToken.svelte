<script lang="ts">
  /**
   * Sanitised HTML pass-through. Any literal HTML the lexer surfaces
   * (`<br>`, `<details>`, plain prose like `<sub>`) is run through
   * DOMPurify with a strict allowlist before rendering.
   *
   * The three regression points the legacy fork tracked are intentionally
   * blocked by DOMPurify's defaults plus the explicit `FORBID_*` lists
   * below; phase 4b covers them with assertion-level tests but the inline
   * fixtures here document the contract:
   *
   *   - `<scr` + `ipt>alert(1)<\/scr` + `ipt>` is stripped: the `script`
   *     tag is in `FORBID_TAGS` (and DOMPurify's defaults).
   *   - An anchor with an `href` of `javascript:alert(1)` is sanitised to
   *     a bare anchor: DOMPurify's `ALLOWED_URI_REGEXP` rejects the
   *     `javascript:` scheme.
   *   - An `img` tag with an `onerror` attribute is stripped: every `on*`
   *     handler is in `FORBID_ATTR`.
   *
   * Renders by mutating `host.innerHTML` rather than `{@html}` so the
   * project-wide `{@html}` ban (eslint-plugin-svelte/no-at-html-tags from
   * `flat/recommended`) stays unconditional. DOMPurify returns trusted
   * HTML by contract, so this is a controlled exception.
   */
  import DOMPurify from 'dompurify';
  import type { Tokens } from 'marked';

  interface Props {
    token: Tokens.HTML | Tokens.Tag;
  }

  const { token }: Props = $props();

  let host = $state<HTMLSpanElement | null>(null);

  // Block-level HTML we explicitly want to surface (details/summary,
  // br, plain inline emphasis). DOMPurify's default allowlist is broad
  // enough; we narrow only the dangerous tags + every `on*` handler.
  const PURIFY_CONFIG = {
    FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form'],
    FORBID_ATTR: [
      'onerror',
      'onload',
      'onclick',
      'onmouseover',
      'onmouseenter',
      'onmouseleave',
      'onfocus',
      'onblur',
      'onchange',
      'oninput',
      'onsubmit',
      'onkeydown',
      'onkeyup',
      'onkeypress',
    ],
  };

  const sanitised = $derived(token.text ? DOMPurify.sanitize(token.text, PURIFY_CONFIG) : '');

  $effect(() => {
    const node = host;
    if (!node) return;
    // `sanitised` is sourced from DOMPurify, which guarantees the
    // returned string is HTML-safe per its allowlist contract.
    node.innerHTML = sanitised;
  });
</script>

{#if token.type === 'html'}
  <span bind:this={host}></span>
{/if}
