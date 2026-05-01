<script lang="ts">
  /**
   * The share-link modal mounted from `ConversationView`'s header.
   *
   * Pinned by `rebuild/docs/plans/m3-sharing.md` § Owner UX:
   *   - Three states: `not-shared` -> `shared` -> `stop-confirm` ->
   *     `not-shared`, with `Esc` and backdrop-click closing only when
   *     no fetch is in flight.
   *   - Snapshot semantics copy is verbatim from the plan: "Sharing
   *     creates a snapshot at this moment in time. To share later
   *     edits, click Stop sharing and Generate a new link."
   *   - Stop-sharing prompts an INLINE confirmation inside the same
   *     modal, never `window.confirm` (the plan rules that out
   *     explicitly because it flashes outside the theme).
   *   - All three mutating actions disable while in flight.
   *
   * Design notes (impeccable `craft` per
   * `.cursor/skills/impeccable/PROJECT.md`):
   *   - Modal envelope follows the canonical Modal Surface from
   *     `project/DESIGN.json`: `rounded-4xl`, blurred translucent
   *     fill, hairline ghost border, soft lift. Tailwind 4 role
   *     tokens (`bg-background-app`, `border-hairline`, `text-ink-*`)
   *     pick up Tokyo Night vs Day automatically through the M1 theme
   *     resolution path.
   *   - Backdrop uses `bg-background-app/70` + `backdrop-blur-sm`
   *     (Blur-Is-The-Depth Rule); the modal carries the lift, the
   *     backdrop carries the depth cue.
   *   - Primary CTA inverts in dark mode via `bg-ink-strong`/
   *     `text-background-app`, which round-trips through the role
   *     tokens regardless of the active preset.
   *   - No hex literals, no `#000`/`#fff`, no second decorative hue
   *     (per project absolute bans).
   *
   * The component is a controlled child: the parent owns `open`
   * (just toggles via `onClose`) and patches its own local state
   * via `onShareChange` so the chat header can re-render without
   * waiting for a refetch.
   */
  import { tick, untrack } from 'svelte';
  import { ApiError, shares } from '$lib/api/client';
  import { useToast } from '$lib/stores/toast.svelte';
  import type { ChatRead } from '$lib/types/chat';
  import { formatRelativeTime } from '$lib/utils/relative-time';

  interface Props {
    chat: ChatRead;
    onClose: () => void;
    /**
     * Optional patch hook so the parent (`ConversationView`) can
     * mutate its local `activeChat.chat.share_id` immediately when
     * the share is created or revoked, instead of waiting for a
     * refetch. `null` is "share has been revoked".
     */
    onShareChange?: (nextShareId: string | null) => void;
  }

  let { chat, onClose, onShareChange }: Props = $props();

  const toast = useToast();
  const labelId = $props.id();

  type Phase = 'not-shared' | 'shared' | 'stop-confirm';

  // Derive the initial phase from the seed prop, then own the phase
  // locally — generate / revoke transitions are user-driven inside
  // this modal and shouldn't be re-derived from prop changes.
  let phase: Phase = $state(untrack(() => (chat.share_id ? 'shared' : 'not-shared')));

  // The share token in display. `null` until we either come in with
  // `chat.share_id` set (return visit) or generate a new one.
  let token: string | null = $state(untrack(() => chat.share_id));

  /** Snapshot mtime. Populated on `Generate` or via lazy fetch on open. */
  let createdAt: number | null = $state(null);
  /** True while a network call is open — debounces double-clicks AND
   *  locks the Esc / backdrop close affordances per the plan. */
  let inFlight = $state(false);

  // Modal root, used to scope the focus trap.
  let modalEl: HTMLDivElement | null = $state(null);
  // Primary action — focused on every state transition so keyboard
  // users land on the most likely next step (Generate / Copy /
  // Stop sharing -> Stop sharing again on the inline confirm).
  let primaryActionEl: HTMLElement | null = $state(null);

  // Build the absolute URL from the current origin, only on the client.
  // SSR cannot construct the absolute URL (no `window.location`); we
  // render the relative `/s/{token}` instead until hydration lands.
  const absoluteUrl = $derived.by<string | null>(() => {
    if (token === null) return null;
    if (typeof window === 'undefined') return `/s/${token}`;
    return `${window.location.origin}/s/${token}`;
  });

  const capturedLabel = $derived.by<string | null>(() => {
    if (createdAt === null) return null;
    return `Captured ${formatRelativeTime(createdAt)}`;
  });

  // ------------------------------------------------------------------
  // Lifecycle: lock body scroll + focus primary on every open.
  // ------------------------------------------------------------------
  $effect(() => {
    if (typeof document === 'undefined') return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  });

  // Focus the primary button each time the phase changes so keyboard
  // users always land on the right next step.
  $effect(() => {
    void phase;
    void tick().then(() => {
      primaryActionEl?.focus();
    });
  });

  // If we opened in `shared` state without a known `createdAt` (a
  // return visit — the parent only kept the token, not the timestamp),
  // pull the snapshot once so the "Captured ..." line can render.
  // We don't keep the rest of the response — only `created_at` is
  // needed here. Any failure is silently tolerated; the line is
  // ancillary and the modal is still functional without it.
  $effect(() => {
    if (phase !== 'shared') return;
    if (token === null) return;
    if (createdAt !== null) return;
    let cancelled = false;
    void shares
      .get(token)
      .then((snapshot) => {
        if (cancelled) return;
        createdAt = snapshot.created_at;
      })
      .catch(() => {
        /* ignore — line is optional. */
      });
    return () => {
      cancelled = true;
    };
  });

  // ------------------------------------------------------------------
  // Actions.
  // ------------------------------------------------------------------
  async function handleGenerate(): Promise<void> {
    if (inFlight) return;
    inFlight = true;
    try {
      const response = await shares.create(chat.id);
      token = response.token;
      createdAt = response.created_at;
      onShareChange?.(response.token);
      phase = 'shared';
    } catch (err) {
      toast.pushError(err instanceof ApiError ? err.message : String(err));
    } finally {
      inFlight = false;
    }
  }

  async function handleCopy(): Promise<void> {
    if (inFlight || absoluteUrl === null) return;
    inFlight = true;
    try {
      await navigator.clipboard.writeText(absoluteUrl);
      toast.pushSuccess('Link copied');
    } catch (err) {
      toast.pushError(err instanceof Error ? err.message : 'Failed to copy');
    } finally {
      inFlight = false;
    }
  }

  function requestStop(): void {
    if (inFlight) return;
    phase = 'stop-confirm';
  }

  function cancelStop(): void {
    if (inFlight) return;
    phase = 'shared';
  }

  async function handleStop(): Promise<void> {
    if (inFlight) return;
    inFlight = true;
    try {
      await shares.revoke(chat.id);
      token = null;
      createdAt = null;
      onShareChange?.(null);
      phase = 'not-shared';
    } catch (err) {
      toast.pushError(err instanceof ApiError ? err.message : String(err));
    } finally {
      inFlight = false;
    }
  }

  function handleClose(): void {
    if (inFlight) return;
    onClose();
  }

  // ------------------------------------------------------------------
  // Keyboard: Esc closes, Tab traps focus inside the modal.
  // ------------------------------------------------------------------
  const FOCUSABLE_SELECTOR =
    'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])';

  function handleKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      handleClose();
      return;
    }
    if (event.key !== 'Tab' || modalEl === null) return;
    const nodes = Array.from(modalEl.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
      (el) => !el.hasAttribute('aria-hidden'),
    );
    if (nodes.length === 0) return;
    const first = nodes[0]!;
    const last = nodes[nodes.length - 1]!;
    const active = document.activeElement as HTMLElement | null;
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function handleBackdropClick(event: MouseEvent): void {
    if (event.target !== event.currentTarget) return;
    handleClose();
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<!-- Backdrop: blurred translucent. `role="presentation"` so it's
     transparent to assistive tech (the dialog inside is what
     screen readers focus). Click-anywhere-outside dismiss is
     mouse-only; keyboard users use the Close button or Escape. -->
<div
  role="presentation"
  class="bg-background-app/70 fixed inset-0 z-40 flex items-center justify-center p-4 backdrop-blur-sm"
  onclick={handleBackdropClick}
>
  <div
    bind:this={modalEl}
    role="dialog"
    aria-modal="true"
    aria-labelledby={labelId}
    class="bg-background-app/95 border-hairline text-ink-body w-full max-w-md rounded-4xl border p-7 text-start shadow-2xl backdrop-blur-md"
  >
    <header class="mb-4 flex items-start justify-between gap-3">
      <h2 id={labelId} class="text-ink-strong text-base font-medium">Share this chat</h2>
      <button
        type="button"
        onclick={handleClose}
        disabled={inFlight}
        aria-label="Close"
        class="text-ink-muted hover:text-ink-strong motion-safe:ease-out-quart -me-1 -mt-1 inline-flex h-7 w-7 items-center justify-center rounded-full disabled:opacity-40 motion-safe:transition-colors motion-safe:duration-150"
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          aria-hidden="true"
        >
          <path d="m4 4 8 8M12 4l-8 8" />
        </svg>
      </button>
    </header>

    {#if phase === 'not-shared'}
      <p class="text-ink-muted text-sm leading-relaxed">
        Sharing creates a snapshot at this moment in time. To share later edits, click Stop sharing
        and Generate a new link.
      </p>
      <div class="mt-6 flex items-center justify-end gap-2">
        <button
          type="button"
          onclick={handleClose}
          disabled={inFlight}
          class="text-ink-secondary hover:text-ink-strong motion-safe:ease-out-quart inline-flex h-9 items-center rounded-3xl px-4 text-sm font-medium disabled:opacity-40 motion-safe:transition-colors motion-safe:duration-150"
        >
          Cancel
        </button>
        <button
          bind:this={primaryActionEl}
          type="button"
          onclick={handleGenerate}
          disabled={inFlight}
          class="bg-ink-strong text-background-app hover:bg-ink-body motion-safe:ease-out-quart inline-flex h-9 items-center rounded-3xl px-4 text-sm font-medium disabled:opacity-40 motion-safe:transition-colors motion-safe:duration-150"
        >
          {inFlight ? 'Generating…' : 'Generate share link'}
        </button>
      </div>
    {:else if phase === 'shared'}
      <p class="text-ink-muted text-sm leading-relaxed">
        Anyone signed in to Canva who opens this link will see the conversation as it stands now.
      </p>

      <label class="mt-5 block">
        <span class="text-ink-muted tracking-label sr-only text-xs font-medium uppercase"
          >Share link</span
        >
        <div
          class="bg-background-elevated border-hairline mt-1 flex items-stretch rounded-2xl border"
        >
          <input
            type="text"
            readonly
            value={absoluteUrl ?? ''}
            class="text-ink-body min-w-0 flex-1 truncate bg-transparent px-3 py-2 font-mono text-xs outline-none"
            aria-label="Share link"
          />
          <button
            bind:this={primaryActionEl}
            type="button"
            onclick={handleCopy}
            disabled={inFlight}
            class="text-ink-secondary hover:text-ink-strong border-hairline motion-safe:ease-out-quart inline-flex items-center gap-1.5 border-s px-3 py-2 text-xs font-medium disabled:opacity-40 motion-safe:transition-colors motion-safe:duration-150"
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              stroke-width="1.5"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <rect x="5" y="5" width="9" height="9" rx="1.5" />
              <path
                d="M11 5V3.5A1.5 1.5 0 0 0 9.5 2H3.5A1.5 1.5 0 0 0 2 3.5v6A1.5 1.5 0 0 0 3.5 11H5"
              />
            </svg>
            {inFlight ? 'Copying…' : 'Copy link'}
          </button>
        </div>
      </label>

      {#if capturedLabel !== null}
        <p class="text-ink-muted mt-3 text-xs">{capturedLabel}</p>
      {/if}

      <div class="mt-6 flex items-center justify-between gap-3">
        <button
          type="button"
          onclick={requestStop}
          disabled={inFlight}
          class="text-status-danger hover:text-status-danger motion-safe:ease-out-quart inline-flex h-9 items-center rounded-3xl px-4 text-sm font-medium disabled:opacity-40 motion-safe:transition-colors motion-safe:duration-150"
        >
          Stop sharing
        </button>
        <button
          type="button"
          onclick={handleClose}
          disabled={inFlight}
          class="bg-ink-strong text-background-app hover:bg-ink-body motion-safe:ease-out-quart inline-flex h-9 items-center rounded-3xl px-4 text-sm font-medium disabled:opacity-40 motion-safe:transition-colors motion-safe:duration-150"
        >
          Done
        </button>
      </div>
    {:else}
      <!-- stop-confirm: inline confirmation, never window.confirm. -->
      <p class="text-ink-body text-sm leading-relaxed">
        Stop sharing? The current link will stop working immediately.
      </p>
      <div class="mt-6 flex items-center justify-end gap-2">
        <button
          type="button"
          onclick={cancelStop}
          disabled={inFlight}
          class="text-ink-secondary hover:text-ink-strong motion-safe:ease-out-quart inline-flex h-9 items-center rounded-3xl px-4 text-sm font-medium disabled:opacity-40 motion-safe:transition-colors motion-safe:duration-150"
        >
          Cancel
        </button>
        <button
          bind:this={primaryActionEl}
          type="button"
          onclick={handleStop}
          disabled={inFlight}
          class="bg-status-danger text-paper-white hover:bg-status-danger/90 motion-safe:ease-out-quart inline-flex h-9 items-center rounded-3xl px-4 text-sm font-medium disabled:opacity-40 motion-safe:transition-colors motion-safe:duration-150"
        >
          {inFlight ? 'Stopping…' : 'Stop sharing'}
        </button>
      </div>
    {/if}
  </div>
</div>
