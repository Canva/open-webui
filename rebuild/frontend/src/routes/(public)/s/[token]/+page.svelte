<script lang="ts">
  /**
   * Public share view at `/s/{token}`. Renders a snapshot of someone
   * else's chat through the M2 message renderer in `readonly` mode.
   *
   * Locked by `rebuild/docs/plans/m3-sharing.md` § Frontend route:
   *   - Title + "Shared by {name} {relative time}" subline.
   *   - Body uses M2's `MessageList` + `Message` components in
   *     read-only mode (no composer, no regen, no model selector,
   *     no scroll-to-bottom-on-stream).
   *   - Max-width matches the conversation thread (`max-w-3xl`).
   *   - Long histories keep the M2 `content-visibility: auto`
   *     virtualisation behaviour because the renderer is unchanged
   *     in `readonly` mode.
   *   - On 404 (snapshot === null), render a minimal "no longer
   *     active" panel — terminal state, no affordances back into
   *     the app (the recipient may not have a workspace surface to
   *     navigate to).
   *
   * The route is mounted under the existing `(public)` route group
   * which already provides the theme-aware shell. We do NOT import
   * the theme store here.
   */
  import MessageList from '$lib/components/chat/MessageList.svelte';
  import { formatRelativeTime } from '$lib/utils/relative-time';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  const snapshot = $derived(data.snapshot);
  const sharedSubline = $derived.by<string | null>(() => {
    if (snapshot === null) return null;
    return `Shared by ${snapshot.shared_by.name}, ${formatRelativeTime(snapshot.created_at)}`;
  });
</script>

<svelte:head>
  {#if snapshot}
    <title>{snapshot.title} · Shared chat</title>
  {:else}
    <title>Shared chat unavailable</title>
  {/if}
</svelte:head>

<div class="bg-background-app text-ink-body min-h-svh">
  {#if snapshot === null}
    <!-- 404 panel. No affordances back into the app — recipient may not
         have an account surface to land on. Terminal state, calm tone. -->
    <main class="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 py-16">
      <div class="border-hairline bg-background-app/95 w-full rounded-3xl border p-8 text-center">
        <h1 class="text-ink-strong text-base font-medium">Shared chat unavailable</h1>
        <p class="text-ink-muted mt-2 text-sm leading-relaxed">
          This share link is no longer active.
        </p>
      </div>
    </main>
  {:else}
    <article class="mx-auto w-full max-w-3xl px-4 py-10 md:py-14">
      <header class="border-hairline mb-6 border-b pb-6">
        <h1 class="text-ink-strong font-display text-xl leading-tight font-semibold">
          {snapshot.title}
        </h1>
        {#if sharedSubline}
          <p class="text-ink-muted mt-1.5 text-xs">
            {sharedSubline}
          </p>
        {/if}
      </header>

      <!-- The renderer carries `content-visibility: auto` virtualisation
           via the existing thread layout (cf. M2 plan); read-only mode
           strips per-message edit / regen affordances and the branch
           chevrons but leaves the visual rhythm intact. -->
      <MessageList history={snapshot.history} readonly />
    </article>
  {/if}
</div>
