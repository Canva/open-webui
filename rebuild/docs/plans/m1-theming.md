# M1 — Theming

> Milestone 1 of the Open WebUI slim rebuild. Reference the top-level plan at [rebuild.md](../../../rebuild.md). The brand voice is locked in [PRODUCT.md](../../../PRODUCT.md); the design tokens, role-token vocabulary, and the four shipping preset palettes are locked in [DESIGN.md](../../../DESIGN.md). This document only fills in the implementation detail.

## Goal

Land the brand canon as a working theme system before any product feature ships. Deliver four Tokyo Night presets — **Tokyo Day**, **Tokyo Storm**, **Tokyo Moon**, **Tokyo Night** — every component renders against the same role-based CSS variable tokens (`background-app`, `accent-selection`, `ink-body`, `syntax-keyword`, …), the active preset binds the tokens, and switching is instant. The page-load default honours `prefers-color-scheme` (`light` → Day, `dark` → Night). The user's explicit choice always wins, persists per browser via a `theme` cookie + `localStorage` mirror, and never reaches MySQL on any code path. The Shiki code-block highlighter and the Mermaid diagram theme are generated from the same tokens so chrome and content swap together. By the end of M1 a Canva employee lands on the empty FastAPI `/api/me` shell, sees the OS-mapped preset on first paint with no FOUC, opens Settings (or hits `Cmd-K → Theme: Tokyo Storm`), picks Storm, reloads, and sees Storm — and all of M2–M6 build directly against the role-token vocabulary M1 ships.

This milestone is **frontend-only**. Zero backend code changes. Zero Alembic revision. Zero new env vars on `Settings`. The only thing the SvelteKit `handle` hook touches that the M0 hook didn't is one cookie read.

## Deliverables

