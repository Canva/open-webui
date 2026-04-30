<script lang="ts">
  /**
   * Authenticated chat shell. Replaces the M0 identity demo with the
   * real chrome: a persistent sidebar (chats + folders + workspace
   * actions) on the inline-start, the active conversation surface on
   * the inline-end, the global toaster pinned to the bottom-end.
   *
   * Construction site for every M2 store. Pinned by
   * `rebuild/docs/plans/m2-conversations.md` § Stores and state (lines
   * 1003-1019) and `rebuild/docs/plans/m0-foundations.md` § Frontend
   * conventions (cross-cutting): one class per store, instances
   * provided via `setContext` per request, no module-level `$state`.
   *
   * The M1 ThemeStore wiring is preserved verbatim (per the dispatch
   * spec): the matchMedia $effect listens for OS preference changes
   * and re-resolves the theme without persisting unless the user has
   * an explicit choice.
   *
   * The smoke routes under `(app)/(internal)/` use a `+layout@.svelte`
   * reset to escape this layout (see
   * `rebuild/docs/best-practises/sveltekit-best-practises.md` § 1.4)
   * so the visual baselines do not pick up any sidebar chrome.
   */
  import { setContext, untrack } from 'svelte';
  import type { Snippet } from 'svelte';

  import { provideActiveChat } from '$lib/stores/active-chat.svelte';
  import { provideChats } from '$lib/stores/chats.svelte';
  import { provideFolders } from '$lib/stores/folders.svelte';
  import { provideModels } from '$lib/stores/models.svelte';
  import { provideToast } from '$lib/stores/toast.svelte';
  import { THEME_CONTEXT_KEY, ThemeStore } from '$lib/stores/theme.svelte';
  import { resolveTheme } from '$lib/theme/presets';
  import Sidebar from '$lib/components/chat/Sidebar.svelte';
  import Toaster from '$lib/components/ui/Toaster.svelte';
  import { afterNavigate } from '$app/navigation';
  import type { LayoutData } from './$types';

  let { data, children }: { data: LayoutData; children: Snippet } = $props();

  /**
   * Below `md` (768px) the sidebar collapses to a slide-in drawer
   * (DESIGN.md § Components > Navigation: "Mobile treatment: Sidebar
   * becomes a drawer"). At wider viewports the drawer state is
   * irrelevant — the sidebar is always visible in the grid column.
   * Default closed so the conversation view owns first paint on
   * narrow screens.
   */
  let drawerOpen = $state(false);

  // Close the drawer on every client navigation so a chat tap doesn't
  // leave it stuck open on top of the new conversation.
  afterNavigate(() => {
    drawerOpen = false;
  });

  // Stores are instance-scoped to this layout (one per request render
  // tree). `setContext` in `provide*()` makes them visible to any
  // descendant via `use*()`. `untrack` makes the "we want the snapshot
  // at construction time" intent explicit and silences
  // svelte/state_referenced_locally — the stores own the live state
  // from this point on, the `data` prop only seeds them.
  untrack(() => {
    provideChats(data.chats ?? null);
    provideFolders(data.folders ?? []);
    provideModels(data.models ?? []);
    provideActiveChat();
    provideToast();
  });

  // M1 ThemeStore wiring — copied verbatim from the previous M0 layout
  // so the M1 theme picker keeps working across the M2 layout swap.
  // `untrack` makes the "we genuinely want the snapshot" intent
  // explicit and silences svelte/state_referenced_locally without a
  // noisy ignore comment.
  const themeStore = untrack(
    () =>
      new ThemeStore({
        initial: data.theme,
        osDark: null,
        initialSource: data.themeSource === 'explicit' ? 'explicit' : undefined,
      }),
  );
  setContext(THEME_CONTEXT_KEY, themeStore);

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

{#if data.user === null}
  <!--
    Trusted-header gate failed (no `X-Forwarded-Email` on the request).
    Render a minimal explanation so engineers hitting the dev server
    without the proxy see what's wrong instead of a blank shell.
    Acceptance bullets requiring authenticated chrome (sidebar, branch
    chevrons, etc) only fire when `data.user` is present.
  -->
  <div class="bg-background-app flex min-h-svh flex-col items-center justify-center gap-3 px-6">
    <p class="text-ink-muted tracking-label text-xs font-medium uppercase">
      Trusted-header auth required
    </p>
    <h1 class="text-ink-strong font-display text-xl font-semibold">
      No proxy header on this request.
    </h1>
    <p class="text-ink-secondary max-w-md text-center text-sm leading-relaxed">
      Set <code class="font-mono text-xs">X-Forwarded-Email</code> at the edge, or pass
      <code class="font-mono text-xs">-H 'X-Forwarded-Email: you@canva.com'</code> to curl, to
      populate
      <code class="font-mono text-xs">event.locals.user</code>.
    </p>
  </div>
{:else}
  <div
    class="bg-background-app text-ink-body relative grid h-svh w-full grid-cols-[minmax(0,1fr)] overflow-hidden md:grid-cols-[280px_minmax(0,1fr)]"
  >
    <aside
      data-open={drawerOpen}
      class="bg-background-sidebar border-hairline motion-safe:ease-out-quart fixed inset-y-0 start-0 z-30 w-[280px] -translate-x-full overflow-hidden border-e data-[open=true]:translate-x-0 motion-safe:transition-transform motion-safe:duration-200 md:static md:translate-x-0 rtl:translate-x-full rtl:data-[open=true]:translate-x-0 rtl:md:translate-x-0"
      aria-label="Workspace navigation"
    >
      <Sidebar onnavigate={() => (drawerOpen = false)} />
    </aside>
    <main class="relative min-w-0 overflow-hidden">
      <button
        type="button"
        class="text-ink-muted hover:bg-background-elevated hover:text-ink-strong border-hairline focus-visible:outline-accent-mention bg-background-app/80 absolute start-3 top-3 z-20 inline-flex h-8 w-8 items-center justify-center rounded-lg border backdrop-blur-sm focus-visible:outline-2 focus-visible:outline-offset-2 md:hidden"
        aria-label={drawerOpen ? 'Close navigation' : 'Open navigation'}
        aria-expanded={drawerOpen}
        onclick={() => (drawerOpen = !drawerOpen)}
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
          <path d="M2 4h12M2 8h12M2 12h12" />
        </svg>
      </button>
      {@render children()}
    </main>
    {#if drawerOpen}
      <button
        type="button"
        class="bg-ink-strong/30 fixed inset-0 z-20 backdrop-blur-sm md:hidden"
        aria-label="Close navigation"
        onclick={() => (drawerOpen = false)}
      ></button>
    {/if}
  </div>
{/if}

<Toaster />
