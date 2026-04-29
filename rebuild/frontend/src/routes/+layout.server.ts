import type { LayoutServerLoad } from './$types';

// Auth populate already happened in `hooks.server.ts handle`; this just
// surfaces the request-scoped user to every child route via `data.user`.
// Keep this file a one-liner; see m0 plan § Auth populate.
export const load: LayoutServerLoad = ({ locals }) => ({ user: locals.user });
