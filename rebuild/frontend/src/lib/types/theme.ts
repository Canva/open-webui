/**
 * Public theme type surface. Re-exports from `$lib/theme/presets.ts` so
 * downstream consumers (the store, the picker, server hooks, tests) do not
 * have to reach into the preset catalog directly.
 *
 * The contract is locked by `rebuild/docs/plans/m1-theming.md` § Resolution
 * order: there are exactly four shipping presets, identified by stable string
 * ids. Anything that accepts user input MUST narrow to `ThemeId` via
 * `THEME_IDS.includes(...)` before trusting it.
 */
export type { ThemeId, ThemePreset, ThemeSource } from '$lib/theme/presets';
export { THEME_IDS, THEME_PRESETS } from '$lib/theme/presets';
