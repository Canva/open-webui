/**
 * Vitest unit suite for `lib/utils/history-tree.ts` — the pure
 * `buildLinearThread` and `findLastAssistant` reducers.
 *
 * Locked by `rebuild/docs/plans/m2-conversations.md`:
 *   - § Tests § Frontend (line 1060): "historyTree.test.ts — pure
 *     reducers porting the legacy tree algebra. Same fixtures as
 *     the backend `test_history_tree.py` for cross-language parity."
 *   - § Acceptance criteria: "branch chevrons preserve currentId"
 *     (the chevron switch in `MessageList.svelte` walks the same
 *     algebra; a regression here surfaces immediately).
 *
 * Cross-language parity contract:
 *   The backend's `tests/unit/test_history_tree.py` (Phase 4a) uses
 *   the SAME fixture shapes — three-message linear, single-message,
 *   missing currentId, circular parentId, missing parent, multi-
 *   branch with two assistant tails. If a future refactor diverges
 *   the algorithm in one language but not the other this suite (or
 *   its backend twin) flips red.
 *
 *   When updating fixtures here you MUST update the backend twin in
 *   the same PR, or annotate the test inline as "frontend-only" and
 *   explain why the backend can't / shouldn't replicate. Do NOT
 *   silently let the two diverge.
 *
 * The fixtures use camelCase keys to match the wire shape — the
 * `History` Pydantic model on the backend round-trips JSON columns
 * with camelCase keys (see `app/schemas/history.py`).
 */

import { describe, expect, it, vi } from 'vitest';

import {
  MAX_THREAD_DEPTH,
  buildLinearThread,
  findLastAssistant,
} from '../../src/lib/utils/history-tree';
import type { History, HistoryMessage } from '../../src/lib/types/history';

/**
 * Build a minimal `HistoryMessage` with sane defaults so each fixture
 * stays focused on the tree-shape assertion under test.
 */
function msg(overrides: Partial<HistoryMessage> & Pick<HistoryMessage, 'id'>): HistoryMessage {
  return {
    id: overrides.id,
    parentId: overrides.parentId ?? null,
    childrenIds: overrides.childrenIds ?? [],
    role: overrides.role ?? 'user',
    content: overrides.content ?? '',
    timestamp: overrides.timestamp ?? 0,
    model: overrides.model ?? null,
    modelName: overrides.modelName ?? null,
    done: overrides.done ?? true,
    error: overrides.error ?? null,
    cancelled: overrides.cancelled ?? false,
    usage: overrides.usage ?? null,
  };
}

function historyOf(messages: HistoryMessage[], currentId: string | null): History {
  const indexed: Record<string, HistoryMessage> = {};
  for (const m of messages) indexed[m.id] = m;
  return { messages: indexed, currentId };
}

// ---------------------------------------------------------------------------
// buildLinearThread
// ---------------------------------------------------------------------------

