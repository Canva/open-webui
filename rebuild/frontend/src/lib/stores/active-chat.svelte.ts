/**
 * Per-request active-chat store. Owns the chat currently in view —
 * including the full `History` tree and the in-flight SSE stream — so
 * `ConversationView.svelte`, `MessageList.svelte`, `MessageInput.svelte`,
 * and `Markdown.svelte` (Phase 3d) can all bind to one source of truth.
 *
 * Locked by:
 * - `rebuild/docs/plans/m2-conversations.md` § Stores and state
 *   (the `ActiveChatStore` row on lines 949-952; the streaming-state
 *   field drives the input UI).
 * - `rebuild/docs/plans/m2-conversations.md` § "State + data flow for
 *   the streaming send" (lines 889-901) — the eight-step lifecycle
 *   that drives `send()`.
 * - `rebuild/docs/plans/m2-conversations.md` § SSE streaming (lines
 *   660-668) — the seven-event taxonomy this store consumes via
 *   `parseSSE` from `$lib/utils/sse`.
 * - `rebuild/docs/plans/m0-foundations.md` § Frontend conventions
 *   (cross-cutting): class + `setContext`, no module-level `$state`,
 *   AbortController owned by the store but anchored by the consuming
 *   component's `$effect` (which calls `unload()` on teardown — see
 *   the `ConversationView.svelte` snippet on plan lines 1027-1037).
 *
 * Scope (this store):
 * - `chat`, `streaming`, `error`, `currentId` are reactive surface
 *   state for components.
 * - `send()` opens the SSE connection, walks the seven-event union,
 *   and folds each frame into `chat.history` so `<Message>` re-renders
 *   token-by-token.
 * - `cancel()` posts the explicit `/cancel` and aborts the underlying
 *   `fetch`. The Esc-key path lives here.
 * - `switchBranch()` and `editAndResend()` are UI-only mutations that
 *   the next `send()` picks up via `chat.history.currentId`.
 *
 * Out of scope (this store):
 * - Toast surfacing on error — Phase 3d's `<ConversationView>` wraps
 *   `send()` in a try/catch and dispatches to `ToastStore`. The store
 *   sets `error` and lets the caller decide.
 * - Timer ownership for retries / reconnects — there are none in M2.
 *   The Esc / unmount path is the entire cancel surface.
 *
 * The streaming-state cleanup pattern is the one in plan lines
 * 1019-1031: `$effect(() => { activeChat.load(id); return () =>
 * activeChat.unload(); })`. `unload()` aborts the in-flight controller
 * synchronously so the route-change handoff is deterministic.
 */

import { getContext, setContext } from 'svelte';

import { ApiError, chats as chatsApi } from '$lib/api/client';
import type { ChatParams, ChatRead, MessageSend } from '$lib/types/chat';
import type { History, HistoryMessage, HistoryMessageUsage } from '$lib/types/history';
import { findLastAssistant } from '$lib/utils/history-tree';
import { parseSSE } from '$lib/utils/sse';

const KEY = Symbol('activeChat');

/**
 * Streaming lifecycle phases. Drives the `MessageInput` UI:
 * - `idle`: input is enabled, send button visible.
 * - `sending`: optimistic insert applied, awaiting the `start` frame.
 * - `streaming`: tokens flowing; Esc cancels.
 * - `cancelling`: `/cancel` posted but no terminal frame yet.
 *
 * Plan lock: `m2-conversations.md` § Stores and state row for
 * `ActiveChatStore`.
 */
export type StreamingPhase = 'idle' | 'sending' | 'streaming' | 'cancelling';

/** Argument shape for `send()`. Mirrors the relevant slice of `MessageSend`. */
export interface SendInput {
  content: string;
  model: string;
  params?: ChatParams;
  /** Defaults to `chat.history.currentId` on the wire. */
  parent_id?: string | null;
}

export class ActiveChatStore {
  /**
   * The loaded chat including its full history tree. `null` until
   * `load(id)` resolves; `unload()` (route change, manual reset) sets
   * it back to `null` after aborting any in-flight stream.
   *
   * Deep `$state` (not `$state.raw`) so token-by-token mutation of
   * `chat.history.messages[id].content` triggers a `<Message>`
   * re-render without reassigning the whole `chat` object.
   */
  chat: ChatRead | null = $state(null);

