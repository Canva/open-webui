# Visual QA — three-layer discipline

A feature is not "complete" until every visible user journey it introduces has passed **all three** of the layers below. Behavioural tests (`@smoke`, `send-and-stream.spec.ts`, and the CT keyboard-contract specs) prove a click produces the right state change; they say nothing about whether the state looks right. Pixel-diff baselines (`@visual-m{n}`) catch drift from a locked image but are blind to bugs present when the baseline was first captured. The geometric-invariant layer and the human-judgment layer close the gap.

This document is the single source of truth for the discipline. The milestone plans reference it from their `## User journeys` and `## Acceptance criteria` sections; the `verifier` subagent enforces it before marking acceptance green.

## The mechanical shape: every new user flow gets full three-layer coverage

Every milestone and feature plan under `rebuild/docs/plans/m*.md` and `rebuild/docs/plans/feature-*.md` ships a `## User journeys` section with the columns `Journey | Layer A baseline | Layer B geometric spec | Layer C impeccable review`. The canonical shape is in [rebuild/docs/plans/PLAN-TEMPLATE.md](../plans/PLAN-TEMPLATE.md); the `make lint-plans` gate (wired into `make lint`) fails if any plan is missing the section or the mandatory three-layer acceptance-criteria row. This makes the "every new flow triggers coverage" discipline mechanical rather than aspirational.

### What counts as a "new user flow"

Any of the following ships a new row into `## User journeys`:

