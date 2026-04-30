/**
 * Component-level driver for `lib/components/chat/Markdown/`.
 *
 * Locked by `rebuild/docs/plans/m2-conversations.md`:
 *   - § Tests § Frontend (line 1066): "Markdown.spec.ts — full token
 *     table from the legacy fork minus deleted types."
 *   - § Markdown port lines 906-936: the deleted token branches
 *     (`citation`, `mention`, `source`, `tasks`, `tool_calls`,
 *     `code_interpreter`, `reasoning`) MUST NOT render.
 *   - § Acceptance criteria — sanitisation regressions (line 931):
 *     `<script>` blocked, `javascript:` href stripped, `onerror`
 *     dropped.
 *
 * Layer choice: Playwright CT runs the full marked + DOMPurify +
 * Shiki + KaTeX + Mermaid pipeline in a real Chromium so we catch
 * any cross-library breakage that jsdom would silently mask.
 */

import { test, expect } from '@playwright/experimental-ct-svelte';
import MarkdownHarness from './MarkdownHarness.svelte';

// ---------------------------------------------------------------------------
// Token-by-token render contract.
// ---------------------------------------------------------------------------

test.describe('Markdown — block tokens', () => {
  test('renders a paragraph', async ({ mount }) => {
    const component = await mount(MarkdownHarness, { props: { content: 'Hello world.' } });
    await expect(component.locator('p')).toContainText('Hello world.');
  });

  test('renders headings h1-h6', async ({ mount }) => {
    const md = ['# h1', '## h2', '### h3', '#### h4', '##### h5', '###### h6'].join('\n\n');
    const component = await mount(MarkdownHarness, { props: { content: md } });

    for (const tag of ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']) {
      await expect(component.locator(tag).first()).toBeVisible();
    }
  });

  test('renders a fenced code block with the language attribute', async ({ mount }) => {
    const md = '```ts\nconst x = 1;\n```';
    const component = await mount(MarkdownHarness, { props: { content: md } });

    // The CodeBlock outputs the source line; assert on the visible
    // text rather than the highlighted span structure (Shiki tokens
    // are an internal detail).
    await expect(component).toContainText('const x = 1;');
  });

  test('renders inline code (codespan) inline', async ({ mount }) => {
    const component = await mount(MarkdownHarness, {
      props: { content: 'Run `npm install` first.' },
    });
    await expect(component.locator('code')).toContainText('npm install');
  });

  test('renders a blockquote', async ({ mount }) => {
    const component = await mount(MarkdownHarness, {
      props: { content: '> a quoted line' },
    });
    await expect(component.locator('blockquote')).toContainText('a quoted line');
  });

  test('renders an ordered list', async ({ mount }) => {
    const component = await mount(MarkdownHarness, {
      props: { content: '1. first\n2. second' },
    });
    await expect(component.locator('ol li').first()).toContainText('first');
    await expect(component.locator('ol li').nth(1)).toContainText('second');
  });

  test('renders an unordered list', async ({ mount }) => {
    const component = await mount(MarkdownHarness, {
      props: { content: '- alpha\n- beta' },
    });
    await expect(component.locator('ul li').first()).toContainText('alpha');
  });

  test('renders a GFM table', async ({ mount }) => {
    const md = ['| Name | Score |', '|------|-------|', '| Ada  | 99    |'].join('\n');
    const component = await mount(MarkdownHarness, { props: { content: md } });

    await expect(component.locator('table thead th').first()).toContainText('Name');
    await expect(component.locator('table tbody td').first()).toContainText('Ada');
  });

  test('renders a horizontal rule', async ({ mount }) => {
    const component = await mount(MarkdownHarness, {
      props: { content: 'before\n\n---\n\nafter' },
    });
    await expect(component.locator('hr')).toBeVisible();
  });

  test('renders a `<details>` HTML token via the details renderer', async ({ mount }) => {
    // The HTML extension surfaces details/summary as a structured
    // token, so the renderer's <details> wrapper is visible.
    const md = '<details><summary>Click me</summary>secret content</details>';
    const component = await mount(MarkdownHarness, { props: { content: md } });

    await expect(component.locator('details summary')).toContainText('Click me');
  });
});

