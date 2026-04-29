import type { Handle, HandleFetch } from '@sveltejs/kit';
import { env } from '$env/dynamic/private';
import type { User } from '$lib/types/user';

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
 */
export const handle: Handle = async ({ event, resolve }) => {
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
  return resolve(event);
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
