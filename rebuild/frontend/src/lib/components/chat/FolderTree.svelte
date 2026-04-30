<script lang="ts">
  /**
   * Recursive folder list. Renders a tree of folders + the chats that
   * live directly inside each one. Uses the new self-import pattern
   * (`import FolderTree from './FolderTree.svelte'`) per Phase 3c
   * guidance — the legacy `<svelte:self>` is gone in Svelte 5.
   *
   * Pinned by `rebuild/docs/plans/m2-conversations.md` § Frontend
   * components (line 887): "FolderTree — recursive (self-import).
   * Reads `useFolders().byParent`, toggles via
   * `useFolders().toggleExpanded(id)`. Drag targets so a chat row
   * dropped onto a folder calls `useChats().move(id, folderId)`."
   *
   * The chevron uses `transform: rotate(...)` only, gated by Tailwind
   * `motion-safe:` so a `prefers-reduced-motion` user gets a static
   * indicator (still readable as ▸/▾). LOC budget ≤ 200.
   */
  import { useChats } from '$lib/stores/chats.svelte';
  import { useFolders } from '$lib/stores/folders.svelte';
  import { useToast } from '$lib/stores/toast.svelte';
  import type { FolderRead } from '$lib/types/folder';
  import SidebarChatRow from './SidebarChatRow.svelte';
  import FolderTreeSelf from './FolderTree.svelte';

  interface Props {
    folders: FolderRead[];
    activeId: string | null;
    onnavigate?: () => void;
  }

  let { folders: levelFolders, activeId, onnavigate }: Props = $props();

  const folders = useFolders();
  const chats = useChats();
  const toast = useToast();

  let editingId = $state<string | null>(null);
  let draftName = $state('');
  let dragOverId = $state<string | null>(null);

  const childrenByParent = $derived(folders.byParent);

  function chatsInFolder(folderId: string) {
    return chats.byPinnedThenUpdated.filter((c) => c.folder_id === folderId && !c.archived);
  }

  async function toggleFolder(folder: FolderRead): Promise<void> {
    try {
      await folders.toggleExpanded(folder.id);
    } catch (err) {
      toast.pushError(err instanceof Error ? err.message : String(err));
    }
  }

  function startRename(folder: FolderRead, event: MouseEvent): void {
    event.preventDefault();
    editingId = folder.id;
    draftName = folder.name;
  }

  async function commitRename(folder: FolderRead): Promise<void> {
    const next = draftName.trim();
    editingId = null;
    if (next.length === 0 || next === folder.name) return;
    try {
      await folders.patch(folder.id, { name: next });
    } catch (err) {
      toast.pushError(err instanceof Error ? err.message : String(err));
    }
  }

  function onRenameKeydown(event: KeyboardEvent, folder: FolderRead): void {
    if (event.key === 'Enter') {
      event.preventDefault();
      void commitRename(folder);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      editingId = null;
    }
  }

  async function deleteFolder(folder: FolderRead): Promise<void> {
    try {
      const result = await folders.remove(folder.id);
      chats.detachFromDeletedFolder(result.detached_chat_ids);
    } catch (err) {
      toast.pushError(err instanceof Error ? err.message : String(err));
    }
  }

  function onDragOverFolder(event: DragEvent, folder: FolderRead): void {
    if (!event.dataTransfer?.types.includes('text/x-chat-id')) return;
    event.preventDefault();
    dragOverId = folder.id;
  }

  function onDragLeaveFolder(): void {
    dragOverId = null;
  }

  async function onDropOnFolder(event: DragEvent, folder: FolderRead): Promise<void> {
    event.preventDefault();
    dragOverId = null;
    const id = event.dataTransfer?.getData('text/x-chat-id');
    if (!id) return;
    try {
      await chats.move(id, folder.id);
    } catch (err) {
      toast.pushError(err instanceof Error ? err.message : String(err));
    }
  }
</script>

<ul class="flex flex-col gap-px" role="tree">
  {#each levelFolders as folder (folder.id)}
    {@const children = childrenByParent[folder.id] ?? []}
    {@const folderChats = chatsInFolder(folder.id)}
    <li role="treeitem" aria-expanded={folder.expanded} aria-selected="false">
      <div
        role="group"
        aria-label="Folder {folder.name}"
        data-dragover={dragOverId === folder.id}
        ondragover={(e) => onDragOverFolder(e, folder)}
        ondragleave={onDragLeaveFolder}
        ondrop={(e) => onDropOnFolder(e, folder)}
        oncontextmenu={(e) => startRename(folder, e)}
        class="text-ink-body hover:bg-background-elevated motion-safe:ease-out-quart group data-[dragover=true]:bg-accent-mention/10 flex min-h-7 items-center gap-1 rounded-xl px-2 py-1 motion-safe:transition-colors motion-safe:duration-150"
      >
        <button
          type="button"
          onclick={() => toggleFolder(folder)}
          aria-label={folder.expanded ? 'Collapse folder' : 'Expand folder'}
          class="text-ink-muted hover:text-ink-strong motion-safe:ease-out-quart inline-flex h-5 w-5 items-center justify-center motion-safe:transition-transform motion-safe:duration-150"
          style:transform={folder.expanded ? 'rotate(90deg)' : 'rotate(0deg)'}
        >
          <svg width="9" height="9" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
            <path d="M5 3l5 5-5 5z" />
          </svg>
        </button>
        {#if editingId === folder.id}
          <input
            bind:value={draftName}
            onkeydown={(e) => onRenameKeydown(e, folder)}
            onblur={() => commitRename(folder)}
            class="text-ink-strong bg-background-app border-hairline focus:border-hairline-strong block flex-1 rounded-md border px-2 py-0.5 text-sm outline-none"
            aria-label="Rename folder"
          />
        {:else}
          <button
            type="button"
            onclick={() => toggleFolder(folder)}
            ondblclick={(e) => startRename(folder, e)}
            class="block flex-1 truncate text-start text-sm leading-tight"
            title={folder.name}
          >
            {folder.name}
          </button>
        {/if}
        <span class="text-ink-muted text-[10px] tabular-nums">{folderChats.length}</span>
        <button
          type="button"
          onclick={() => deleteFolder(folder)}
          class="text-ink-muted hover:text-status-danger motion-safe:ease-out-quart -me-1 inline-flex h-5 w-5 items-center justify-center opacity-0 group-hover:opacity-100 motion-safe:transition-opacity motion-safe:duration-150"
          aria-label="Delete folder"
          title="Delete folder"
        >
          <svg
            width="10"
            height="10"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            aria-hidden="true"
          >
            <path d="M3 5h10M6 5V3h4v2M5 5l1 9h4l1-9" />
          </svg>
        </button>
      </div>
      {#if folder.expanded}
        <div class="border-hairline ms-4 border-s ps-1">
          {#each folderChats as chat (chat.id)}
            <SidebarChatRow {chat} active={activeId === chat.id} {onnavigate} />
          {/each}
          {#if children.length > 0}
            <FolderTreeSelf folders={children} {activeId} {onnavigate} />
          {/if}
          {#if folderChats.length === 0 && children.length === 0}
            <p class="text-ink-muted px-2 py-1 text-[11px]">Empty</p>
          {/if}
        </div>
      {/if}
    </li>
  {/each}
</ul>
