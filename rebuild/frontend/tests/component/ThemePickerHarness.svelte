<!--
  Harness for the M1 ThemePicker CT spec.

  The picker reads its store from `getContext(THEME_CONTEXT_KEY)` which
  the (app)/(public) layouts construct in production. Playwright CT's
  `mount(...)` cannot serialise a ThemeStore instance across the worker
  boundary, so this harness constructs the store inside the browser
  (after `mount` runs the script) and exposes it via setContext.

  Optional props:
    - initial: ThemeId        (defaults to 'tokyo-night')
    - initialSource: 'explicit' | undefined  (controls the picker's
      "Match system" reset button visibility on first paint)
    - osDark: boolean | null  (drives the resolved OS preference inside
      the store; `null` mirrors the server-construction case where the
      matchMedia $effect hasn't fired yet)

  The harness also stashes the store on `window.__themeStore` so tests
  that need to read the store's reactive state directly (e.g. `current`,
  `source`) can do so via `page.evaluate(...)` without scraping DOM.
-->
<script lang="ts">
  import { setContext, untrack } from 'svelte';
  import { ThemeStore, THEME_CONTEXT_KEY } from '$lib/stores/theme.svelte';
  import type { ThemeId } from '$lib/theme/presets';
  import ThemePicker from '$lib/components/settings/ThemePicker.svelte';

  interface Props {
    initial?: ThemeId;
    initialSource?: 'explicit';
    osDark?: boolean | null;
  }

  let { initial = 'tokyo-night', initialSource, osDark = null }: Props = $props();

  // Snapshot the $props at construction time. The harness intentionally
  // captures-on-mount (the picker is the unit under test, not the
  // harness's prop reactivity); `untrack` makes the snapshot semantics
  // explicit and silences `svelte/state_referenced_locally`.
  // Mirror of the production `(app)/+layout.svelte` pattern.
  const initialSnapshot: ThemeId = untrack(() => initial);
  const osDarkSnapshot: boolean | null = untrack(() => osDark);
  const initialSourceSnapshot: 'explicit' | undefined = untrack(() => initialSource);

  // Apply the initial theme to documentElement BEFORE constructing the
  // store. The store's matchMedia $effect-driven setOsDark fires later,
  // but the picker's tile-swatch cascade reads `data-theme` synchronously
  // on render — getting it on the html element first means the very
  // first paint already shows the right tokens.
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = initialSnapshot;
  }

  const store = new ThemeStore({
    initial: initialSnapshot,
    osDark: osDarkSnapshot,
    initialSource: initialSourceSnapshot,
  });
  setContext(THEME_CONTEXT_KEY, store);

  // Expose the store on window so the spec can introspect reactive
  // state directly (current, source) without scraping DOM. Cast through
  // `unknown` to avoid leaking the store type into the production
  // global namespace.
  if (typeof window !== 'undefined') {
    (window as unknown as { __themeStore: ThemeStore }).__themeStore = store;
  }
</script>

<ThemePicker />
