<script lang="ts">
  /**
   * A single message in the conversation thread. Renders user vs.
   * assistant differently:
   *   - user: bubble fill on the inline-end (`me-*`), plain text only
   *     (escaped by Svelte's default text interpolation).
   *   - assistant: full-width column, markdown via `<Markdown>`,
   *     metadata row beneath.
   *
   * Pinned by `rebuild/docs/plans/m2-conversations.md` § Frontend
   * components (line 887): "Message — user vs assistant rendering;
   * regenerate / copy buttons; cancelled / error / timeout state
   * surfacing." LOC budget ≤ 200.
   *
   * The streaming caret (`▍`) appears at the end of the assistant
   * content while `!message.done`. Per project bans, motion is
   * transform/opacity only and gated by `motion-safe:`.
   */
  import { getContext, untrack } from 'svelte';
  import Markdown from './Markdown/Markdown.svelte';
  import { ACTIVE_CHAT_CONTEXT_KEY, type ActiveChatStore } from '$lib/stores/active-chat.svelte';
  import { TOAST_CONTEXT_KEY, type ToastStore } from '$lib/stores/toast.svelte';
  import type { HistoryMessage } from '$lib/types/history';

  interface Props {
    message: HistoryMessage;
    parent: HistoryMessage | null;
    /**
     * Read-only mode. When `true`, the per-message action row (Copy /
     * Regenerate) and any retry affordance on the error panel are
     * suppressed. The streaming caret stays — a snapshot can in
     * principle hold a `done: false` message (the M6 sweeper handles
     * it server-side); the caret is a passive visual signal.
     *
     * Default `false` so M2's existing call sites are unchanged.
     */
    readonly?: boolean;
  }

  let { message, parent, readonly = false }: Props = $props();

  // Same `getContext` branching as `MessageList`: the public share
  // view does not provide either store, so we pull them via the
  // raw context key and guard every consumer behind `!readonly`.
  // `untrack` because we want the snapshot at construction time —
  // a parent never flips a Message between mutable and read-only,
  // and `getContext` is only valid during component init.
  const activeChat = untrack(() =>
    readonly ? null : (getContext(ACTIVE_CHAT_CONTEXT_KEY) as ActiveChatStore),
  );
  const toast = untrack(() => (readonly ? null : (getContext(TOAST_CONTEXT_KEY) as ToastStore)));

  const isUser = $derived(message.role === 'user');
  const isAssistant = $derived(message.role === 'assistant');
  const isSystem = $derived(message.role === 'system');
  const isStreaming = $derived(isAssistant && !message.done);
  const isCancelled = $derived(message.cancelled && message.error === null);
  const hasError = $derived(message.error !== null);

  async function handleCopy(): Promise<void> {
    if (toast === null) return;
    try {
      await navigator.clipboard.writeText(message.content);
      toast.pushSuccess('Copied to clipboard');
    } catch (err) {
      toast.pushError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleRegenerate(): Promise<void> {
    if (activeChat === null || toast === null) return;
    if (parent === null || parent.role !== 'user') return;
    try {
      await activeChat.editAndResend(parent.id, parent.content);
    } catch (err) {
      toast.pushError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleRetry(): Promise<void> {
    await handleRegenerate();
  }

  function formatUsage(): string | null {
    if (!message.usage) return null;
    const u = message.usage;
    return `${u.total_tokens} tokens (${u.prompt_tokens} in, ${u.completion_tokens} out)`;
  }

  const usageText = $derived(formatUsage());
</script>

{#if isSystem}
  <!-- System messages render as a quiet rule above the thread; we
       don't render full UI for them since the M2 surface is "user
       picks system at send-time" via the disclosure. -->
  <div
    class="border-hairline tracking-label text-ink-muted my-2 flex items-center gap-2 px-1 text-[10px] uppercase"
  >
    <span class="border-hairline flex-1 border-t"></span>
    <span>System</span>
    <span class="border-hairline flex-1 border-t"></span>
  </div>
{:else if isUser}
  <div class="flex justify-end">
    <div
      class="bg-background-elevated text-ink-strong border-hairline ms-12 max-w-[min(80ch,80%)] rounded-2xl border px-4 py-2 text-sm/[1.55]"
    >
      <p class="break-words whitespace-pre-wrap">{message.content}</p>
    </div>
  </div>
{:else}
  <article class="text-ink-body group flex w-full flex-col gap-2">
    {#if hasError && message.error}
      <!-- Error panel: gateway / provider failure surfaced in-thread. -->
      <div
        class="border-status-danger/30 bg-status-danger/10 text-status-danger rounded-2xl border px-4 py-3"
      >
        <p class="tracking-label text-xs font-medium uppercase">Stream failed</p>
        <p class="mt-1 text-sm leading-snug">
          {message.error.message ?? 'The provider returned an error.'}
        </p>
        {#if message.error.code}
          <p class="text-status-danger/80 mt-1 font-mono text-[11px]">{message.error.code}</p>
        {/if}
        {#if !readonly && parent && parent.role === 'user'}
          <button
            type="button"
            onclick={handleRetry}
            class="border-status-danger/40 text-status-danger hover:bg-status-danger/15 motion-safe:ease-out-quart mt-3 inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-xs motion-safe:transition-colors motion-safe:duration-150"
          >
            Retry
          </button>
        {/if}
      </div>
    {:else}
      <Markdown content={message.content} streaming={isStreaming} />
      {#if isStreaming}
        <span
          class="text-accent-stream -mt-2 inline-block animate-pulse text-sm leading-none"
          aria-hidden="true"
        >
          ▍
        </span>
      {/if}
      {#if isCancelled}
        <p
          class="bg-status-warning/10 text-status-warning inline-block self-start rounded-md px-2 py-0.5 text-xs"
        >
          Cancelled
        </p>
      {/if}
    {/if}

    <!-- Metadata + actions row. Hidden on streaming so it doesn't
         flicker during token arrival. In `readonly` mode the row
         still renders so agent + usage stay visible, but the action
         cluster (Copy / Regenerate) is suppressed. -->
    {#if !isStreaming}
      <div class="text-ink-muted flex items-center gap-3 text-[11px]">
        {#if message.agentName || message.agent_id}
          <span class="font-mono">{message.agentName ?? message.agent_id}</span>
        {/if}
        {#if usageText}
          <span title={usageText}>{message.usage?.total_tokens} tokens</span>
        {/if}
        {#if !readonly}
          <div
            class="motion-safe:ease-out-quart ms-auto flex items-center gap-1 opacity-0 group-hover:opacity-100 motion-safe:transition-opacity motion-safe:duration-150"
          >
            <button
              type="button"
              onclick={handleCopy}
              class="text-ink-muted hover:text-ink-strong hover:bg-background-elevated motion-safe:ease-out-quart inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] motion-safe:transition-colors motion-safe:duration-150"
              aria-label="Copy message"
            >
              Copy
            </button>
            {#if parent && parent.role === 'user'}
              <button
                type="button"
                onclick={handleRegenerate}
                class="text-ink-muted hover:text-ink-strong hover:bg-background-elevated motion-safe:ease-out-quart inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] motion-safe:transition-colors motion-safe:duration-150"
                aria-label="Regenerate message"
              >
                Regenerate
              </button>
            {/if}
          </div>
        {/if}
      </div>
    {/if}
  </article>
{/if}
