<!--
  Harness for the M2 Sidebar CT spec.

  `Sidebar.svelte` reads three contexts (`useChats`, `useFolders`,
  `useToast`) and reaches into `$app/state.page` for the active
  `aria-current` styling. The page-state import resolves inside CT
  via the project's `$lib` alias plumbing — no extra mock needed
  because the M0 setup already provides the SvelteKit runtime.

  Test seam: the harness REPLACES the chats / folders methods that
  trigger network IO (`refresh`, `create`, `move`, `togglePin`,
  `toggleArchive`, `remove`, `patch`, `toggleExpanded`) with
  recording stubs that resolve immediately. Specs assert on the
  arrays via `window.__chatsCalls` / `window.__foldersCalls` so the
  CT bundle does not need MSW running.
-->
<script lang="ts">
  import { setContext, untrack } from 'svelte';
  import { ChatsStore, CHATS_CONTEXT_KEY } from '$lib/stores/chats.svelte';
  import { FoldersStore, FOLDERS_CONTEXT_KEY } from '$lib/stores/folders.svelte';
  import { ToastStore, TOAST_CONTEXT_KEY } from '$lib/stores/toast.svelte';
  import Sidebar from '$lib/components/chat/Sidebar.svelte';
  import type {
    ChatCreate,
    ChatList,
    ChatListFilter,
    ChatPatch,
    ChatRead,
    ChatSummary,
  } from '$lib/types/chat';
  import type { FolderRead } from '$lib/types/folder';

  interface Props {
    /** Number of synthetic chats to populate (defaults to 5). */
    chatCount?: number;
    /** Optional folder fixtures. */
    folders?: FolderRead[];
    /** Optional explicit chat list (overrides chatCount when set). */
    chatList?: ChatList;
  }

  let { chatCount = 5, folders = [], chatList }: Props = $props();

  const chatCountSnapshot = untrack(() => chatCount);
  const foldersSnapshot = untrack(() => folders);
  const chatListSnapshot = untrack(() => chatList);

  function buildChats(n: number): ChatList {
    const items: ChatSummary[] = [];
    for (let i = 0; i < n; i += 1) {
      items.push({
        id: `chat-${i}`,
        title: `Chat ${i}`,
        pinned: false,
        archived: false,
        folder_id: null,
        created_at: 1_700_000_000_000 + i,
        updated_at: 1_700_000_000_000 + i,
      });
    }
    return { items, next_cursor: null };
  }

  const initialChatList = chatListSnapshot ?? buildChats(chatCountSnapshot);

  const chatsStore = new ChatsStore(initialChatList);
  const foldersStore = new FoldersStore(foldersSnapshot);
  const toastStore = new ToastStore();
  setContext(CHATS_CONTEXT_KEY, chatsStore);
  setContext(FOLDERS_CONTEXT_KEY, foldersStore);
  setContext(TOAST_CONTEXT_KEY, toastStore);

  // Recording shims so the spec can assert on what was called WITHOUT
  // running MSW inside the CT bundle.
  type PatchArgs = { id: string; partial: ChatPatch };
  type MoveArgs = { id: string; folderId: string | null };
  type ToggleArgs = { id: string };
  type RemoveArgs = { id: string };

  const chatsCalls = {
    refresh: [] as ChatListFilter[],
    create: [] as ChatCreate[],
    patch: [] as PatchArgs[],
    move: [] as MoveArgs[],
    togglePin: [] as ToggleArgs[],
    toggleArchive: [] as ToggleArgs[],
    remove: [] as RemoveArgs[],
  };
  chatsStore.refresh = async (filter: ChatListFilter = {}): Promise<void> => {
    chatsCalls.refresh.push(filter);
  };
  chatsStore.create = async (input: ChatCreate): Promise<ChatRead> => {
    chatsCalls.create.push(input);
    const now = Date.now();
    return {
      id: `chat-new-${chatsCalls.create.length}`,
      title: input.title ?? 'New Chat',
      pinned: false,
      archived: false,
      folder_id: input.folder_id ?? null,
      created_at: now,
      updated_at: now,
      history: { messages: {}, currentId: null },
      share_id: null,
    };
  };
  chatsStore.patch = async (id: string, partial: ChatPatch): Promise<void> => {
    chatsCalls.patch.push({ id, partial });
  };
  chatsStore.move = async (id: string, folderId: string | null): Promise<void> => {
    chatsCalls.move.push({ id, folderId });
  };
  chatsStore.togglePin = async (id: string): Promise<void> => {
    chatsCalls.togglePin.push({ id });
  };
  chatsStore.toggleArchive = async (id: string): Promise<void> => {
    chatsCalls.toggleArchive.push({ id });
  };
  chatsStore.remove = async (id: string): Promise<void> => {
    chatsCalls.remove.push({ id });
  };

  if (typeof window !== 'undefined') {
    const w = window as unknown as {
      __chatsStore: ChatsStore;
      __foldersStore: FoldersStore;
      __toastStore: ToastStore;
      __chatsCalls: typeof chatsCalls;
    };
    w.__chatsStore = chatsStore;
    w.__foldersStore = foldersStore;
    w.__toastStore = toastStore;
    w.__chatsCalls = chatsCalls;
  }
</script>

<div class="bg-background-sidebar h-svh w-[280px]">
  <Sidebar />
</div>
