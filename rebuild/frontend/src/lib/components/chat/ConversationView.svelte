<script lang="ts">
  /**
   * The conversation surface that mounts at `/c/[id]`. Owns:
   *   - The active-chat lifecycle (`load(id)` on mount, `unload()` on
   *     teardown — cancels any in-flight stream).
   *   - The vertical layout: header / message list (scrollable) /
   *     bottom-pinned composer.
   *   - Auto-scroll while streaming, pinned to the user's manual
   *     scroll position when they pull up.
   *   - Picking up the empty-state's `sessionStorage` handoff so the
   *     first message of a new chat dispatches automatically once the
   *     `ActiveChatStore` has hydrated from the SSR'd payload.
   *
   * Pinned by `rebuild/docs/plans/m2-conversations.md`:
   *   - § Frontend components (line 887): "ConversationView — owns the
   *     active-chat lifecycle, header, scroll behaviour."
   *   - § Stores and state (lines 1019-1031): the canonical lifecycle
   *     pattern for the streaming `$effect` — `load` on mount,
   *     `unload` on cleanup, AbortController owned by the store.
   *
   * LOC budget ≤ 300.
   */
  import { untrack } from 'svelte';
  import { goto } from '$app/navigation';
  import { useActiveChat } from '$lib/stores/active-chat.svelte';
  import { useChats } from '$lib/stores/chats.svelte';
  import { useToast } from '$lib/stores/toast.svelte';
  import type { ChatRead } from '$lib/types/chat';
  import MessageList from './MessageList.svelte';
  import MessageInput from './MessageInput.svelte';
  import ShareModal from './ShareModal.svelte';

  interface Props {
    chat: ChatRead;
  }

  let { chat: serverChat }: Props = $props();

  const activeChat = useActiveChat();
  const chats = useChats();
  const toast = useToast();

  /** Storage key the empty-state composer wrote to before navigating. */
  const PENDING_KEY = 'rebuild:pending-first-message';

  let scrollEl: HTMLDivElement | null = $state(null);
  /** True when the user has manually scrolled away from the bottom. */
  let stickToBottom = $state(true);
  /** Title editor state. */
  let editingTitle = $state(false);
  let titleDraft = $state('');
  /** Share modal visibility. The modal owns its own state machine
   *  (not-shared / shared / stop-confirm); this flag just controls
   *  whether it is mounted at all. */
  let showShareModal = $state(false);

  /**
   * Empty-state handoff captured synchronously at construction time so
   * the composer can hydrate with the agent the user picked on `/`
   * before any `$effect` runs. The dispatch effect below still owns
   * the actual `send()` call and clears sessionStorage to prevent
   * replay; this snapshot just exposes the agent to `<MessageInput>`'s
   * initial render. SSR-safe via the `typeof window` guard, and
   * scoped to this chat id so a stale entry from another chat doesn't
   * leak into the wrong composer. `untrack` makes the "snapshot
   * semantics" intent explicit (we want the construction-time chat
   * id, not a tracked subscription) and silences
   * svelte/state_referenced_locally — same pattern used in the M2
   * `(app)/+layout.svelte` for store seeding.
   */
  let pendingHandoff = $state<{ content: string; agent_id: string } | null>(
    untrack(() => (typeof window === 'undefined' ? null : readPendingHandoff(serverChat.id))),
  );

  // Bind the local view to whatever is currently in the
  // `ActiveChatStore`. The store holds the live history (token-by-
  // token mutations); the SSR'd `serverChat` is the seed.
  const chat = $derived(activeChat.chat ?? serverChat);
  /**
   * The agent id the composer should default to. Walks history for
   * the most recent assistant turn (so follow-ups inherit the agent
   * the conversation has been using); falls back to the empty-state
   * handoff so a fresh chat continues with whatever the user picked
   * on `/` instead of going back to nothing. Returns `''` when both
   * are absent — `<MessageInput>` then surfaces an empty selector
   * and `<AgentSelector>`'s "No agents available" empty state if the
   * catalogue is also empty.
   */
  const initialAgentId = $derived.by<string>(() => {
    const messages = Object.values(chat.history.messages);
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const msg = messages[i];
      if (msg && msg.role === 'assistant' && msg.agent_id) return msg.agent_id;
    }
    return pendingHandoff?.agent_id ?? '';
  });

  function readPendingHandoff(chatId: string): { content: string; agent_id: string } | null {
    const raw = sessionStorage.getItem(PENDING_KEY);
    if (raw === null) return null;
    try {
      const parsed = JSON.parse(raw) as { chatId: string; content: string; agent_id: string };
      if (parsed.chatId !== chatId) return null;
      return { content: parsed.content, agent_id: parsed.agent_id };
    } catch {
      return null;
    }
  }

  // ------------------------------------------------------------------
  // Lifecycle: load on mount / unload on cleanup. The route `id` is
  // captured via the `serverChat.id` prop so a SvelteKit param change
  // (`/c/a` -> `/c/b` without a full reload) re-runs the effect.
  // ------------------------------------------------------------------
  $effect(() => {
    const id = serverChat.id;
    void activeChat.load(id).catch((err: unknown) => {
      toast.pushError(err instanceof Error ? err.message : String(err));
    });
    return () => {
      activeChat.unload();
    };
  });

  // ------------------------------------------------------------------
  // Empty-state handoff. The composer at `/` stashes
  // `{ chatId, content, agent_id }` in sessionStorage before
  // `goto('/c/<id>')`; the script-body snapshot above captured it for
  // the composer's initial agent. Once the active-chat store has
  // hydrated for this id, we dispatch the first message and clear
  // sessionStorage so a refresh during the in-flight stream doesn't
  // replay it.
  // ------------------------------------------------------------------
  $effect(() => {
    if (typeof window === 'undefined') return;
    if (activeChat.chat?.id !== serverChat.id) return;
    if (pendingHandoff === null) return;
    sessionStorage.removeItem(PENDING_KEY);
    const { content, agent_id } = pendingHandoff;
    pendingHandoff = null;
    void activeChat.send({ content, agent_id }).catch((err: unknown) => {
      toast.pushError(err instanceof Error ? err.message : String(err));
    });
  });

  // ------------------------------------------------------------------
  // Scroll behaviour: track user scroll-position to decide whether
  // new tokens should auto-scroll to the bottom.
  // ------------------------------------------------------------------
  const SCROLL_THRESHOLD = 64;
  $effect(() => {
    const el = scrollEl;
    if (!el) return;
    const onScroll = (): void => {
      const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      stickToBottom = distanceFromBottom < SCROLL_THRESHOLD;
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  });

  // Re-scroll whenever the streaming content advances. We watch the
  // current message's content length specifically so a passive
  // history mutation (folder rename, sidebar refresh) doesn't snap
  // the view.
  const streamingTick = $derived.by<number>(() => {
    if (activeChat.streaming === 'idle') return 0;
    const id = activeChat.currentId;
    if (id === null) return 0;
    return chat.history.messages[id]?.content.length ?? 0;
  });

  $effect(() => {
    void streamingTick;
    if (!stickToBottom || !scrollEl) return;
    queueMicrotask(() => {
      if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight;
    });
  });

  // ------------------------------------------------------------------
  // Header actions.
  // ------------------------------------------------------------------
  function startEditTitle(): void {
    titleDraft = chat.title;
    editingTitle = true;
  }

  async function commitTitle(): Promise<void> {
    const next = titleDraft.trim();
    editingTitle = false;
    if (next.length === 0 || next === chat.title) return;
    try {
      await chats.patch(chat.id, { title: next });
      if (activeChat.chat) activeChat.chat.title = next;
    } catch (err) {
      toast.pushError(err instanceof Error ? err.message : String(err));
    }
  }

  function onTitleKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter') {
      event.preventDefault();
      void commitTitle();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      editingTitle = false;
    }
  }

  async function handleDelete(): Promise<void> {
    if (!confirm('Delete this conversation? This cannot be undone.')) return;
    const id = chat.id;
    try {
      await chats.remove(id);
      activeChat.unload();
      await goto('/');
    } catch (err) {
      toast.pushError(err instanceof Error ? err.message : String(err));
    }
  }

  const isStreaming = $derived(
    activeChat.streaming === 'streaming' || activeChat.streaming === 'sending',
  );

  // Sharing an empty chat is a no-op per `m3-sharing.md` § Owner UX:
  // the Share button is hidden until at least one message has landed.
  const hasMessages = $derived(Object.keys(chat.history.messages).length > 0);
  const isShared = $derived(chat.share_id !== null);

  function openShareModal(): void {
    showShareModal = true;
  }

  function closeShareModal(): void {
    showShareModal = false;
  }

  /**
   * Modal callback when the share is created or revoked. Patches the
   * local `activeChat.chat.share_id` so the header updates without a
   * refetch — same pattern as the title-edit flow above. The store
   * exposes `chat` as deep `$state`, so a property write is reactive.
   */
  function handleShareChange(nextShareId: string | null): void {
    if (activeChat.chat) activeChat.chat.share_id = nextShareId;
  }

  /**
   * Return-visit copy: when `chat.share_id` is set, the header shows
   * a small icon-button that copies the absolute URL inline without
   * opening the modal. Per the plan's § Owner UX bullet on the chat
   * header surfacing a copy affordance for return visits.
   */
  async function handleCopyShareLink(): Promise<void> {
    if (chat.share_id === null) return;
    if (typeof window === 'undefined') return;
    const url = `${window.location.origin}/s/${chat.share_id}`;
    try {
      await navigator.clipboard.writeText(url);
      toast.pushSuccess('Link copied');
    } catch (err) {
      toast.pushError(err instanceof Error ? err.message : 'Failed to copy');
    }
  }
