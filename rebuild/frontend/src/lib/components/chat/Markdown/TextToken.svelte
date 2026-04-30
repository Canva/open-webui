<script lang="ts">
  /**
   * Inline `text` token renderer.
   *
   * Marked's inline `text` token may carry pre-tokenised inline children
   * (links, em/strong, codespans) when the text was discovered inside a
   * larger paragraph; in that case we recurse via `InlineTokens`. The leaf
   * case is just the literal text content.
   *
   * `escapeRawAngleBrackets` was already applied upstream in
   * `Markdown.svelte`, which writes `&lt;` into the marked source for
   * prose comparison operators (`5 < 10`). Svelte's `{token.text}`
   * interpolation would otherwise re-escape the `&` and surface
   * `5 &lt; 10` in the DOM. `decodeBasicEntities` reverses the pre-escape
   * (and any user-typed `&amp;` / `&gt;` / `&quot;` / `&#39;`) so the
   * rendered text matches what marked's own HTML renderer would emit.
   */
  import type { Tokens } from 'marked';
  import { decodeBasicEntities } from '$lib/utils/markdown';

  interface Props {
    token: Tokens.Text | Tokens.Escape;
  }

  const { token }: Props = $props();

  const text = $derived(decodeBasicEntities(token.text));
</script>

{text}
