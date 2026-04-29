/**
 * Typed env barrel for client-visible config.
 *
 * Only `PUBLIC_API_BASE_URL` is wired in M0. M2+ may add more `PUBLIC_*`
 * statics here. Runtime server-only secrets (`BACKEND_URL`) are read
 * directly via `$env/dynamic/private` inside `hooks.server.ts` so they
 * stay out of the browser bundle.
 */
export { PUBLIC_API_BASE_URL } from '$env/static/public';