- A new route under `rebuild/frontend/src/routes/` that a user can reach.
- A new component with visible state under `rebuild/frontend/src/lib/components/` — including disclosures / toggles / tabs that a user can dwell on.
- A new visible variant of an existing component (e.g. an error state that wasn't there before, a new size, a new layout the user can reach).
- A new banner, toast, modal, or inline alert anywhere in the shell.
- A new copy/typography state that changes the information architecture of an existing surface (e.g. a one-line error becomes a multi-line error with an action affordance).

If in doubt, add the row. Over-enumerating costs nothing; under-enumerating leaves holes that Layer A + Layer B + Layer C cannot fill because they do not know the surface exists.

### Who adds the row and when

- `svelte-engineer` — when about to ship a new visible surface, pings `plan-keeper` to add the row before opening the PR. This is the hot path for most new flows.
- `plan-keeper` — owns every edit to `## User journeys`. Populates new rows during milestone authoring (from the plan's `## Deliverables` and `## Frontend routes and components` sections) and backfills them during implementation when `svelte-engineer` discovers a surface the plan missed.
- `test-author` — consumes the table to decide what specs to author. Never invents rows; if a component needs a geometric spec, the row for that component must already exist in the plan. If it doesn't, escalate to `plan-keeper`.
- `verifier` — walks every row at acceptance time. A plan with a surface that lacks its row fails acceptance, even if that surface's behavioural spec is green.

### What the verifier checks per row

For each journey in `## User journeys`:

1. **Layer A** — the named baseline PNG exists under `tests/visual-baselines/m{n}/`, is tracked via Git LFS, and the corresponding `@visual-m{n}` spec in `tests/e2e/visual-m{n}.spec.ts` is green.
2. **Layer B** — the named `*-geometry.spec.ts` file exists under `tests/component/` (or `tests/e2e/journeys/` for escalated multi-surface rows) and `make test-component` / `@journey-m{n}` is green.
3. **Layer C** — the `impeccable` skill has been invoked over the baseline PNG with the journey description as the prompt; Blocker findings (if any) are resolved or explicitly deferred by the user.

Missing baselines, missing geometry specs, or Blocker-level `impeccable` findings all block acceptance. Polish findings go to `## {M{n}} follow-ups`; Nits are discarded unless a reviewer elects to act. The lint gate (`make lint-plans`) is the first line of defence; the verifier's acceptance walk is the last.

## The three layers

| Layer                        | Home                                                                                                                                                                             | Catches                                                                                                                 | Misses                                                                                                                 | Owned by                                                                                                                                                                          |
| ---------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A — pixel-diff baseline      | `@visual-m{n}` tag in `frontend/tests/e2e/visual-m{n}.spec.ts`                                                                                                                   | Drift from an approved visual state on a known surface.                                                                 | Bugs already present when the baseline is first captured; surfaces not enumerated in the plan.                         | `test-author` authors the spec; the Buildkite `block: "Refresh visual baselines"` step regenerates PNGs (see [m6-hardening.md § Visual-regression CI](../plans/m6-hardening.md)). |
| B — geometric invariants     | Primarily `frontend/tests/component/*-geometry.spec.ts` (Playwright CT); escalates to `frontend/tests/e2e/journeys/` only when the assertion crosses multiple routes or surfaces | Overlap, clipping, overflow, below-minimum content width. Fails on the FIRST run when the bug is present.               | Aesthetic issues that don't violate a boolean invariant (e.g. "this looks crowded but technically doesn't overlap").   | `test-author` authors the spec using `tests/e2e/helpers/geometry.ts`.                                                                                                             |
| C — impeccable design review | Manual gate in verifier                                                                                                                                                          | Everything B misses — hierarchy, rhythm, alignment, colour, UX copy, i18n truncation that B's heuristic didn't foresee. | Nothing A or B catches that C is better at. C's weakness is only that it requires a model/human pass, not a green bit. | `svelte-engineer` via the `.cursor/skills/impeccable/SKILL.md` audit; `verifier` runs the pass over the screenshots `test-visual` produced and reports findings.                  |

Layer A + Layer B are machine-checkable and always run on every PR that touches `rebuild/frontend/**`. Layer C runs once per milestone on the journeys the plan enumerates, before the `verifier` reports green.

### Why Layer B lives in Component Testing by default

The bugs this layer is designed to catch are almost always single-component concerns — a disclosure inside a composer, a label beside an input, a tooltip above a button. CT mounts the real component against the real Tailwind CSS at a deterministic viewport, which is:

- **Faster** — ~200 ms per assertion vs ~2-4 s for an E2E that has to boot the stack.
- **More reliable** — no Docker compose, no Vite dev server, no backend state. Runs in the existing `make test-component` step.
- **More hermetic** — the harness provides stub stores, so the invariant is measured on the component in isolation, not on whatever happens to render around it that day.

Escalate to E2E journeys (`frontend/tests/e2e/journeys/*.spec.ts`) only when the invariant genuinely crosses routes or surfaces — e.g. "the sidebar-collapse toggle never sits under the composer's send button after a route change". The vast majority of cases are single-component and belong in CT.

## Layer A — pixel-diff baselines

### When to add a baseline

Every distinct _visible state_ a user can reach in one click from a cold load needs a baseline. The closed composer and the composer-with-Options-open are two states, not one: add two PNGs, not one. Empty state, loading state, error state, hover state, focus state — each is its own baseline if it's a surface a user actually dwells on.

The plan author maintains the list of visual states in the milestone's `## User journeys` section. If a new state ships without a corresponding baseline, the `verifier` blocks acceptance.

### Spec shape

Tests live in `rebuild/frontend/tests/e2e/visual-m{n}.spec.ts` and tag `@visual-m{n}`. They always:

- set the theme via cookie (`setupForPreset` / `setupForTokyoNight`),
- inject the deterministic-boot init script (freeze `Date.now`, `Math.random`, `animation: none`),
- stub the backend routes the layout-load depends on so the capture is hermetic,
- call `toHaveScreenshot(name, { maxDiffPixels: 100 })` — never zero-tolerance (locked by [rebuild.md § 8 Layer 4](../../../rebuild.md)).

### Capture workflow

Baselines are generated on the same Linux container that runs CI. The local `make test-visual-update` is gated behind `SKIP_VISUAL=0` so a developer running the full E2E suite on macOS does not accidentally regenerate PNGs with macOS font hinting. The canonical workflow is the Buildkite manual-trigger step; see [m6-hardening.md § Baseline refresh](../plans/m6-hardening.md).

## Layer B — geometric invariants

### Why this layer exists

If a new surface ships with a bug and the baseline captures the bug, Layer A goes green forever. Layer B encodes _intent_ — "sibling inputs don't overlap", "controls stay inside their container", "content-box is wide enough for the placeholder" — so the first run fails when the bug is there. Layer B is the single highest-signal layer for the cost.

### The helpers (`tests/e2e/helpers/geometry.ts`)

Location note: the helpers live under `tests/e2e/helpers/` so both CT specs (`tests/component/*-geometry.spec.ts`) and e2e journey specs (`tests/e2e/journeys/*.spec.ts`) can import them. The helpers are framework-neutral — they only depend on `@playwright/test`'s `Locator` and `expect` APIs, which CT re-exports compatibly.

- `expectNoOverlap(a, b, labels)` — the flagship assertion. Fails with both rects pretty-printed so the diagnostic tells you exactly how much the two controls collide.
- `expectContains(outer, inner, labels)` — catches "advanced knobs spill out of the composer card", "tooltip overflows the viewport", "sidebar row's pin icon pushes beyond the 240 px column".
- `expectMinContentWidth(input, minPx, label)` — catches `"default"` truncating to `"defa"` because `w-20` is too narrow for the placeholder. Subtracts the Chromium number-stepper chrome for `type="number"` inputs so the assertion reflects actual text space.
- `expectNoTextClipping(locator, label)` — `scrollWidth > clientWidth`, the CSS-level truncation check; use for labels and selects where the pixel budget is not knowable ahead of time.

### Spec template (Component Testing — default)

Tests live in `rebuild/frontend/tests/component/<component>-geometry.spec.ts`. Canonical shape — see `composer-options-geometry.spec.ts`:

1. Import the helpers from `../e2e/helpers/geometry`.
2. Set a **deterministic viewport** via `test.use({ viewport })` — the grid breakpoints are often the bug; if you don't lock the viewport, the invariant is meaningless.
3. `mount` the component's existing CT harness (same harness the behavioural CT spec uses — reuse, don't duplicate).
4. Drive the UI along the user's exact path (click, type, click).
5. Call the `expect*` helpers with descriptive `labels` — the diagnostics are the only thing a verifier reviewing a failed CI run has.

Cover desktop and narrow viewports as separate top-level `test.describe` blocks (not nested describes — CT's viewport fixture doesn't always propagate cleanly into nested describes).

One important gotcha: the locator returned by `mount()` is the component's root element. If the component's root IS the container you want to measure (e.g. `MessageInput`'s root is `<form>`), calling `component.locator('form')` searches for a _nested_ form and misses. Either use `component` directly, or reach the container via `page.locator(...)`.

### Spec template (E2E journey — escalation only)

Tests live in `rebuild/frontend/tests/e2e/journeys/<journey>.spec.ts` and tag `@journey-m{n}`. Reserved for multi-route / multi-surface invariants. Shape is the same as Layer A's visual-regression spec (stub the backend routes the layout-load needs, navigate, assert) but the assertions come from `helpers/geometry.ts` rather than `toHaveScreenshot`.

### What Layer B does NOT try to catch

- Typography taste ("this is the wrong weight for a caption") — Layer C.
- Colour taste ("this is the wrong accent for a warning") — Layer C.
- Information architecture ("this button should not be here") — Layer C.
- Cognitive load ("three disclosures in a row is too many") — Layer C.

If you find yourself reaching for a regex on the rendered text to make an aesthetic assertion, stop and escalate to Layer C instead.

## Layer C — impeccable design review

### The gate

After `make test-visual` produces the baseline PNGs, the `verifier` subagent invokes the `impeccable` skill over each screenshot with the journey description as the prompt:

> "A user opened a new chat, typed a message, then clicked the `+ Options` disclosure in the composer. The composer with Options expanded is visible in `composer-options-open-tokyo-night.png`. Is the visible content well-aligned, uncrowded, and free of truncation? Flag every issue — we want specific findings, not a summary."

`impeccable` returns a list of findings. Each finding is one of:

- **Blocker** — ships a visible bug (overlap Layer B missed, clipping, colour contrast below AA, wrong hierarchy). Blocks acceptance.
- **Polish** — ships a rough edge (kerning, rhythm, copy clarity). Does not block acceptance; filed as a follow-up issue in the milestone's `## Follow-ups` section.
- **Nit** — opinion, not a defect. Reviewer discretion.

### What the verifier does with findings

- **Blockers** — verifier reports "not complete" and names the finding. The owning subagent (`svelte-engineer` for product surfaces, `test-author` if the spec itself is wrong) fixes and re-runs the gate.
- **Polish** — verifier includes the list in its final report and adds each item to `## Follow-ups` in the milestone plan via `plan-keeper`.
- **Nits** — discarded unless the reviewer elects to act on them.

### When Layer C runs

Once per journey, per milestone, before acceptance is signed off. It does **not** run on every PR — too slow, too noisy. It runs:

- at milestone acceptance time (before the milestone plan's checklist goes green),
- after any PR that changes the design tokens (`app.css`, `theme/tokens.css`, any `@theme` block) or adds a new visual state,
- ad-hoc when a reviewer flags a specific surface.

## How each subagent plugs in

- **`test-author`** — authors `@visual-m{n}` specs, `*-geometry.spec.ts` CT specs, (rarely) `@journey-m{n}` e2e specs, and the `tests/e2e/helpers/*.ts` helpers they use. Never commits the PNGs itself; the manual-refresh workflow owns those. Consumes `## User journeys` as the canonical list of what to spec — does not invent rows; escalates missing rows to `plan-keeper`.
- **`svelte-engineer`** — authors the UI. Owns the `impeccable` skill per the subagent descriptor ("Owns design quality on every dispatched surface via the impeccable skill"). When about to ship a new visible surface, pings `plan-keeper` to add a `## User journeys` row BEFORE opening the PR. When `verifier` flags a Blocker, this is the subagent that fixes it.
- **`plan-keeper`** — sole owner of `## User journeys`. Populates rows during milestone authoring (from `## Deliverables` / `## Frontend routes and components`) and backfills rows when `svelte-engineer` discovers a surface the plan missed. Files Layer C polish items into `## {M{n}} follow-ups`.
- **`verifier`** — independent validator. Runs `make lint-plans` (structural gate — every plan has the section and the mandatory three-layer acceptance row), `make test-component` (covers Layer B), `make test-visual` (covers Layer A), and any `@journey-m{n}` specs (`npx playwright test -c playwright.config.ts --grep @journey`) as part of the acceptance gate. Walks every row in `## User journeys` and invokes `impeccable` over the captured PNGs. Reports blockers and polish findings; does not write code.

## Commands (quick reference)

```
make lint-plans             # Structural gate: every plan has § User journeys + 3-layer AC row (runs under `make lint`)
make test-component         # Layer B primary home (CT geometric invariants)
make test-visual            # Layer A — pixel-diff, Linux container only
make test-visual-update     # Layer A — manual refresh (Buildkite block step)
```

E2E journey specs (escalation for multi-surface invariants) run via `npx playwright test -c playwright.config.ts --grep @journey` and are wired into CI the same way `@smoke` is. They are not given their own Makefile target because that would imply they are the primary Layer B home — which they are not.

The `impeccable` gate is not a Makefile target; it is a named step inside the verifier's checklist. Adding a Makefile target would imply it is automatable, which it is not yet — the model / human pass sits in the loop.
