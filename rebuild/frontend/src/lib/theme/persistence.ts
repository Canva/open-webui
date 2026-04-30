/**
 * Browser-only theme persistence: cookie + localStorage written together.
 *
 * Pinned by `rebuild/docs/plans/m1-theming.md` § Persistence. The two
 * surfaces are coupled deliberately:
 *   - the cookie carries the value into `hooks.server.ts` for FOUC-free
 *     SSR;
 *   - localStorage carries the value past third-party-cookie cleanup
 *     extensions that wipe `Lax` cookies on a schedule.
 *
 * `writeChoice` writes both in the same call so they cannot drift.
 * `clearChoice` deletes both so the user's "Match system" reset cannot
 * leave a stale half-state.
 *
 * This module is browser-only by design — every entry point is gated on
 * `typeof document !== 'undefined'`. Importing it from a server-only path
 * is harmless (the writes silently no-op) but pointless; the SSR side
 * reads the cookie via SvelteKit's `event.cookies` instead.
 */

import type { ThemeId } from '$lib/theme/presets';

const COOKIE_NAME = 'theme';
// One year in seconds. The browser eventually evicts; reads on a stale
// cookie validate against THEME_IDS in `hooks.server.ts` and drop unknown
// values, so an out-of-band rename of preset ids degrades gracefully.
const COOKIE_MAX_AGE = 60 * 60 * 24 * 365;
const STORAGE_KEY = 'theme';

/**
 * Write `id` to BOTH the cookie and `localStorage` in a single call. The
 * `Secure` cookie attribute is derived from `location.protocol` — dev over
 * `http://localhost:5173` writes a non-Secure cookie (Chrome would reject
 * Secure on HTTP), every other origin gets `Secure` automatically. This
 * needs no env-var plumbing per `m1-theming.md` § Persistence.
 *
 * Either surface failing (Safari private browsing throws on
 * `localStorage.setItem`) does NOT block the other — both writes are
 * attempted and failures are silently swallowed. The store will pick up
 * whichever surface succeeded on the next read.
 */
export function writeChoice(id: ThemeId): void {
  if (typeof document === 'undefined') return;

  const secure = locationIsHttps() ? '; Secure' : '';
  document.cookie = `${COOKIE_NAME}=${encodeURIComponent(id)}; Max-Age=${COOKIE_MAX_AGE}; Path=/; SameSite=Lax${secure}`;

  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // Safari private browsing throws QuotaExceededError on setItem; cookie
    // still carries the choice. Silent on purpose.
  }
}

/**
 * Delete from BOTH surfaces. Used by the picker's "Match system" reset.
 * Does NOT call `setTheme` — the caller (the store) re-resolves to the
 * OS preference after clearing.
 */
export function clearChoice(): void {
  if (typeof document === 'undefined') return;

  const secure = locationIsHttps() ? '; Secure' : '';
  document.cookie = `${COOKIE_NAME}=; Max-Age=0; Path=/; SameSite=Lax${secure}`;

  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // See writeChoice — Safari private browsing throws on access.
  }
}

/**
 * Read the localStorage entry. Returns `null` when storage is unavailable
 * (Safari private browsing throws on the first access) so callers can
 * fall through to the cookie tier without re-implementing the try/catch
 * dance. Validation against `THEME_IDS` is the caller's responsibility —
 * this is plumbing, not a theme resolver.
 */
export function readStoredChoice(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

/**
 * Parse the `theme` cookie out of `document.cookie`. Returns `null` if
 * absent. Validation against `THEME_IDS` is the caller's responsibility.
 */
export function readCookieChoice(): string | null {
  if (typeof document === 'undefined') return null;
  const match = /(?:^|;\s*)theme=([^;]+)/.exec(document.cookie);
  if (!match || !match[1]) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return null;
  }
}

function locationIsHttps(): boolean {
  if (typeof window === 'undefined') return false;
  return window.location.protocol === 'https:';
}
