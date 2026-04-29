---
name: implement-plan
description: Implement a rebuild milestone plan (or a scoped sub-section of one) by breaking it into concrete actions, mapping each action to the correct specialist subagent (db-architect, fastapi-engineer, realtime-engineer, svelte-engineer, test-author, verifier, plan-keeper), and dispatching them in dependency order. Use when the user says "implement m1/m2/m3/m4/m5", "implement the <feature> plan", "build out <section> from the milestone", "execute the milestone", or any phrasing that asks to turn a written plan in `rebuild/docs/plans/` into shipped code.
---

# Implement a Rebuild Milestone Plan

You are the orchestrator. Your job is to turn a written milestone plan (or a scoped piece of one) into shipped code by delegating to the seven specialist subagents in `.cursor/agents/`. You do not write code yourself in this flow — you read, plan, dispatch, and report.

## Available subagents (anchor these names exactly)

| Subagent | Owns | Read order | Best-practises file(s) it loads |
|---|---|---|---|
| `plan-keeper` | `rebuild.md`, milestone plans, best-practises files (read-only) | First (scope check), last (drift sweep) | All four (curator of the canonical files) |
| `db-architect` | SQLAlchemy models, Alembic revisions, indexes, constraints | Phase 1 | `rebuild/docs/best-practises/database-best-practises.md` (+ `rebuild/docs/plans/MYSQL_FEATURE_AUDIT.md`) |
| `fastapi-engineer` | Routers, schemas, services, dependencies | Phase 2 | `rebuild/docs/best-practises/FastAPI-best-practises.md` |
| `realtime-engineer` | SSE, `StreamRegistry`, socket.io + Redis adapter, webhooks | Phase 2 (parallel with fastapi when independent) | `rebuild/docs/best-practises/FastAPI-best-practises.md` (sections A.2, A.7, A.8, B.6) |
| `svelte-engineer` | SvelteKit routes, runes stores, Tailwind 4 components, **design quality (impeccable)** | Phase 3 | `rebuild/docs/best-practises/svelte-best-practises.md`, `rebuild/docs/best-practises/sveltekit-best-practises.md`, **plus** the `impeccable` skill |
| `test-author` | Vitest unit, Playwright CT/E2E, visual baselines, MSW, LLM cassettes | Phase 4 (and proactively per layer) | The same best-practises file(s) as the layer being tested |
| `verifier` | Runs lint/typecheck/test gates and grep checks | Final phase (read-only, fast model) | The same best-practises file(s) as the layer being verified |

The four best-practises files plus the impeccable skill:

| Source | Path |
|---|---|
| FastAPI best practises | `rebuild/docs/best-practises/FastAPI-best-practises.md` |
| Database best practises | `rebuild/docs/best-practises/database-best-practises.md` |
| Svelte 5 best practises | `rebuild/docs/best-practises/svelte-best-practises.md` |
| SvelteKit best practises | `rebuild/docs/best-practises/sveltekit-best-practises.md` |
| Impeccable (design craft) | `.cursor/skills/impeccable/SKILL.md` (+ `PROJECT.md`, `project/`, `reference/`) |

Always name the relevant source(s) in every subagent dispatch (see Phase 3, step 4).

## Workflow

Run these phases in order. Do not skip.

### Phase 0 — Scope and read

1. Identify the target plan from the user's request. The current numbering is M0 = Foundations, M1 = Theming, M2 = Conversations, M3 = Sharing, M4 = Channels, M5 = Automations, M6 = Hardening — so "m4" or "channels" maps to `rebuild/docs/plans/m4-channels.md`, "m1" or "theming" to `rebuild/docs/plans/m1-theming.md`, and so on. If they named a sub-section ("the SSE streaming pipeline", "the file upload bits"), keep that scope front-of-mind for every later phase.
2. Read the plan in full. Specifically locate these sections (names may vary slightly per milestone):
   - **Goal** — one paragraph framing.
   - **Deliverables** — the bullet list of files to create.
   - **Data model** — tables, columns, indexes, constraints.
   - **API surface** — routes, payloads, status codes.
   - **Realtime / Streaming-pipeline / Socket.io** sections (M2 and M4).
   - **Frontend deliverables** — routes, components, stores.
   - **Tests** / **Acceptance criteria** / **Definition of done**.