  streaming: StreamingPhase = $state('idle');

  error: string | null = $state(null);

  /**
   * Convenience accessor for the active branch leaf id. Components
   * that render the linear thread call `buildLinearThread(history,
   * currentId)` and pass this in.
   */
  currentId: string | null = $derived(this.chat?.history.currentId ?? null);

  /**
   * Owns the in-flight `fetch` so `cancel()` and `unload()` can tear
   * it down. Plain instance field (not `$state`) because no UI binds
   * to its identity — only the side-effects matter.
   */
  #abortController: AbortController | null = null;

  /**
   * The server-assigned id of the assistant message currently being
   * streamed. Set on `start`, cleared in the `finally`. Used by
   * `cancel()` to address the explicit `/cancel` endpoint and by the
   * delta/usage/done branches to fold tokens into the right message.
   */
  #assistantMessageId: string | null = null;

  /**
   * Load a chat by id. Aborts any in-flight stream first via
   * `unload()` so the route-change handoff doesn't leak. Throws on
   * 404/401 so the caller (`+page.server.ts` already validated; the
   * client `load(id)` from `+page.svelte`'s `$effect` re-validates
   * after navigation).
   */
  load = async (id: string): Promise<void> => {
    this.unload();
    this.error = null;
    try {
      const loaded = await chatsApi.get(id);
      this.chat = loaded;
    } catch (err) {
      this.error = err instanceof ApiError ? err.message : String(err);
      throw err;
    }
  };

  /**
   * Synchronous teardown. Aborts the in-flight `AbortController`
   * (which causes `parseSSE`'s `reader.read()` to throw, which the
   * `send()` catch handler swallows as a user cancellation), clears
   * the active chat, and resets streaming state.
   *
   * Called from `ConversationView.svelte`'s top-level `$effect`
   * cleanup on route change (per plan lines 1033-1036), and also
   * once at the start of `load(id)` to guarantee a clean handoff
   * between two consecutive deep-links.
   */
  unload = (): void => {
    if (this.#abortController !== null) {
      this.#abortController.abort();
      this.#abortController = null;
    }
    this.#assistantMessageId = null;
    this.chat = null;
    this.streaming = 'idle';
    this.error = null;
  };

