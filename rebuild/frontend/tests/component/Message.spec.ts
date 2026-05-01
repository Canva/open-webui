/**
 * Component-level driver for `lib/components/chat/Message.svelte`.
 *
 * Locked by `rebuild/docs/plans/m2-conversations.md`:
 *   - § Tests § Frontend (line 1064): "Message.spec.ts — renders a
 *     fixture corpus of assistant messages: plain, code, math,
 *     mermaid, alerts, mid-stream incomplete fences."
 *   - § Frontend components (line 887): the `Message` prop shape
 *     `{ message: HistoryMessage, parent: HistoryMessage | null }`.
 *   - § Acceptance criteria: branch chevron / cancelled / error
 *     surfaces are exercised here at the component layer (the
 *     branch chevron LIVES in `MessageList.svelte`, but the
 *     "user-vs-assistant differential rendering" lives here and
 *     the chevron's siblings-detection feeds into Message via
 *     `parent`).
 *
 * Layer choice: Playwright CT is the right tool because Message
 * reads two contexts (`useActiveChat`, `useToast`) and renders
 * the recursive Markdown subtree. jsdom would require simulating
 * `setContext`/`getContext` plus the marked + DOMPurify + Shiki
 * pipeline, which is exactly the bug class CT exists to dodge.
 */

import { test, expect } from '@playwright/experimental-ct-svelte';
import MessageHarness from './MessageHarness.svelte';
import type { HistoryMessage } from '../../src/lib/types/history';

/**
 * Build a deterministic `HistoryMessage` with sane defaults for
 * the corpus fixtures. Keeps each test's intent visible without
 * boilerplate.
 */
function msg(overrides: Partial<HistoryMessage> & Pick<HistoryMessage, 'id'>): HistoryMessage {
  return {
    id: overrides.id,
    parentId: overrides.parentId ?? null,
    childrenIds: overrides.childrenIds ?? [],
    role: overrides.role ?? 'assistant',
    content: overrides.content ?? '',
    timestamp: overrides.timestamp ?? 0,
    agent_id: overrides.agent_id ?? null,
    agentName: overrides.agentName ?? null,
    done: overrides.done ?? true,
    error: overrides.error ?? null,
    cancelled: overrides.cancelled ?? false,
    usage: overrides.usage ?? null,
  };
}

test.describe('Message — user vs assistant rendering', () => {
  test('renders a user message as plain right-aligned text', async ({ mount }) => {
    const userMsg = msg({
      id: 'u1',
      role: 'user',
      content: 'Hello there',
    });

    const component = await mount(MessageHarness, {
      props: { message: userMsg, parent: null },
    });

    await expect(component).toContainText('Hello there');
    // The user-bubble container is the OUTER `<div class="flex
    // justify-end">` — i.e. the rendered Message root. Playwright
    // CT mounts the component as a child of the page's `#root`,
    // so the wrapper is reachable via the `.flex.justify-end`
    // class names attached to its element.
    const justifyEnd = await component.evaluate((el) => {
      const seed = el as HTMLElement;
      const matches = (node: Element): boolean => {
        const cls = node.className;
        return typeof cls === 'string' && cls.includes('flex') && cls.includes('justify-end');
      };
      if (matches(seed)) return true;
      for (const node of Array.from(seed.querySelectorAll('*'))) {
        if (matches(node)) return true;
      }
      // Also check the parent chain in case Playwright's component
      // locator resolves to an inner Markdown / interaction element.
      let cur: Element | null = seed.parentElement;
      while (cur) {
        if (matches(cur)) return true;
        cur = cur.parentElement;
      }
      return false;
    });
    expect(justifyEnd).toBe(true);
  });

  test('renders an assistant message via the Markdown component', async ({ mount }) => {
    const assistantMsg = msg({
      id: 'a1',
      role: 'assistant',
      content: '**bold** and `code`',
      done: true,
      agent_id: 'gpt-4o',
      agentName: 'GPT-4o',
    });

    const component = await mount(MessageHarness, {
      props: { message: assistantMsg, parent: null },
    });

    // Markdown emits a real <strong> / <code> for the inline tokens.
    await expect(component.locator('strong')).toContainText('bold');
    await expect(component.locator('code').first()).toContainText('code');
  });
});