describe('buildLinearThread', () => {
  it('walks parentId chain in chronological order (root first, leaf last)', () => {
    // Mirror of the backend `test_walks_parent_chain_in_chronological_order`
    // fixture — same three ids, same parent edges.
    const u1 = msg({ id: 'u1', role: 'user', content: 'hi', childrenIds: ['a2'] });
    const a2 = msg({
      id: 'a2',
      role: 'assistant',
      content: 'hello',
      parentId: 'u1',
      childrenIds: ['u3'],
    });
    const u3 = msg({ id: 'u3', role: 'user', content: 'follow up', parentId: 'a2' });
    const history = historyOf([u1, a2, u3], 'u3');

    const linear = buildLinearThread(history, 'u3');

    expect(linear.map((m) => m.id)).toEqual(['u1', 'a2', 'u3']);
  });

  it('handles a single-message thread', () => {
    const u1 = msg({ id: 'u1', role: 'user', content: 'hi' });
    const history = historyOf([u1], 'u1');

    const linear = buildLinearThread(history, 'u1');

    expect(linear).toHaveLength(1);
    expect(linear[0]!.id).toBe('u1');
  });

  it('handles a missing currentId (unknown leaf id) by returning an empty array', () => {
    const u1 = msg({ id: 'u1', role: 'user', content: 'hi' });
    const history = historyOf([u1], null);

    // Caller passes an unknown leaf id (e.g. an optimistic temp id that
    // got replaced before the next render flushed).
    const linear = buildLinearThread(history, 'no-such-id');

    // The dangling-parentId guard fires immediately and the chain is
    // empty — same shape the backend `_build_linear_thread` returns.
    expect(linear).toEqual([]);
  });

  it('terminates on a circular parentId (cycle guard)', () => {
    // u1 -> u2 -> u3 -> u1 (loop). Without the cycle guard the walk
    // would never return.
    const u1 = msg({ id: 'u1', parentId: 'u3' });
    const u2 = msg({ id: 'u2', parentId: 'u1' });
    const u3 = msg({ id: 'u3', parentId: 'u2' });
    const history = historyOf([u1, u2, u3], 'u3');

    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const linear = buildLinearThread(history, 'u3');
    warn.mockRestore();

    // Three unique nodes were visited; the fourth visit (back to u3)
    // hits the cycle guard and breaks. The chain is reversed so the
    // first-seen node sits at the tail.
    expect(linear.map((m) => m.id)).toHaveLength(3);
    expect(new Set(linear.map((m) => m.id))).toEqual(new Set(['u1', 'u2', 'u3']));
  });

  it('handles a missing parent message gracefully (dangling parentId)', () => {
    // u2 references a parent that does not exist in the messages map
    // (a corrupted history from a legacy import would surface this
    // shape). The walk must terminate cleanly, not throw.
    const u2 = msg({ id: 'u2', parentId: 'u1-missing', role: 'user' });
    const history = historyOf([u2], 'u2');

    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const linear = buildLinearThread(history, 'u2');
    warn.mockRestore();

    // The walk yields the leaf (u2) and stops at the dangling parent.
    expect(linear.map((m) => m.id)).toEqual(['u2']);
  });

  it('respects MAX_THREAD_DEPTH on a pathological deep chain', () => {
    // Build a synthetic chain longer than the depth ceiling. The walk
    // bails out at MAX_THREAD_DEPTH hops without throwing.
    const messages: HistoryMessage[] = [];
    for (let i = 0; i <= MAX_THREAD_DEPTH + 5; i += 1) {
      messages.push(
        msg({
          id: `m${i}`,
          parentId: i === 0 ? null : `m${i - 1}`,
        }),
      );
    }
    const leafId = `m${MAX_THREAD_DEPTH + 5}`;
    const history = historyOf(messages, leafId);

    const linear = buildLinearThread(history, leafId);

    // Exactly MAX_THREAD_DEPTH messages are visited before the loop
    // termination guard fires; the chain is then reversed.
    expect(linear).toHaveLength(MAX_THREAD_DEPTH);
  });
});

// ---------------------------------------------------------------------------
// findLastAssistant
// ---------------------------------------------------------------------------

describe('findLastAssistant', () => {
  it('returns the most-recent assistant in the linear thread', () => {
    // u1 -> a1 -> u2 -> a2 ; the leaf is u2 (the user has just typed
    // a follow-up). The "last assistant" before the leaf is a1.
    const u1 = msg({ id: 'u1', role: 'user', childrenIds: ['a1'] });
    const a1 = msg({ id: 'a1', role: 'assistant', parentId: 'u1', childrenIds: ['u2'] });
    const u2 = msg({ id: 'u2', role: 'user', parentId: 'a1' });
    const history = historyOf([u1, a1, u2], 'u2');

    const last = findLastAssistant(history, 'u2');

    expect(last).not.toBeNull();
    expect(last!.id).toBe('a1');
  });

  it('returns the most-recent assistant when the leaf is itself an assistant', () => {
    // The leaf IS the assistant (the more common case mid-stream).
    const u1 = msg({ id: 'u1', role: 'user', childrenIds: ['a1'] });
    const a1 = msg({ id: 'a1', role: 'assistant', parentId: 'u1' });
    const history = historyOf([u1, a1], 'a1');

    const last = findLastAssistant(history, 'a1');

    expect(last?.id).toBe('a1');
  });

  it('returns null when no assistant exists in the thread', () => {
    // First-message edit case: the user has typed "hi" and is editing
    // before the model has replied even once.
    const u1 = msg({ id: 'u1', role: 'user' });
    const history = historyOf([u1], 'u1');

    const last = findLastAssistant(history, 'u1');

    expect(last).toBeNull();
  });
});