</script>

<div class="flex h-full flex-col">
  <!-- Header ------------------------------------------------------- -->
  <header class="border-hairline flex items-center justify-between gap-3 border-b px-6 py-3">
    <div class="ms-12 flex min-w-0 flex-1 items-center gap-3 md:ms-0">
      {#if editingTitle}
        <input
          bind:value={titleDraft}
          onkeydown={onTitleKeydown}
          onblur={commitTitle}
          class="text-ink-strong bg-background-app border-hairline focus:border-hairline-strong w-full max-w-xl rounded-md border px-2 py-1 text-sm outline-none"
          aria-label="Rename conversation"
        />
      {:else}
        <button
          type="button"
          ondblclick={startEditTitle}
          class="text-ink-strong block min-w-0 truncate text-start text-sm font-medium"
          title="Double-click to rename"
        >
          {chat.title}
        </button>
        {#if hasMessages}
          <div class="flex flex-shrink-0 items-center gap-1">
            <button
              type="button"
              onclick={openShareModal}
              class="text-ink-muted hover:text-ink-body motion-safe:ease-out-quart text-xs motion-safe:transition-colors motion-safe:duration-150"
              aria-label={isShared ? 'Manage share link' : 'Share this chat'}
            >
              Share
            </button>
            {#if isShared}
              <button
                type="button"
                onclick={handleCopyShareLink}
                aria-label="Copy share link"
                title="Copy share link"
                class="text-ink-muted hover:text-ink-body motion-safe:ease-out-quart inline-flex h-6 w-6 items-center justify-center rounded-md motion-safe:transition-colors motion-safe:duration-150"
              >
                <svg
                  width="13"
                  height="13"
                  viewBox="0 0 16 16"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                >
                  <rect x="5" y="5" width="9" height="9" rx="1.5" />
                  <path
                    d="M11 5V3.5A1.5 1.5 0 0 0 9.5 2H3.5A1.5 1.5 0 0 0 2 3.5v6A1.5 1.5 0 0 0 3.5 11H5"
                  />
                </svg>
              </button>
            {/if}
          </div>
        {/if}
      {/if}
    </div>
    <div class="flex items-center gap-2">
      {#if isStreaming}
        <span
          class="text-accent-stream tracking-label inline-flex items-center gap-1.5 text-[10px] font-medium uppercase"
        >
          <span
            class="bg-accent-stream inline-block h-1.5 w-1.5 animate-pulse rounded-full"
            aria-hidden="true"
          ></span>
          Streaming
        </span>
      {/if}
      <button
        type="button"
        onclick={handleDelete}
        class="text-ink-muted hover:text-status-danger motion-safe:ease-out-quart text-xs motion-safe:transition-colors motion-safe:duration-150"
        aria-label="Delete conversation"
      >
        Delete
      </button>
    </div>
  </header>

  {#if showShareModal}
    <ShareModal {chat} onClose={closeShareModal} onShareChange={handleShareChange} />
  {/if}

  <!-- Scrollable thread ------------------------------------------- -->
  <div bind:this={scrollEl} class="min-h-0 flex-1 overflow-y-auto">
    <MessageList history={chat.history} />
  </div>

  <!-- Composer ----------------------------------------------------- -->
  <div class="border-hairline border-t px-4 py-4">
    <div class="mx-auto w-full max-w-3xl">
      <MessageInput {initialAgentId} />
    </div>
  </div>
</div>
