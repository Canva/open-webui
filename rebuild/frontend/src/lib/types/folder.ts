/**
 * Mirror of `app/schemas/folder.py` — the M2 folder surface wire types.
 *
 * Locked by `rebuild/docs/plans/m2-conversations.md` § Folder CRUD.
 * Snake_case field names match the API; `FolderDeleteResult` carries
 * both the cascaded folder ids and the chats whose `folder_id` was
 * set to `NULL` so the sidebar can update in place without refetching
 * either list.
 */

export interface FolderRead {
  id: string;
  parent_id: string | null;
  name: string;
  expanded: boolean;
  /** epoch milliseconds */
  created_at: number;
  /** epoch milliseconds */
  updated_at: number;
}

export interface FolderCreate {
  name: string;
  parent_id?: string | null;
}

export interface FolderPatch {
  name?: string | null;
  parent_id?: string | null;
  expanded?: boolean | null;
}

export interface FolderDeleteResult {
  /** The target folder + every descendant. */
  deleted_folder_ids: string[];
  /** Chats whose `folder_id` was just set to `NULL`. */
  detached_chat_ids: string[];
}
