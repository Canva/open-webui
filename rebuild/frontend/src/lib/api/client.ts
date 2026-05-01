/**
 * Typed `fetch` wrapper for the FastAPI backend.
 *
 * The M0 dispatch shipped `apiFetch` + `ApiError` — both kept verbatim
 * for back-compat with the unit tests at
 * `tests/unit/api-client.test.ts`. M2 adds three namespaced surfaces
 * (`chats`, `folders`, `models`) for the conversation routes; the
 * stores call into those instead of issuing raw `fetch` calls.
 *
 * Per `rebuild/docs/plans/m0-foundations.md` § Frontend conventions
 * (cross-cutting), rule 5: "Every mutation in M2-M5 is a typed `fetch`
 * from a store action against the FastAPI `/api/...` route" — that
 * fetch goes through `apiFetch` here, never `globalThis.fetch` from a
 * component or store.
 *
 * The streaming endpoint (`chats.send`) is the one exception that
 * returns a raw `Response` instead of a parsed JSON body — the caller
 * (`ActiveChatStore`) reads `response.body` as a `ReadableStream` and
 * passes it through `parseSSE`. The 4xx/5xx pre-stream check still
 * happens here so the store does not have to duplicate the error
 * unwrap.
 */

import { PUBLIC_API_BASE_URL } from '$env/static/public';

import type {
  ChatCreate,
  ChatList,
  ChatListFilter,
  ChatPatch,
  ChatRead,
  MessageSend,
  TitleRequest,
  TitleResponse,
} from '$lib/types/chat';
import type { FolderCreate, FolderDeleteResult, FolderPatch, FolderRead } from '$lib/types/folder';
import type { ModelList } from '$lib/types/model';
import type { ShareCreateResponse, SharedChatSnapshot } from '$lib/types/share';

/**
 * The single error shape thrown by every typed call. Routes / stores
 * may catch and surface `status` to render different UI for 401 / 404 / 422.
 */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/**
 * Typed `fetch` wrapper hitting the FastAPI backend.
 *
 * Pass SvelteKit's enhanced `fetch` from a `load` (third arg) so the request
 * is replayed into the SSR'd HTML and the browser does not refetch on
 * hydration. Plain `globalThis.fetch` works too in client-only call sites.
 */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  fetcher: typeof fetch = fetch,
): Promise<T> {
  const url = `${PUBLIC_API_BASE_URL}${path}`;
  const res = await fetcher(url, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init.headers ?? {}) },
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => undefined);
    throw new ApiError(res.status, res.statusText, detail);
  }
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Serialise a partial filter into a URL query string. Drops
 * `undefined` and `null` keys so callers can pass sparse filters
 * without manually pruning. Booleans serialise as `"true"` / `"false"`
 * to match FastAPI's `Query[bool]` parsing.
 */
function buildQuery(params: Record<string, string | number | boolean | undefined | null>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  }
  return parts.length === 0 ? '' : `?${parts.join('&')}`;
}

// ---------------------------------------------------------------------------
// `chats` namespace — everything under `/api/chats`.
// ---------------------------------------------------------------------------

