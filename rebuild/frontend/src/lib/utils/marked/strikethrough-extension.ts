/**
 * GFM strikethrough fixer for marked.
 *
 * GFM technically allows single-tilde strikethroughs (`~text~`) but the
 * legacy fork's regression set showed users routinely typed standalone
 * tildes inside KaTeX expressions and prose, where the auto-strikethrough
 * was a footgun. This `tokenizer.del` override accepts only the canonical
 * double-tilde form (`~~text~~`); single tildes are passed by returning
 * `false`, which makes marked's inline lexer fall through to the next
 * rule and ultimately consume the `~` as plain text.
 *
 * The legacy fork additionally emitted an explicit `text` token for the
 * single-tilde case, but marked v18 narrowed `tokenizer.del`'s return
 * type to `Del | undefined | false` and rejects a `Text` return at the
 * type level. Falling through to the default text-tokenisation path is
 * the type-safe equivalent and produces identical user-visible output.
 */
import type { Tokens } from 'marked';

interface DelTokenizerThis {
  lexer: { inlineTokens(src: string): Tokens.Generic[] };
}

export const disableSingleTilde = {
  tokenizer: {
    del(this: DelTokenizerThis, src: string): Tokens.Del | false {
      const doubleMatch = /^~~(?=\S)([\s\S]*?\S)~~/.exec(src);
      if (doubleMatch) {
        const inner = doubleMatch[1] ?? '';
        return {
          type: 'del',
          raw: doubleMatch[0],
          text: inner,
          tokens: this.lexer.inlineTokens(inner),
        } as Tokens.Del;
      }
      return false;
    },
  },
};
