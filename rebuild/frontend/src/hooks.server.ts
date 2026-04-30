import type { Handle, HandleFetch } from '@sveltejs/kit';
import { env } from '$env/dynamic/private';
import type { User } from '$lib/types/user';
import { isThemeId, resolveTheme, type ThemeId } from '$lib/theme/presets';
import { BOOT_SCRIPT_SOURCE } from '$lib/theme/boot';

const BACKEND_URL = env.BACKEND_URL ?? 'http://app:8080';

/**
 * Auth populate runs on every server request (including form-action POSTs and
 * `+server.ts` calls), per rebuild/docs/best-practises/sveltekit-best-practises.md § 6.2 / § 6.3 and the
 * m0 plan § Auth populate via `hooks.server.ts handle`. Doing it in a layout
 * `load` alone leaks across navigations because layout `load` results are
 * cached.
 *
 * The trusted-header contract is mirrored from the FastAPI backend's
 * `app.core.auth.get_user` dep: `X-Forwarded-Email` is required (case-
 * insensitive); `X-Forwarded-Name` is optional. A 401 from `/api/me` is
 * surfaced to downstream code as `event.locals.user = null`.
 *
 * M1 extends this hook with the theme cookie path:
 *   1. Read `theme` cookie; validate against `THEME_IDS`; drop unknown.
 *   2. Resolve to a final `ThemeId` via the brand-canonical fallback
 *      (`tokyo-night`) when no valid cookie is present. Server has no
 *      reliable signal for `prefers-color-scheme` (the
 *      `Sec-CH-Prefers-Color-Scheme` request header is not universally
 *      emitted), so the inline boot script in `app.html` corrects the
 *      DOM before hydration if the server picked the wrong fallback.
 *   3. Emit on `<html data-theme="...">` AND substitute the boot IIFE
 *      via `transformPageChunk` so the network response carries the
 *      correct theme without an extra round trip.
 */
export const handle: Handle = async ({ event, resolve }) => {
  // ----- auth populate -----
  const email = event.request.headers.get('x-forwarded-email');
  if (email) {
    try {
      const res = await event.fetch(`${BACKEND_URL}/api/me`, {
        headers: {
          'x-forwarded-email': email,
          'x-forwarded-name': event.request.headers.get('x-forwarded-name') ?? '',
        },
      });
      event.locals.user = res.ok ? ((await res.json()) as User) : null;
    } catch {
      event.locals.user = null;
    }
  } else {
    event.locals.user = null;
  }

  // ----- theme populate -----
  const cookieValue = event.cookies.get('theme');
  let resolvedTheme: ThemeId;
  let themeSource: 'explicit' | 'fallback';
  if (isThemeId(cookieValue)) {
    resolvedTheme = cookieValue;
    themeSource = 'explicit';
  } else {
    // No reliable OS signal on the server in M1; the inline boot
    // script reconciles client-side before hydration. Fall back to
    // the brand-canonical default.
    resolvedTheme = resolveTheme({});
    themeSource = 'fallback';
  }
  event.locals.theme = resolvedTheme;
  event.locals.themeSource = themeSource;

  return resolve(event, {
    transformPageChunk: ({ html }) =>
      html.replace('%theme.id%', resolvedTheme).replace('%theme.boot%', BOOT_SCRIPT_SOURCE),
  });
};

/**
 * Rewrites `event.fetch` URLs so calls from `load` or actions reach the
 * FastAPI service inside the compose network. Two cases:
 *
 *   1. Already-absolute `BACKEND_URL` request: forward the trusted-header
 *      pair so the backend's `get_user` sees them.
 *   2. Relative `/api/...` request: rewrite to `${BACKEND_URL}/api/...` and
 *      forward the trusted-header pair.
 *
 * Same-origin assets, the SvelteKit dev runtime, and any non-`/api/` path
 * fall through unchanged.
 */
export const handleFetch: HandleFetch = async ({ event, request, fetch }) => {
  const url = new URL(request.url);
  const isBackendAbsolute = request.url.startsWith(BACKEND_URL);
  const isApiPath = url.pathname.startsWith('/api/');

  if (!isBackendAbsolute && !isApiPath) {
    return fetch(request);
  }

  const target = isBackendAbsolute ? request.url : `${BACKEND_URL}${url.pathname}${url.search}`;

  const headers = new Headers(request.headers);
  const incomingEmail = event.request.headers.get('x-forwarded-email');
  const incomingName = event.request.headers.get('x-forwarded-name');
  if (incomingEmail) headers.set('x-forwarded-email', incomingEmail);
  if (incomingName) headers.set('x-forwarded-name', incomingName);

  return fetch(new Request(target, { ...request, headers }));
};