export const chats = {
  /**
   * `GET /api/chats` — sidebar list, cursor-paginated. The `folder_id`
   * filter accepts the literal string `"none"` per the M2 backend
   * contract (means "no folder"); pass `undefined` to skip the filter.
   */
  async list(filter: ChatListFilter = {}, fetcher: typeof fetch = fetch): Promise<ChatList> {
    const query = buildQuery({
      folder_id: filter.folder_id,
      archived: filter.archived,
      pinned: filter.pinned,
      q: filter.q,
      limit: filter.limit,
      cursor: filter.cursor,
    });
    return apiFetch<ChatList>(`/api/chats${query}`, { method: 'GET' }, fetcher);
  },

  /** `POST /api/chats` — create a new (empty) chat. */
  async create(input: ChatCreate, fetcher: typeof fetch = fetch): Promise<ChatRead> {
    return apiFetch<ChatRead>(
      '/api/chats',
      { method: 'POST', body: JSON.stringify(input) },
      fetcher,
    );
  },

  /** `GET /api/chats/{id}` — full chat including `history`. */
  async get(id: string, fetcher: typeof fetch = fetch): Promise<ChatRead> {
    return apiFetch<ChatRead>(`/api/chats/${encodeURIComponent(id)}`, { method: 'GET' }, fetcher);
  },

  /** `PATCH /api/chats/{id}` — partial update of metadata. */
  async patch(id: string, partial: ChatPatch, fetcher: typeof fetch = fetch): Promise<ChatRead> {
    return apiFetch<ChatRead>(
      `/api/chats/${encodeURIComponent(id)}`,
      { method: 'PATCH', body: JSON.stringify(partial) },
      fetcher,
    );
  },

  /** `DELETE /api/chats/{id}` — hard delete; backend returns 204. */
  async delete(id: string, fetcher: typeof fetch = fetch): Promise<void> {
    const url = `${PUBLIC_API_BASE_URL}/api/chats/${encodeURIComponent(id)}`;
    const res = await fetcher(url, { method: 'DELETE' });
    if (!res.ok) {
      const detail = await res.json().catch(() => undefined);
      throw new ApiError(res.status, res.statusText, detail);
    }
  },

  /** `POST /api/chats/{id}/title` — auto-title helper. Non-streaming. */
  async title(
    id: string,
    body: TitleRequest,
    fetcher: typeof fetch = fetch,
  ): Promise<TitleResponse> {
    return apiFetch<TitleResponse>(
      `/api/chats/${encodeURIComponent(id)}/title`,
      { method: 'POST', body: JSON.stringify(body) },
      fetcher,
    );
  },

  /**
   * `POST /api/chats/{id}/messages` — open the SSE stream.
   *
   * Returns the raw `Response` so the caller can read `response.body`
   * as a `ReadableStream`. We assert `response.ok` here (throwing
   * `ApiError` on a 4xx/5xx **before** the stream opens — at this
   * point the body is JSON, not SSE) so the store gets either a usable
   * stream or a typed error and never has to disambiguate. After the
   * `start` SSE frame the response status is locked at 200; mid-stream
   * failures arrive as terminal `error` SSE frames, not as HTTP errors.
   *
   * Pass `opts.signal` from a caller-owned `AbortController` so cancel
   * paths (Esc key, `unload()` on route change, explicit `cancel()`)
   * tear down the underlying `fetch` cleanly.
   */
  async send(
    chatId: string,
    body: MessageSend,
    opts: { signal?: AbortSignal; fetcher?: typeof fetch } = {},
  ): Promise<Response> {
    const fetcher = opts.fetcher ?? fetch;
    const url = `${PUBLIC_API_BASE_URL}/api/chats/${encodeURIComponent(chatId)}/messages`;
    const res = await fetcher(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'text/event-stream' },
      body: JSON.stringify(body),
      signal: opts.signal,
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => undefined);
      throw new ApiError(res.status, res.statusText, detail);
    }
    return res;
  },

  /**
   * `POST /api/chats/{id}/messages/{message_id}/cancel` — explicit
   * cancel for cases where dropping the connection isn't enough
   * (multi-tab share, Esc key with the response already buffered by a
   * proxy). Best-effort: returns 204 even if the stream already
   * finished.
   */
  async cancel(chatId: string, messageId: string, fetcher: typeof fetch = fetch): Promise<void> {
    const url = `${PUBLIC_API_BASE_URL}/api/chats/${encodeURIComponent(
      chatId,
    )}/messages/${encodeURIComponent(messageId)}/cancel`;
    const res = await fetcher(url, { method: 'POST' });
    if (!res.ok) {
      const detail = await res.json().catch(() => undefined);
      throw new ApiError(res.status, res.statusText, detail);
    }
  },
};

// ---------------------------------------------------------------------------
// `folders` namespace — everything under `/api/folders`.
// ---------------------------------------------------------------------------

