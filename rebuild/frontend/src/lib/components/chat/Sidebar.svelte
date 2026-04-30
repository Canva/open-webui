<script lang="ts">
  /**
   * Workshop sidebar. The persistent navigation chrome for every
   * authenticated route. Owns:
   *   - The wordmark + "+ New" button.
   *   - A debounced search input that filters the chat list via
   *     `useChats().refresh({ q })`.
   *   - The folder tree (recursive `<FolderTree>`).
   *   - Un-foldered chats (rendered after the tree).
   *   - Drag-and-drop targets so a chat row can be dropped into a
   *     folder.
   *   - The footer link to /settings (preserves the M0 entry point).
   *
   * Pinned by `rebuild/docs/plans/m2-conversations.md` § Frontend
   * components (line 887). LOC budget ≤ 400. Virtualisation uses
   * `content-visibility: auto` per plan line 880 (the "v0.9.2 trick")
   * — applied to each chat row's container so off-screen rows skip
   * paint and layout entirely.
   *
   * Design system anchors (DESIGN.json + project/DESIGN.md):
   *   - `bg-background-sidebar` host fill (slightly elevated above
   *     `background-app`); the parent `<aside>` already sets it.
   *   - Active row: `bg-accent-selection` + `text-ink-strong`.
   *   - Hover row: `bg-background-elevated`.
   *   - Drag-over folder: `bg-accent-mention/10` + accent text.
   *   - Body scale, weight 400 ("Active item does not bold — the
   *     background fill is the tell" per DESIGN.md § Components >
   *     Navigation).
   */
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { useChats } from '$lib/stores/chats.svelte';
  import { useFolders, FOLDER_ROOT_KEY } from '$lib/stores/folders.svelte';
  import { useToast } from '$lib/stores/toast.svelte';
  import FolderTree from './FolderTree.svelte';
  import SidebarChatRow from './SidebarChatRow.svelte';

  interface Props {
    onnavigate?: () => void;
  }

  let { onnavigate }: Props = $props();

  const chats = useChats();
  const folders = useFolders();
  const toast = useToast();

  let query = $state('');
  let creating = $state(false);

  /** The currently-active chat id, derived from the URL. Drives the
   * `aria-current="page"` styling on the row. */
  const activeId = $derived.by<string | null>(() => {
    const match = page.url.pathname.match(/^\/c\/([^/]+)/);
    return match ? decodeURIComponent(match[1] as string) : null;
  });

  // Un-foldered chats (the "loose" rows under the folder tree).
  // Filtered by the local search query as well so the sidebar
  // responds instantly to `q` while the debounced server refresh is
  // in flight (no flash of un-filtered results).
  const ungrouped = $derived.by(() => {
    const q = query.trim().toLowerCase();
    return chats.byPinnedThenUpdated.filter((c) => {
      if (c.folder_id !== null) return false;
      if (c.archived) return false;
      if (q.length === 0) return true;
      return c.title.toLowerCase().includes(q);
    });
  });

  /**
   * Debounced server-side filter. The local `ungrouped` derivation
   * above already responds synchronously to keystrokes; this effect
   * just refreshes the list against the backend's `?q=` filter so
   * server-side pagination finds matches the user typed beyond the
   * 50-row first page. 200ms is the standard human-perceptible
   * debounce floor.
   *
   * Cleanup pattern per `svelte-best-practises.md` § 12: timer is
   * created inside the effect, cleared by the returned cleanup on
   * every re-run + unmount.
   */
  $effect(() => {
    const q = query.trim();
    const handle = setTimeout(() => {
      void chats.refresh(q.length > 0 ? { q, limit: 50 } : { limit: 50 });
    }, 200);
    return () => clearTimeout(handle);
  });

  async function handleNew(): Promise<void> {
    creating = true;
    try {
      const created = await chats.create({});
      onnavigate?.();
      await goto(`/c/${created.id}`);
    } catch (err) {
      toast.pushError(err instanceof Error ? err.message : String(err));
    } finally {
      creating = false;
    }
  }

  async function handleNewFolder(): Promise<void> {
    try {
      await folders.create({ name: 'New folder' });
    } catch (err) {
      toast.pushError(err instanceof Error ? err.message : String(err));
    }
  }

  function handleSearchKey(event: KeyboardEvent): void {
    if (event.key === 'Escape' && query.length > 0) {
      query = '';
      event.preventDefault();
    }
  }

  // ----- drag-and-drop helpers ---------------------------------------
  // Native HTML5 DnD only — no third-party library per project bans.
  // The chat row is the draggable; the folder row + the "no folder"
  // gutter are the drop targets.
  let dragOverFolderId = $state<string | null | 'root'>(null);

  function onDropToRoot(event: DragEvent): void {
    event.preventDefault();
    dragOverFolderId = null;
    const id = event.dataTransfer?.getData('text/x-chat-id');
    if (!id) return;
    void chats.move(id, null).catch((err: unknown) => {
      toast.pushError(err instanceof Error ? err.message : String(err));
    });
  }

  function onDragOverRoot(event: DragEvent): void {
    if (!event.dataTransfer?.types.includes('text/x-chat-id')) return;
    event.preventDefault();
    dragOverFolderId = 'root';
  }

  function onDragLeaveRoot(): void {
    dragOverFolderId = null;
  }

  // The root folder bucket from the folders store (top-level folders
  // with `parent_id === null`).
  const rootFolders = $derived(folders.byParent[FOLDER_ROOT_KEY] ?? []);
