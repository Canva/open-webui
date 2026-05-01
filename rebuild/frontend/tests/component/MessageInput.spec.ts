/**
 * Component-level driver for `lib/components/chat/MessageInput.svelte`.
 *
 * Locked by `rebuild/docs/plans/m2-conversations.md`:
 *   - § Tests § Frontend: "MessageInput.spec.ts — Enter sends,
 *     Shift+Enter newlines, Esc fires cancel, agent dropdown shows
 *     the populated `agents` store."
 *   - § Frontend components: "MessageInput — single textarea,
 *     auto-grows, Enter sends, Shift+Enter newlines, Esc cancels
 *     in-flight stream."
 *
 * Layer choice: Playwright CT — the component reads three contexts
 * and composes the `<AgentSelector>` recursively. The harness
 * (`MessageInputHarness.svelte`) constructs each store and exposes
 * recording stubs for `send`/`cancel` so the spec asserts on the
 * input's contract WITHOUT needing MSW inside the CT bundle.
 */

import { test, expect } from '@playwright/experimental-ct-svelte';
import MessageInputHarness from './MessageInputHarness.svelte';
import type { AgentInfo } from '../../src/lib/types/agent';

test.describe('MessageInput — keyboard contract', () => {
  test('Enter sends the message and clears the textarea', async ({ mount, page }) => {
    const component = await mount(MessageInputHarness, {
      props: { initialAgentId: 'gpt-4o' },
    });

    const textarea = component.getByRole('textbox', { name: 'Compose a message' });
    await textarea.fill('Hello there');
    await textarea.press('Enter');

    // The recording stub captured one call with the typed content.
    const calls = await page.evaluate(
      () => (window as unknown as { __sendCalls: { content: string }[] }).__sendCalls,
    );
    expect(calls).toHaveLength(1);
    expect(calls[0]!.content).toBe('Hello there');

    // The textarea has been cleared so the user can keep typing.
    await expect(textarea).toHaveValue('');
  });

  test('Shift+Enter inserts a newline without sending', async ({ mount, page }) => {
    const component = await mount(MessageInputHarness, {
      props: { initialAgentId: 'gpt-4o' },
    });

    const textarea = component.getByRole('textbox', { name: 'Compose a message' });
    await textarea.fill('line one');
    await textarea.press('Shift+Enter');
    await textarea.type('line two');

    // The recording stub stays empty (no send fired).
    const calls = await page.evaluate(
      () => (window as unknown as { __sendCalls: unknown[] }).__sendCalls,
    );
    expect(calls).toHaveLength(0);

    // The textarea contains both lines separated by a newline.
    const value = await textarea.inputValue();
    expect(value).toContain('line one');
    expect(value).toContain('line two');
    expect(value.split('\n').length).toBeGreaterThanOrEqual(2);
  });

  test('Esc fires cancel when streaming is in flight', async ({ mount, page }) => {
    const component = await mount(MessageInputHarness, {
      props: { initialAgentId: 'gpt-4o' },
    });

    // Flip streaming to 'streaming' via the exposed store handle so
    // the component renders the cancel branch (Esc only fires while
    // streaming is in flight).
    await page.evaluate(() => {
      (
        window as unknown as { __activeChatStore: { streaming: string } }
      ).__activeChatStore.streaming = 'streaming';
    });

    const textarea = component.getByRole('textbox', { name: 'Compose a message' });
    await textarea.focus();
    await textarea.press('Escape');

    const cancelCalls = await page.evaluate(
      () => (window as unknown as { __cancelCalls: number[] }).__cancelCalls,
    );
    expect(cancelCalls.length).toBeGreaterThanOrEqual(1);
  });
});

test.describe('MessageInput — disabled state during streaming', () => {
  test('the send submit button disables itself while streaming === "sending"', async ({
    mount,
    page,
  }) => {
    const component = await mount(MessageInputHarness, {
      props: { initialAgentId: 'gpt-4o' },
    });

    // While idle the send button is enabled once the user has typed.
    const textarea = component.getByRole('textbox', { name: 'Compose a message' });
    await textarea.fill('hi');
    const sendButton = component.getByRole('button', { name: 'Send' });
    await expect(sendButton).toBeEnabled();

    // Flip to 'sending' — the component swaps the send button for the
    // cancel button (the M2 spec checks `isStreaming` to choose
    // between the two affordances).
    await page.evaluate(() => {
      (
        window as unknown as { __activeChatStore: { streaming: string } }
      ).__activeChatStore.streaming = 'sending';
    });

    // Send button disappears; cancel button takes its place.
    await expect(component.getByRole('button', { name: /cancel/i })).toBeVisible();
    await expect(component.getByRole('button', { name: 'Send' })).toHaveCount(0);
  });
});

test.describe('MessageInput — agent dropdown population', () => {
  test('the agent dropdown shows the populated agents store (≤10 = native select)', async ({
    mount,
  }) => {
    const agents: AgentInfo[] = [
      { id: 'gpt-4o', label: 'GPT-4o', owned_by: 'openai' },
      { id: 'gpt-4o-mini', label: 'GPT-4o mini', owned_by: 'openai' },
      { id: 'claude-3-5-sonnet', label: 'Claude 3.5 Sonnet', owned_by: 'anthropic' },
    ];

    const component = await mount(MessageInputHarness, {
      props: { initialAgentId: 'gpt-4o', agents },
    });

    // The AgentSelector renders a native <select> when there are ≤10
    // agents. Each agent id must appear as an <option>.
    const select = component.locator('select');
    await expect(select).toBeVisible();

    for (const a of agents) {
      await expect(select.locator(`option[value="${a.id}"]`)).toHaveCount(1);
    }
  });

  test('the agent dropdown switches to a popover when there are >10 agents', async ({
    mount,
  }) => {
    // 11 agents forces the popover branch (`POPOVER_THRESHOLD = 10`).
    const agents: AgentInfo[] = Array.from({ length: 11 }, (_, i) => ({
      id: `agent-${i}`,
      label: `Agent ${i}`,
      owned_by: 'openai',
    }));

    const component = await mount(MessageInputHarness, {
      props: { initialAgentId: 'agent-0', agents },
    });

    // No native <select>; instead the trigger button is exposed.
    await expect(component.locator('select')).toHaveCount(0);
    await expect(component.getByRole('button', { name: /Agent 0|Select agent/ })).toBeVisible();
  });
});

test.describe('MessageInput — system + temperature disclosure', () => {
  test('the advanced disclosure is collapsed by default and toggles open on click', async ({
    mount,
  }) => {
    const component = await mount(MessageInputHarness, {
      props: { initialAgentId: 'gpt-4o' },
    });

    // Closed by default — the temperature input is not in the DOM.
    await expect(component.getByRole('spinbutton', { name: 'Temperature' })).toHaveCount(0);

    // The toggle button reads "+ Options" closed and "− Options" open.
    const toggle = component.getByRole('button', { name: '+ Options' });
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await toggle.click();

    // Now the disclosure reveals the temperature input.
    await expect(component.getByRole('spinbutton', { name: 'Temperature' })).toBeVisible();
    await expect(component.getByRole('button', { name: '− Options' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  });
});
