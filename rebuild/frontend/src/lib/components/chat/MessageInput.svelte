<script lang="ts">
  /**
   * The bottom-pinned composer. Owns:
   *   - The auto-grow textarea.
   *   - Enter to send / Shift+Enter newline / Esc cancel.
   *   - The agent selector + send/cancel toggle.
   *   - A `<details>` disclosure for `temperature` + `system` so the
   *     advanced knobs stay collapsed by default.
   *
   * Pinned by `rebuild/docs/plans/m2-conversations.md` § Frontend
   * components: "MessageInput — single textarea, auto-grows, Enter
   * sends, Shift+Enter newlines, Esc cancels in-flight stream.
   * AgentSelector + temperature/system disclosure beneath."
   * LOC budget ≤ 200.
   *
   * Defaults pulled from previous user state by the consumer
   * (`ConversationView`) so the input does not have to reach into
   * `ActiveChatStore` for "what agent was last used here" — that's
   * the parent's call, this component just binds to props.
   */
  import { untrack } from 'svelte';
  import { useActiveChat } from '$lib/stores/active-chat.svelte';
  import { useToast } from '$lib/stores/toast.svelte';
  import AgentSelector from './AgentSelector.svelte';

  interface Props {
    /** Initial agent id; the selector is bindable so the user can change it. */
    initialAgentId?: string;
  }

  let { initialAgentId = '' }: Props = $props();

  const activeChat = useActiveChat();
  const toast = useToast();

  let content = $state('');
  // `untrack` so we explicitly seed `agentId` from the initial prop value
  // without making it reactive to subsequent prop changes — the user
  // owns the selection from this point on.
  let agentId = $state(untrack(() => initialAgentId));
  let temperature = $state<number | null>(null);
  let system = $state('');
  let showAdvanced = $state(false);
  let textarea: HTMLTextAreaElement | null = $state(null);

  const streaming = $derived(activeChat.streaming);
  const isStreaming = $derived(streaming === 'streaming' || streaming === 'sending');
  const canSend = $derived(content.trim().length > 0 && agentId !== '' && streaming === 'idle');

  // Auto-grow up to 12 lines (`24 * 12 = 288px`); after that the
  // textarea scrolls internally. The effect runs on every keystroke
  // (textarea content tracked) so the box reflects the user's typing
  // immediately.
  const MAX_AUTOGROW_PX = 288;
  $effect(() => {
    void content;
    if (!textarea) return;
    textarea.style.height = 'auto';
    const next = Math.min(textarea.scrollHeight, MAX_AUTOGROW_PX);
    textarea.style.height = `${next}px`;
  });

  async function handleSend(): Promise<void> {
    if (!canSend) return;
    const body = content.trim();
    const params: { temperature?: number; system?: string } = {};
    if (temperature !== null) params.temperature = temperature;
    if (system.trim().length > 0) params.system = system.trim();
    content = '';
    try {
      await activeChat.send({
        content: body,
        agent_id: agentId,
        ...(Object.keys(params).length > 0 ? { params } : {}),
      });
    } catch (err) {
      toast.pushError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleCancel(): Promise<void> {
    try {
      await activeChat.cancel();
    } catch (err) {
      toast.pushError(err instanceof Error ? err.message : String(err));
    }
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void handleSend();
      return;
    }
    if (event.key === 'Escape' && isStreaming) {
      event.preventDefault();
      void handleCancel();
    }
  }
</script>

<form
  class="bg-background-elevated border-hairline motion-safe:ease-out-quart hover:border-hairline-strong focus-within:border-hairline-strong rounded-3xl border p-3 shadow-lg motion-safe:transition-colors motion-safe:duration-150"
  onsubmit={(e) => {
    e.preventDefault();
    void handleSend();
  }}
>
  <textarea
    bind:this={textarea}
    bind:value={content}
    onkeydown={onKeydown}
    rows="1"
    placeholder={isStreaming
      ? 'Press Esc to cancel.'
      : 'Send a message. Enter to send, Shift+Enter for newline.'}
    aria-label="Compose a message"
    class="text-ink-strong placeholder:text-ink-placeholder block w-full resize-none border-none bg-transparent px-3 py-2 text-sm/[1.55] outline-none"
    style="max-height: {MAX_AUTOGROW_PX}px;"
  ></textarea>

  {#if showAdvanced}
    <div class="border-hairline mt-2 grid grid-cols-1 gap-3 border-t pt-3 sm:grid-cols-[120px_1fr]">
      <label class="text-ink-muted flex items-center gap-2 text-xs">
        <span>Temperature</span>
        <input
          type="number"
          min="0"
          max="2"
          step="0.1"
          bind:value={temperature}
          placeholder="default"
          class="bg-background-app text-ink-body border-hairline focus:border-hairline-strong w-20 rounded-md border px-2 py-1 text-xs outline-none"
        />
      </label>
      <label class="text-ink-muted flex items-start gap-2 text-xs">
        <span class="mt-1">System</span>
        <textarea
          bind:value={system}
          rows="2"
          placeholder="Optional system instruction"
          class="text-ink-body bg-background-app border-hairline focus:border-hairline-strong block w-full resize-y rounded-md border px-2 py-1 text-xs outline-none"
        ></textarea>
      </label>
    </div>
  {/if}

  <div class="border-hairline mt-2 flex items-center justify-between gap-2 border-t pt-2">
    <div class="flex items-center gap-2">
      <AgentSelector bind:value={agentId} />
      <button
        type="button"
        onclick={() => (showAdvanced = !showAdvanced)}
        aria-expanded={showAdvanced}
        class="text-ink-muted hover:text-ink-strong tracking-label motion-safe:ease-out-quart text-[10px] font-medium uppercase motion-safe:transition-colors motion-safe:duration-150"
      >
        {showAdvanced ? '− Options' : '+ Options'}
      </button>
    </div>
    {#if isStreaming}
      <button
        type="button"
        onclick={handleCancel}
        class="border-hairline text-status-warning hover:bg-status-warning/10 motion-safe:ease-out-quart inline-flex items-center gap-1.5 rounded-3xl border px-3 py-1.5 text-xs font-medium motion-safe:transition-colors motion-safe:duration-150"
        aria-label="Cancel stream (Esc)"
      >
        <svg width="10" height="10" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
          <rect x="4" y="4" width="8" height="8" rx="1" />
        </svg>
        <span>Cancel</span>
      </button>
    {:else}
      <button
        type="submit"
        disabled={!canSend}
        class="bg-ink-strong text-background-app hover:bg-ink-body motion-safe:ease-out-quart inline-flex items-center gap-1.5 rounded-3xl px-4 py-1.5 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-40 motion-safe:transition-colors motion-safe:duration-150"
        aria-label="Send"
      >
        <span>Send</span>
        <svg
          width="12"
          height="12"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="1.75"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M3 8h10M9 4l4 4-4 4" />
        </svg>
      </button>
    {/if}
  </div>
</form>