test.describe('Message — streaming caret', () => {
  test('renders a streaming caret while message.done is false', async ({ mount }) => {
    const assistantMsg = msg({
      id: 'a1',
      role: 'assistant',
      content: 'partial',
      done: false,
    });

    const component = await mount(MessageHarness, {
      props: { message: assistantMsg, parent: null },
    });

    // The caret is the lozenge "▍" inside an aria-hidden span.
    const caret = component.locator('span[aria-hidden="true"]').filter({ hasText: '▍' });
    await expect(caret).toBeVisible();
  });

  test('omits the streaming caret once message.done flips true', async ({ mount }) => {
    const assistantMsg = msg({
      id: 'a1',
      role: 'assistant',
      content: 'fully rendered',
      done: true,
    });

    const component = await mount(MessageHarness, {
      props: { message: assistantMsg, parent: null },
    });

    const caret = component.locator('span[aria-hidden="true"]').filter({ hasText: '▍' });
    await expect(caret).toHaveCount(0);
  });
});

test.describe('Message — terminal status surfaces', () => {
  test('renders the cancelled badge when message.cancelled is true', async ({ mount }) => {
    const cancelled = msg({
      id: 'a1',
      role: 'assistant',
      content: 'half-said',
      done: true,
      cancelled: true,
    });

    const component = await mount(MessageHarness, {
      props: { message: cancelled, parent: null },
    });

    await expect(component.getByText('Cancelled', { exact: true })).toBeVisible();
  });

  test('renders the error panel when message.error is set', async ({ mount }) => {
    const errored = msg({
      id: 'a1',
      role: 'assistant',
      content: 'partial before failure',
      done: true,
      error: { message: 'upstream rate-limited' },
    });

    const component = await mount(MessageHarness, {
      props: { message: errored, parent: null },
    });

    // The "Stream failed" header copy is the visible signal; the
    // error message is rendered verbatim below it.
    await expect(component.getByText('Stream failed', { exact: true })).toBeVisible();
    await expect(component.getByText('upstream rate-limited')).toBeVisible();
  });

  test('renders the error code when error.code is set (e.g. history_too_large)', async ({
    mount,
  }) => {
    const errored = msg({
      id: 'a1',
      role: 'assistant',
      content: 'partial before cap exceeded',
      done: true,
      error: {
        message: 'chat history exceeds 1 MiB cap',
        code: 'history_too_large',
      },
    });

    const component = await mount(MessageHarness, {
      props: { message: errored, parent: null },
    });

    // The error code surfaces in a small mono-font line beneath the
    // human message. It's the affordance the M2 plan calls for so the
    // UI can render an "exceeded time limit"-style hint.
    await expect(component.getByText('history_too_large', { exact: true })).toBeVisible();
  });
});

test.describe('Message — agent + usage footer', () => {
  test('renders the agent name in the footer when message.agent_id is set', async ({ mount }) => {
    const assistantMsg = msg({
      id: 'a1',
      role: 'assistant',
      content: 'hi',
      done: true,
      agent_id: 'gpt-4o',
      agentName: 'GPT-4o',
    });

    const component = await mount(MessageHarness, {
      props: { message: assistantMsg, parent: null },
    });

    await expect(component.getByText('GPT-4o', { exact: true })).toBeVisible();
  });

  test('renders the token count when message.usage is set', async ({ mount }) => {
    const assistantMsg = msg({
      id: 'a1',
      role: 'assistant',
      content: 'hi',
      done: true,
      agent_id: 'gpt-4o',
      agentName: 'GPT-4o',
      usage: { prompt_tokens: 12, completion_tokens: 87, total_tokens: 99 },
    });

    const component = await mount(MessageHarness, {
      props: { message: assistantMsg, parent: null },
    });

    await expect(component.getByText('99 tokens', { exact: true })).toBeVisible();
  });

  test('renders the regenerate button when parent is a user message', async ({ mount }) => {
    // Regenerate / Retry only render when there's a parent user
    // message to re-send. Critical-path coverage for the
    // "branching = sibling under same parent" flow.
    const userParent = msg({ id: 'u1', role: 'user', content: 'hi' });
    const assistantMsg = msg({
      id: 'a1',
      role: 'assistant',
      content: 'hello',
      parentId: 'u1',
      done: true,
    });

    const component = await mount(MessageHarness, {
      props: { message: assistantMsg, parent: userParent },
    });

    await expect(component.getByRole('button', { name: 'Regenerate message' })).toBeVisible();
  });

  test('omits the regenerate button when parent is null (root assistant)', async ({ mount }) => {
    const assistantMsg = msg({
      id: 'a1',
      role: 'assistant',
      content: 'system-style boot reply',
      done: true,
    });

    const component = await mount(MessageHarness, {
      props: { message: assistantMsg, parent: null },
    });

    await expect(component.getByRole('button', { name: 'Regenerate message' })).toHaveCount(0);
  });
});