- A four-preset palette catalog at [rebuild/frontend/src/lib/theme/presets.ts](../../frontend/src/lib/theme/presets.ts) — one TypeScript module exporting a `ThemePreset` type, a `THEME_PRESETS: Record<ThemeId, ThemePreset>` constant containing **Tokyo Day**, **Tokyo Storm**, **Tokyo Moon**, **Tokyo Night**, and a `THEME_IDS` array (`["tokyo-day", "tokyo-storm", "tokyo-moon", "tokyo-night"]`) used as the canonical iteration order in the picker, the cookie validator, and the visual-regression matrix. Each preset is a flat object keyed by role-token name (`backgroundApp`, `backgroundSidebar`, `accentSelection`, `inkBody`, `syntaxKeyword`, …) with OKLCH string values; the literal hex equivalents from [DESIGN.md § colors](../../../DESIGN.md) are commented inline next to each value for the visual-regression authoring loop.
- The CSS variable bindings at [rebuild/frontend/src/lib/theme/tokens.css](../../frontend/src/lib/theme/tokens.css) — one `[data-theme="tokyo-{id}"]` block per preset, each declaring every role token as a `--` custom property. The selector is intentionally unprefixed (`[data-theme=…]`, **not** `:root[data-theme=…]`) so that any nested element carrying its own `data-theme` attribute overrides the role tokens for that subtree — the M1 `ThemePicker` relies on this so each preview tile cascades to its OWN preset regardless of the page-level `<html data-theme>`. Page-level theming still works the same way: Tailwind 4's `@theme inline { --color-x: var(--x); }` block in `app.css` resolves the runtime variable via the cascade, so `<html data-theme="tokyo-night">` paints the chrome correctly. Imported once from [rebuild/frontend/src/app.css](../../frontend/src/app.css) and consumed by Tailwind 4 via `@theme inline { … }` so utility classes like `bg-background-app` / `text-ink-body` / `border-hairline` resolve through the variables.
- A theme runes-class store at [rebuild/frontend/src/lib/stores/theme.svelte.ts](../../frontend/src/lib/stores/theme.svelte.ts) — exports `class ThemeStore` with `current: ThemeId` (`$state.raw`), `source: "explicit" | "os" | "default"` (read-only `$derived`), `setTheme(id, { persist?: boolean }): void`, `clearChoice(): void`, and `presets: readonly ThemePreset[]`. Constructed once in `(app)/+layout.svelte` and the public `(public)/+layout.svelte` and provided via `setContext('theme', store)` per the cross-cutting frontend conventions in [m0-foundations.md § Frontend conventions (cross-cutting)](m0-foundations.md#frontend-conventions-cross-cutting). Module-level `$state` is banned (per-user data → SSR leak); the store instance lives on the request-scoped context only.
- The SSR cookie path at [rebuild/frontend/src/hooks.server.ts](../../frontend/src/hooks.server.ts) — extends the M0 `handle` hook to read `cookies.get("theme")`, validate against `THEME_IDS`, store on `event.locals.theme` (typed via `App.Locals` in [src/app.d.ts](../../frontend/src/app.d.ts)), and emit it on `<html data-theme="…">` via `transformPageChunk` so first paint is correct without JS.
- The pre-hydration boot script at [rebuild/frontend/src/lib/theme/boot.ts](../../frontend/src/lib/theme/boot.ts) — a stringified IIFE inlined into [rebuild/frontend/src/app.html](../../frontend/src/app.html) inside `<head>` **before** `%sveltekit.head%` (not inside it). Placement matters: `%sveltekit.head%` expands to SvelteKit's own preload `<link>` tags and module imports; sitting in front of that placeholder means the IIFE executes before any SvelteKit JS parses, so `<html data-theme>` is final by the time hydration begins and the preload race cannot defeat the FOUC contract. The script reads `localStorage.getItem("theme")` (preferred) → cookie (fallback) → `matchMedia("(prefers-color-scheme: dark)")` (fallback) → `"tokyo-night"` (final fallback), and sets `document.documentElement.dataset.theme` accordingly. The same module is unit-tested as a pure function so the inlined string is verifiable.
- The cookie writer / localStorage mirror at [rebuild/frontend/src/lib/theme/persistence.ts](../../frontend/src/lib/theme/persistence.ts) — `writeChoice(id: ThemeId): void` writes both the cookie (1-year `Max-Age`, `Path=/`, `SameSite=Lax`; `Secure` flag derived from `location.protocol === "https:"` so dev `http://localhost:5173` is unaffected and every non-dev environment gets `Secure` automatically with no env-var plumbing) and `localStorage`. Plus `clearChoice(): void` deletes both. The two writes happen in the same call so they cannot drift.
- The Shiki theme generator at [rebuild/frontend/src/lib/theme/shiki.ts](../../frontend/src/lib/theme/shiki.ts) — exports `buildShikiTheme(preset: ThemePreset): ShikiTheme` returning a Shiki theme object whose `colors.editor.background` is `preset.backgroundCode`, `tokenColors[*].settings.foreground` map to the `syntaxKeyword` / `syntaxString` / `syntaxFunction` / `syntaxNumber` / `syntaxComment` / `syntaxTag` tokens, and `name` is `tokyo-{id}`. Wired into the [rebuild/frontend/src/lib/markdown/codeblock.ts](../../frontend/src/lib/markdown/codeblock.ts) module that M2 stands up — for M1 we ship a smoke component that renders one fenced block per preset to exercise the pipeline.
- The Mermaid theme generator at [rebuild/frontend/src/lib/theme/mermaid.ts](../../frontend/src/lib/theme/mermaid.ts) — exports `buildMermaidThemeVariables(preset: ThemePreset): Record<string, string>` returning the Mermaid `themeVariables` block (`primaryColor` → `accent-selection`, `lineColor` → `hairline-strong`, `textColor` → `ink-body`, `mainBkg` → `background-elevated`, `secondaryColor` → `background-sidebar`, `tertiaryColor` → `background-topbar`). Re-applied on every preset switch via the `ThemeStore` subscriber so visible diagrams re-render.
- A theme picker UI at [rebuild/frontend/src/lib/components/settings/ThemePicker.svelte](../../frontend/src/lib/components/settings/ThemePicker.svelte) — a 2×2 grid of preview tiles (one per preset), each tile showing a 160×100px miniature of that preset's surface ramp + accent palette. The active preset is outlined in `accent-selection`. Click → `themeStore.setTheme(id)`; tiles are real `<button>` elements with proper `aria-pressed` for keyboard / screen-reader users. A "Match system" reset button at the bottom calls `themeStore.clearChoice()` and re-resolves to the OS preference; the reset surfaces only when the user has made an explicit pick (`themeStore.source === 'explicit'`). When the active theme is OS-resolved (or the brand-canonical fallback) the button is hidden because there is nothing to clear, and the absence of the button is itself the "you are tracking the OS" signifier — a button that does nothing in its current state is the UX papercut [DESIGN.md](../../../DESIGN.md) calls out as decorative-only chrome. Switching is **instant** — no transition — so the user reads the change as deliberate.
- A command-palette entry that exposes the same picker as `Theme: Tokyo Day | Storm | Moon | Night | Match system` (added via the M0 command palette stub; if the palette is not yet wired in M0, this deliverable is descoped to a `Cmd-K`-shaped TODO in the picker's docstring). Owns the same store action; no separate code path.
- A first-class `<Settings>` route at [rebuild/frontend/src/routes/(app)/settings/+page.svelte](../../frontend/src/routes/(app)/settings/+page.svelte) that mounts the picker. The route is gated behind the M0 trusted-header auth (it lives under `(app)/`, which already uses the M0 `getUser` server load). M2+ extend this route with their own settings sections (display name, default model, …).
- A `(public)/+layout.svelte` shell that also reads from the same store, so the M3 share view inherits the active theme via the cookie path. Public-route theming is implicit — the cookie is set browser-wide, so a recipient of a share link who has Tokyo Storm picked sees the share view in Storm.
- Backend negative test at [rebuild/backend/tests/integration/test_theming_no_db.py](../../backend/tests/integration/test_theming_no_db.py) — two complementary assertions: (1) wires SQLAlchemy's `before_cursor_execute` event onto the M0 async engine, captures every SQL statement issued during a single `GET /api/me` request, and asserts the touched-table set contains only the M0 `user` upsert/select; (2) introspects `app.routes` and asserts no FastAPI route's path or handler-function name matches `r"theme"` (case-insensitive). The two together are equivalent to "no SQL flows during the picker round-trip" — the picker only ever calls `/api/me`, and the FastAPI app exposes no theme endpoint. Locks the "no DB persistence" decision at the integration layer, not just by convention.
- Frontend unit tests at [rebuild/frontend/tests/unit/theme/](../../frontend/tests/unit/theme/) covering `presets`, `boot`, `persistence`, `shiki`, `mermaid`, and the resolution-order helper.
- Component test at [rebuild/frontend/tests/component/theme-picker.spec.ts](../../frontend/tests/component/theme-picker.spec.ts) driving the picker through all four presets + the "Match system" reset, asserting `document.documentElement.dataset.theme` updates and the cookie + localStorage write happens in the same tick.
- E2E tests at [rebuild/frontend/tests/e2e/theme-fouc.spec.ts](../../frontend/tests/e2e/theme-fouc.spec.ts), [tests/e2e/theme-os-default.spec.ts](../../frontend/tests/e2e/theme-os-default.spec.ts), [tests/e2e/theme-explicit-persists.spec.ts](../../frontend/tests/e2e/theme-explicit-persists.spec.ts), [tests/e2e/theme-cross-tab.spec.ts](../../frontend/tests/e2e/theme-cross-tab.spec.ts).
- Visual-regression baselines at [rebuild/frontend/tests/visual-baselines/m1/](../../frontend/tests/visual-baselines/m1/) (Git LFS): one baseline per preset for `chat-empty-{preset}`, `sidebar-{preset}`, `theme-picker-{preset}` — twelve images total. The smoke fenced-codeblock + smoke mermaid surfaces add three more (`code-block-{tokyo-night}`, `mermaid-{tokyo-night}`, `theme-picker-collapsed-{tokyo-night}`), captured against `tokyo-night` only, because the chrome screenshots already cover preset coverage and these two are syntax-/diagram-pipeline smoke checks.

## Theme presets (the four shipping rooms)

The presets are the **only** theme choices the user ever sees. The file [rebuild/frontend/src/lib/theme/presets.ts](../../frontend/src/lib/theme/presets.ts) is the binding source of truth for every value below; the [DESIGN.md `colors:` block](../../../DESIGN.md) is the human-readable mirror.

| Preset id | Mode | OS-mapped when | Mood | Default for |
|---|---|---|---|---|
| `tokyo-day` | light | `prefers-color-scheme: light` | Crisp paper, restrained ink, saturated accents | Light-mode users |
| `tokyo-storm` | dark | — (explicit only) | Slate-blue dark, less saturated than Night | Office monitor in mixed lighting |
| `tokyo-moon` | dark | — (explicit only) | Warmer dark, softest ramp | Long focus sessions |
| `tokyo-night` | dark | `prefers-color-scheme: dark` (also the final fallback when `matchMedia` returns no preference) | Deepest dark, most saturated accents | Brand-canonical look |

Every preset exports the **same set of role tokens** (the full list lives in [DESIGN.md § 3 Colour Tokens](../../../DESIGN.md#3-colour-tokens)):

- **Surface ramp** — `background-app`, `background-sidebar`, `background-topbar`, `background-elevated`, `background-code`, `background-mention`.
- **Hairlines and ink** — `hairline`, `hairline-strong`, `ink-placeholder`, `ink-muted`, `ink-secondary`, `ink-body`, `ink-strong`.
- **Accents (4)** — `accent-selection`, `accent-selection-pressed`, `accent-mention`, `accent-headline`, `accent-stream`.
- **Status hues (4)** — `status-success`, `status-warning`, `status-danger`, `status-info`.
- **Syntax (6)** — `syntax-keyword`, `syntax-string`, `syntax-comment`, `syntax-function`, `syntax-number`, `syntax-tag`.

Components reach for role tokens. Components NEVER reach for a hex value or a preset name. A ruff-style grep gate (see § Acceptance criteria) fails the build on a `#[0-9a-fA-F]{6}` literal in a `.svelte` file outside `presets.ts` and `tokens.css`.

## Resolution order

This is the only behavioural contract that matters. Stated once, locked in `presets.ts` as a pure function `resolveTheme(input: { explicit?: ThemeId, osDark?: boolean }): ThemeId`:

1. If `explicit` is one of `THEME_IDS`, return it.
2. Else if `osDark === true`, return `"tokyo-night"`.
3. Else if `osDark === false`, return `"tokyo-day"`.
4. Else (no preference reported), return `"tokyo-night"` (the brand-canonical fallback).

The `explicit` argument is the user's choice as recorded in localStorage (preferred) or the cookie (fallback when localStorage is unavailable, e.g. private browsing). The `osDark` argument comes from `matchMedia("(prefers-color-scheme: dark)").matches` on the client, or from the `Sec-CH-Prefers-Color-Scheme` request header on the server when present (the header is best-effort; absent → tier 4 fallback). The same function runs in the inline boot script (client) and in `hooks.server.ts` (server) so both paths cannot disagree.

A unit test in [rebuild/frontend/tests/unit/theme/resolve.spec.ts](../../frontend/tests/unit/theme/resolve.spec.ts) parametrises every combination of `(explicit, osDark)` × 4 × 3 = 12 cases plus the "explicit value is not a known preset id" case (must fall through to OS) and the "explicit value is empty string" case (must fall through to OS).

## Persistence

The two persistence surfaces — cookie + localStorage — are NOT independent. They are written together by `writeChoice(id)` and cleared together by `clearChoice()`. The contract:

| Surface | Role | Read by | Written by |
|---|---|---|---|
| `theme` cookie | SSR-correct first paint. The SvelteKit `handle` hook reads it before HTML is generated; `<html data-theme="…">` is correct on the network response, no FOUC. | `hooks.server.ts` `handle`; `boot.ts` (fallback when localStorage is empty) | `persistence.writeChoice` (`Set-Cookie` via `document.cookie` with `Max-Age=31536000; Path=/; SameSite=Lax`, plus `Secure` when `location.protocol === "https:"`) |
| `localStorage["theme"]` | Client source of truth. Survives third-party-cookie cleanup tools that wipe `Lax` cookies. | `boot.ts` (preferred); `themeStore` constructor for hydration | `persistence.writeChoice` (`localStorage.setItem`) |

**Why both:** the cookie is required for FOUC-free SSR; `localStorage` is required because some users run cookie-clearing extensions that don't touch local storage and we don't want to silently drop their theme on every reload. Choosing one would either reintroduce the flash (localStorage-only) or be brittle to cookie cleanup (cookie-only). The 6 LOC of `writeChoice` that writes both is the price.

**No cross-tab synchronisation in M1.** A `storage` event listener that propagates a cross-tab theme change is a 4-line addition; we descope it for M1 because the cross-tab case is rare and the wrong-tab user can `Cmd-R` to converge. The `theme-cross-tab.spec.ts` E2E test asserts the *load-time* converge: setting the theme in tab A and opening tab B picks up A's choice on B's load. (Re-asserting this without the storage listener costs nothing and protects the cookie path.)

**No backend persistence. Anywhere.** No `user.theme_preference` column, no settings table, no `/api/me/theme` endpoint, no socket.io theme broadcast. The integration test `test_theming_no_db.py` enforces this at the framework level.

## Tailwind 4 wiring

Tailwind 4 uses `@theme` blocks to declare design tokens at build time. The pattern (consumed by [rebuild/frontend/src/app.css](../../frontend/src/app.css)):

```css
/* tokens.css — one per role, value is a CSS var that resolves at runtime */
@import "./theme/tokens.css";

@theme inline {
  --color-background-app: var(--background-app);
  --color-background-sidebar: var(--background-sidebar);
  --color-background-topbar: var(--background-topbar);
  --color-background-elevated: var(--background-elevated);
  --color-background-code: var(--background-code);
  --color-background-mention: var(--background-mention);
  --color-hairline: var(--hairline);
  --color-hairline-strong: var(--hairline-strong);
  --color-ink-placeholder: var(--ink-placeholder);
  --color-ink-muted: var(--ink-muted);
  --color-ink-secondary: var(--ink-secondary);
  --color-ink-body: var(--ink-body);
  --color-ink-strong: var(--ink-strong);
  --color-accent-selection: var(--accent-selection);
  --color-accent-selection-pressed: var(--accent-selection-pressed);
  --color-accent-mention: var(--accent-mention);
  --color-accent-headline: var(--accent-headline);
  --color-accent-stream: var(--accent-stream);
  --color-status-success: var(--status-success);
  --color-status-warning: var(--status-warning);
  --color-status-danger: var(--status-danger);
  --color-status-info: var(--status-info);
}
```

`tokens.css` itself emits one `[data-theme="tokyo-{id}"] { --background-app: …; … }` block per preset (selector is unprefixed for the per-tile cascade reason documented in § Deliverables), generated at build time from `presets.ts` so the source of truth is the TypeScript module (one place to edit) and the CSS is mechanical. A small Vite plugin at [rebuild/frontend/src/lib/theme/vite-emit-tokens.ts](../../frontend/src/lib/theme/vite-emit-tokens.ts) does the codegen on dev start and on every `presets.ts` change; the generated `tokens.css` is committed (not generated at production build time only) so reviewers see the diff when a preset changes.

After this wiring, every Tailwind utility resolves through the runtime variable: `bg-background-app`, `text-ink-body`, `border-hairline`, `text-accent-headline`. Switching `data-theme` re-points all variables in one DOM mutation; the browser repaints in one frame; nothing else has to know.

## Frontend conventions inherited from M0

- One store per `*.svelte.ts` file under `src/lib/stores/`, exporting a class. Constructed once and provided via `setContext` in `(app)/+layout.svelte` (and `(public)/+layout.svelte` for the public share view in M3). No module-level `$state` (per-user data → SSR leak). See [m0-foundations.md § Frontend conventions (cross-cutting)](m0-foundations.md#frontend-conventions-cross-cutting).
- Reactive collections use `SvelteMap` / `SvelteSet` from `svelte/reactivity` — the theme store doesn't need a collection (its state is one `ThemeId`), but the contract holds for any future addition.
- Snippets and `{@render}` are the templating primitive (no `<slot>`). The picker uses snippets for the per-tile preview chrome.
- Callback props (`onThemeChange`) instead of legacy `createEventDispatcher` (banned).

## Tests

### Unit (`rebuild/frontend/tests/unit/theme/`)

- `presets.spec.ts` — every preset declares every role token; the set of token names is identical across all four presets; OKLCH values parse via the `culori` test dep and round-trip cleanly.
- `resolve.spec.ts` — the 12 + 2 cases of `resolveTheme(...)` from § Resolution order.
- `boot.spec.ts` — pure-function tests of `bootResolveTheme(localStorage, cookie, mediaQuery)` covering the 4-tier precedence, plus the "localStorage throws on access" branch (Safari private browsing simulation) where it must fall back to cookie / OS.
- `persistence.spec.ts` — `writeChoice` writes to both surfaces; `clearChoice` clears both; cookie attributes are correct (`Max-Age=31536000; Path=/; SameSite=Lax`); the `Secure` flag is present iff `location.protocol === "https:"` (test stubs both branches by mutating `window.location` via `Object.defineProperty`).
- `shiki.spec.ts` — `buildShikiTheme(preset)` produces the right `colors.editor.background` and the six `tokenColors` ranges; snapshot tests against a one-line fixture per preset.
- `mermaid.spec.ts` — `buildMermaidThemeVariables(preset)` produces the expected six-key map; snapshot tests the values against the preset's role tokens.
- `contrast.spec.ts` — for each preset, asserts WCAG contrast ratios from § Accessibility budget (body ink ≥ 4.5:1 against `background-app`; secondary ink ≥ 3:1; status badge text against its 20% tinted fill ≥ 4.5:1). Uses `culori`'s `contrast` helper. Failing this test on a new preset blocks the merge.

### Component (Playwright CT, `rebuild/frontend/tests/component/`)

- `theme-picker.spec.ts` — drives `ThemePicker.svelte` through all four presets and the "Match system" reset. Asserts:
  - Click on a tile → `document.documentElement.dataset.theme` updates within one frame.
  - Click on a tile → cookie is set with the right value AND localStorage is set with the same value (single tick, no race).
  - Click "Match system" → both storages are cleared AND the resolved theme falls back to the OS-mapped preset (test sets `prefers-color-scheme: dark` via Playwright's `colorScheme` option to make this deterministic).
  - The active tile renders with the `accent-selection` ring (asserted via computed style).
  - Keyboard navigation: `Tab` moves between tiles; `Enter` / `Space` activates; `aria-pressed` reflects state.
- `theme-picker-tile.spec.ts` — renders one tile in isolation against each preset, asserts the miniature renders the right surface ramp and accent.

### E2E (Playwright, `rebuild/frontend/tests/e2e/`)

- `theme-fouc.spec.ts` — the **single most important test in M1**. With a `theme=tokyo-storm` cookie pre-set, `page.goto("/")` records every `data-theme` value the document ever held during load (via a `MutationObserver` injected into the page before navigation). Asserts the only value seen is `tokyo-storm` — no flash through `tokyo-night`, no transient `null`. Run against all four presets via parametrise.
- `theme-os-default.spec.ts` — no cookie, no localStorage; Playwright's `colorScheme: 'dark'` → first paint is `tokyo-night`; `colorScheme: 'light'` → first paint is `tokyo-day`; `colorScheme: 'no-preference'` → first paint is `tokyo-night`.
- `theme-explicit-persists.spec.ts` — set theme to `tokyo-moon` in Settings, full reload, assert `tokyo-moon` survives. Same again after closing and reopening the browser context.
- `theme-cross-tab.spec.ts` — set `tokyo-storm` in tab A; open tab B → tab B loads in `tokyo-storm` (the cookie is the synchronisation surface; cross-tab live propagation is descoped).
- `theme-public-share.spec.ts` — (placeholder; the test exists in M1 with a `test.skip()` annotation pointing at M3, where the share view becomes a real surface. The skip lifts in M3 once `/s/{token}` exists. The placeholder is committed in M1 so the M3 author doesn't have to invent it.)

### Backend integration (`rebuild/backend/tests/integration/`)

- `test_theming_no_db.py` — the only backend test M1 ships. Two pytest functions, both pinned to the locked "no DB persistence" decision. (1) `test_picker_round_trip_touches_only_the_user_table`: wires SQLAlchemy's `before_cursor_execute` event onto the M0 async engine, captures every SQL statement issued during a single `GET /api/me` request (the only HTTP request the picker page lifecycle makes backend-side; the cookie + `localStorage` writes happen entirely in JS), and asserts the touched-table set contains only the M0 `user` upsert/select. (2) `test_no_fastapi_route_references_theme`: introspects `app.routes` and asserts no route's path or handler-function name matches `r"theme"` (case-insensitive). The combination captures the same invariant the plan originally described as "run the full Playwright `theme-explicit-persists.spec.ts` flow against the real backend": the picker only ever calls `/api/me`, the FastAPI app exposes no theme endpoint, so the union of "single `/api/me` request touches only `user`" and "no theme route exists" is equivalent to "no SQL flows during the picker round-trip." Deliberate scope-down from running Playwright inside pytest — cross-process plumbing (pytest → vite dev server → playwright) is fragile, and the static route walk plus the single-request SQL trace captures the same locked decision without the cross-runtime fragility. The Playwright `theme-explicit-persists.spec.ts` still runs UI-side end-to-end via the M0 E2E pipeline; this backend test pins the SQL+route invariant. A regression that adds `await session.execute(insert(UserTheme)…)` to a `+page.server.ts` chain or registers a `POST /api/users/me/theme` router fails CI immediately.

### Visual regression (`rebuild/frontend/tests/visual-baselines/m1/`, Git LFS)

- One baseline per `(preset, surface)` pair for `(tokyo-day, tokyo-storm, tokyo-moon, tokyo-night)` × `(chat-empty, sidebar, theme-picker)` = 12 baselines.
- Three additional Tokyo-Night-only baselines: `code-block-tokyo-night.png` (smoke fenced block exercising every `syntax-*` token), `mermaid-tokyo-night.png` (smoke flowchart exercising the Mermaid theme variables), `theme-picker-collapsed-tokyo-night.png` (the picker's settings-row collapsed state).

Per `rebuild.md` § 8 Layer 4: deterministic via `--prefers-reduced-motion: reduce` + frozen `Date.now`; `maxDiffPixels` tolerance, never zero-tolerance; baselines updated via a manual workflow only.

## User journeys

Every click-path a real user takes on M1-owned surfaces. Each row binds the three layers of coverage per [visual-qa-best-practises.md § The three layers](../best-practises/visual-qa-best-practises.md#the-three-layers). The `verifier` walks this table on acceptance.

| Journey | Visual baseline (Layer A) | Geometric invariants (Layer B) | Impeccable review (Layer C) |
|---------|---------------------------|-------------------------------|-----------------------------|
| Cold load → first paint in OS-mapped preset (no FOUC) | `chat-empty-{preset}.png` for each of the four presets | n/a (full-page first-paint has no single component to assert geometric invariants on; the FOUC contract is behaviourally covered by `theme-fouc.spec.ts`) | sign-off required |
| Open `/settings` → see the 2×2 picker grid with four preset tiles and the "Match system" reset | `theme-picker-{preset}.png` for each of the four presets | `tests/component/ThemePicker-geometry.spec.ts` — tiles stay inside the container at every viewport, the "Match system" reset does not collide with the last tile, tile captions (`Tokyo Day`, `Tokyo Storm`, `Tokyo Moon`, `Tokyo Night`) are not text-clipped | sign-off required |
| Picker in narrow column (`<360 px` single-column `@container` fallback) | `theme-picker-collapsed-tokyo-night.png` | covered by the same `ThemePicker-geometry.spec.ts` at the 320-px viewport branch | sign-off required |
| Shell chrome in each preset (sidebar / topbar role tokens resolve) | `sidebar-{preset}.png` for each of the four presets | n/a at M1 — no sidebar component ships yet (identity-card proxy); M2's real sidebar gets its own `Sidebar-geometry.spec.ts` row in [m2 § User journeys](m2-conversations.md) | sign-off required |
| Shiki-highlighted code block in the active preset | `code-block-tokyo-night.png` | n/a (pure token-swap smoke; diff-caught by Layer A) | sign-off required |
| Mermaid diagram in the active preset | `mermaid-tokyo-night.png` | n/a (same rationale) | sign-off required |

**Baseline backfill (post-M1 follow-up).** The 15 spec assertions are authored in M1 (`frontend/tests/e2e/visual-m1.spec.ts`) but the PNG baselines themselves must be generated on the CI Linux container — not on a developer macOS / Windows host — to avoid font-rendering drift versus the CI environment that runs the regression. Workflow: from `rebuild/`, run `npx playwright test --grep @visual-m1 --update-snapshots` inside the same container image used by the Buildkite `e2e-smoke` step (or trigger the manual `test:visual:update` workflow once the script lands per [m6-hardening.md § Visual-regression CI](m6-hardening.md#visual-regression-ci)), then commit the resulting PNGs through Git LFS — the `.gitattributes` entry from M0 already filters `tests/visual-baselines/**`. The 12 chrome baselines snapshot `/settings`; the three Tokyo-Night smoke baselines (`code-block-tokyo-night.png`, `mermaid-tokyo-night.png`, `theme-picker-collapsed-tokyo-night.png`) target placeholder mounts in M1 and re-target the dedicated `(internal)/smoke/code-block` + `(internal)/smoke/mermaid` routes promoted by M2 (see [m2-conversations.md § Deliverables](m2-conversations.md)); the baseline filenames stay stable across the route move so the LFS-tracked PNGs are not re-keyed. Until the backfill lands the 15 specs are spec-authoring-only and do not gate CI.

## Acceptance criteria

- [ ] [rebuild/frontend/src/lib/theme/presets.ts](../../frontend/src/lib/theme/presets.ts) exports four presets: `tokyo-day`, `tokyo-storm`, `tokyo-moon`, `tokyo-night`. Every preset exports the full role-token set listed in [DESIGN.md § 3](../../../DESIGN.md#3-colour-tokens).
- [ ] [rebuild/frontend/src/lib/theme/tokens.css](../../frontend/src/lib/theme/tokens.css) emits one `[data-theme="tokyo-{id}"] { … }` block per preset with all tokens declared (selector is unprefixed so per-tile previews in `ThemePicker` cascade correctly). Generated at build time from `presets.ts` via [src/lib/theme/vite-emit-tokens.ts](../../frontend/src/lib/theme/vite-emit-tokens.ts); the generated file is committed.
- [ ] Tailwind utility classes resolve through the role tokens (`bg-background-app`, `text-ink-body`, `border-hairline`, `text-accent-headline`, `bg-status-success/20`).
- [ ] A grep gate in `rebuild/.buildkite/rebuild.yml` fails the build on `#[0-9a-fA-F]{6}` literals in any `*.svelte` file outside `src/lib/theme/`.
- [ ] [rebuild/frontend/src/hooks.server.ts](../../frontend/src/hooks.server.ts) reads the `theme` cookie, validates against `THEME_IDS`, drops invalid values, stores on `event.locals.theme`, and emits `<html data-theme="…">` via `transformPageChunk` so server-rendered HTML carries the correct `data-theme`.
- [ ] [rebuild/frontend/src/app.html](../../frontend/src/app.html) inlines the boot script inside `<head>` **before** `%sveltekit.head%` — the script runs before SvelteKit's preload links and module imports parse, so `data-theme` is final before any framework JS executes and corrects the value if the cookie path was missing or stale. The inlined string is generated from [src/lib/theme/boot.ts](../../frontend/src/lib/theme/boot.ts) at build time so the unit-tested module IS the inlined script.
- [ ] [rebuild/frontend/src/lib/stores/theme.svelte.ts](../../frontend/src/lib/stores/theme.svelte.ts) exports `ThemeStore`. The store is constructed in `(app)/+layout.svelte` and `(public)/+layout.svelte` and provided via `setContext("theme", store)`. Module-level `$state` is **not used** (assert via the AST gate from `m0-foundations.md`).
- [ ] [rebuild/frontend/src/lib/components/settings/ThemePicker.svelte](../../frontend/src/lib/components/settings/ThemePicker.svelte) renders four tiles and a "Match system" reset that surfaces only when the user has an explicit pick (`themeStore.source === 'explicit'`); tiles are real `<button>` elements with `aria-pressed`; keyboard navigation works.
- [ ] [rebuild/frontend/src/routes/(app)/settings/+page.svelte](../../frontend/src/routes/(app)/settings/+page.svelte) mounts the picker. The route is gated by the M0 trusted-header auth.
- [ ] The Shiki theme generator at [src/lib/theme/shiki.ts](../../frontend/src/lib/theme/shiki.ts) and the Mermaid theme generator at [src/lib/theme/mermaid.ts](../../frontend/src/lib/theme/mermaid.ts) emit per-preset themes; the smoke fenced-codeblock and smoke mermaid surfaces render against `tokyo-night` for the visual baseline.
- [ ] All unit tests in `tests/unit/theme/` pass (presets, resolve, boot, persistence, shiki, mermaid, contrast).
- [ ] Component test `theme-picker.spec.ts` passes for all four presets and the reset.
- [ ] E2E tests `theme-fouc.spec.ts` (parametrised over all four presets), `theme-os-default.spec.ts`, `theme-explicit-persists.spec.ts`, `theme-cross-tab.spec.ts` all pass.
- [ ] `theme-fouc.spec.ts` asserts the document carries exactly one `data-theme` value across the entire load (i.e. no transient flash).
- [ ] Backend integration test `test_theming_no_db.py` passes — a single `GET /api/me` round-trip touches only the M0 `user` table (via the `before_cursor_execute` capture in `test_picker_round_trip_touches_only_the_user_table`), AND no FastAPI route registers a path or handler name matching `r"theme"` (via the `app.routes` walk in `test_no_fastapi_route_references_theme`).
- [ ] Twelve chrome visual-regression baselines + three smoke baselines committed under `tests/visual-baselines/m1/` via Git LFS.
- [ ] **Three-layer visual QA** (per [visual-qa-best-practises.md](../best-practises/visual-qa-best-practises.md)): every row in § User journeys has (a) a committed baseline PNG under `tests/visual-baselines/m1/` produced by the manual refresh workflow, (b) a green geometric-invariant spec — CT `*-geometry.spec.ts` by default under `tests/component/`, escalating to `@journey-m1` under `tests/e2e/journeys/` only for multi-surface invariants, and (c) an `impeccable` design-review pass with zero Blockers. Polish findings are filed into § M1 follow-ups rather than blocking acceptance. `make test-component` and `make test-visual` both green; the verifier records the impeccable pass output.
- [ ] No new env vars on `Settings`. No new SvelteKit `PUBLIC_*` env vars. The `Secure` cookie flag is derived from `location.protocol === "https:"` at write time, so the dev / staging / prod split needs no plumbing through [m0-foundations.md § Settings(BaseSettings)](m0-foundations.md#settingsbasesettings).
- [ ] No Alembic revision authored.
- [ ] `rebuild.md` § 0 milestones table, § 5 phased delivery, § 8 critical-path table, and § 9 decisions all reference this milestone consistently with the M2–M6 renumber.

## Accessibility budget

Every shipping preset clears the contrast bar from [PRODUCT.md § Accessibility & Inclusion](../../../PRODUCT.md#accessibility--inclusion):

- `ink-body` against `background-app` ≥ **4.5:1**.
- `ink-secondary` against `background-app` ≥ **3:1**.
- `accent-selection` against `background-app` ≥ **3:1** (used as focus ring; non-text contrast threshold).
- Each `status-*` hue at full chroma against its own 20% tint ≥ **4.5:1**.

The `contrast.spec.ts` unit test enforces all four checks for all four presets. A new preset (anyone proposes one in the future) must add to this test before merge.

## Out of scope

- **No per-user theme persistence in the database.** Cookie + localStorage is the entire surface. Locked in `rebuild.md` § 9.
- **No cross-tab live propagation** (the `storage` event listener path). The cross-tab convergence happens at next page load via the cookie. The 4 LOC addition is reserved for a future minor.
- **No custom-preset authoring UI.** Users pick from the four shipping presets; they do not get colour pickers. A "Theme Designer" surface would be a multi-week feature with its own constraints around accessibility validation and is explicitly *not* the scope here.
- **No light-mode-only or dark-mode-only constraint.** Every component renders in all four presets. PRs that hard-code a "dark variant" of a colour outside the role-token vocabulary are rejected.
- **No font-family theming.** Typography is brand-fixed (Archivo / Inter / JetBrainsMono / InstrumentSerif / Vazirmatn). Letting users swap to Comic Sans is not a feature.
- **No `--app-text-scale` slider** in M1's settings page. The variable exists from M0 (per [DESIGN.md § Typography](../../../DESIGN.md#4-typography)) and components honour it; an actual UI to set it is descoped to a future settings expansion.
- **No theme-specific motion or transition rules.** Theme switching is instant — there is no fade. The only motion in M1 is the picker tile's `:hover` outline, ≤ 150ms.
- **No "Sync theme across devices" feature.** Out of scope by decision (`rebuild.md` § 9 — theme is a per-room comfort setting, not part of identity).
- **No automation that changes theme on a schedule** (e.g. "switch to Day at sunrise"). The OS already does this when the user has chosen "Match system."
- **No theme analytics.** We do not log which preset a user chose; there is no metric called `theme_preset_picked_total{preset="..."}` in M6.
- **No A/B testing infrastructure for new presets.** New presets ship to everyone or to no one.

## Dependencies on other milestones

- **M0 (hard).** Requires the SvelteKit 2 + Svelte 5 + Tailwind 4 skeleton, the M0 `(app)/+layout.svelte` shell, the trusted-header `getUser` server load, the M0 `app.html`, the M0 `hooks.server.ts`, the deterministic E2E stack, and the Git LFS visual-baseline filter.
- **No dependency on M2, M3, M4, M5, M6.** This milestone ships completely on the M0 foundation. The forward-link to M2 (markdown headings render in `accent-headline`; code blocks render via the M1 Shiki theme) is satisfied by deliverables M2 owns; M1 only needs the theme system to *exist*, not the chat surface that consumes it. The forward-link to M3 (the public share view inherits the active theme) is similarly an M3 obligation that the M1 cookie path makes free.

## Open questions

None blocking. Two implementation-time confirmations to make during M1:

1. **Tailwind 4 `@theme inline` runtime resolution.** Confirm that `@theme inline { --color-x: var(--x); }` produces a Tailwind utility class that resolves the runtime CSS variable (vs. baking the resolved value into the build). The Tailwind 4 docs say it does; the test is to switch `data-theme` at runtime in dev and watch `bg-background-app` repaint. If it doesn't, the fallback is to emit per-preset Tailwind utility blocks via the Vite plugin — slightly more CSS, no runtime difference. Either way the API surface for components stays identical.
2. **Shiki theme regeneration cost.** Confirm that swapping the Shiki theme on every preset switch doesn't re-tokenize every visible code block (which would stutter on a long markdown render). The Shiki docs say themes can be swapped without re-tokenizing; spot-check on a 200-block fixture to confirm. If re-tokenization is unavoidable, debounce the picker so a user dragging through previews doesn't trigger four full reflows.

Both are 5-minute confirmations during the implementation tick; neither is a scope risk.
