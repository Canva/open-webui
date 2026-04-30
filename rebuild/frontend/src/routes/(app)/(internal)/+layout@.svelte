<script lang="ts">
  /**
   * Internal route-group layout for the M1 smoke / visual-regression
   * pages. Filename uses the SvelteKit `@` reset (`+layout@.svelte`,
   * see `rebuild/docs/best-practises/sveltekit-best-practises.md`
   * § 1.4 "Route groups and layout breakouts") so the parent
   * `(app)/+layout.svelte` chrome (the M0 identity demo, soon the
   * Phase 3d chat shell) does NOT wrap children. Without the reset,
   * Svelte nests this layout inside the parent's markup and the
   * smoke screenshots would diff against the wrong chrome.
   *
   * Important: the `@` reset detaches this branch from the parent
   * server-load chain too, not just from the parent layout markup.
   * `parent()` from a `(internal)/+layout.server.ts` returns `{}`
   * instead of the (app) layout's data. The sibling
   * `(internal)/+layout.server.ts` therefore reads `event.locals`
   * directly (the same shape `(app)/+layout.server.ts` exposes,
   * mirroring the `(public)` route-group pattern). The auth gate
   * (`event.locals.user` populated from `X-Forwarded-Email` by
   * `src/hooks.server.ts`) is still in force on every request.
   *
   * The `ThemeStore` setup mirrors `(public)/+layout.svelte` (the
   * established prior art for an isolated route-group shell that
   * still needs theme context). Smoke components call
   * `getContext<ThemeStore>(THEME_CONTEXT_KEY)`, so the context must
   * exist; the `(app)` parent's `setContext` does not reach this
   * subtree because of the `@` reset.
   *
   * The `matchMedia` $effect from `(app)/+layout.svelte` and
   * `(public)/+layout.svelte` is intentionally omitted: smoke routes
   * are pinned to a deterministic `theme` cookie by the Playwright
   * visual runner (see `tests/e2e/visual-m1.spec.ts` `setupForPreset`),
   * so reactive OS-preference handling adds no value here and would
   * widen the surface for non-deterministic pixel diffs. Real-user
   * navigation to these routes is rare enough (they are "internal
   * pipeline smoke surfaces, not public chrome", per
   * `rebuild/docs/plans/m2-conversations.md` § Deliverables) that
   * skipping the OS sync is the right trade.
   */
  import { setContext, untrack } from 'svelte';
  import type { Snippet } from 'svelte';
  import { ThemeStore, THEME_CONTEXT_KEY } from '$lib/stores/theme.svelte';
  import type { LayoutData } from './$types';

  let { data, children }: { data: LayoutData; children: Snippet } = $props();

  // Snapshot the server-resolved theme on construction; the visual
  // runner sets the `theme` cookie before navigation, so `data.theme`
  // is the only signal we need. `untrack` matches the parent layout's
  // pattern and silences `svelte/state_referenced_locally` without an
  // explicit ignore comment.
  const themeStore = untrack(
    () =>
      new ThemeStore({
        initial: data.theme,
        osDark: null,
        initialSource: data.themeSource === 'explicit' ? 'explicit' : undefined,
      }),
  );
  setContext(THEME_CONTEXT_KEY, themeStore);
</script>

{@render children()}
