/**
 * Per-request chats store. Constructed in `(app)/+layout.svelte`
 * via `provideChats(data.chats)` and consumed by `Sidebar.svelte`
 * (Phase 3d) to render the chat list.
 *
 * Locked by:
 * - `rebuild/docs/plans/m2-conversations.md` § Stores and state
 *   (the `ChatsStore` row in the table on lines 949-952).
 * - `rebuild/docs/plans/m2-conversations.md` § Chat CRUD — the API
 *   contract every method here calls into.
 *
 * Mutations are optimistic with rollback on error: the local mutation
 * is applied immediately so the sidebar feels live, then the network
 * call runs; on failure we restore the snapshot and surface the
 * error. The store does NOT depend on `ToastStore` directly — Phase
 * 3d's `<Sidebar>` wraps each method call with a toast on `error`.
 *
 * Sort: `byPinnedThenUpdated` is a `$derived` view of `items` sorted
 * by `(pinned desc, updated_at desc)` so the sidebar renders pinned
 * chats first without re-sorting on every render.
 */

import { getContext, setContext } from 'svelte';

import { ApiError, chats as chatsApi } from '$lib/api/client';
import type {
  ChatCreate,
  ChatList,
  ChatListFilter,
  ChatPatch,
  ChatRead,
  ChatSummary,
} from '$lib/types/chat';

const KEY = Symbol('chats');

export class ChatsStore {
  items = $state<ChatSummary[]>([]);
  loading = $state(false);
  error: string | null = $state(null);
  next_cursor: string | null = $state(null);

  /**
   * Read-side convenience: `items` sorted by `(pinned desc,
   * updated_at desc)`. The sidebar binds to this directly so pinned
   * chats float to the top without the consumer re-implementing the
   * comparator.
   *
   * `$derived.by` so the comparator body is readable; the result is
   * recomputed only when `items` changes.
   */
  byPinnedThenUpdated: ChatSummary[] = $derived.by<ChatSummary[]>(() => {
    const copy = this.items.slice();
    copy.sort((a, b) => {
      if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
      return b.updated_at - a.updated_at;
    });
    return copy;
  });

  constructor(initial: ChatList | null = null) {
    if (initial) {
      this.items = initial.items;
      this.next_cursor = initial.next_cursor;
    }
  }

  /**
   * Refetch the sidebar list. With a `cursor` in the filter, append
   * the next page; without one, replace the current items wholesale.
   * Errors are captured into the store's `error` field; loading state
   * always resets in `finally`.
   */
  refresh = async (filter: ChatListFilter = {}): Promise<void> => {
    this.loading = true;
    try {
      const list = await chatsApi.list(filter);
      if (filter.cursor) {
        // Append-on-page-2+. De-dup by id so a missed cursor or a
        // server-side overlap doesn't double-render a chat.
        const seen = new Set(this.items.map((c) => c.id));
        for (const item of list.items) {
          if (!seen.has(item.id)) this.items.push(item);
        }
      } else {
        this.items = list.items;
      }
      this.next_cursor = list.next_cursor;
      this.error = null;
    } catch (err) {
      this.error = err instanceof ApiError ? err.message : String(err);
    } finally {
      this.loading = false;
    }
  };

  /**
   * Optimistic create: insert a placeholder summary at the top with a
   * temp id, fire the request, swap the temp for the server response.
   * Rolls back on failure.
   *
   * Returns the full `ChatRead` from the server so the caller (Phase
   * 3d's "+ new chat" button) can `goto(`/c/${created.id}`)` directly
   * with the canonical id.
   */
  create = async (input: ChatCreate): Promise<ChatRead> => {
    const tempId = `temp-${crypto.randomUUID()}`;
    const now = Date.now();
    const placeholder: ChatSummary = {
      id: tempId,
      title: input.title ?? 'New Chat',
      pinned: false,
      archived: false,
      folder_id: input.folder_id ?? null,
      created_at: now,
      updated_at: now,
    };
    this.items.unshift(placeholder);
    try {
      const created = await chatsApi.create(input);
      const idx = this.items.findIndex((c) => c.id === tempId);
      const summary: ChatSummary = {
        id: created.id,
        title: created.title,
        pinned: created.pinned,
        archived: created.archived,
        folder_id: created.folder_id,
        created_at: created.created_at,
        updated_at: created.updated_at,
      };
      if (idx >= 0) this.items[idx] = summary;
      return created;
    } catch (err) {
      const idx = this.items.findIndex((c) => c.id === tempId);
      if (idx >= 0) this.items.splice(idx, 1);
      this.error = err instanceof ApiError ? err.message : String(err);
      throw err;
    }
  };

