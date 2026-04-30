/**
 * Per-request folders store. Constructed in `(app)/+layout.svelte`
 * via `provideFolders(data.folders)` and consumed by `FolderTree.svelte`
 * (Phase 3d) to render the sidebar tree.
 *
 * Locked by:
 * - `rebuild/docs/plans/m2-conversations.md` § Stores and state
 *   (the `FoldersStore` row in the table on lines 949-952).
 * - `rebuild/docs/plans/m2-conversations.md` § Folder CRUD — the API
 *   contract every method here calls into.
 *
 * Mutations are optimistic with rollback on error: the local mutation
 * is applied immediately so the sidebar feels live, then the network
 * call runs; on failure we restore the snapshot and surface the
 * error. The store does NOT depend on `ToastStore` directly — Phase
 * 3d's `<FolderTree>` wraps each method call with a toast on `error`.
 *
 * The `byParent` map is a `$derived` view of `items` so the recursive
 * `FolderTree.svelte` component can `byParent['root']` / `byParent[parentId]`
 * without re-grouping on every render. The literal string `'root'`
 * key stands in for `parent_id === null` so consumers can use a
 * uniform indexed lookup.
 *
 * The `delete` response carries `detached_chat_ids` — the list of
 * chats whose `folder_id` was set to `NULL` because they lived inside
 * a deleted folder. The caller (Phase 3d's `<FolderTree>` action
 * handler) is responsible for forwarding that list to `ChatsStore`
 * to update the affected chats in place; this store deliberately does
 * not reach across to `ChatsStore` to keep the dependency direction
 * one-way.
 */

import { getContext, setContext } from 'svelte';

import { ApiError, folders as foldersApi } from '$lib/api/client';
import type { FolderCreate, FolderDeleteResult, FolderPatch, FolderRead } from '$lib/types/folder';

const KEY = Symbol('folders');

/**
 * Sentinel key for the top-level (`parent_id === null`) bucket in the
 * `byParent` derived map. Exported so the consuming `<FolderTree>`
 * component can write `byParent[FOLDER_ROOT_KEY]` without re-stating
 * the magic string.
 */
export const FOLDER_ROOT_KEY = 'root' as const;

export type FolderByParent = Record<string, FolderRead[]>;

export class FoldersStore {
  items = $state<FolderRead[]>([]);
  loading = $state(false);
  error: string | null = $state(null);

  /**
   * Group items by `parent_id`. The literal string `'root'` is used
   * for the top-level (`parent_id === null`) bucket so consumers can
   * use a single indexed-lookup pattern (`byParent[parentId ?? FOLDER_ROOT_KEY]`).
   *
   * `$derived.by` because the body is multi-line; the result is
   * recomputed only when `items` changes.
   */
  byParent: FolderByParent = $derived.by<FolderByParent>(() => {
    const grouped: FolderByParent = {};
    for (const folder of this.items) {
      const key = folder.parent_id ?? FOLDER_ROOT_KEY;
      const bucket = grouped[key] ?? (grouped[key] = []);
      bucket.push(folder);
    }
    return grouped;
  });

  constructor(initial: FolderRead[] = []) {
    this.items = initial;
  }

  /** Force a full refresh from `GET /api/folders`. */
  refresh = async (): Promise<void> => {
    this.loading = true;
    try {
      this.items = await foldersApi.list();
      this.error = null;
    } catch (err) {
      this.error = err instanceof ApiError ? err.message : String(err);
    } finally {
      this.loading = false;
    }
  };

  /**
   * Optimistic create: insert a placeholder with a temp id at the end
   * of `items`, fire the request, swap the temp id for the server
   * response on success, remove the placeholder on failure.
   */
  create = async (input: FolderCreate): Promise<FolderRead> => {
    const tempId = `temp-${crypto.randomUUID()}`;
    const now = Date.now();
    const placeholder: FolderRead = {
      id: tempId,
      parent_id: input.parent_id ?? null,
      name: input.name,
      expanded: false,
      created_at: now,
      updated_at: now,
    };
    this.items.push(placeholder);
    try {
      const created = await foldersApi.create(input);
      const idx = this.items.findIndex((f) => f.id === tempId);
      if (idx >= 0) this.items[idx] = created;
      return created;
    } catch (err) {
      const idx = this.items.findIndex((f) => f.id === tempId);
      if (idx >= 0) this.items.splice(idx, 1);
      this.error = err instanceof ApiError ? err.message : String(err);
      throw err;
    }
  };

