/**
 * Mirror of `app/schemas/user.py::UserRead` from the FastAPI backend.
 *
 * The shape is locked by the M0 `/api/me` contract:
 *   { id, email, name, timezone, created_at }
 *
 * `created_at` is a BIGINT epoch-ms value straight from the row (project-wide
 * convention from rebuild.md §4); render via `new Date(created_at)` on the
 * frontend, the same helper later milestones use for chat / channel /
 * automation timestamps.
 */
export interface User {
  id: string;
  email: string;
  name: string;
  timezone: string;
  /** epoch milliseconds */
  created_at: number;
}
