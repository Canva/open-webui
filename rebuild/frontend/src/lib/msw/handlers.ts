import { http, HttpResponse } from 'msw';
import type { User } from '$lib/types/user';
import type { ChatList, ChatRead, ChatSummary } from '$lib/types/chat';
import type { FolderRead } from '$lib/types/folder';
import type { ModelInfo } from '$lib/types/model';

/**
 * Shared MSW handlers used by:
 *   - Vitest unit tests (via `lib/msw/node.ts`) for any module that
 *     reaches for `fetch`.
 *   - Playwright Component Tests (Phase 4b) — registered via the
 *     CT bundle when a spec needs network interception. The CT
 *     entry point at `frontend/playwright/index.ts` does NOT auto-
 *     start MSW; specs that need it call into a thin browser-side
 *     setup (out of scope for this dispatch).
 *   - Dev-mode browser worker via `lib/msw/browser.ts` when
 *     `PUBLIC_USE_MSW=1`.
 *
 * The M2 surface is parameterisable: the default handlers serve
 * stable empty fixtures so the M0 layout server `load` succeeds,
 * but every spec can override per-call via MSW's `server.use(...)`
 * pattern (Vitest) or `worker.use(...)` (browser).
 *
 * Locked by `rebuild/docs/plans/m2-conversations.md` § API surface.
 */

const fixtureUser: User = {
  id: '01900000-0000-7000-8000-000000000000',
  email: 'alice@canva.com',
  name: 'Alice Example',
  timezone: 'UTC',
  created_at: 1_704_067_200_000,
};

/**
 * Default deterministic chat-summary fixture for the empty-state tests.
 * Component / E2E specs that need a populated sidebar override via
 * `server.use(http.get(URL, () => HttpResponse.json(custom)))` where
 * `URL` is the M2 chats endpoint glob (the literal closes a JSDoc
 * block so it can't appear inline here).
 */
const EMPTY_CHAT_LIST: ChatList = { items: [], next_cursor: null };

/** Default deterministic models fixture — the three models the legacy fork shipped. */
const DEFAULT_MODELS: ModelInfo[] = [
  { id: 'gpt-4o', label: 'GPT-4o', owned_by: 'openai' },
  { id: 'gpt-4o-mini', label: 'GPT-4o mini', owned_by: 'openai' },
  { id: 'claude-3-5-sonnet', label: 'Claude 3.5 Sonnet', owned_by: 'anthropic' },
];

/**
 * Build a minimal `ChatRead` skeleton for the optimistic-create echo
 * branch. The handler reads the body (a `ChatCreate`) and stamps a
 * deterministic id so tests can drive `goto('/c/<id>')` afterwards.
 */
function buildChatStub(input: {
  id?: string;
  title?: string | null;
  folder_id?: string | null;
}): ChatRead {
  const now = 1_735_689_600_000;
  return {
    id: input.id ?? '01900000-0000-7000-8000-000000000aaa',
    title: input.title ?? 'New Chat',
    pinned: false,
    archived: false,
    folder_id: input.folder_id ?? null,
    created_at: now,
    updated_at: now,
    history: { messages: {}, currentId: null },
    share_id: null,
  };
}

/**
 * Compose a single SSE frame in the wire shape `chat_stream.py` emits
 * (`event: <name>\ndata: <json>\n\n`). Exported for spec authors that
 * want to register a custom handler returning a different sequence.
 */
export function sseFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

/**
 * Default deterministic SSE stream for `POST /api/chats/{id}/messages`.
 * Mirrors the cassette the M2 plan promises for `(model="gpt-4o",
 * messages=[{role: "user", content: "Hello"}])`: tokens render in
 * order, then a `usage` block, then `done`.
 */
function defaultStreamBody(): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  const frames = [
    sseFrame('start', {
      user_message_id: 'user-msg-1',
      assistant_message_id: 'asst-msg-1',
    }),
    sseFrame('delta', { content: 'Hi' }),
    sseFrame('delta', { content: ' there' }),
    sseFrame('delta', { content: '!' }),
    sseFrame('usage', { prompt_tokens: 8, completion_tokens: 3, total_tokens: 11 }),
    sseFrame('done', { assistant_message_id: 'asst-msg-1', finish_reason: 'stop' }),
  ];
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(frame));
      controller.close();
    },
  });
}

export const handlers = [
  // -------------------------------------------------------------------
  // M0 surface (the fixture user from `/api/me`).
  // -------------------------------------------------------------------
  http.get('*/api/me', () => HttpResponse.json(fixtureUser)),

  // -------------------------------------------------------------------
  // M2 chat CRUD.
  // -------------------------------------------------------------------
  http.get('*/api/chats', () => HttpResponse.json(EMPTY_CHAT_LIST)),

  http.post('*/api/chats', async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as {
      title?: string | null;
      folder_id?: string | null;
    };
    return HttpResponse.json(buildChatStub(body));
  }),

  http.get('*/api/chats/:id', ({ params }) =>
    HttpResponse.json(buildChatStub({ id: String(params.id) })),
  ),

  http.patch('*/api/chats/:id', async ({ params, request }) => {
    const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
    const stub = buildChatStub({ id: String(params.id) });
    return HttpResponse.json({ ...stub, ...body });
  }),

  http.delete('*/api/chats/:id', () => new HttpResponse(null, { status: 204 })),

  // -------------------------------------------------------------------
  // M2 folder CRUD. Default: empty list. Specs override as needed.
  // -------------------------------------------------------------------
  http.get('*/api/folders', () => HttpResponse.json([] as FolderRead[])),

  // -------------------------------------------------------------------
  // M2 models passthrough.
  // -------------------------------------------------------------------
  http.get('*/api/models', () => HttpResponse.json({ items: DEFAULT_MODELS })),

  // -------------------------------------------------------------------
  // M2 streaming. Default cassette: deterministic "Hi there!" reply.
  // Specs override to record long streams (cancel cases) or terminal
  // error frames via `server.use(http.post(...))`.
  // -------------------------------------------------------------------
  http.post('*/api/chats/:id/messages', () => {
    return new HttpResponse(defaultStreamBody(), {
      status: 200,
      headers: {
        'content-type': 'text/event-stream',
        'cache-control': 'no-cache',
      },
    });
  }),

  http.post(
    '*/api/chats/:id/messages/:messageId/cancel',
    () => new HttpResponse(null, { status: 204 }),
  ),
];

/**
 * Helper for spec authors composing a one-off chat fixture.
 * Re-exported so tests don't redeclare the empty-history shape
 * inline. Keep tiny — pre-populating a `ChatRead` with several
 * messages is a per-test concern (see `tests/e2e/visual-m2.spec.ts`).
 */
export { buildChatStub };

/** Tiny barrel for spec authors that want to assert against a known summary fixture. */
export const SAMPLE_CHAT_SUMMARY: ChatSummary = {
  id: 'sample-chat-1',
  title: 'Sample chat',
  pinned: false,
  archived: false,
  folder_id: null,
  created_at: 1_735_689_600_000,
  updated_at: 1_735_689_600_000,
};

export const SAMPLE_MODELS: ModelInfo[] = DEFAULT_MODELS;
