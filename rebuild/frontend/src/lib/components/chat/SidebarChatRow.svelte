<script lang="ts">
  /**
   * Single chat row inside the sidebar list. Extracted from
   * `Sidebar.svelte` to keep the parent under the 400 LOC plan cap;
   * each row owns its own drag handle, right-click menu, and
   * `content-visibility: auto` virtualisation hint.
   *
   * Pinned by `rebuild/docs/plans/m2-conversations.md` § Frontend
   * components (line 887): "Drag-and-drop for moving chats; right-
   * click menu for pin/archive/rename/delete. Virtualised with
   * `content-visibility: auto` (port the v0.9.2 trick from legacy)."
   *
   * Virtualisation: the row container declares `content-visibility:
   * auto; contain-intrinsic-size: 0 32px;` via inline style. The 32px
   * intrinsic size matches the `min-h-8` row height (DESIGN.md §
   * Components > Navigation: "hit targets remain at the 32px
   * min-height set via #sidebar-chat-item"). Off-screen rows are
   * skipped during paint and layout, which is what makes a 5000-row
   * sidebar still smooth without a third-party virtualisation lib.
   */
  import { goto } from '$app/navigation';
  import { useChats } from '$lib/stores/chats.svelte';
  import { useToast } from '$lib/stores/toast.svelte';
  import type { ChatSummary } from '$lib/types/chat';

  interface Props {
    chat: ChatSummary;
    active: boolean;
    onnavigate?: () => void;
  }

  let { chat, active, onnavigate }: Props = $props();

  const chats = useChats();
  const toast = useToast();

  let menuOpen = $state(false);
  let editing = $state(false);
  let draftTitle = $state('');
  let editInput: HTMLInputElement | null = $state(null);

  function onDragStart(event: DragEvent): void {
    if (!event.dataTransfer) return;
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/x-chat-id', chat.id);
  }

  function openMenu(event: MouseEvent): void {
    event.preventDefault();
    menuOpen = true;
  }

  function closeMenu(): void {
    menuOpen = false;
  }

  async function withMenuClosed<T>(fn: () => Promise<T> | T): Promise<void> {
    closeMenu();
    try {
      await fn();
    } catch (err) {
      toast.pushError(err instanceof Error ? err.message : String(err));
    }
  }

  function startRename(): void {
    closeMenu();
    draftTitle = chat.title;
    editing = true;
    queueMicrotask(() => editInput?.focus());
  }

  async function commitRename(): Promise<void> {
    const next = draftTitle.trim();
    editing = false;
    if (next.length === 0 || next === chat.title) return;
    try {
      await chats.patch(chat.id, { title: next });
    } catch (err) {
      toast.pushError(err instanceof Error ? err.message : String(err));
    }
  }

  function onRenameKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter') {
      event.preventDefault();
      void commitRename();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      editing = false;
    }
  }

  async function handleClick(event: MouseEvent): Promise<void> {
    // Don't navigate if the user is interacting with the inline rename
    // input — the click bubbles otherwise.
    if (editing) return;
    event.preventDefault();
    onnavigate?.();
    await goto(`/c/${chat.id}`);
  }
</script>

<div
  role="listitem"
  draggable="true"
  ondragstart={onDragStart}
  oncontextmenu={openMenu}
  data-active={active}
  class="group text-ink-body hover:bg-background-elevated motion-safe:ease-out-quart data-[active=true]:bg-accent-selection data-[active=true]:text-ink-strong relative my-px flex min-h-8 items-center gap-1 rounded-xl bg-transparent px-2 py-1 motion-safe:transition-colors motion-safe:duration-150"
  style="content-visibility: auto; contain-intrinsic-size: 0 32px;"
>
  {#if editing}
    <input
      bind:this={editInput}
      bind:value={draftTitle}
      onkeydown={onRenameKeydown}
      onblur={commitRename}
      class="text-ink-strong bg-background-app border-hairline focus:border-hairline-strong block flex-1 rounded-md border px-2 py-0.5 text-sm outline-none"
      aria-label="Rename conversation"
    />
  {:else}
    <a
      href="/c/{chat.id}"
      onclick={handleClick}
      aria-current={active ? 'page' : undefined}
      class="block flex-1 truncate text-sm leading-tight outline-none"
      title={chat.title}
    >
      {chat.title}
    </a>
    {#if chat.pinned}
      <span class="text-accent-mention" aria-label="Pinned" title="Pinned">
        <svg width="10" height="10" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
          <path d="M9 1l3 3-2.5 2.5L11 9 7 13l-2.5-2.5L2 13v-2l2.5-2.5L7 5l2-2L9 1z" />
        </svg>
      </span>
    {/if}
    <button
      type="button"
      onclick={openMenu}
      class="text-ink-muted hover:text-ink-strong motion-safe:ease-out-quart -me-1 inline-flex h-5 w-5 items-center justify-center rounded opacity-0 group-hover:opacity-100 motion-safe:transition-opacity motion-safe:duration-150"
      aria-label="More actions"
    >
      <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
        <circle cx="3" cy="8" r="1.25" />
        <circle cx="8" cy="8" r="1.25" />
        <circle cx="13" cy="8" r="1.25" />
      </svg>
    </button>
  {/if}

  {#if menuOpen}
    <!-- Native popover (CSS-only positioning). The backdrop button
         absorbs outside clicks for keyboard / mouse parity without
         pulling in a focus-trap library. -->
    <button
      type="button"
      class="fixed inset-0 z-30 cursor-default"
      onclick={closeMenu}
      aria-label="Close menu"
    ></button>
    <div
      role="menu"
      class="bg-background-elevated border-hairline absolute end-1 top-full z-40 mt-1 flex min-w-[180px] flex-col rounded-xl border p-1 shadow-lg backdrop-blur-sm"
    >
      <button
        type="button"
        role="menuitem"
        class="text-ink-body hover:bg-background-app rounded-lg px-3 py-1.5 text-start text-xs"
        onclick={() => withMenuClosed(() => chats.togglePin(chat.id))}
      >
        {chat.pinned ? 'Unpin' : 'Pin'}
      </button>
      <button
        type="button"
        role="menuitem"
        class="text-ink-body hover:bg-background-app rounded-lg px-3 py-1.5 text-start text-xs"
        onclick={() => withMenuClosed(() => chats.toggleArchive(chat.id))}
      >
        {chat.archived ? 'Unarchive' : 'Archive'}
      </button>
      <button
        type="button"
        role="menuitem"
        class="text-ink-body hover:bg-background-app rounded-lg px-3 py-1.5 text-start text-xs"
        onclick={startRename}
      >
        Rename
      </button>
      <button
        type="button"
        role="menuitem"
        class="text-status-danger hover:bg-status-danger/10 rounded-lg px-3 py-1.5 text-start text-xs"
        onclick={() => withMenuClosed(() => chats.remove(chat.id))}
      >
        Delete
      </button>
    </div>
  {/if}
</div>
