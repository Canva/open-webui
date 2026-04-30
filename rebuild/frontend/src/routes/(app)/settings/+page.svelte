<script lang="ts">
  /**
   * Settings · Appearance.
   *
   * The single Settings surface M1 ships. Mounts the `ThemePicker`
   * under an `Appearance` section header. M2+ extend this route with
   * additional sections (display name, default model, ...) by adding
   * sibling `<section>` blocks below.
   *
   * Auth-gated explicitly: the route lives under `(app)/`, but the
   * (app) layout currently renders the M0 identity demo above
   * `{@render children()}` without conditionally hiding children for
   * unauthenticated requests. This page therefore short-circuits its
   * own render with `if (data.user)` per the M1 dispatch — when the
   * trusted proxy header is missing, the layout's "no proxy header"
   * empty state already explains the situation, and the Settings
   * surface stays empty.
   */
  import ThemePicker from '$lib/components/settings/ThemePicker.svelte';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();
</script>

<svelte:head>
  <title>Settings · Open WebUI</title>
</svelte:head>

{#if data.user}
  <div class="flex flex-col gap-10">
    <header class="space-y-2">
      <h1 class="font-display text-ink-strong tracking-headline text-xl/[1.25] font-semibold">
        Settings
      </h1>
      <p class="text-ink-secondary text-sm/[1.5]">Personalize how the workshop looks.</p>
    </header>

    <section class="space-y-3">
      <div class="space-y-1">
        <h2 class="text-ink-strong text-sm font-medium">Appearance</h2>
        <p class="text-ink-muted text-xs/[1.5]">
          Pick a Tokyo Night room. Your choice lives in this browser only, never on the server.
        </p>
      </div>
      <ThemePicker />
    </section>
  </div>
{/if}
