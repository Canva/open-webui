/**
 * Colon-fence extension for marked. Mermaid only.
 *
 * Tokenises `:::mermaid\n...\n:::` into a `colonFence` token whose
 * `fenceType` is always `mermaid`. The legacy fork accepted any
 * `:::<identifier>` block (writing, code_execution, search_results, ...);
 * the rebuild deletes those branches per `m2-conversations.md` § Markdown
 * port; only mermaid survives. Other colon-fence types fall through as
 * plain markdown lines, which preserves the user's content without
 * surfacing chrome we no longer support.
 *
 * The renderer is a no-op (returns the raw text) since the rebuild renders
 * the diagram through `ColonFenceBlock.svelte`, not through marked's HTML
 * output.
 */
import type { TokenizerExtension, TokenizerThis } from 'marked';

interface ColonFenceToken {
  type: 'colonFence';
  raw: string;
  fenceType: 'mermaid';
  text: string;
}

const COLON_FENCE_REGEX = /^:::mermaid[^\n]*\n([\s\S]*?)(?:\n:::(?:\s*(?:\n|$)))/;

function colonFenceTokenizer(this: TokenizerThis, src: string): ColonFenceToken | undefined {
  const match = COLON_FENCE_REGEX.exec(src);
  if (!match) return undefined;
  return {
    type: 'colonFence',
    raw: match[0],
    fenceType: 'mermaid',
    text: (match[1] ?? '').trim(),
  };
}

function colonFenceStart(src: string): number {
  // Only flag the start when a `:::mermaid` opener is plausible. Other
  // `:::xxx` openers are intentionally ignored so they fall through as
  // plain text rather than being silently consumed.
  const idx = src.match(/^:::mermaid\b/m);
  return idx ? (idx.index ?? -1) : -1;
}

function colonFenceExtension(): TokenizerExtension {
  return {
    name: 'colonFence',
    level: 'block',
    start: colonFenceStart,
    tokenizer: colonFenceTokenizer,
  };
}

export default function colonFenceExtensionPlugin() {
  return {
    extensions: [colonFenceExtension()],
  };
}
