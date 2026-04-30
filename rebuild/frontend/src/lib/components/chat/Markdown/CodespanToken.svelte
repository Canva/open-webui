<script lang="ts">
  /**
   * Inline codespan renderer (`` `code` ``). One of the few places the
   * markdown port relies on a hard-coded em adjustment: the standard body
   * scale would render a codespan visibly larger than the surrounding
   * prose because JetBrainsMono runs taller than Inter at the same em.
   * `text-[0.92em]` brings the optical size back in line with the body
   * line height. This is the single tolerated `text-[…]` deviation in
   * the markdown port (see m2-conversations.md § Markdown port, line 928
   * for the rationale).
   */
  import type { Tokens } from 'marked';

  interface Props {
    token: Tokens.Codespan;
  }

  const { token }: Props = $props();
</script>

<code
  class="bg-background-code text-ink-strong border-hairline rounded-sm border px-1 py-0.5 font-mono text-[0.92em]"
  >{token.text}</code
>