3. Re-read `rebuild.md` §9 (locked decisions) so you don't accidentally invite a subagent to violate one.
4. If anything in the user's request contradicts a locked decision or a plan section, stop and dispatch `plan-keeper` first to surface the drift. Do not proceed with implementation until the user confirms how to resolve it.

### Phase 1 — Build the dispatch plan

Map every actionable item from the plan to exactly one subagent. Use this rubric:

| Plan content | Subagent |
|---|---|
| New table, new column, new index, new constraint, new Alembic revision | `db-architect` |
| New router, new endpoint, new Pydantic schema, new service, new dependency, route renames | `fastapi-engineer` |
| SSE generator, `StreamRegistry`, socket.io event/room, webhook delivery, presence/typing/read receipts | `realtime-engineer` |
| New SvelteKit route, new component, new store (`*.svelte.ts`), Tailwind work, legacy port with dead-import strip, design polish on existing surface | `svelte-engineer` |
| Unit test, component test, E2E test, multi-context test, visual baseline, MSW handler, LLM cassette | `test-author` |
| Acceptance-criteria sweep, regression-first gate enforcement, grep checks for non-negotiables | `verifier` |
| Plan edit (data-model row, API surface row, deliverable bullet) | `plan-keeper` |

For every `svelte-engineer` row in the dispatch plan, name the **impeccable command** the subagent should run. Pick from the routing table in `.cursor/skills/impeccable/PROJECT.md` § Command routing for `svelte-engineer`:

| Work shape | Impeccable command |
|---|---|
| Net-new visually-significant route or component | `craft` (run `shape` first) |
| Net-new small variation of an existing component | `polish` |
| Legacy port from `src/lib/components/{chat,channel,automations}/` | `polish` then `harden` |
| Style refresh on existing rebuild surface | `polish` (or `bolder` / `quieter` / `distill` if briefed) |
| Bug fix with no visual delta | none |
| Pre-milestone sweep across multiple surfaces | `audit` then `polish` per finding |
| Empty / loading / error / first-run states | `onboard` then `harden` |
| Adapt for a new viewport | `adapt` |
| UI feels slow or janky | `optimize` |
| Copy / labels / errors | `clarify` |

A port is **never** `craft`. If the user asked for what looks like a `craft` on a port, surface the conflict before dispatching — that is scope creep into redesign and the user must confirm.

Now create a TodoWrite list with one todo per subagent dispatch. Keep todo descriptions specific (not "do db work" — say "create `0004_m4_channels.py` with all tables in m4-channels.md § Data model"). For `svelte-engineer` todos, include the impeccable command in the description (e.g. "polish + harden the ported `(app)/c/[id]/+page.svelte`, strip dead RAG/MCP imports"). Mark the first phase-1 todo as `in_progress` and present the full list to the user before launching anything.

### Phase 2 — Confirm with the user

Before dispatching any subagent, surface the dispatch plan as a brief table:

- Phase 1 (sequential): list of `db-architect` invocations with one-line task each.
- Phase 2 (parallel where possible): `fastapi-engineer` and `realtime-engineer` invocations.
- Phase 3 (sequential after Phase 2): `svelte-engineer` invocations, **each with its impeccable command named** (e.g. `craft`, `polish + harden`, `audit`, or `none` for no-visual-delta tasks).
- Phase 4 (proactive throughout, finalised here): `test-author` invocations.
- Phase 5: single `verifier` run.
- Phase 6 (only if Phase 0 surfaced drift): `plan-keeper` plan edits.

