/**
 * Mirror of `app/schemas/history.py::HistoryMessage` and `History`.
 *
 * Locked by `rebuild/docs/plans/m2-conversations.md` § JSON shape of
 * `chat.history` (the canonical tree shape) and the M2 `History`
 * Pydantic model. Field names are camelCase here because the backend
 * round-trips them as-is — see `app.schemas.history` for the rationale
 * (the legacy fork used camelCase in the JSON column and the rebuild
 * preserves that to keep the Pydantic validator strict and the
 * frontend/backend payloads identical).
 *
 * Field semantics:
 * - `messages`: dict keyed by message id (O(1) updates during streaming).
 * - `parentId` / `childrenIds`: tree edges. Branching (regenerate,
 *   edit-and-resend) appends a sibling under the same parent.
 * - `currentId`: leaf of the active branch; the linear thread is
 *   rebuilt by walking `parentId` from `currentId` to the root.
 * - `done` is `false` only while a stream is in flight; flips to
 *   `true` on every terminal branch (success / cancelled / timeout /
 *   error).
 * - `cancelled` pairs with `done=true` on user/timeout cancellation.
 * - `error` carries the gateway error shape (or `{code: "history_too_large"}`
 *   on the M2 cap branch).
 * - `usage` is the gateway's final `usage` chunk; `null` if the
 *   gateway didn't return one.
 */

export interface HistoryMessageError {
  /** Server-emitted code, e.g. `"history_too_large"`. */
  code?: string;
  /** Human-readable message; surfaced in the UI verbatim. */
  message?: string;
}

export interface HistoryMessageUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface HistoryMessage {
  id: string;
  parentId: string | null;
  childrenIds: string[];
  role: 'user' | 'assistant' | 'system';
  content: string;
  /** epoch milliseconds */
  timestamp: number;
  agent_id: string | null;
  agentName: string | null;
  done: boolean;
  error: HistoryMessageError | null;
  cancelled: boolean;
  usage: HistoryMessageUsage | null;
}

export interface History {
  messages: Record<string, HistoryMessage>;
  currentId: string | null;
}
