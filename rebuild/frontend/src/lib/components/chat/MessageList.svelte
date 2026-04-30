<script lang="ts">
  /**
   * Pure render of the linear thread for the active branch. Walks
   * `history.parentId` from `currentId` to the root via the pure
   * `buildLinearThread` helper (Phase 3a) and maps each turn to a
   * `<Message>` instance.
   *
   * Pinned by `rebuild/docs/plans/m2-conversations.md`:
   *   - § Frontend components (line 887): "MessageList — Renders the
   *     linear thread (`buildLinearThread(history, currentId)`).
   *     Branch chevrons (`< 2 / 3 >`) when a parent has multiple
   *     childrenIds; clicking switches branches via
   *     `useActiveChat().switchBranch`."
   *
   * Branching: when a message has a parent that has more than one
   * `childrenIds`, render a chevron row `< (idx+1) / total >` before
   * the message body. The chevrons are typography-driven (mono digits
   * in `text-ink-muted`) so the alternative-thread switcher stays
   * quiet — branching is a power-user gesture, not a hero affordance.
   *
   * LOC budget ≤ 200.
   */
  import { useActiveChat } from '$lib/stores/active-chat.svelte';
  import { buildLinearThread } from '$lib/utils/history-tree';
  import type { History, HistoryMessage } from '$lib/types/history';
  import Message from './Message.svelte';

  interface Props {
    history: History;
  }

  let { history }: Props = $props();

  const activeChat = useActiveChat();

  const linear = $derived.by<HistoryMessage[]>(() => {
    if (history.currentId === null) return [];
    return buildLinearThread(history, history.currentId);
  });

  /** Returns the parent message (or null) for branch chevron context. */
  function parentOf(message: HistoryMessage): HistoryMessage | null {
    if (message.parentId === null) return null;
    return history.messages[message.parentId] ?? null;
  }

  function siblingsFor(message: HistoryMessage): {
    siblings: string[];
    index: number;
  } | null {
    const parent = parentOf(message);
    if (!parent || parent.childrenIds.length <= 1) return null;
    const idx = parent.childrenIds.indexOf(message.id);
    if (idx < 0) return null;
    return { siblings: parent.childrenIds, index: idx };
  }

  function previousBranch(message: HistoryMessage): void {
    const info = siblingsFor(message);
    if (!info || info.index === 0) return;
    const prev = info.siblings[info.index - 1];
    if (prev !== undefined && message.parentId !== null) {
      activeChat.switchBranch(message.parentId, prev);
    }
  }

  function nextBranch(message: HistoryMessage): void {
    const info = siblingsFor(message);
    if (!info || info.index >= info.siblings.length - 1) return;
    const next = info.siblings[info.index + 1];
    if (next !== undefined && message.parentId !== null) {
      activeChat.switchBranch(message.parentId, next);
    }
  }
</script>

<div class="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6">
  {#if linear.length === 0}
    <p class="text-ink-muted py-8 text-center text-sm">
      No messages yet. Send the first one below.
    </p>
  {:else}
    {#each linear as message (message.id)}
      {@const branch = siblingsFor(message)}
      <div class="flex flex-col gap-1.5">
        {#if branch}
          <div
            class="text-ink-muted flex items-center gap-2 font-mono text-xs"
            aria-label="Branch switcher"
          >
            <button
              type="button"
              onclick={() => previousBranch(message)}
              disabled={branch.index === 0}
              class="hover:text-ink-strong inline-flex h-5 w-5 items-center justify-center rounded disabled:opacity-30 motion-safe:transition-colors motion-safe:duration-150"
              aria-label="Previous branch"
            >
              <span aria-hidden="true">‹</span>
            </button>
            <span class="tabular-nums">{branch.index + 1} / {branch.siblings.length}</span>
            <button
              type="button"
              onclick={() => nextBranch(message)}
              disabled={branch.index >= branch.siblings.length - 1}
              class="hover:text-ink-strong inline-flex h-5 w-5 items-center justify-center rounded disabled:opacity-30 motion-safe:transition-colors motion-safe:duration-150"
              aria-label="Next branch"
            >
              <span aria-hidden="true">›</span>
            </button>
          </div>
        {/if}
        <Message {message} parent={parentOf(message)} />
      </div>
    {/each}
  {/if}
</div>