  /**
   * Open the SSE stream and fold its events into `chat.history`. The
   * eight-step lifecycle on plan lines 889-901:
   *
   *  1. Optimistically insert a temporary user message and an empty
   *     assistant placeholder so the UI re-renders before the network
   *     round-trip lands.
   *  2. Open the connection via `chats.send(...)`.
   *  3. On `start`: replace the temp ids with the server-assigned
   *     ones (and rewrite parent/child references in their neighbours)
   *     so subsequent edits/branches use the canonical keys.
   *  4. On `delta`: append `data.content` to the assistant message.
   *  5. On `usage`: store on the assistant message.
   *  6-8. On `done` / `cancelled` / `timeout` / `error`: flip
   *       terminal flags, update `streaming`, and stop reading.
   *
   * The store does NOT push to `ToastStore` itself — Phase 3d's
   * `<ConversationView>` wraps this call and surfaces `error` via the
   * toast. Keeping the store toast-free preserves a one-way
   * dependency (`ToastStore` is provided alongside `ActiveChatStore`
   * in `(app)/+layout.svelte` but neither imports the other).
   */
  send = async (input: SendInput): Promise<void> => {
    if (this.chat === null) {
      throw new Error('ActiveChatStore.send: no chat loaded');
    }
    if (this.streaming !== 'idle') {
      // Defensive: components disable the send button while streaming,
      // but a stray double-fire (Enter held down) shouldn't open two
      // concurrent streams against the same chat.
      throw new Error(`ActiveChatStore.send: cannot send while ${this.streaming}`);
    }

    const chat = this.chat;
    const parentId = input.parent_id ?? chat.history.currentId ?? null;
    const tempUserId = `temp-user-${crypto.randomUUID()}`;
    const tempAssistantId = `temp-asst-${crypto.randomUUID()}`;
    const now = Date.now();

    // ----- Step 1: optimistic insert ---------------------------------
    const userMsg: HistoryMessage = {
      id: tempUserId,
      parentId,
      childrenIds: [tempAssistantId],
      role: 'user',
      content: input.content,
      timestamp: now,
      model: null,
      modelName: null,
      done: true,
      error: null,
      cancelled: false,
      usage: null,
    };
    const assistantMsg: HistoryMessage = {
      id: tempAssistantId,
      parentId: tempUserId,
      childrenIds: [],
      role: 'assistant',
      content: '',
      timestamp: now,
      model: input.model,
      modelName: null,
      done: false,
      error: null,
      cancelled: false,
      usage: null,
    };
    chat.history.messages[tempUserId] = userMsg;
    chat.history.messages[tempAssistantId] = assistantMsg;
    if (parentId !== null) {
      const parent = chat.history.messages[parentId];
      if (parent) parent.childrenIds.push(tempUserId);
    }
    chat.history.currentId = tempAssistantId;

    this.streaming = 'sending';
    this.error = null;
    const body: MessageSend = {
      content: input.content,
      model: input.model,
      ...(input.params !== undefined ? { params: input.params } : {}),
      ...(parentId !== null ? { parent_id: parentId } : {}),
    };
    const controller = new AbortController();
    this.#abortController = controller;

    try {
      // ----- Step 2: open the stream ---------------------------------
      const response = await chatsApi.send(chat.id, body, { signal: controller.signal });
      if (response.body === null) {
        throw new ApiError(502, 'no response body for SSE stream');
      }
      this.streaming = 'streaming';

      // ----- Steps 3-7: fold each event into history -----------------
      for await (const frame of parseSSE(response.body)) {
        switch (frame.event) {
          case 'start': {
            this.#applyStart({
              chat,
              tempUserId,
              tempAssistantId,
              userMessageId: frame.data.user_message_id,
              assistantMessageId: frame.data.assistant_message_id,
            });
            this.#assistantMessageId = frame.data.assistant_message_id;
            break;
          }
          case 'delta': {
            const id = this.#assistantMessageId;
            if (id === null) break;
            const msg = chat.history.messages[id];
            if (msg) msg.content += frame.data.content;
            break;
          }
          case 'usage': {
            const id = this.#assistantMessageId;
            if (id === null) break;
            const msg = chat.history.messages[id];
            if (msg) msg.usage = frame.data satisfies HistoryMessageUsage;
            break;
          }
          case 'done': {
            const msg = chat.history.messages[frame.data.assistant_message_id];
            if (msg) msg.done = true;
            this.streaming = 'idle';
            break;
          }
          case 'cancelled': {
            const msg = chat.history.messages[frame.data.assistant_message_id];
            if (msg) {
              msg.done = true;
              msg.cancelled = true;
            }
            this.streaming = 'idle';
            break;
          }
          case 'timeout': {
            const msg = chat.history.messages[frame.data.assistant_message_id];
            if (msg) {
              msg.done = true;
              msg.cancelled = true;
            }
            this.error = `Stream exceeded ${frame.data.limit_seconds}s limit`;
            this.streaming = 'idle';
            break;
          }
          case 'error': {
            const id = frame.data.assistant_message_id ?? this.#assistantMessageId;
            if (id !== null) {
              const msg = chat.history.messages[id];
              if (msg) {
                msg.done = true;
                msg.error = {
                  message: frame.data.message,
                  ...(frame.data.code !== undefined ? { code: frame.data.code } : {}),
                };
              }
            }
            this.error = frame.data.message;
            this.streaming = 'idle';
            break;
          }
        }
      }
      // If the stream closed without a terminal frame (proxy cut, server
      // crash) we still need to land on `idle`; the assistant stays
      // `done: false` so the M6 sweeper can reap it.
      if (this.streaming !== 'idle') {
        this.streaming = 'idle';
      }
    } catch (err) {
      // AbortError surfaces as `DOMException` in browsers and as a
      // `name === 'AbortError'` shape in Node's undici. Treat it as
      // user-driven cancellation: the SSE branches above (or the
      // server-side `/cancel` path) have already updated the assistant
      // message; just reset transport state silently.
      const isAbort = isAbortError(err);
      if (!isAbort) {
        this.error = err instanceof ApiError ? err.message : String(err);
        const id = this.#assistantMessageId;
        if (id !== null) {
          const msg = chat.history.messages[id];
          if (msg) {
            msg.done = true;
            msg.error = { message: this.error };
          }
        }
        throw err;
      }
    } finally {
      this.streaming = 'idle';
      this.#abortController = null;
      this.#assistantMessageId = null;
    }
  };

  /**
   * Cancel the in-flight stream. Posts the explicit `/cancel` (so a
   * cross-pod stream gets the Redis pub/sub signal) and aborts the
   * local `fetch` — the order matters: post first so the server has a
   * chance to persist `cancelled: true, done: true` and emit the
   * terminal `cancelled` SSE frame before we drop the connection.
   *
   * Best-effort: if `/cancel` 4xx-fails (stream already finished) we
   * still abort locally so the UI returns to `idle` without waiting.
   */
  cancel = async (): Promise<void> => {
    if (this.streaming === 'idle' || this.streaming === 'cancelling') return;
    if (this.chat === null) return;
    this.streaming = 'cancelling';
    const messageId = this.#assistantMessageId;
    const chatId = this.chat.id;
    if (messageId !== null) {
      try {
        await chatsApi.cancel(chatId, messageId);
      } catch (err) {
        // Swallow — the abort below still terminates the local fetch.
        // The server may have already persisted the terminal frame.
        console.warn('ActiveChatStore.cancel: explicit cancel failed', err);
      }
    }
    if (this.#abortController !== null) {
      this.#abortController.abort();
    }
  };

  /**
   * UI-only branch switch. Sets `chat.history.currentId` to `childId`
   * so the linear thread re-derives. The next `send()` picks up from
   * here. No API call — branching is a server concept driven by which
   * `parent_id` the next message lands under.
   *
   * `parentId` is accepted for symmetry with the upstream API
   * (`switchBranch(parentId, childId)`) and validated: callers should
   * only switch among the parent's existing `childrenIds`.
   */
  switchBranch = (parentId: string, childId: string): void => {
    if (this.chat === null) return;
    const parent = this.chat.history.messages[parentId];
    if (!parent) {
      console.warn('ActiveChatStore.switchBranch: unknown parent', parentId);
      return;
    }
    if (!parent.childrenIds.includes(childId)) {
      console.warn('ActiveChatStore.switchBranch: child not under parent', {
        parentId,
        childId,
      });
      return;
    }
    const child = this.chat.history.messages[childId];
    if (!child) {
      console.warn('ActiveChatStore.switchBranch: unknown child', childId);
      return;
    }
    // Walk down the picked branch following the first child each hop
    // so the leaf — not the immediate child — is the active currentId.
    // Without this, switching to an older branch would land us on its
    // root and hide every assistant turn that followed.
    this.chat.history.currentId = walkToLeaf(this.chat.history, childId);
  };

  /**
   * Edit a message and resend it as a sibling under the same parent,
   * picking up the model/params from the most recent assistant in the
   * current branch (so the user doesn't have to re-pick).
   *
   * Throws (so the caller can surface a toast) when:
   * - The message id is unknown.
   * - There is no prior assistant turn to inherit model/params from
   *   AND the caller didn't supply an override. Callers can pass an
   *   explicit `model` to break the dependency on prior history (the
   *   first-message edit case in an empty chat).
   */
  editAndResend = async (
    messageId: string,
    newContent: string,
    overrides?: { model?: string; params?: ChatParams },
  ): Promise<void> => {
    if (this.chat === null) {
      throw new Error('ActiveChatStore.editAndResend: no chat loaded');
    }
    const target = this.chat.history.messages[messageId];
    if (!target) {
      throw new Error(`ActiveChatStore.editAndResend: unknown message ${messageId}`);
    }
    const parentId = target.parentId;
    // Pick "last model" from the most recent assistant in the linear
    // thread that ends at the target's parent (the new sibling lives
    // under the same parent so we walk from there, not from the
    // target itself).
    const lastAssistant = parentId !== null ? findLastAssistant(this.chat.history, parentId) : null;
    const model = overrides?.model ?? lastAssistant?.model ?? null;
    if (model === null) {
      throw new Error(
        'ActiveChatStore.editAndResend: no prior assistant message to inherit model from; pass overrides.model',
      );
    }
    await this.send({
      content: newContent,
      model,
      ...(overrides?.params !== undefined ? { params: overrides.params } : {}),
      parent_id: parentId,
    });
  };

  /**
   * Replace the temp ids assigned during the optimistic insert with
   * the server-assigned canonical ids. The two messages live in
   * `chat.history.messages` keyed by id, and their parent/child
   * references in neighbouring messages also need rewriting.
   */
  #applyStart(args: {
    chat: ChatRead;
    tempUserId: string;
    tempAssistantId: string;
    userMessageId: string;
    assistantMessageId: string;
  }): void {
    const { chat, tempUserId, tempAssistantId, userMessageId, assistantMessageId } = args;
    const messages = chat.history.messages;

    const userMsg = messages[tempUserId];
    const assistantMsg = messages[tempAssistantId];
    if (!userMsg || !assistantMsg) return;

    userMsg.id = userMessageId;
    userMsg.childrenIds = userMsg.childrenIds.map((id) =>
      id === tempAssistantId ? assistantMessageId : id,
    );
    assistantMsg.id = assistantMessageId;
    assistantMsg.parentId = userMessageId;

    // Rewrite the parent's `childrenIds` so the user message's new id
    // lands under it. The user message's parent is the previous active
    // leaf (or null if this is the root turn).
    if (userMsg.parentId !== null) {
      const parent = messages[userMsg.parentId];
      if (parent) {
        parent.childrenIds = parent.childrenIds.map((id) =>
          id === tempUserId ? userMessageId : id,
        );
      }
    }

    // Re-key the dictionary: delete the temp keys, install canonical
    // ones. Doing this in two steps avoids any chance of a transient
    // double-entry that the rune proxy could observe mid-mutation.
    delete messages[tempUserId];
    delete messages[tempAssistantId];
    messages[userMessageId] = userMsg;
    messages[assistantMessageId] = assistantMsg;
    chat.history.currentId = assistantMessageId;
  }
}

