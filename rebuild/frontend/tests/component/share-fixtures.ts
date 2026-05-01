/**
 * Shared fixtures for the M3 ShareModal + SharedView CT specs.
 *
 * Lives outside the `.svelte` harness files because Playwright CT's
 * Svelte loader treats every `.svelte` import as a component to be
 * `mount(...)`'d — mixing named non-component exports into the
 * component module makes the bundler's life unnecessarily hard. The
 * established pattern in this repo (every existing
 * `*Harness.svelte` exposes only its default component export) is
 * preserved by extracting all helper data here.
 *
 * Locked by `rebuild/docs/plans/m3-sharing.md` § Data model:
 *   - 43-char URL-safe base64 token shape (matches
 *     `secrets.token_urlsafe(32)`).
 *   - epoch-ms `created_at`.
 *   - `SharedChatSnapshot` is the same JSON shape as `chat.history`.
 */

import type { ChatRead } from '$lib/types/chat';
import type { History, HistoryMessage } from '$lib/types/history';
import type { SharedChatSnapshot } from '$lib/types/share';

/** 43-char URL-safe base64 token to mirror `secrets.token_urlsafe(32)`. */
export const TEST_TOKEN = 'TESTtoken000000000000000000000000000000000';
export const FIXTURE_CHAT_ID = 'chat-share-fixture';
export const FIXTURE_NOW = 1_735_689_600_000;

/** Build a `ChatRead` skeleton with sensible defaults; pass `share_id`
 *  through `overrides` to drive the modal's shared-state branch. */
export function defaultChatFixture(overrides: Partial<ChatRead> = {}): ChatRead {
  return {
    id: FIXTURE_CHAT_ID,
    title: 'Test chat',
    pinned: false,
    archived: false,
    folder_id: null,
    created_at: FIXTURE_NOW,
    updated_at: FIXTURE_NOW,
    history: { messages: {}, currentId: null },
    share_id: null,
    ...overrides,
  };
}

/** Build a `HistoryMessage` with sensible defaults. Mirrors the
 *  helper in `Message.spec.ts` so corpus fixtures look the same
 *  across CT specs. */
export function msg(
  overrides: Partial<HistoryMessage> & Pick<HistoryMessage, 'id' | 'role'>,
): HistoryMessage {
  return {
    id: overrides.id,
    parentId: overrides.parentId ?? null,
    childrenIds: overrides.childrenIds ?? [],
    role: overrides.role,
    content: overrides.content ?? '',
    timestamp: overrides.timestamp ?? FIXTURE_NOW,
    agent_id: overrides.agent_id ?? null,
    agentName: overrides.agentName ?? null,
    done: overrides.done ?? true,
    error: overrides.error ?? null,
    cancelled: overrides.cancelled ?? false,
    usage: overrides.usage ?? null,
  };
}

/** Linear two-message snapshot (one user, one assistant with a code
 *  fence) suitable for the happy-path "renders the snapshot" cases. */
export function defaultSnapshotFixture(
  overrides: Partial<SharedChatSnapshot> = {},
): SharedChatSnapshot {
  const userMsg = msg({
    id: 'u-1',
    role: 'user',
    content: 'Refactor this function for clarity.',
    childrenIds: ['a-1'],
  });
  const assistantMsg = msg({
    id: 'a-1',
    role: 'assistant',
    parentId: 'u-1',
    content:
      'Here is a tidier version:\n\n```ts\nconst sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);\n```',
    agent_id: 'gpt-4o',
    agentName: 'GPT-4o',
  });
  const history: History = {
    messages: { 'u-1': userMsg, 'a-1': assistantMsg },
    currentId: 'a-1',
  };
  return {
    token: TEST_TOKEN,
    title: 'Refactor draft',
    history,
    shared_by: { name: 'Alice Example', email: 'alice@canva.com' },
    created_at: FIXTURE_NOW,
    ...overrides,
  };
}

/** Long history (`pairs` user/assistant pairs => `2 * pairs` messages)
 *  for the virtualisation test. Threads each turn under the previous
 *  one so `buildLinearThread` walks the full chain. */
export function longHistoryFixture(pairs = 200): SharedChatSnapshot {
  const messages: Record<string, HistoryMessage> = {};
  let prevId: string | null = null;
  let lastId = '';
  for (let i = 0; i < pairs; i += 1) {
    const userId = `u-${i}`;
    const asstId = `a-${i}`;
    messages[userId] = msg({
      id: userId,
      role: 'user',
      parentId: prevId,
      childrenIds: [asstId],
      content: `User turn ${i}`,
    });
    messages[asstId] = msg({
      id: asstId,
      role: 'assistant',
      parentId: userId,
      childrenIds: [],
      content: `Assistant turn ${i}`,
    });
    prevId = asstId;
    lastId = asstId;
  }
  return {
    token: TEST_TOKEN,
    title: 'Long thread',
    history: { messages, currentId: lastId },
    shared_by: { name: 'Alice Example', email: 'alice@canva.com' },
    created_at: FIXTURE_NOW,
  };
}
