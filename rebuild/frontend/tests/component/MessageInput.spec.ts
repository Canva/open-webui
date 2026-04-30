/**
 * Component-level driver for `lib/components/chat/MessageInput.svelte`.
 *
 * Locked by `rebuild/docs/plans/m2-conversations.md`:
 *   - § Tests § Frontend (line 1065): "MessageInput.spec.ts — Enter
 *     sends, Shift+Enter newlines, Esc fires cancel, model dropdown
 *     shows the populated `models` store."
 *   - § Frontend components (line 887): "MessageInput — single
 *     textarea, auto-grows, Enter sends, Shift+Enter newlines,
 *     Esc cancels in-flight stream."
 *
 * Layer choice: Playwright CT — the component reads three contexts
 * and composes the `<ModelSelector>` recursively. The harness
 * (`MessageInputHarness.svelte`) constructs each store and exposes
 * recording stubs for `send`/`cancel` so the spec asserts on the
 * input's contract WITHOUT needing MSW inside the CT bundle.
 */

import { test, expect } from '@playwright/experimental-ct-svelte';
import MessageInputHarness from './MessageInputHarness.svelte';
import type { ModelInfo } from '../../src/lib/types/model';

test.describe('MessageInput — keyboard contract', () => {
  test('Enter sends the message and clears the textarea', async ({ mount, page }) => {
    const component = await mount(MessageInputHarness, {
      props: { initialModel: 'gpt-4o' },
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
      props: { initialModel: 'gpt-4o' },
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
      props: { initialModel: 'gpt-4o' },
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
      props: { initialModel: 'gpt-4o' },
    });

    // While idle the send button is enabled once the user has typed.
    const textarea = component.getByRole('textbox', { name: 'Compose a message' });
    await textarea.fill('hi');
    const sendButton = component.getByRole('button', { name: 'Send' });
    await expect(sendButton).toBeEnabled();

    // Flip to 'sending' — the component swaps the send button for the
    // cancel button (the M2 spec at line 161 in MessageInput.svelte
    // checks `isStreaming` to choose between the two affordances).
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

test.describe('MessageInput — model dropdown population', () => {
  test('the model dropdown shows the populated models store (≤10 = native select)', async ({
    mount,
  }) => {
    const models: ModelInfo[] = [
      { id: 'gpt-4o', label: 'GPT-4o', owned_by: 'openai' },
      { id: 'gpt-4o-mini', label: 'GPT-4o mini', owned_by: 'openai' },
      { id: 'claude-3-5-sonnet', label: 'Claude 3.5 Sonnet', owned_by: 'anthropic' },
    ];

    const component = await mount(MessageInputHarness, {
      props: { initialModel: 'gpt-4o', models },
    });

    // The ModelSelector renders a native <select> when there are ≤10
    // models. Each model id must appear as an <option>.
    const select = component.locator('select');
    await expect(select).toBeVisible();

    for (const m of models) {
      await expect(select.locator(`option[value="${m.id}"]`)).toHaveCount(1);
    }
  });

  test('the model dropdown switches to a popover when there are >10 models', async ({ mount }) => {
    // 11 models forces the popover branch (`POPOVER_THRESHOLD = 10`).
    const models: ModelInfo[] = Array.from({ length: 11 }, (_, i) => ({
      id: `model-${i}`,
      label: `Model ${i}`,
      owned_by: 'openai',
    }));

    const component = await mount(MessageInputHarness, {
      props: { initialModel: 'model-0', models },
    });

    // No native <select>; instead the trigger button is exposed.
    await expect(component.locator('select')).toHaveCount(0);
    await expect(component.getByRole('button', { name: /Model 0|Select model/ })).toBeVisible();
  });
});

test.describe('MessageInput — system + temperature disclosure', () => {
  test('the advanced disclosure is collapsed by default and toggles open on click', async ({
    mount,
  }) => {
    const component = await mount(MessageInputHarness, {
      props: { initialModel: 'gpt-4o' },
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
