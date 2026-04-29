import { PUBLIC_API_BASE_URL } from '$env/static/public';

/**
 * The single error shape thrown by every typed `apiFetch` call. Routes / stores
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