  /**
   * Optimistic patch: snapshot the matching summary, apply the partial
   * locally with `updated_at = Date.now()` for sort-stability between
   * request and response, fire the request, restore the snapshot on
   * failure.
   *
   * `folder_id` accepts `null` explicitly (vs `undefined`) — the M2
   * `PATCH /api/chats/{id}` contract treats `null` as "detach from
   * current folder" while `undefined` is "leave folder_id alone".
   */
  patch = async (id: string, partial: ChatPatch): Promise<void> => {
    const idx = this.items.findIndex((c) => c.id === id);
    if (idx < 0) {
      throw new Error(`ChatsStore.patch: unknown chat id ${id}`);
    }
    const snapshot = this.items[idx]!;
    const optimistic: ChatSummary = {
      ...snapshot,
      title: partial.title ?? snapshot.title,
      folder_id: partial.folder_id === undefined ? snapshot.folder_id : partial.folder_id,
      pinned: partial.pinned ?? snapshot.pinned,
      archived: partial.archived ?? snapshot.archived,
      updated_at: Date.now(),
    };
    this.items[idx] = optimistic;
    try {
      const updated = await chatsApi.patch(id, partial);
      const reIdx = this.items.findIndex((c) => c.id === id);
      const summary: ChatSummary = {
        id: updated.id,
        title: updated.title,
        pinned: updated.pinned,
        archived: updated.archived,
        folder_id: updated.folder_id,
        created_at: updated.created_at,
        updated_at: updated.updated_at,
      };
      if (reIdx >= 0) this.items[reIdx] = summary;
    } catch (err) {
      const reIdx = this.items.findIndex((c) => c.id === id);
      if (reIdx >= 0) this.items[reIdx] = snapshot;
      this.error = err instanceof ApiError ? err.message : String(err);
      throw err;
    }
  };

  /**
   * Optimistic remove: drop the summary locally, fire the request,
   * restore the snapshot on failure.
   */
  remove = async (id: string): Promise<void> => {
    const idx = this.items.findIndex((c) => c.id === id);
    if (idx < 0) return;
    const snapshot = this.items[idx]!;
    this.items.splice(idx, 1);
    try {
      await chatsApi.delete(id);
    } catch (err) {
      // Re-insert at the original position (best-effort) so the
      // sidebar order is stable on rollback.
      this.items.splice(idx, 0, snapshot);
      this.error = err instanceof ApiError ? err.message : String(err);
      throw err;
    }
  };

  /** Move a chat into a folder, or detach (`folderId === null`). */
  move = (id: string, folderId: string | null): Promise<void> => {
    return this.patch(id, { folder_id: folderId });
  };

  /** Flip the `pinned` flag. */
  togglePin = (id: string): Promise<void> => {
    const current = this.items.find((c) => c.id === id);
    if (!current) {
      throw new Error(`ChatsStore.togglePin: unknown chat id ${id}`);
    }
    return this.patch(id, { pinned: !current.pinned });
  };

  /** Flip the `archived` flag. */
  toggleArchive = (id: string): Promise<void> => {
    const current = this.items.find((c) => c.id === id);
    if (!current) {
      throw new Error(`ChatsStore.toggleArchive: unknown chat id ${id}`);
    }
    return this.patch(id, { archived: !current.archived });
  };

  /**
   * In-place update for chats whose `folder_id` was set to `NULL`
   * because their folder was deleted. Called by the consumer (Phase
   * 3d's `<FolderTree>` action handler) after `FoldersStore.remove(id)`
   * resolves with `detached_chat_ids`.
   *
   * Pure local mutation — no API call. The server has already done
   * the work; we're just keeping the sidebar in sync without a refetch.
   */
  detachFromDeletedFolder = (chatIds: readonly string[]): void => {
    if (chatIds.length === 0) return;
    const detached = new Set(chatIds);
    for (const chat of this.items) {
      if (detached.has(chat.id)) {
        chat.folder_id = null;
      }
    }
  };
}

export function provideChats(initial: ChatList | null = null): ChatsStore {
  const store = new ChatsStore(initial);
  setContext(KEY, store);
  return store;
}

export function useChats(): ChatsStore {
  return getContext<ChatsStore>(KEY);
}

export const CHATS_CONTEXT_KEY = KEY;
