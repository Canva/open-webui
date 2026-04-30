/**
 * Two pure helpers consumed by `Markdown.svelte`. Replaces the legacy
 * fork's `replaceTokens` + `processResponseContent` pair, which pulled in
 * unrelated helpers (i18n, mention substitution, citation formatting) the
 * rebuild does not need.
 *
 * Both functions are pure (no DOM, no globals) so they are unit-testable
 * from `vitest` without a Svelte runtime, per `m2-conversations.md`
 * § Markdown port.
 *
 * Locked by `m2-conversations.md` § Markdown port (lines 906-936). Kept
 * deliberately small (~40 LOC budget the plan calls out).
 */

/**
 * If `content` ends mid-fenced-code-block (odd number of triple-backtick
 * or triple-tilde fences), append a closing fence so the marked lexer
 * renders the partial block as it streams in. Without this, the closing
 * fence only appears once the gateway emits the final chunk and the user
 * sees a giant unstyled paragraph in the meantime.
 *
 * Backticks and tildes are counted independently because GFM forbids
 * closing one variant with the other; we close whichever is currently
 * unbalanced.
 */
export function closeOpenFences(content: string): string {
  if (!content) return content;
  let backticks = 0;
  let tildes = 0;
  for (const line of content.split('\n')) {
    const trimmed = line.replace(/^[ \t]{0,3}/, '');
    if (trimmed.startsWith('```')) backticks += 1;
    else if (trimmed.startsWith('~~~')) tildes += 1;
  }
  let out = content;
  if (backticks % 2 === 1) out += '\n```';
  if (tildes % 2 === 1) out += '\n~~~';
  return out;
}

/**
 * Escape `<` characters that cannot start an HTML tag (e.g. `5 < 10`)
 * outside of fenced code blocks and inline codespans, so the marked lexer
 * doesn't trip on prose `<` and the user's comparison stays visible during
 * streaming.
 *
 * Codespans and fenced code blocks are skipped because their text is
 * displayed verbatim by `CodespanToken` / `CodeBlock`, where escaping
 * would surface the literal `&lt;` to the user.
 */
export function escapeRawAngleBrackets(content: string): string {
  if (!content) return content;
  const lines = content.split('\n');
  let inFence = false;
  let fenceMarker: '```' | '~~~' | null = null;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? '';
    const trimmed = line.replace(/^[ \t]{0,3}/, '');
    if (inFence) {
      if (fenceMarker && trimmed.startsWith(fenceMarker)) {
        inFence = false;
        fenceMarker = null;
      }
      continue;
    }
    if (trimmed.startsWith('```')) {
      inFence = true;
      fenceMarker = '```';
      continue;
    }
    if (trimmed.startsWith('~~~')) {
      inFence = true;
      fenceMarker = '~~~';
      continue;
    }
    lines[i] = escapeOutsideCodespans(line);
  }
  return lines.join('\n');
}

/**
 * Reverse the small set of HTML entity references the marked lexer can
 * carry through to a `text`-shaped token's `.text` field, so the Svelte
 * `{token.text}` interpolation in `TextToken.svelte` does not surface
 * the literal entity to the user.
 *
 * Two source paths converge here:
 *   1. `escapeRawAngleBrackets` (above) writes `&lt;` into the marked
 *      source for prose comparison operators (`5 < 10`). Without this
 *      decode the user sees `5 &lt; 10` in the DOM (Svelte's `{}`
 *      interpolation re-escapes the `&` for free).
 *   2. CommonMark says any HTML entity in markdown source is rendered
 *      as the corresponding character (`&amp;` ⇒ `&`). The marked
 *      *renderer* would do this for HTML output; we use the *lexer*
 *      and own the renderer ourselves, so we replay that contract here.
 *
 * Sanitisation is unaffected: HTML tokens go through `HTMLToken.svelte`
 * (DOMPurify) and never reach this helper. Codespans render verbatim
 * via `CodespanToken.svelte` and are never touched by either pre-escape
 * or this decode pass.
 *
 * `&amp;` is replaced last so user input like `&amp;lt;` (literal "&lt;"
 * in the DOM) is preserved instead of being collapsed to `<`.
 */
export function decodeBasicEntities(text: string): string {
  if (!text) return text;
  return text
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&');
}

/**
 * Escape `<` outside backtick-delimited spans on a single line. Walks the
 * string once, toggling on every `` ` `` run.
 */
function escapeOutsideCodespans(line: string): string {
  if (!line.includes('<')) return line;
  let out = '';
  let i = 0;
  while (i < line.length) {
    const ch = line[i];
    if (ch === '`') {
      // Find matching closing backtick (same run length, GFM rule).
      let runLen = 1;
      while (line[i + runLen] === '`') runLen += 1;
      const opener = line.slice(i, i + runLen);
      const closeAt = line.indexOf(opener, i + runLen);
      if (closeAt === -1) {
        out += line.slice(i);
        return out;
      }
      out += line.slice(i, closeAt + runLen);
      i = closeAt + runLen;
      continue;
    }
    if (ch === '<' && !/[A-Za-z/!?]/.test(line[i + 1] ?? '')) {
      out += '&lt;';
      i += 1;
      continue;
    }
    out += ch;
    i += 1;
  }
  return out;
}
