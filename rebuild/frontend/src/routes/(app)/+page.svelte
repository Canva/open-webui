<script lang="ts">
  /**
   * The `/` empty-state landing surface — pinned by
   * `rebuild/docs/plans/m2-conversations.md` § Frontend routes (line
   * 869): "empty-state landing screen ('start a conversation')".
   *
   * NOT a ChatGPT-clone centred-prompt-in-a-void. The sidebar stays
   * visible (M2 layout owns it). This pane is a focused composer plus
   * a short row of recent conversations — a workshop bench, not a
   * marketing landing.
   *
   * Interaction:
   *   - The composer auto-focuses on mount.
   *   - Enter (no shift) creates a chat via `useChats().create({})`,
   *     navigates to `/c/<id>`, then dispatches the user's message via
   *     a session-only handoff in `sessionStorage` (the conversation
   *     view picks it up on mount and runs `useActiveChat().send()`).
   *   - Below the composer: the five most-recently-touched chats from
   *     `useChats().byPinnedThenUpdated` so the user can re-enter
   *     ongoing work without round-tripping through the sidebar.
   *
   * Copy is precise / composed / kinetic — not "Hi! How can I help?".
   * No em dashes anywhere; commas / periods / colons only.
   */
  import { goto } from '$app/navigation';
  import { useChats } from '$lib/stores/chats.svelte';
  import { useModels } from '$lib/stores/models.svelte';
  import { useToast } from '$lib/stores/toast.svelte';
  import ModelSelector from '$lib/components/chat/ModelSelector.svelte';

  const chats = useChats();
  const models = useModels();
  const toast = useToast();

  const PENDING_KEY = 'rebuild:pending-first-message';

  let prompt = $state('');
  let model = $state('');
  let sending = $state(false);
  let textarea: HTMLTextAreaElement | null = $state(null);

  const recent = $derived(chats.byPinnedThenUpdated.slice(0, 5));
  const canSend = $derived(prompt.trim().length > 0 && model !== '' && !sending);

  // Hydrate a default model from the catalog. The composer is unusable
  // without one, so picking the first available item is preferable to
  // forcing the user to open the dropdown to start typing.
  $effect(() => {
    if (model === '' && models.items.length > 0) {
      const first = models.items[0];
      if (first) model = first.id;
    }
  });

  // Auto-focus on mount so the user lands ready to type. Bypassed when
  // a screen reader is present? — the visible textarea is the primary
  // affordance here, so explicit focus is appropriate (per
  // `reference/onboard.md`: "Get users to value as quickly as
  // possible").
  $effect(() => {
    textarea?.focus();
  });

  async function handleSubmit(): Promise<void> {
    if (!canSend) return;
    const content = prompt.trim();
    sending = true;
    try {
      const created = await chats.create({});
      // Stash the pending message so the conversation view picks it up
      // and dispatches `useActiveChat().send(...)` after `load()`
      // finishes. Using sessionStorage instead of a query parameter
      // keeps the URL clean and the body out of any browser history /
      // server access logs.
      sessionStorage.setItem(PENDING_KEY, JSON.stringify({ chatId: created.id, content, model }));
      prompt = '';
      await goto(`/c/${created.id}`);
    } catch (err) {
      toast.pushError(err instanceof Error ? err.message : String(err));
      sending = false;
    }
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void handleSubmit();
    }
  }

  function chatHref(id: string): string {
    return `/c/${id}`;
  }
</script>

<div class="flex h-full flex-col items-center justify-center px-6">
  <div class="w-full max-w-2xl">
    <header class="mb-8">
      <p class="text-ink-muted tracking-label text-xs font-medium uppercase">Workshop</p>
      <h1 class="text-ink-strong font-display tracking-display mt-2 text-2xl/[1.2] font-semibold">
        What are you working on?
      </h1>
      <p class="text-ink-secondary mt-2 text-sm/[1.5]">
        Start a conversation, or return to one in progress.
      </p>
    </header>

    <form
      class="bg-background-elevated border-hairline motion-safe:ease-out-quart hover:border-hairline-strong focus-within:border-hairline-strong rounded-3xl border p-3 shadow-lg motion-safe:transition-colors motion-safe:duration-150"
      onsubmit={(e) => {
        e.preventDefault();
        void handleSubmit();
      }}
    >
      <textarea
        bind:this={textarea}
        bind:value={prompt}
        onkeydown={onKeydown}
        rows="3"
        placeholder="Ask the agent. Enter to send, Shift+Enter for a newline."
        aria-label="Compose a message"
        class="text-ink-strong placeholder:text-ink-placeholder block w-full resize-none border-none bg-transparent px-3 py-2 text-sm/[1.5] outline-none"
      ></textarea>
      <div class="border-hairline mt-2 flex items-center justify-between gap-2 border-t pt-2">
        <ModelSelector bind:value={model} />
        <button
          type="submit"
          disabled={!canSend}
          class="bg-ink-strong text-background-app hover:bg-ink-body motion-safe:ease-out-quart inline-flex items-center gap-1.5 rounded-3xl px-4 py-1.5 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-40 motion-safe:transition-colors motion-safe:duration-150"
          aria-label="Send"
        >
          <span>Send</span>
          <svg
            width="12"
            height="12"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.75"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M3 8h10M9 4l4 4-4 4" />
          </svg>
        </button>
      </div>
    </form>

    {#if recent.length > 0}
      <section class="mt-8">
        <p class="text-ink-muted tracking-label text-xs font-medium uppercase">Recent</p>
        <ul class="mt-2 flex flex-col gap-px">
          {#each recent as chat (chat.id)}
            <li>
              <a
                href={chatHref(chat.id)}
                class="text-ink-body hover:bg-background-elevated hover:text-ink-strong motion-safe:ease-out-quart group flex items-center justify-between gap-3 rounded-xl px-3 py-2 text-sm motion-safe:transition-colors motion-safe:duration-150"
              >
                <span class="truncate">{chat.title}</span>
                {#if chat.pinned}
                  <span
                    class="text-accent-mention tracking-label text-[10px] font-medium uppercase"
                    aria-label="Pinned"
                  >
                    Pinned
                  </span>
                {/if}
              </a>
            </li>
          {/each}
        </ul>
      </section>
    {:else}
      <p class="text-ink-muted mt-8 text-center text-xs">Your conversations will appear here.</p>
    {/if}
  </div>
</div>
