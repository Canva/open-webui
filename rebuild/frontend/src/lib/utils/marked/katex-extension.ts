/**
 * KaTeX math extension for marked.
 *
 * Tokenises inline (`$...$`, `\(...\)`, `\ce{...}`, `\pu{...}`) and block
 * (`$$...$$`, `\[...\]`, `\begin{equation}...\end{equation}`) math
 * delimiters into `inlineKatex` / `blockKatex` tokens so the renderer can
 * pass the raw TeX source to KaTeX. The renderer is a no-op (returns the
 * raw text) since the rebuild renders math through `KatexRenderer.svelte`,
 * not through marked's HTML output.
 *
 * Ported verbatim from the legacy fork's `src/lib/utils/marked/katex-extension.ts`
 * (commit history reference: aug 2024 `mhchem` extension addition; oct 2024
 * `ALLOWED_SURROUNDING_CHARS` regex precompile to fix the 87% rendering-
 * time hot-spot). The performance comment is preserved verbatim because the
 * regex compilation is genuinely the load-bearing detail.
 */
import type { TokenizerExtension, TokenizerExtensionFunction } from 'marked';

const DELIMITER_LIST = [
  { left: '$$', right: '$$', display: true },
  { left: '$', right: '$', display: false },
  { left: '\\pu{', right: '}', display: false },
  { left: '\\ce{', right: '}', display: false },
  { left: '\\(', right: '\\)', display: false },
  { left: '\\[', right: '\\]', display: true },
  { left: '\\begin{equation}', right: '\\end{equation}', display: true },
];

const ALLOWED_SURROUNDING_CHARS =
  '\\s。，、､;；„“‘’“”（）「」『』［］《》【】‹›«»…⋯:：？！～⇒?!-\\/:-@\\[-`{-~\\p{Script=Han}\\p{Script=Hiragana}\\p{Script=Katakana}\\p{Script=Hangul}';

// Pre-compile the surrounding-character regex once at module load. The
// Unicode property escapes (\p{Script=Han}, etc.) are extremely expensive
// to recompile; doing so on every call previously caused ~87% of markdown
// rendering time to be spent in KaTeX regex compilation.
const ALLOWED_SURROUNDING_CHARS_REGEX = new RegExp(`[${ALLOWED_SURROUNDING_CHARS}]`, 'u');

const inlinePatterns: string[] = [];
const blockPatterns: string[] = [];

function escapeRegex(s: string): string {
  return s.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&');
}

function generateRegexRules(delimiters: typeof DELIMITER_LIST) {
  delimiters.forEach((delimiter) => {
    const { left, right, display } = delimiter;
    const escapedLeft = escapeRegex(left);
    const escapedRight = escapeRegex(right);

    if (!display) {
      inlinePatterns.push(`${escapedLeft}((?:\\\\[^]|[^\\\\])+?)${escapedRight}`);
    } else {
      inlinePatterns.push(`${escapedLeft}(?!\\n)((?:\\\\[^]|[^\\\\])+?)(?!\\n)${escapedRight}`);
      blockPatterns.push(`${escapedLeft}\\n((?:\\\\[^]|[^\\\\])+?)\\n${escapedRight}`);
    }
  });

  const inlineRule = new RegExp(
    `^(${inlinePatterns.join('|')})(?=[${ALLOWED_SURROUNDING_CHARS}]|$)`,
    'u',
  );
  const blockRule = new RegExp(
    `^(${blockPatterns.join('|')})(?=[${ALLOWED_SURROUNDING_CHARS}]|$)`,
    'u',
  );

  return { inlineRule, blockRule };
}

const { inlineRule, blockRule } = generateRegexRules(DELIMITER_LIST);

function isAllowedTrailing(src: string, i: number): boolean {
  return i >= src.length || ALLOWED_SURROUNDING_CHARS_REGEX.test(src.charAt(i));
}

function isBlockBoundary(src: string, i: number): boolean {
  return /^(?:[ \t]*\r?\n|$)/.test(src.slice(i));
}

function findClosingDelimiter(src: string, i: number): number {
  // Iterative for clarity; the legacy recursion worked but was harder to
  // reason about during the v18 marked port.
  let j = i;
  while (j < src.length - 1) {
    if (src[j] === '\\') {
      j += 2;
      continue;
    }
    if (src[j] === '$' && src[j + 1] === '$') {
      return j;
    }
    j += 1;
  }
  return -1;
}

interface KatexToken {
  type: 'inlineKatex' | 'blockKatex';
  raw: string;
  text: string;
  displayMode: boolean;
}

export function tokenizeDisplayMath(
  src: string,
  type: 'inlineKatex' | 'blockKatex',
  requireBlockBoundary = false,
): KatexToken | undefined {
  if (!src.startsWith('$$')) return undefined;

  const endIndex = findClosingDelimiter(src, 2);
  if (endIndex === -1) return undefined;

  const raw = src.slice(0, endIndex + 2);
  const text = raw.slice(2, -2);
  const afterClose = endIndex + 2;

  const valid =
    text.trim().length > 0 &&
    isAllowedTrailing(src, afterClose) &&
    (!requireBlockBoundary || isBlockBoundary(src, afterClose));

  return valid ? { type, raw, text, displayMode: true } : undefined;
}

function katexStart(src: string, displayMode: boolean): number | undefined {
  for (let i = 0; i < src.length; i++) {
    const ch = src.charCodeAt(i);

    if (ch === 36 /* $ */) {
      if (displayMode && src.charAt(i + 1) !== '$') continue;
      if (i === 0 || ALLOWED_SURROUNDING_CHARS_REGEX.test(src.charAt(i - 1))) {
        return i;
      }
    } else if (ch === 92 /* \ */) {
      const next = src.charAt(i + 1);
      if (displayMode) {
        if (next !== '[' && next !== 'b') continue;
      } else {
        if (next !== '(' && next !== 'c' && next !== 'p') continue;
      }
      if (i === 0 || ALLOWED_SURROUNDING_CHARS_REGEX.test(src.charAt(i - 1))) {
        return i;
      }
    }
  }
  return undefined;
}

const katexTokenizer = (displayMode: boolean): TokenizerExtensionFunction => {
  return function (src) {
    if (src.startsWith('$$')) {
      const displayToken = tokenizeDisplayMath(
        src,
        displayMode ? 'blockKatex' : 'inlineKatex',
        displayMode,
      );
      if (displayToken) return displayToken;
    }

    const ruleReg = displayMode ? blockRule : inlineRule;
    const type: 'inlineKatex' | 'blockKatex' = displayMode ? 'blockKatex' : 'inlineKatex';

    const match = ruleReg.exec(src);
    if (!match) return undefined;

    const text = match
      .slice(2)
      .filter((item): item is string => Boolean(item))
      .find((item) => item.trim());

    if (text === undefined) return undefined;

    return {
      type,
      raw: match[0],
      text,
      displayMode,
    };
  };
};

function inlineKatex(): TokenizerExtension {
  return {
    name: 'inlineKatex',
    level: 'inline',
    start: (src) => katexStart(src, false),
    tokenizer: katexTokenizer(false),
  };
}

function blockKatex(): TokenizerExtension {
  return {
    name: 'blockKatex',
    level: 'block',
    start: (src) => katexStart(src, true),
    tokenizer: katexTokenizer(true),
  };
}

export default function katexExtensionPlugin() {
  return {
    extensions: [inlineKatex(), blockKatex()],
  };
}
