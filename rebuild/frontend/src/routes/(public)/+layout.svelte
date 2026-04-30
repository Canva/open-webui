<script lang="ts">
  /**
   * Public-route shell. Constructs the same per-request `ThemeStore`
   * the (app) layout does so M3's share view inherits the active
   * theme via the cookie path. No identity chrome — the public layout
   * has no nav, no header, no auth gate.
   */
  import { setContext, untrack } from 'svelte';
  import type { Snippet } from 'svelte';
  import { resolveTheme } from '$lib/theme/presets';
  import { ThemeStore, THEME_CONTEXT_KEY } from '$lib/stores/theme.svelte';
  import type { LayoutData } from './$types';

  let { data, children }: { data: LayoutData; children: Snippet } = $props();

  const themeStore = untrack(
    () =>
      new ThemeStore({
        initial: data.theme,
        osDark: null,
        initialSource: data.themeSource === 'explicit' ? 'explicit' : undefined,
      }),
  );
  setContext(THEME_CONTEXT_KEY, themeStore);

  // Mutations wrapped in `untrack` so this effect doesn't track the
  // store's internal `$state.raw` fields and re-fire on every write.
  // See `(app)/+layout.svelte` for the long-form rationale.
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

{@render children()}
