/**
 * `<details>` block extension for marked.
 *
 * Tokenises a literal `<details>...</details>` HTML block (with optional
 * `<summary>` first child) into a `details` token so the renderer can show
 * a Svelte-controlled disclosure instead of falling through to the raw
 * `html` token branch.
 *
 * Ported verbatim from the legacy fork's `src/lib/utils/marked/extension.ts`,
 * minus the legacy attribute branches (`type="tool_calls" | "reasoning" |
 * "code_interpreter"`) which the rebuild deliberately strips. The extension
 * still parses arbitrary attributes; the renderer simply ignores any not
 * named `summary`.
 */
import type { TokenizerExtension, TokenizerThis } from 'marked';

interface DetailsToken {
  type: 'details';
  raw: string;
  summary: string;
  text: string;
  attributes: Record<string, string>;
}

function findMatchingClosingTag(src: string, openTag: string, closeTag: string): number {
  let depth = 1;
  let index = openTag.length;
  while (depth > 0 && index < src.length) {
    if (src.startsWith(openTag, index)) {
      depth++;
    } else if (src.startsWith(closeTag, index)) {
      depth--;
    }
    if (depth > 0) {
      index++;
    }
  }
  return depth === 0 ? index + closeTag.length : -1;
}

function parseAttributes(tag: string): Record<string, string> {
  const attributes: Record<string, string> = {};
  const attrRegex = /(\w+)="(.*?)"/g;
  let match: RegExpExecArray | null;
  while ((match = attrRegex.exec(tag)) !== null) {
    const key = match[1];
    if (key) attributes[key] = match[2] ?? '';
  }
  return attributes;
}

function detailsTokenizer(this: TokenizerThis, src: string): DetailsToken | undefined {
  const detailsRegex = /^<details(\s+[^>]*)?>\n/;
  const summaryRegex = /^<summary>(.*?)<\/summary>\n/;

  const detailsMatch = detailsRegex.exec(src);
  if (!detailsMatch) return undefined;

  const endIndex = findMatchingClosingTag(src, '<details', '</details>');
  if (endIndex === -1) return undefined;

  const fullMatch = src.slice(0, endIndex);
  const detailsTag = detailsMatch[0];
  const attributes = parseAttributes(detailsTag);

  let content = fullMatch.slice(detailsTag.length, -10).trim();
  let summary = '';

  const summaryMatch = summaryRegex.exec(content);
  if (summaryMatch) {
    summary = (summaryMatch[1] ?? '').trim();
    content = content.slice(summaryMatch[0].length).trim();
  }

  return {
    type: 'details',
    raw: fullMatch,
    summary,
    text: content,
    attributes,
  };
}

function detailsStart(src: string): number {
  return src.match(/^<details[\s>]/) ? 0 : -1;
}

function detailsExtension(): TokenizerExtension {
  return {
    name: 'details',
    level: 'block',
    start: detailsStart,
    tokenizer: detailsTokenizer,
  };
}

export default function detailsExtensionPlugin() {
  return {
    extensions: [detailsExtension()],
  };
}