Ask the user to confirm or scope down. Implementation is expensive and the plan may include sections the user wants to defer. Use the AskQuestion tool only if the dispatch plan has more than ~6 subagent invocations or the user gave an ambiguous scope ("implement some of m3"). For small scopes, a one-paragraph confirmation in plain text is enough.

### Phase 3 — Dispatch in dependency order

Use the Task tool to launch subagents. Respect these dependencies:

- **Schema before code that queries it.** `db-architect` finishes before any `fastapi-engineer`/`realtime-engineer`/`svelte-engineer` task that reads or writes the new column.
- **API contracts before UI.** `fastapi-engineer` finishes its routes for a given domain before `svelte-engineer` ports the UI for that domain.
- **Realtime can usually parallel HTTP.** Within a milestone, `realtime-engineer` and `fastapi-engineer` rarely touch the same files; launch them in parallel when their inputs are independent (run both Task tool calls in the same message).
- **Tests author per layer.** Dispatch `test-author` after each layer completes, not only at the end. This catches breakage while the context is still fresh and stops Phase 5's `verifier` from drowning in failures.
- **Verifier is always last.** Even if every subagent reported success, `verifier` is the regression-first gate.

For each Task call:

1. Pass the milestone plan path and the specific section(s) the subagent should re-read.
2. Pass the exact deliverables the subagent owns from your dispatch plan — quote bullets or table rows from the plan rather than paraphrasing.
3. Tell the subagent which other subagents have already run, so it knows what files it can assume exist.
4. **Name the best-practises file(s) it must load into context** from the table above. Each subagent's own prompt already requires loading them, but naming them in the dispatch removes any chance of it skipping. Specifically:
   - `db-architect` — `rebuild/docs/best-practises/database-best-practises.md` and `rebuild/docs/plans/MYSQL_FEATURE_AUDIT.md`.
   - `fastapi-engineer` — `rebuild/docs/best-practises/FastAPI-best-practises.md`.
   - `realtime-engineer` — `rebuild/docs/best-practises/FastAPI-best-practises.md` (call out sections A.2 / A.7 / A.8 / B.6).
   - `svelte-engineer` — `rebuild/docs/best-practises/svelte-best-practises.md`, `rebuild/docs/best-practises/sveltekit-best-practises.md`, **plus** the impeccable command from the routing table, `.cursor/skills/impeccable/SKILL.md`, `.cursor/skills/impeccable/PROJECT.md`, and the project context under `.cursor/skills/impeccable/project/`.
   - `test-author` — the same best-practises file(s) as the layer it is testing.
   - `verifier` — the same best-practises file(s) as the layer it is verifying.
5. Specify what to return: list of files created/changed, any tests added, anything it deferred or refused, **and the list of best-practises files (and impeccable refs, where relevant) it actually loaded vs already had cached**. For `svelte-engineer`, also require the eight-line design self-critique result described in `.cursor/agents/svelte-engineer.md` § Handoff message contract.

Mark each TodoWrite item `completed` as soon as its subagent returns, and update the next one to `in_progress`.

### Phase 4 — Drift sweep and verification

After all implementation subagents return:

1. If any subagent reported it added a column/index/route/event/store that wasn't in the plan, dispatch `plan-keeper` with the diff. `plan-keeper` updates the milestone plan; never let implementation subagents edit plans.
2. Dispatch `verifier` with the full list of changes from this run. Wait for its three-bucket report (Verified and passing / Claimed but incomplete or broken / Risks not blocking).
3. If `verifier` flags incomplete work, do not auto-fix. Surface the report to the user and ask whether to re-dispatch the relevant specialist or accept the gap.

### Phase 5 — Final report to the user

Summarise in this shape:

- **Scope implemented** — bullet list, mapped to plan sections.
- **Subagents dispatched** — table of subagent name, task summary, status (succeeded / partial / failed). Include the impeccable command for each `svelte-engineer` row.
- **Files changed** — grouped by directory (`rebuild/backend/app/models/`, `rebuild/backend/alembic/versions/`, `rebuild/frontend/src/routes/`, etc.).
- **Verifier outcome** — copy the three-bucket summary.
- **Design self-critique** — for each `svelte-engineer` dispatch with a non-`none` impeccable command, copy the eight-line self-critique result. This is qualitative and lives next to (not inside) the verifier outcome.
- **Plan drift** — what `plan-keeper` updated, if anything.
- **Deferred** — anything the user scoped out, anything subagents declined to do, anything left for a follow-up. Include any design-self-critique items marked deferred and any token deviations the svelte-engineer kept with justification.

Do not commit changes unless the user explicitly asks. The repo's `AGENTS.md` requires `make format` before commit; if the user does ask to commit, dispatch `verifier` once more after running it.

## Worked example (M3 sharing)

User says: `implement m2`.

Phase 0: read `rebuild/docs/plans/m3-sharing.md` and `rebuild.md` §9.

Phase 1 dispatch plan:

- `db-architect`: create `0003_m3_sharing.py` with the `shared_chat` table (token-only, snapshot history JSON, no access table per `rebuild.md` §3); add `share_id?` column to `chat`.
- `fastapi-engineer`: add `POST /api/chats/{id}/share`, `DELETE /api/chats/{id}/share`, `GET /s/{token}` per the m3-sharing.md API surface section. Token generation uses `secrets.token_urlsafe(32)`.
- `svelte-engineer` (impeccable: `craft` for the new public route, `polish` for the chat-header share button): add `(public)/s/[token]/+page.svelte` route reusing the M2 message renderer in read-only mode; add a Share button on the chat header that calls the new endpoints and copies the URL to clipboard. The public read-only view is a net-new surface so it gets `craft` and `shape`; the header button is a small additive change so it gets `polish`.
- `test-author`: unit test for token generation collision rate; component test for the read-only message renderer; E2E for "share chat → second context (different `X-Forwarded-Email`) opens `/s/:token` → reads → revoke → 404".
- `verifier`: lint, typecheck, test-unit, test-component, test-e2e-smoke; grep for bare `Depends`, `uuid.uuid4`, `datetime.utcnow`.

Phase 2: present the table, confirm scope.

Phase 3: dispatch `db-architect` first (blocking). Then `fastapi-engineer` and `svelte-engineer` in parallel after waiting for the schema. Then `test-author` once both implementation subagents return.

Phase 4: `verifier`. If it passes all three buckets, no drift sweep needed.

Phase 5: report.

## Anti-patterns (do not do these)

- **Do not write code yourself.** If you find yourself reaching for `Write` or `StrReplace`, you've collapsed into one of the subagents and lost the context-isolation benefit.
- **Do not skip `plan-keeper` when scope contradicts a locked decision.** Locked decisions are locked for a reason; surface the contradiction and let the user pick.
- **Do not skip `verifier`.** Even on a "tiny" change. The whole point of the regression-first strategy is that nothing ships without the gate.
- **Do not parallelise across dependency edges.** Schema before code-that-queries-it, API before UI. Parallelism only inside a phase.
- **Do not let an implementation subagent edit `rebuild/docs/plans/`.** Only `plan-keeper` touches plans.
- **Do not silently rescope.** If you implemented less than the user asked, the final report's *Deferred* section names every gap.
- **Do not strip the impeccable command from a `svelte-engineer` dispatch.** Even on a "tiny port", it still gets `polish`. The whole point of layering impeccable into `svelte-engineer` is that no visual change escapes the design loop. The only legal value for "no impeccable" is `none`, reserved for bug fixes with zero visual delta.
- **Do not let `verifier` substitute for design self-critique.** `verifier` checks lint, types, and tests. It does not check whether a surface looks like AI slop, whether tokens were used, or whether copy has em dashes. The design self-critique from `svelte-engineer` is the orthogonal gate; both must pass.