  /**
   * Optimistic patch: snapshot the matching summary, apply the partial
   * locally with `updated_at = Date.now()` for sort-stability, fire
   * the request, restore the snapshot on failure.
   */
  patch = async (id: string, partial: FolderPatch): Promise<FolderRead> => {
    const idx = this.items.findIndex((f) => f.id === id);
    if (idx < 0) {
      throw new Error(`FoldersStore.patch: unknown folder id ${id}`);
    }
    const snapshot = this.items[idx]!;
    const optimistic: FolderRead = {
      ...snapshot,
      name: partial.name ?? snapshot.name,
      parent_id: partial.parent_id === undefined ? snapshot.parent_id : partial.parent_id,
      expanded: partial.expanded ?? snapshot.expanded,
      updated_at: Date.now(),
    };
    this.items[idx] = optimistic;
    try {
      const updated = await foldersApi.patch(id, partial);
      // Re-look up — the index may have shifted if a parallel mutation
      // landed during the await.
      const reIdx = this.items.findIndex((f) => f.id === id);
      if (reIdx >= 0) this.items[reIdx] = updated;
      return updated;
    } catch (err) {
      const reIdx = this.items.findIndex((f) => f.id === id);
      if (reIdx >= 0) this.items[reIdx] = snapshot;
      this.error = err instanceof ApiError ? err.message : String(err);
      throw err;
    }
  };

  /**
   * Optimistic remove: drop the target locally (and recursively, every
   * descendant we know about — the server will return the canonical
   * list of cascaded ids), fire the request, restore the snapshot on
   * failure. Returns the server's `FolderDeleteResult` so the caller
   * can drive `ChatsStore` updates for `detached_chat_ids`.
   */
  remove = async (id: string): Promise<FolderDeleteResult> => {
    const snapshot = this.items.slice();
    const descendants = this.#collectDescendants(id);
    const toRemove = new Set<string>([id, ...descendants]);
    this.items = this.items.filter((f) => !toRemove.has(f.id));
    try {
      const result = await foldersApi.delete(id);
      // The server may have cascaded folders we didn't track; reconcile
      // by removing any extras the server reported.
      const serverCascade = new Set(result.deleted_folder_ids);
      this.items = this.items.filter((f) => !serverCascade.has(f.id));
      return result;
    } catch (err) {
      this.items = snapshot;
      this.error = err instanceof ApiError ? err.message : String(err);
      throw err;
    }
  };

  /**
   * Convenience: `patch(id, { expanded: !current.expanded })`.
   *
   * Throws if the id is unknown — callers should always pass a folder
   * id from `items`, so this is a programmer error not a user one.
   */
  toggleExpanded = async (id: string): Promise<FolderRead> => {
    const current = this.items.find((f) => f.id === id);
    if (!current) {
      throw new Error(`FoldersStore.toggleExpanded: unknown folder id ${id}`);
    }
    return this.patch(id, { expanded: !current.expanded });
  };

  /**
   * Walk the local `items` to collect every descendant id of `id`
   * (excluding `id` itself). Used by the optimistic-remove path so the
   * sidebar drops the whole subtree immediately; the server's
   * `FolderDeleteResult.deleted_folder_ids` is still treated as the
   * source of truth on success.
   */
  #collectDescendants(id: string): string[] {
    const result: string[] = [];
    const stack: string[] = [id];
    while (stack.length > 0) {
      const current = stack.pop();
      if (current === undefined) break;
      for (const folder of this.items) {
        if (folder.parent_id === current) {
          result.push(folder.id);
          stack.push(folder.id);
        }
      }
    }
    return result;
  }
}

export function provideFolders(initial: FolderRead[] = []): FoldersStore {
  const store = new FoldersStore(initial);
  setContext(KEY, store);
  return store;
}

export function useFolders(): FoldersStore {
  return getContext<FoldersStore>(KEY);
}

export const FOLDERS_CONTEXT_KEY = KEY;
