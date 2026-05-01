# PLAN-TEMPLATE — canonical shape every milestone and feature plan follows

This is the template `plan-keeper` uses when authoring a new plan and when backfilling an existing one. It encodes the mandatory sections and their contract. **The `## User journeys` section is non-optional.** The `make lint-plans` gate (registered into `make lint`) fails if any plan under `rebuild/docs/plans/m*.md` or `rebuild/docs/plans/feature-*.md` is missing it.

The gate exists because the three-layer visual-QA discipline — pixel-diff baselines + geometric-invariant specs + impeccable design review, see [visual-qa-best-practises.md](../best-practises/visual-qa-best-practises.md) — needs a single authoritative list of what a user can visibly do in each milestone. Without that list, Layer A has no baselines to capture, Layer B has no components to assert on, Layer C has no surfaces to review, and the `verifier` subagent has nothing to check against.

## Mandatory sections (in this order)

1. `# {Milestone ID} — {one-line title}` — e.g. `# M2 — Conversations + history`.
2. `## Goal` — three-to-six-sentence paragraph locking the milestone's outcome.
3. `## Deliverables` — the bullet list of concrete artefacts.
4. Domain sections — whatever the milestone needs (data model, API surface, frontend routes, scheduler worker, etc.). Flexible shape; owned by the plan author.
5. `## User journeys` — **mandatory**. See § The User journeys section below.
6. `## Tests` — unit / component / e2e / visual layers, including the `*-geometry.spec.ts` entries for every UI component that ships.
7. `## Dependencies on other milestones` — upstream / downstream constraints.
8. `## Acceptance criteria` — the checklist. Includes the three-layer visual-QA row verbatim (see § Mandatory acceptance criterion below).
9. `## Out of scope` — explicit non-goals.
10. Optional: `## Open questions`, `## {M{n}} follow-ups`.

## The `## User journeys` section

One sentence of intro, then a markdown table. The table has these columns exactly:

| Journey | Visual baseline (Layer A) | Geometric invariants (Layer B) | Impeccable review (Layer C) |
|---------|---------------------------|-------------------------------|-----------------------------|

Each row is one click-path a real user takes on a surface the milestone ships. Rows must cover — at minimum — every route the milestone adds under `src/routes/`, every distinct visible state of every component listed in `## Deliverables` (closed / open / hover / error / empty / loading — count each as its own state if a user dwells on it), and every piece of chrome a user sees for more than a frame (banners, toasts, modals).

### Column rules

- **Journey** — describes the click-path, not the surface. e.g. "New chat → type → open `+ Options` → Temperature + System visible", not "Options panel".
- **Visual baseline (Layer A)** — the filename of the baseline PNG under `frontend/tests/visual-baselines/m{n}/`. If the baseline is deferred to a later milestone (common when the feature is minimal in its shipping milestone and stabilises later), cite the deferring row in that milestone's `## {M{n}} follow-ups`. "n/a" is only acceptable when the journey has no meaningful visual (e.g. a backend redirect that never paints).
- **Geometric invariants (Layer B)** — path to the `*-geometry.spec.ts` file in `frontend/tests/component/` that asserts overlap / containment / min-width / no-clipping for this journey's component(s). For multi-surface invariants (rare) cite the `@journey-m{n}` e2e spec under `frontend/tests/e2e/journeys/`. "covered by behavioural spec X (see note)" is acceptable only with an explicit follow-up row in `## {M{n}} follow-ups` promising a geometric spec in a later milestone.
- **Impeccable review (Layer C)** — `sign-off required` for every row. The `verifier` records the impeccable pass output as part of its acceptance report; rows without "sign-off required" are invalid.

### Content rules

- Empty `## User journeys` sections fail the lint gate. If a milestone genuinely ships no product UI (e.g. a hardening-only milestone that only touches backend policy), write `_No product UI in this milestone._` as the section's sole content. The lint gate accepts that literal phrase and no other empty-section phrasing.
- Every journey listed in `## Deliverables` that produces visible output must appear in `## User journeys`. If you catch a deliverable that surfaces UI but has no matching journey row, that's a plan-keeper escalation — file the row, don't paper over.
- Follow-up rows that defer Layer A or Layer B coverage are only valid when the deferred work is tracked in `## {M{n}} follow-ups` of some milestone (the current one or a later one). Without the follow-up, the deferral fails review.

## Mandatory acceptance criterion

Every plan's `## Acceptance criteria` includes this row verbatim, with `{M{n}}` substituted:

```
- [ ] **Three-layer visual QA** (per [visual-qa-best-practises.md](../best-practises/visual-qa-best-practises.md)): every row in § User journeys has (a) a committed baseline PNG under `tests/visual-baselines/m{n}/` produced by the manual refresh workflow, (b) a green geometric-invariant spec — CT `*-geometry.spec.ts` by default under `tests/component/`, escalating to `@journey-m{n}` under `tests/e2e/journeys/` only for multi-surface invariants, and (c) an `impeccable` design-review pass with zero Blockers. Polish findings are filed into § {M{n}} follow-ups rather than blocking acceptance. `make test-component` and `make test-visual` both green; the verifier records the impeccable pass output.
```

Plans that ship no product UI substitute the row with:

```
- [ ] **Three-layer visual QA** — n/a (this milestone ships no product UI). The `## User journeys` section is empty; the `lint-plans` gate accepts the literal phrase `_No product UI in this milestone._`.
```

## What triggers an update to `## User journeys`

A plan-keeper update is required whenever any of the following happens during the milestone's implementation:

- A new route is added under `src/routes/` that a user can reach.
- A new component with visible state is added under `src/lib/components/` — including states the user can toggle (open/closed, hover/focus, error/success).
- A new banner, toast, modal, or disclosure is introduced.
- A component gains a new visible variant (e.g. `MessageInput` gets an attachment button that was not in the original plan).

The update is small (one new row in the table) but it is blocking — the `verifier` refuses to mark the milestone complete if the shipped surface is larger than what the plan enumerates.

## How verifier / test-author / svelte-engineer consume the section

- **`verifier`** — walks the table on acceptance. For each row: (a) confirms the baseline PNG exists and is committed via Git LFS; (b) confirms the `*-geometry.spec.ts` file exists and `make test-component` is green; (c) invokes `impeccable` with the journey description as the prompt over the baseline PNG and records findings. A Blocker finding blocks acceptance.
- **`test-author`** — authors every `*-geometry.spec.ts` entry in the table. Re-uses the existing CT harness for each component; does NOT author a new harness per geometry spec.
- **`svelte-engineer`** — owns the UI changes that land rows in the table. When a new surface is shipped, pings `plan-keeper` to add the row before opening the PR.