</script>

<div class="flex h-full flex-col">
  <!-- Header: brand mark + new-chat affordance ----------------------- -->
  <div class="flex items-center justify-between gap-2 px-3 pt-4 pb-3">
    <a
      href="/"
      class="text-ink-strong tracking-display font-display text-base/[1.2] font-semibold"
      onclick={() => onnavigate?.()}
    >
      Workshop
    </a>
    <button
      type="button"
      class="bg-ink-strong text-background-app hover:bg-ink-body motion-safe:ease-out-quart inline-flex h-7 items-center gap-1 rounded-3xl px-2.5 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-40 motion-safe:transition-colors motion-safe:duration-150"
      disabled={creating}
      onclick={handleNew}
      aria-label="New chat"
    >
      <svg
        width="11"
        height="11"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        stroke-width="1.75"
        stroke-linecap="round"
        aria-hidden="true"
      >
        <path d="M8 3v10M3 8h10" />
      </svg>
      <span>New</span>
    </button>
  </div>

  <!-- Search ------------------------------------------------------- -->
  <div class="px-3 pb-3">
    <input
      type="search"
      bind:value={query}
      onkeydown={handleSearchKey}
      placeholder="Search conversations"
      aria-label="Search conversations"
      class="bg-background-app text-ink-body placeholder:text-ink-placeholder border-hairline focus:border-hairline-strong block w-full rounded-lg border px-3 py-1.5 text-sm outline-none motion-safe:transition-colors motion-safe:duration-150"
    />
  </div>

  <!-- Section divider + actions row ---------------------------------- -->
  <div class="flex items-center justify-between px-4 pt-2 pb-1">
    <p class="text-ink-muted tracking-label text-[10px] font-medium uppercase">Folders</p>
    <button
      type="button"
      class="text-ink-muted hover:text-ink-strong tracking-label motion-safe:ease-out-quart text-[10px] font-medium uppercase motion-safe:transition-colors motion-safe:duration-150"
      onclick={handleNewFolder}
      aria-label="New folder"
    >
      + Folder
    </button>
  </div>

  <!-- Scrollable list region ----------------------------------------- -->
  <div class="min-h-0 flex-1 overflow-y-auto pb-3">
    <!-- Folder tree --------------------------------------------------- -->
    {#if rootFolders.length > 0}
      <div class="px-2">
        <FolderTree folders={rootFolders} {activeId} {onnavigate} />
      </div>
    {/if}

    <!-- Un-foldered chats -------------------------------------------- -->
    <div class="mt-3 flex items-center justify-between px-4 pb-1">
      <p class="text-ink-muted tracking-label text-[10px] font-medium uppercase">Conversations</p>
      <span class="text-ink-muted text-[10px]">{ungrouped.length}</span>
    </div>
    <div
      role="list"
      data-dragover={dragOverFolderId === 'root'}
      class="motion-safe:ease-out-quart data-[dragover=true]:bg-accent-mention/10 mx-1 rounded-xl px-2 pb-2 motion-safe:transition-colors motion-safe:duration-150"
      ondragover={onDragOverRoot}
      ondragleave={onDragLeaveRoot}
      ondrop={onDropToRoot}
    >
      {#each ungrouped as chat (chat.id)}
        <SidebarChatRow {chat} active={activeId === chat.id} {onnavigate} />
      {:else}
        {#if query.trim().length === 0}
          <p class="text-ink-muted px-2 py-3 text-xs">No loose conversations.</p>
        {:else}
          <p class="text-ink-muted px-2 py-3 text-xs">No matches.</p>
        {/if}
      {/each}
    </div>
  </div>

  <!-- Footer: settings link ----------------------------------------- -->
  <div class="border-hairline border-t px-3 py-3">
    <a
      href="/settings"
      onclick={() => onnavigate?.()}
      class="text-ink-muted hover:text-ink-strong motion-safe:ease-out-quart inline-flex items-center gap-1 text-xs motion-safe:transition-colors motion-safe:duration-150"
    >
      Settings
      <svg
        width="10"
        height="10"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        stroke-width="1.75"
        stroke-linecap="round"
        aria-hidden="true"
      >
        <path d="M5 3l5 5-5 5" />
      </svg>
    </a>
  </div>
</div>