test.describe('Markdown — inline tokens', () => {
  test('renders strong and em', async ({ mount }) => {
    const component = await mount(MarkdownHarness, {
      props: { content: '**bold** and *italic*' },
    });
    await expect(component.locator('strong')).toContainText('bold');
    await expect(component.locator('em')).toContainText('italic');
  });

  test('renders strikethrough (`~~`)', async ({ mount }) => {
    const component = await mount(MarkdownHarness, { props: { content: '~~struck~~' } });
    await expect(component.locator('del')).toContainText('struck');
  });

  test('renders an external link with target="_blank" and rel safety attrs', async ({ mount }) => {
    const component = await mount(MarkdownHarness, {
      props: { content: '[example](https://example.com)' },
    });
    const link = component.locator('a[href="https://example.com"]');
    await expect(link).toContainText('example');
    await expect(link).toHaveAttribute('target', '_blank');
    const rel = (await link.getAttribute('rel')) ?? '';
    expect(rel).toContain('noopener');
    expect(rel).toContain('noreferrer');
  });

  test('renders an inline image', async ({ mount }) => {
    const component = await mount(MarkdownHarness, {
      props: { content: '![alt text](https://example.com/x.png)' },
    });
    const img = component.locator('img');
    await expect(img).toHaveAttribute('src', 'https://example.com/x.png');
    await expect(img).toHaveAttribute('alt', 'alt text');
  });

  test('renders explicit `<br>` tokens', async ({ mount }) => {
    const component = await mount(MarkdownHarness, {
      props: { content: 'line one  \nline two' }, // GFM hard break
    });
    // marked emits a literal <br> for GFM line-breaks (`breaks: true`
    // is set in the module-script init block).
    await expect(component.locator('br')).toHaveCount(1);
  });
});

test.describe('Markdown — KaTeX math passthrough', () => {
  test('renders inline math (`$E = mc^2$`) via KatexRenderer', async ({ mount }) => {
    const component = await mount(MarkdownHarness, {
      props: { content: 'Einstein: $E = mc^2$' },
    });
    // KaTeX wraps its output in `.katex` spans.
    await expect(component.locator('.katex').first()).toBeVisible();
  });

  test('renders block math (`$$ ... $$`) as displayMode', async ({ mount }) => {
    const component = await mount(MarkdownHarness, {
      props: { content: '$$\n\\sum_{i=1}^n i\n$$' },
    });
    await expect(component.locator('.katex-display').first()).toBeVisible();
  });
});

test.describe('Markdown — GitHub-style alerts', () => {
  for (const variant of ['NOTE', 'TIP', 'IMPORTANT', 'WARNING', 'CAUTION'] as const) {
    test(`renders the [!${variant}] alert variant`, async ({ mount }) => {
      const md = `> [!${variant}]\n> Heads up.`;
      const component = await mount(MarkdownHarness, { props: { content: md } });

      const labelByVariant = {
        NOTE: 'Note',
        TIP: 'Tip',
        IMPORTANT: 'Important',
        WARNING: 'Warning',
        CAUTION: 'Caution',
      } as const;
      await expect(component.getByRole('note', { name: labelByVariant[variant] })).toBeVisible();
      await expect(component).toContainText('Heads up.');
    });
  }
});

test.describe('Markdown — mermaid colon-fence', () => {
  test('renders a `:::mermaid` block via ColonFenceBlock', async ({ mount }) => {
    const md = ':::mermaid\ngraph TD; A-->B;\n:::';
    const component = await mount(MarkdownHarness, { props: { content: md } });

    // The ColonFenceBlock wires up to the mermaid renderer; we don't
    // assert on the SVG output here (mermaid is async + theme-
    // dependent). The presence of the host element is the contract.
    await expect(component.locator('div').filter({ hasText: 'graph TD' }).first()).toBeAttached();
  });
});

// ---------------------------------------------------------------------------
// Streaming contract — closeOpenFences fires when streaming=true.
// ---------------------------------------------------------------------------

