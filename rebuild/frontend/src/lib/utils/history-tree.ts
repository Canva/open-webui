/**
 * Pure helpers for the chat history tree.
 *
 * Mirrors the backend reducers in `app.services.chat_stream` so the
 * frontend's optimistic-insert and edit-and-resend paths reach for the
 * same algebra. Tested independently in
 * `tests/unit/historyTree.test.ts` (Phase 4b) — extracting the helpers
 * here keeps `ActiveChatStore` thin and lets the test file mount them
 * without instantiating the rune-reactive store.
 *
 * Locked by:
 * - `rebuild/docs/plans/m2-conversations.md` § JSON shape of
 *   `chat.history` (the canonical tree shape).
 * - `app/services/chat_stream.py::build_linear_thread` — the reducer
 *   port; the cycle/dangling guards mirror the backend's defensive
 *   shape at line 161-178.
 */

import type { History, HistoryMessage } from '$lib/types/history';

/**
 * Defence-in-depth ceiling on the parent-id walk. Mirrors the backend
 * constant `_MAX_THREAD_DEPTH` (1000) — a pathological history with a
 * circular `parentId` chain would otherwise loop forever.
 */
export const MAX_THREAD_DEPTH = 1000;

/**
 * Walk the `parentId` chain from `leafId` to the root and return the
 * messages in chronological order (root first, leaf last).
 *
 * Guards:
 * - Terminate on `parentId === null` (root reached).
 * - Terminate on a missing id (corrupted history — a dangling
 *   `parentId` from a legacy import would otherwise crash the
 *   render).
 * - Terminate after `MAX_THREAD_DEPTH` hops (cycle guard) — a
 *   mid-walk repeat triggers an early break too.
 */
export function buildLinearThread(history: History, leafId: string): HistoryMessage[] {
  const chain: HistoryMessage[] = [];
  const seen = new Set<string>();
  let currentId: string | null = leafId;
  for (let i = 0; i < MAX_THREAD_DEPTH; i += 1) {
    if (currentId === null) break;
    if (seen.has(currentId)) {
      console.warn('buildLinearThread: cycle at message', currentId);
      break;
    }
    const msg: HistoryMessage | undefined = history.messages[currentId];
    if (!msg) {
      console.warn('buildLinearThread: dangling parentId', currentId);
      break;
    }
    chain.push(msg);
    seen.add(currentId);
    currentId = msg.parentId;
  }
  chain.reverse();
  return chain;
}

/**
 * Find the most recent assistant message in the linear thread ending
 * at `leafId`. Returns `null` if no assistant message exists in the
 * branch (e.g. the user is editing the very first message).
 *
 * Used by `ActiveChatStore.editAndResend` to pick "last agent" /
 * "last params" — falling back to the values the user already saw is
 * less surprising than asking them to re-pick an agent in the editor.
 */
export function findLastAssistant(history: History, leafId: string): HistoryMessage | null {
  const linear = buildLinearThread(history, leafId);
  for (let i = linear.length - 1; i >= 0; i -= 1) {
    const msg = linear[i]!;
    if (msg.role === 'assistant') return msg;
  }
  return null;
}
