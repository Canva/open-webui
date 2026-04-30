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
  import { goto } from '$app/navigation';
  import { useActiveChat } from '$lib/stores/active-chat.svelte';
  import { useChats } from '$lib/stores/chats.svelte';
  import { useToast } from '$lib/stores/toast.svelte';
  import type { ChatRead } from '$lib/types/chat';
  import MessageList from './MessageList.svelte';
  import MessageInput from './MessageInput.svelte';

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

  // Bind the local view to whatever is currently in the
  // `ActiveChatStore`. The store holds the live history (token-by-
  // token mutations); the SSR'd `serverChat` is the seed.
  const chat = $derived(activeChat.chat ?? serverChat);
  const initialModelFromHistory = $derived.by<string>(() => {
    const messages = Object.values(chat.history.messages);
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const msg = messages[i];
      if (msg && msg.role === 'assistant' && msg.model) return msg.model;
    }
    return '';
  });

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
  // `{ chatId, content, model }` in sessionStorage before
  // `goto('/c/<id>')`; we pick it up here once the store is loaded
  // and dispatch the first message. Cleared immediately so a refresh
  // doesn't replay it.
  // ------------------------------------------------------------------
  $effect(() => {
    if (typeof window === 'undefined') return;
    if (activeChat.chat?.id !== serverChat.id) return;
    const raw = sessionStorage.getItem(PENDING_KEY);
    if (raw === null) return;
    sessionStorage.removeItem(PENDING_KEY);
    try {
      const pending = JSON.parse(raw) as { chatId: string; content: string; model: string };
      if (pending.chatId !== serverChat.id) return;
      void activeChat
        .send({ content: pending.content, model: pending.model })
        .catch((err: unknown) => {
          toast.pushError(err instanceof Error ? err.message : String(err));
        });
    } catch {
      // Malformed payload — drop it; the user can resend manually.
    }
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
</script>

<div class="flex h-full flex-col">
  <!-- Header ------------------------------------------------------- -->
  <header class="border-hairline flex items-center justify-between gap-3 border-b px-6 py-3">
    <div class="ms-12 min-w-0 flex-1 md:ms-0">
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
          class="text-ink-strong block max-w-full truncate text-start text-sm font-medium"
          title="Double-click to rename"
        >
          {chat.title}
        </button>
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

  <!-- Scrollable thread ------------------------------------------- -->
  <div bind:this={scrollEl} class="min-h-0 flex-1 overflow-y-auto">
    <MessageList history={chat.history} />
  </div>

  <!-- Composer ----------------------------------------------------- -->
  <div class="border-hairline border-t px-4 py-4">
    <div class="mx-auto w-full max-w-3xl">
      <MessageInput initialModel={initialModelFromHistory} />
    </div>
  </div>
</div>
