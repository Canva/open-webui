<script lang="ts">
  /**
   * Authenticated app shell. Constructs the per-request `ThemeStore`
   * and exposes it via `setContext('theme', store)` per the
   * cross-cutting frontend conventions in
   * `rebuild/docs/plans/m0-foundations.md` § Frontend conventions.
   *
   * Visible chrome: the M0 identity demo (header + identity card +
   * data.user JSON dump). M2 replaces the demo with the real chat
   * shell; this layout's responsibility is the theme context, the
   * matchMedia $effect, and the agent-workshop navigation chrome.
   */
  import { setContext, untrack } from 'svelte';
  import type { Snippet } from 'svelte';
  import { resolveTheme } from '$lib/theme/presets';
  import { ThemeStore, THEME_CONTEXT_KEY } from '$lib/stores/theme.svelte';
  import type { LayoutData } from './$types';

  let { data, children }: { data: LayoutData; children: Snippet } = $props();

  // Construction captures the initial server-resolved theme on purpose;
  // the matchMedia $effect below handles in-tree changes to the OS
  // preference, and explicit user changes go through `themeStore.setTheme`.
  // `untrack` makes the "we genuinely want the snapshot" intent explicit
  // and silences svelte/state_referenced_locally without a noisy ignore.
  const themeStore = untrack(
    () =>
      new ThemeStore({
        initial: data.theme,
        osDark: null,
        initialSource: data.themeSource === 'explicit' ? 'explicit' : undefined,
      }),
  );
  setContext(THEME_CONTEXT_KEY, themeStore);

  const userJson = $derived(JSON.stringify(data.user, null, 2));

  // Sync OS preference to the store after hydration. Runs on every
  // `prefers-color-scheme` change for the lifetime of the layout. The
  // store ignores the new value when the user has an explicit choice
  // (its `setOsDark` short-circuits in that case), so this effect is
  // safe to run unconditionally.
  //
  // The store mutations are wrapped in `untrack` so this effect only
  // depends on its real inputs (`data.theme`, `data.themeSource`,
  // `mql.matches`) — the store's `_explicit` and `current` $state.raw
  // fields are read inside `setOsDark`/`setTheme`, and tracking those
  // would trip Svelte's effect_update_depth_exceeded guard the moment
  // we mutate them in the same pass.
  $effect(() => {
    if (typeof window === 'undefined') return;
    const mql = window.matchMedia('(prefers-color-scheme: dark)');
    untrack(() => {
      themeStore.setOsDark(mql.matches);
      if (data.themeSource !== 'explicit') {
        const next = resolveTheme({ explicit: data.theme, osDark: mql.matches });
        themeStore.setTheme(next, { persist: false });
      }
    });
    const onChange = (e: MediaQueryListEvent) => untrack(() => themeStore.setOsDark(e.matches));
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  });
</script>

<div class="mx-auto flex min-h-svh w-full max-w-2xl flex-col gap-10 px-6 py-16">
  <header class="space-y-3">
    <!--
      Interim discoverability for the M1 ThemePicker route. The (app)
      layout still ships the M0 identity demo with no nav chrome; this
      single link is the only entry point into `/settings` until M2
      lands the real shell. Drop this row when M2's nav appears.
    -->
    <div class="flex items-baseline justify-between gap-4">
      <p class="text-accent-mention tracking-label text-xs font-medium uppercase">
        M0 / Foundations
      </p>
      {#if data.user}
        <a
          href="/settings"
          class="text-ink-muted motion-safe:ease-out-quart motion-safe:hover:text-ink-strong text-xs font-medium motion-safe:transition-colors motion-safe:duration-150"
          >Settings →</a
        >
      {/if}
    </div>
    <h1 class="font-display text-ink-strong tracking-headline text-xl/[1.25] font-semibold">
      The workshop is wired.
    </h1>
    <p class="text-ink-secondary max-w-prose text-sm/[1.5]">
      Trusted-header authentication round-trips against the FastAPI backend. Theming arrives with
      M1; the chat shell, channels, and automations arrive with M2 through M5; observability and
      deploy land in M6.
    </p>
  </header>

  <section class="border-hairline bg-background-elevated rounded-2xl border p-6">
    <p class="text-ink-muted tracking-label text-xs font-medium uppercase">Identity</p>
    {#if data.user}
      <p class="text-ink-strong mt-3 text-sm/[1.5]">
        Signed in as <span class="font-medium">{data.user.email}</span>
      </p>
      <p class="text-ink-muted mt-1 text-xs">
        {data.user.name} · {data.user.timezone}
      </p>
    {:else}
      <p class="text-ink-strong mt-3 text-sm/[1.5] font-medium">No proxy header on this request.</p>
      <p class="text-ink-muted mt-2 text-sm/[1.5]">
        Set <code class="font-mono text-xs">X-Forwarded-Email</code> at the edge, or pass
        <code class="font-mono text-xs">-H 'X-Forwarded-Email: you@canva.com'</code> to curl, to
        populate <code class="font-mono text-xs">event.locals.user</code>.
      </p>
    {/if}
  </section>

  <section class="space-y-2">
    <p class="text-ink-muted tracking-label text-xs font-medium uppercase">data.user</p>
    <pre
      class="border-hairline bg-background-code text-ink-strong overflow-x-auto rounded-xl border p-4 font-mono text-xs leading-relaxed">{userJson}</pre>
  </section>

  {@render children()}
</div>