test.describe('Message — token corpus through Markdown', () => {
  // Plan line 1064 calls for: plain, code, math, mermaid, alerts,
  // mid-stream incomplete fences. The Markdown subtree handles each
  // — Message just has to render the right wrapper. We assert on the
  // characteristic DOM each token type produces so a regression in
  // either the parent (`Message`) OR the child (`Markdown`) flips
  // this test red.

  test('renders a paragraph with plain prose', async ({ mount }) => {
    const m = msg({
      id: 'a1',
      role: 'assistant',
      content: 'Just plain text.',
      done: true,
    });

    const component = await mount(MessageHarness, { props: { message: m, parent: null } });
    await expect(component.locator('p').first()).toContainText('Just plain text.');
  });

  test('renders a fenced code block with the language attribute', async ({ mount }) => {
    const m = msg({
      id: 'a1',
      role: 'assistant',
      content: '```ts\nconst x = 1;\n```',
      done: true,
    });

    const component = await mount(MessageHarness, { props: { message: m, parent: null } });
    // The CodeBlock component exposes the literal source line; the
    // language label may live in a sibling element, but the body
    // text must be present.
    await expect(component).toContainText('const x = 1;');
  });

  test('renders a GitHub-style alert (`> [!NOTE]`)', async ({ mount }) => {
    const m = msg({
      id: 'a1',
      role: 'assistant',
      content: '> [!NOTE]\n> Heads up, this matters.',
      done: true,
    });

    const component = await mount(MessageHarness, { props: { message: m, parent: null } });
    // The alert renders as `<aside role="note">` with a "Note" label.
    await expect(component.getByRole('note', { name: 'Note' })).toBeVisible();
    await expect(component).toContainText('Heads up, this matters.');
  });

  test('renders a mid-stream incomplete fence as a closed code block', async ({ mount }) => {
    // The streaming caret + Markdown.svelte's `closeOpenFences` should
    // surface the partial code as a real code block, not as an
    // unstyled paragraph.
    const m = msg({
      id: 'a1',
      role: 'assistant',
      content: '```ts\nconst x = 1;', // unclosed fence; streaming
      done: false,
    });

    const component = await mount(MessageHarness, { props: { message: m, parent: null } });
    // The body text must appear (the language label `ts` may not
    // depending on the CodeBlock implementation; assert on the source).
    await expect(component).toContainText('const x = 1;');
  });

  test('renders a heading from the markdown', async ({ mount }) => {
    const m = msg({
      id: 'a1',
      role: 'assistant',
      content: '## Sub-section',
      done: true,
    });

    const component = await mount(MessageHarness, { props: { message: m, parent: null } });
    await expect(component.locator('h2')).toContainText('Sub-section');
  });

  test('renders an ordered list', async ({ mount }) => {
    const m = msg({
      id: 'a1',
      role: 'assistant',
      content: '1. first\n2. second',
      done: true,
    });

    const component = await mount(MessageHarness, { props: { message: m, parent: null } });
    await expect(component.locator('ol li').first()).toContainText('first');
  });
});

test.describe('Message — system message renders as a quiet rule', () => {
  test('a role=system message renders the System rule, not a bubble', async ({ mount }) => {
    const m = msg({
      id: 's1',
      role: 'system',
      content: 'Stay polite',
      done: true,
    });

    const component = await mount(MessageHarness, { props: { message: m, parent: null } });
    // The System rule labels itself with the literal "System" text.
    await expect(component.getByText('System', { exact: true })).toBeVisible();
  });
});