export const folders = {
  /** `GET /api/folders` — flat list (the UI builds the tree client-side). */
  async list(fetcher: typeof fetch = fetch): Promise<FolderRead[]> {
    return apiFetch<FolderRead[]>('/api/folders', { method: 'GET' }, fetcher);
  },

  /** `POST /api/folders` — create. 409 on cycle, 404 on missing parent. */
  async create(input: FolderCreate, fetcher: typeof fetch = fetch): Promise<FolderRead> {
    return apiFetch<FolderRead>(
      '/api/folders',
      { method: 'POST', body: JSON.stringify(input) },
      fetcher,
    );
  },

  /** `PATCH /api/folders/{id}` — rename / move / toggle expanded. */
  async patch(
    id: string,
    partial: FolderPatch,
    fetcher: typeof fetch = fetch,
  ): Promise<FolderRead> {
    return apiFetch<FolderRead>(
      `/api/folders/${encodeURIComponent(id)}`,
      { method: 'PATCH', body: JSON.stringify(partial) },
      fetcher,
    );
  },

  /**
   * `DELETE /api/folders/{id}` — cascades to descendant folders;
   * chats are detached (folder_id set to NULL), never deleted. The
   * response carries both lists so the caller can drive in-place
   * sidebar updates without refetching.
   */
  async delete(id: string, fetcher: typeof fetch = fetch): Promise<FolderDeleteResult> {
    return apiFetch<FolderDeleteResult>(
      `/api/folders/${encodeURIComponent(id)}`,
      { method: 'DELETE' },
      fetcher,
    );
  },
};

// ---------------------------------------------------------------------------
// `models` namespace — `/api/models`.
// ---------------------------------------------------------------------------

export const models = {
  /** `GET /api/models` — passthrough of `/v1/models`, cached server-side. */
  async list(fetcher: typeof fetch = fetch): Promise<ModelList> {
    return apiFetch<ModelList>('/api/models', { method: 'GET' }, fetcher);
  },
};

// ---------------------------------------------------------------------------
// `shares` namespace — `/api/chats/{id}/share` + `/api/shared/{token}`.
//
// Locked by `rebuild/docs/plans/m3-sharing.md` § API surface (the three
// endpoints, their owner-only / proxy-auth gates, and the rotate-on-re-share
// semantics). The frontend never mints a token: that is backend-only.
// ---------------------------------------------------------------------------

export const shares = {
  /**
   * `POST /api/chats/{chat_id}/share` — owner mints (or rotates) the share
   * token. 404 is returned for both "no such chat" and "not the owner" so
   * the response shape never leaks existence.
   */
  async create(chatId: string, fetcher: typeof fetch = fetch): Promise<ShareCreateResponse> {
    return apiFetch<ShareCreateResponse>(
      `/api/chats/${encodeURIComponent(chatId)}/share`,
      { method: 'POST' },
      fetcher,
    );
  },

  /**
   * `DELETE /api/chats/{chat_id}/share` — idempotent revoke. Backend returns
   * 204 even on an already-unshared chat (per the plan's § API surface), so
   * callers can fire-and-forget without tracking the latest server state.
   * Mirrors `chats.delete` in using a raw `fetcher` for the no-content path.
   */
  async revoke(chatId: string, fetcher: typeof fetch = fetch): Promise<void> {
    const url = `${PUBLIC_API_BASE_URL}/api/chats/${encodeURIComponent(chatId)}/share`;
    const res = await fetcher(url, { method: 'DELETE' });
    if (!res.ok) {
      const detail = await res.json().catch(() => undefined);
      throw new ApiError(res.status, res.statusText, detail);
    }
  },

  /**
   * `GET /api/shared/{token}` — read a snapshot. Authentication is the
   * proxy header (`X-Forwarded-Email`); ownership is irrelevant once the
   * token is known. Called from the public route's `+page.server.ts`,
   * which passes the SvelteKit enhanced `fetch` so the proxy headers
   * forward in our deployment.
   */
  async get(token: string, fetcher: typeof fetch = fetch): Promise<SharedChatSnapshot> {
    return apiFetch<SharedChatSnapshot>(
      `/api/shared/${encodeURIComponent(token)}`,
      { method: 'GET' },
      fetcher,
    );
  },
};
