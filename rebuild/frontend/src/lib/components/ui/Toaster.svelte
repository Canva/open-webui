<script lang="ts">
  /**
   * Toast queue surface. Renders the items from `useToast()` as a
   * floating column pinned to the bottom-end of the viewport. Owns the
   * auto-dismiss timer per the `ToastStore` contract — the store stays
   * synchronous and SSR-safe; this component schedules the
   * `setTimeout` via `$effect` so the cleanup fires on every dismiss
   * and on unmount (per `rebuild/docs/best-practises/svelte-best-practises.md`
   * § 3.3 and § 12).
   *
   * Auto-dismiss after 5000ms. Timers are tracked in a per-toast map
   * so manual dismiss cancels the pending timeout cleanly. The
   * `bottom-end` placement uses logical positioning so RTL surfaces
   * keep the toast in the same physical corner relative to the user's
   * reading direction.
   */
  import { useToast, type Toast } from '$lib/stores/toast.svelte';

  const toast = useToast();

  const DISMISS_AFTER_MS = 5000;

  // The effect tracks `toast.items` (deep `$state`) so a push starts a
  // new timer and a dismiss / unmount tears it down. The cleanup runs
  // on every re-execution as well as on unmount, which is correct: any
  // toast that survived the previous run keeps its timer (the
  // identity-stable `id` lets us look it up next iteration).
  $effect(() => {
    const timers = new Map<string, ReturnType<typeof setTimeout>>();
    for (const item of toast.items) {
      if (timers.has(item.id)) continue;
      const remaining = Math.max(0, DISMISS_AFTER_MS - (Date.now() - item.created));
      const handle = setTimeout(() => toast.dismiss(item.id), remaining);
      timers.set(item.id, handle);
    }
    return () => {
      for (const handle of timers.values()) clearTimeout(handle);
    };
  });

  function levelClass(level: Toast['level']): string {
    switch (level) {
      case 'success':
        return 'text-status-success';
      case 'warning':
        return 'text-status-warning';
      case 'danger':
        return 'text-status-danger';
      case 'info':
      default:
        return 'text-ink-strong';
    }
  }
</script>

<div
  class="pointer-events-none fixed end-4 bottom-4 z-50 flex w-full max-w-sm flex-col gap-2"
  aria-live="polite"
  aria-relevant="additions text"
  role="region"
>
  {#each toast.items as item (item.id)}
    <div
      class="border-hairline bg-background-elevated text-ink-body pointer-events-auto flex items-start gap-3 rounded-2xl border px-4 py-3 shadow-lg motion-safe:transition-opacity motion-safe:duration-150"
      role="status"
    >
      <p class="flex-1 text-sm leading-snug {levelClass(item.level)}">{item.message}</p>
      <button
        type="button"
        class="text-ink-muted hover:text-ink-strong tracking-label motion-safe:ease-out-quart -me-1 -mt-0.5 text-xs font-medium uppercase motion-safe:transition-colors motion-safe:duration-150"
        onclick={() => toast.dismiss(item.id)}
        aria-label="Dismiss"
      >
        Close
      </button>
    </div>
  {/each}
</div>