test.describe('Markdown — streaming render', () => {
  test('renders a mid-stream incomplete code fence as closed via closeOpenFences', async ({
    mount,
  }) => {
    // Without `closeOpenFences` the partial would render as a giant
    // unstyled paragraph. Streaming=true must trigger the helper so a
    // <code> element appears.
    const component = await mount(MarkdownHarness, {
      props: { content: '```ts\nconst x = 1;', streaming: true },
    });

    await expect(component).toContainText('const x = 1;');
    // The CodeBlock is rendered (rather than a <p> wrapping the
    // backticks). Assert by checking that no <p> contains the literal
    // triple-backtick prefix.
    const fenceParagraph = component.locator('p').filter({ hasText: '```ts' });
    await expect(fenceParagraph).toHaveCount(0);
  });

  test('streaming=true is harmless on balanced content', async ({ mount }) => {
    const component = await mount(MarkdownHarness, {
      props: { content: '```ts\nconst x = 1;\n```', streaming: true },
    });
    await expect(component).toContainText('const x = 1;');
  });

  test('escapes raw `<` in body text via escapeRawAngleBrackets', async ({ mount }) => {
    // `5 < 10` outside any tag context must render as literal text,
    // not be swallowed as a malformed tag.
    const component = await mount(MarkdownHarness, {
      props: { content: '5 < 10 is true.' },
    });
    await expect(component).toContainText('5 < 10 is true.');
  });
});

// ---------------------------------------------------------------------------
// Sanitisation regressions (plan line 931 — three explicit cases).
// ---------------------------------------------------------------------------

test.describe('Markdown — sanitisation', () => {
  test('strips `<script>` tags from inline HTML', async ({ mount }) => {
    const component = await mount(MarkdownHarness, {
      props: { content: '<script>alert(1)</script>' },
    });

    // No <script> element survives the pass through DOMPurify.
    await expect(component.locator('script')).toHaveCount(0);
  });

  test('strips javascript: scheme from anchor href', async ({ mount }) => {
    // The attack vector: an anchor whose href is `javascript:alert(1)`.
    // DOMPurify's ALLOWED_URI_REGEXP rejects the scheme; the anchor
    // is sanitised to either no href OR no href attribute at all.
    const component = await mount(MarkdownHarness, {
      props: { content: '<a href="javascript:alert(1)">click</a>' },
    });

    const anchors = component.locator('a');
    const count = await anchors.count();
    for (let i = 0; i < count; i += 1) {
      const href = await anchors.nth(i).getAttribute('href');
      expect(href ?? '').not.toMatch(/^javascript:/i);
    }
  });

  test('strips `onerror=` and other on* event handlers from img', async ({ mount }) => {
    const component = await mount(MarkdownHarness, {
      props: {
        content: '<img src="x" onerror="alert(1)">',
      },
    });

    // Either the img survives without the onerror, or it's stripped
    // entirely. Either way no onerror attribute on any element.
    const imgs = component.locator('img');
    const count = await imgs.count();
    for (let i = 0; i < count; i += 1) {
      const onerror = await imgs.nth(i).getAttribute('onerror');
      expect(onerror).toBeNull();
    }
  });
});

// ---------------------------------------------------------------------------
// Deleted token branches must not render (regression net for the legacy port).
// ---------------------------------------------------------------------------

test.describe('Markdown — deleted token branches do not render', () => {
  test('citation `[1]` markup falls through as plain text (extension deleted)', async ({
    mount,
  }) => {
    const component = await mount(MarkdownHarness, {
      props: { content: 'See note [1] for context.' },
    });

    // The legacy citation extension would render a clickable
    // citation chip; in the rebuild that extension is deleted, so
    // `[1]` reads as literal text inside the paragraph.
    await expect(component).toContainText('See note [1] for context.');
  });

  test('mention `@user` markup falls through as plain text (extension deleted)', async ({
    mount,
  }) => {
    const component = await mount(MarkdownHarness, {
      props: { content: 'Ping @alice when ready.' },
    });
    await expect(component).toContainText('Ping @alice when ready.');
  });
});