export function provideActiveChat(): ActiveChatStore {
  const store = new ActiveChatStore();
  setContext(KEY, store);
  return store;
}

export function useActiveChat(): ActiveChatStore {
  return getContext<ActiveChatStore>(KEY);
}

export const ACTIVE_CHAT_CONTEXT_KEY = KEY;

// ---------------------------------------------------------------------------
// Helpers (file-private; not exported because they are implementation
// detail of the store's branch-switch and abort handling).
// ---------------------------------------------------------------------------

/**
 * Walk down the tree from `startId` following `childrenIds[0]` at every
 * fork until a node with no children is reached. Returns the leaf id.
 *
 * Kept here (not in `lib/utils/history-tree.ts`) because the
 * "always pick the first child" tie-break is specific to
 * `switchBranch` — the broader history-tree helpers shouldn't bake
 * that heuristic in.
 */
function walkToLeaf(history: History, startId: string): string {
  let currentId = startId;
  const seen = new Set<string>();
  // Bound the walk to the same depth ceiling the linear-thread builder
  // uses; a pathological tree with a self-referential `childrenIds`
  // entry would otherwise loop forever.
  for (let i = 0; i < 1000; i += 1) {
    if (seen.has(currentId)) {
      console.warn('walkToLeaf: cycle at', currentId);
      return currentId;
    }
    seen.add(currentId);
    const node = history.messages[currentId];
    if (!node || node.childrenIds.length === 0) return currentId;
    const nextId = node.childrenIds[0];
    if (nextId === undefined) return currentId;
    currentId = nextId;
  }
  return currentId;
}

/**
 * Cross-runtime AbortError sniff. Browsers throw `DOMException` with
 * `name === 'AbortError'`; Node's undici matches the same `name`. The
 * narrow shape avoids importing `DOMException` (not in the Node lib).
 */
function isAbortError(err: unknown): boolean {
  if (err === null || typeof err !== 'object') return false;
  const named = err as { name?: unknown };
  return named.name === 'AbortError';
}
