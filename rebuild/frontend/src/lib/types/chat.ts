/**
 * Mirror of `app/schemas/chat.py` — the M2 chat surface wire types.
 *
 * Locked by `rebuild/docs/plans/m2-conversations.md` § API surface
 * (Chat CRUD + SSE streaming bodies). Field names are snake_case to
 * match the FastAPI payloads as-emitted; do not rename to camelCase
 * for "consistency" — the backend treats these as the canonical wire
 * shape and the rebuild has no Pydantic alias layer.
 */

import type { History } from './history';

export interface ChatSummary {
  id: string;
  title: string;
  pinned: boolean;
  archived: boolean;
  folder_id: string | null;
  /** epoch milliseconds */
  created_at: number;
  /** epoch milliseconds */
  updated_at: number;
}

export interface ChatList {
  items: ChatSummary[];
  next_cursor: string | null;
}

export interface ChatRead extends ChatSummary {
  history: History;
  /** Reserved for M3; always `null` in M2. */
  share_id: string | null;
}

export interface ChatCreate {
  title?: string | null;
  folder_id?: string | null;
}

export interface ChatPatch {
  title?: string | null;
  /** `null` explicitly detaches the chat from its current folder. */
  folder_id?: string | null;
  pinned?: boolean | null;
  archived?: boolean | null;
}

/**
 * Per-message provider knobs. Subset of the OpenAI surface; we
 * deliberately do not expose `top_p` / `presence_penalty` / etc until
 * a real user need appears (locked in the M2 plan).
 */
export interface ChatParams {
  /** 0..2 inclusive on the backend; not enforced client-side. */
  temperature?: number | null;
  system?: string | null;
}

export interface MessageSend {
  content: string;
  agent_id: string;
  parent_id?: string | null;
  params?: ChatParams;
}

export interface TitleMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface TitleRequest {
  messages: TitleMessage[];
}

export interface TitleResponse {
  title: string;
}

/**
 * Optional sidebar filter passed to `GET /api/chats`. The backend
 * accepts the literal string `"none"` for `folder_id` to mean
 * "no folder"; null/undefined omits the filter entirely.
 */
export interface ChatListFilter {
  folder_id?: string | 'none';
  archived?: boolean;
  pinned?: boolean;
  q?: string;
  limit?: number;
  cursor?: string;
}
