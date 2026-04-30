/**
 * Vitest unit suite for `lib/utils/markdown.ts` — the two pure
 * helpers `Markdown.svelte` reaches for during streaming render.
 *
 * Locked by `rebuild/docs/plans/m2-conversations.md`:
 *   - § Tests § Frontend (line 1062): "markdown.test.ts —
 *     sanitisation, fenced-code-while-streaming detection, math
 *     passthrough, alert syntax."
 *   - § Markdown port (lines 906-936): the two helpers replace the
 *     legacy `replaceTokens` + `processResponseContent` pair.
 *
 * Sanitisation regressions live next to the `<HTMLToken>` component
 * (Phase 4b CT spec `tests/component/Markdown.spec.ts` covers
 * DOMPurify-stripped script/javascript:/onerror cases).
 */

import { describe, expect, it } from 'vitest';

import { closeOpenFences, escapeRawAngleBrackets } from '../../src/lib/utils/markdown';

// ---------------------------------------------------------------------------
// closeOpenFences
// ---------------------------------------------------------------------------

describe('closeOpenFences', () => {
  it('appends a closing fence when the content has an odd number of unclosed triple backticks', () => {
    const partial = '```ts\nconst x = 1;';
    expect(closeOpenFences(partial)).toBe('```ts\nconst x = 1;\n```');
  });

  it('leaves balanced backtick-fenced content untouched', () => {
    const balanced = '```ts\nconst x = 1;\n```';
    expect(closeOpenFences(balanced)).toBe(balanced);
  });

  it('handles the tilde-fence variant', () => {
    const partial = '~~~python\nprint("hi")';
    expect(closeOpenFences(partial)).toBe('~~~python\nprint("hi")\n~~~');
  });

  it('closes both backtick AND tilde fences when both are unbalanced', () => {
    // Pathological mid-stream snippet. Both fence variants get closed
    // independently because GFM forbids cross-closing them.
    const partial = '```ts\nconst x = 1;\n~~~text\nlorem';
    const closed = closeOpenFences(partial);
    expect(closed.endsWith('\n```\n~~~')).toBe(true);
  });

  it('returns the input unchanged when content is empty', () => {
    expect(closeOpenFences('')).toBe('');
  });

  it('does not double-close when the content already ends with a closing fence', () => {
    const balanced = '```\nfoo\n```';
    expect(closeOpenFences(balanced)).toBe(balanced);
  });
});

// ---------------------------------------------------------------------------
// escapeRawAngleBrackets
// ---------------------------------------------------------------------------

describe('escapeRawAngleBrackets', () => {
  it('escapes `<` outside HTML tag opens (e.g. `5 < 10`)', () => {
    const input = '5 < 10';
    expect(escapeRawAngleBrackets(input)).toBe('5 &lt; 10');
  });

  it('leaves valid HTML tag opens alone', () => {
    // The next character after `<` is a letter — that's a real tag
    // open, so we keep it (HTMLToken.svelte sanitises it later).
    const input = 'plain prose with <br> in the middle';
    expect(escapeRawAngleBrackets(input)).toBe('plain prose with <br> in the middle');
  });

  it('leaves comparison `<` alone when it appears inside an inline code span', () => {
    // The codespan is rendered verbatim by `CodespanToken`; escaping
    // here would surface the literal `&lt;` to the user.
    const input = 'Compare with `a < b` and continue.';
    expect(escapeRawAngleBrackets(input)).toBe('Compare with `a < b` and continue.');
  });

  it('leaves `<` inside fenced code blocks alone', () => {
    const input = ['Here is code:', '```ts', 'if (a < b) return;', '```'].join('\n');
    // The `<` lives inside a fenced block — must not be escaped.
    expect(escapeRawAngleBrackets(input)).toContain('if (a < b) return;');
    expect(escapeRawAngleBrackets(input)).not.toContain('a &lt; b');
  });

  it('leaves `<` inside tilde-fenced code blocks alone (GFM tilde variant)', () => {
    const input = ['~~~python', 'if a < b: return', '~~~'].join('\n');
    expect(escapeRawAngleBrackets(input)).toContain('if a < b: return');
  });

  it('handles streaming input where a fence is unclosed (the closeOpenFences case has not run yet)', () => {
    // If `escapeRawAngleBrackets` runs before `closeOpenFences`, the
    // partial code block's `<` would still be detected as inside-fence
    // (the fence opener is on a prior line) and left alone.
    const input = ['Mid stream:', '```ts', 'a < b'].join('\n');
    expect(escapeRawAngleBrackets(input)).toContain('a < b');
    expect(escapeRawAngleBrackets(input)).not.toContain('a &lt; b');
  });

  it('returns the input unchanged when content is empty', () => {
    expect(escapeRawAngleBrackets('')).toBe('');
  });

  it('does not touch `<` followed by `/` (a tag close like `</br>`)', () => {
    const input = 'before</br>after';
    expect(escapeRawAngleBrackets(input)).toBe('before</br>after');
  });
});
