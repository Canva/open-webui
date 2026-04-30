/**
 * Per-request toast queue. Constructed once in `(app)/+layout.svelte`
 * via `provideToast()` and consumed by every store/component that
 * needs to surface an error or success — primarily the M2 SSE error
 * branch and HTTP failures from `chats` / `folders` / `models`.
 *
 * Locked by:
 * - `rebuild/docs/plans/m2-conversations.md` § Stores and state
 *   (the `ToastStore` row in the table on lines 949-952).
 * - `rebuild/docs/plans/m0-foundations.md` § Frontend conventions
 *   (cross-cutting), rule 2: class + `setContext`, no module-level
 *   `$state` for per-user data.
 *
 * Auto-dismiss: deferred to the consuming `<Toaster>` component (Phase
 * 3d). The store records `created` so the component's `$effect` can
 * compute remaining lifetime; the dismiss `setTimeout` lives on the
 * component (where `$effect`'s cleanup contract reaps it on unmount)
 * rather than inside the store. This is per
 * `rebuild/docs/best-practises/svelte-best-practises.md` § 3.3 and §
 * 9 — long-lived browser side-effects (timers, intervals, listeners)
 * belong to `$effect` in the consuming component, never to the store
 * class itself, never to module scope. The store stays purely
 * synchronous and SSR-safe.
 */

import { getContext, setContext } from 'svelte';

const KEY = Symbol('toast');

export type ToastLevel = 'info' | 'success' | 'warning' | 'danger';

export interface Toast {
  id: string;
  level: ToastLevel;
  message: string;
  /** epoch milliseconds, set by `push()`. */
  created: number;
}

export class ToastStore {
  /**
   * The visible queue. New toasts append; `dismiss()` removes by id.
   * Deep `$state` (not `$state.raw`) so the consuming `<Toaster>`
   * `{#each}` re-renders on every push/dismiss.
   */
  items = $state<Toast[]>([]);

  /**
   * Push a new toast onto the queue. Returns the generated id so the
   * caller (typically a `<Toaster>` component's `$effect`) can wire a
   * dismiss timer keyed on it.
   *
   * `crypto.randomUUID()` is universally available in modern browsers
   * and Node 19+; the rebuild's runtime targets are well above either
   * floor so we don't ship a fallback.
   */
  push = (level: ToastLevel, message: string): string => {
    const id = crypto.randomUUID();
    this.items.push({ id, level, message, created: Date.now() });
    return id;
  };

  /** Convenience for `push('danger', message)` — the most common call site. */
  pushError = (message: string): string => this.push('danger', message);

  /**
   * Remove a toast by id. No-op if the id is unknown (a `<Toaster>`
   * timer firing after the user already dismissed manually is the
   * expected reason for that). Reassigns `items` to a filtered copy
   * so `$state`'s referential-equality short-circuit doesn't suppress
   * the dependent re-render — though in practice the in-place splice
   * also works because deep-`$state` arrays track mutation.
   */
  dismiss = (id: string): void => {
    const idx = this.items.findIndex((t) => t.id === id);
    if (idx >= 0) this.items.splice(idx, 1);
  };
}

export function provideToast(): ToastStore {
  const store = new ToastStore();
  setContext(KEY, store);
  return store;
}

export function useToast(): ToastStore {
  return getContext<ToastStore>(KEY);
}

export const TOAST_CONTEXT_KEY = KEY;
