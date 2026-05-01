/**
 * Mirror of `app/schemas/share.py` — the M3 sharing wire types.
 *
 * Locked by `rebuild/docs/plans/m3-sharing.md` § API surface (the
 * three endpoints' request/response shapes). Snake_case field names
 * track the FastAPI payloads as-emitted, identical to the M2
 * conventions in `chat.ts` and `folder.ts`.
 *
 * Two notes worth restating at the type layer:
 *
 *   - `url` is **relative** (the backend returns `"/s/{token}"`).
 *     The frontend constructs the absolute URL from
 *     `window.location.origin + url` so the same response works in
 *     dev, staging, and prod with no base-URL config.
 *   - Every `created_at` field on this surface is **epoch
 *     milliseconds** — matches `shared_chat.created_at` storage type
 *     and the project-wide convention from `rebuild.md` §4.
 */

import type { History } from './history';

export interface ShareCreateResponse {
  /** 43-char URL-safe base64 token (`secrets.token_urlsafe(32)`). */
  token: string;
  /** Relative path; absolute URL is `window.location.origin + url`. */
  url: string;
  /** epoch milliseconds */
  created_at: number;
}

export interface SharedBy {
  name: string;
  email: string;
}

export interface SharedChatSnapshot {
  token: string;
  title: string;
  /** Same shape as `chat.history`; renders through the M2 message list. */
  history: History;
  shared_by: SharedBy;
  /** epoch milliseconds */
  created_at: number;
}
