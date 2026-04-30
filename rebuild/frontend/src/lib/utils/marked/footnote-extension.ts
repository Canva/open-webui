/**
 * Footnote-reference extension for marked.
 *
 * Tokenises inline footnote references like `[^1]` or `[^note]` into a
 * `footnote` token whose `text` is the bare label and `escapedText` is the
 * HTML-safe form. The renderer is a no-op (returns the raw text); the
 * markdown component renders footnotes as `<sup>` elements directly so
 * sanitisation is a single, predictable pipe.
 *
 * Ported verbatim from the legacy fork's
 * `src/lib/utils/marked/footnote-extension.ts`.
 */
import type { TokenizerExtension } from 'marked';

interface FootnoteToken {
  type: 'footnote';
  raw: string;
  text: string;
  escapedText: string;
}

const HTML_ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => HTML_ESCAPES[c] ?? c);
}

function footnoteExtension(): TokenizerExtension {
  return {
    name: 'footnote',
    level: 'inline',
    start(src: string) {
      return src.search(/\[\^\s*[a-zA-Z0-9_-]+\s*\]/);
    },
    tokenizer(src: string): FootnoteToken | undefined {
      const rule = /^\[\^\s*([a-zA-Z0-9_-]+)\s*\]/;
      const match = rule.exec(src);
      if (!match) return undefined;
      const label = match[1] ?? '';
      return {
        type: 'footnote',
        raw: match[0],
        text: label,
        escapedText: escapeHtml(label),
      };
    },
  };
}

export default function footnoteExtensionPlugin() {
  return {
    extensions: [footnoteExtension()],
  };
}
