/**
 * Discriminated union for the seven SSE event frames emitted by
 * `POST /api/chats/{id}/messages`.
 *
 * Source of truth: `rebuild/backend/app/services/chat_stream.py` (the
 * `sse(event, data)` helper plus the seven event branches) and the
 * event-shape table on `rebuild/docs/plans/m2-conversations.md` lines
 * 660-668. Update this file when the backend taxonomy moves and the
 * parser will narrow correctly at every consumer.
 *
 * Frame ordering on a healthy stream: `start → delta* → usage? → done`.
 * Terminal alternatives: `cancelled` (client/`/cancel`), `timeout`
 * (`SSE_STREAM_TIMEOUT_SECONDS` exceeded), `error` (provider failure
 * or `history_too_large`).
 */

export interface SSEStartData {
  user_message_id: string;
  assistant_message_id: string;
}

export interface SSEDeltaData {
  content: string;
}

export interface SSEUsageData {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface SSEDoneData {
  assistant_message_id: string;
  finish_reason: string | null;
}

export interface SSEErrorData {
  /**
   * Optional on the pre-`start` 4xx branch (no assistant id yet);
   * always present on a mid-stream provider failure or
   * `history_too_large` cap event.
   */
  assistant_message_id?: string;
  message: string;
  status_code: number;
  /** Set to `"history_too_large"` on the M2 cap branch. */
  code?: string;
}

export interface SSECancelledData {
  assistant_message_id: string;
}

export interface SSETimeoutData {
  assistant_message_id: string;
  /** The `SSE_STREAM_TIMEOUT_SECONDS` value the request was capped at. */
  limit_seconds: number;
}

export type SSEEvent =
  | { event: 'start'; data: SSEStartData }
  | { event: 'delta'; data: SSEDeltaData }
  | { event: 'usage'; data: SSEUsageData }
  | { event: 'done'; data: SSEDoneData }
  | { event: 'error'; data: SSEErrorData }
  | { event: 'cancelled'; data: SSECancelledData }
  | { event: 'timeout'; data: SSETimeoutData };

/** Convenience union of just the event-name string literals. */
export type SSEEventName = SSEEvent['event'];
