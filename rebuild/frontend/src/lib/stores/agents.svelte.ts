/**
 * Per-request agents store. Constructed in `(app)/+layout.svelte`
 * via `provideAgents(data.agents)` and consumed by the agent
 * selector + the `ActiveChatStore` (which validates that the
 * selected agent is in the catalogue before opening the stream).
 *
 * Locked by `rebuild/docs/plans/m2-conversations.md` § Stores and
 * state — the canonical example block on lines 949-994 is the shape
 * for every M2 store; this file matches it verbatim with the typed
 * `agents.list()` client call instead of a raw `fetch`.
 *
 * Refresh strategy: `maybeRefresh(maxAgeMs = 30_000)` is called from
 * the agent dropdown's open handler; the backend already caches for
 * 5 minutes so this is mostly a "freshen on first open after the
 * cache window" gesture, not a high-RPS poll.
 */

import { getContext, setContext } from 'svelte';

import { ApiError, agents as agentsApi } from '$lib/api/client';
import type { AgentInfo } from '$lib/types/agent';

const KEY = Symbol('agents');

export class AgentsStore {
  items = $state<AgentInfo[]>([]);
  loaded = $state(false);
  loading = $state(false);
  error: string | null = $state(null);

  /**
   * Last successful refresh timestamp (epoch ms). Plain instance
   * field, not `$state` — `maybeRefresh()` only ever reads it
   * synchronously to gate the call; the UI binds to `loaded` /
   * `error` for visible state changes.
   */
  #lastRefreshed = 0;

  constructor(initial: AgentInfo[] = []) {
    this.items = initial;
    this.loaded = initial.length > 0;
    if (this.loaded) {
      this.#lastRefreshed = Date.now();
    }
  }

  /**
   * Force-fetch the catalogue. Resets `loading` / `error` regardless of
   * outcome so the UI always reflects the latest attempt. Errors are
   * captured into the store's `error` field; the caller may also
   * surface a toast if it has access to the `ToastStore` (the
   * dropdown does; `ActiveChatStore.send` does too via the layout
   * wiring).
   */
  refresh = async (): Promise<void> => {
    this.loading = true;
    try {
      const list = await agentsApi.list();
      this.items = list.items;
      this.loaded = true;
      this.error = null;
      this.#lastRefreshed = Date.now();
    } catch (err) {
      this.error = err instanceof ApiError ? err.message : String(err);
    } finally {
      this.loading = false;
    }
  };

  /**
   * Refresh only if the local copy is older than `maxAgeMs`. Fire-and-
   * forget: the dropdown is happy to render the stale list while the
   * fresh one loads in. `void` discards the returned promise so the
   * caller's `onclick` handler stays sync.
   */
  maybeRefresh = (maxAgeMs = 30_000): void => {
    if (Date.now() - this.#lastRefreshed > maxAgeMs) {
      void this.refresh();
    }
  };

  /** Lookup helper for `ActiveChatStore.send` — returns the label, or `null`. */
  labelFor = (agentId: string): string | null => {
    const found = this.items.find((a) => a.id === agentId);
    return found?.label ?? null;
  };
}

export function provideAgents(initial: AgentInfo[] = []): AgentsStore {
  const store = new AgentsStore(initial);
  setContext(KEY, store);
  return store;
}

export function useAgents(): AgentsStore {
  return getContext<AgentsStore>(KEY);
}

export const AGENTS_CONTEXT_KEY = KEY;
