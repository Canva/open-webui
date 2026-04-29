---
name: implement-plan
description: Implement a rebuild milestone plan (or a scoped sub-section of one) by breaking it into concrete actions, mapping each action to the correct specialist subagent (db-architect, fastapi-engineer, realtime-engineer, svelte-engineer, test-author, verifier, plan-keeper), and dispatching them in dependency order. Use when the user says "implement m1/m2/m3/m4/m5", "implement the <feature> plan", "build out <section> from the milestone", "execute the milestone", or any phrasing that asks to turn a written plan in `rebuild/plans/` into shipped code.
---

# Implement a Rebuild Milestone Plan

You are the orchestrator. Your job is to turn a written milestone plan (or a scoped piece of one) into shipped code by delegating to the seven specialist subagents in `.cursor/agents/`. You do not write code yourself in this flow — you read, plan, dispatch, and report.

## Available subagents (anchor these names exactly)

| Subagent | Owns | Read order |
|---|---|---|
| `plan-keeper` | `rebuild.md`, milestone plans, best-practises files (read-only) | First (scope check), last (drift sweep) |
| `db-architect` | SQLAlchemy models, Alembic revisions, indexes, constraints | Phase 1 |
| `fastapi-engineer` | Routers, schemas, services, dependencies | Phase 2 |
| `realtime-engineer` | SSE, `StreamRegistry`, socket.io + Redis adapter, webhooks | Phase 2 (parallel with fastapi when independent) |
| `svelte-engineer` | SvelteKit routes, runes stores, Tailwind 4 components | Phase 3 |
| `test-author` | Vitest unit, Playwright CT/E2E, visual baselines, MSW, LLM cassettes | Phase 4 (and proactively per layer) |
| `verifier` | Runs lint/typecheck/test gates and grep checks | Final phase (read-only, fast model) |

## Workflow

Run these phases in order. Do not skip.

### Phase 0 — Scope and read

1. Identify the target plan from the user's request. If they said "m3" or "channels", that's `rebuild/plans/m3-channels.md`. If they named a sub-section ("the SSE streaming pipeline", "the file upload bits"), keep that scope front-of-mind for every later phase.
2. Read the plan in full. Specifically locate these sections (names may vary slightly per milestone):
   - **Goal** — one paragraph framing.
   - **Deliverables** — the bullet list of files to create.
   - **Data model** — tables, columns, indexes, constraints.
   - **API surface** — routes, payloads, status codes.
   - **Realtime / Streaming-pipeline / Socket.io** sections (M1 and M3).
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
| New SvelteKit route, new component, new store (`*.svelte.ts`), Tailwind work, legacy port with dead-import strip | `svelte-engineer` |
| Unit test, component test, E2E test, multi-context test, visual baseline, MSW handler, LLM cassette | `test-author` |
| Acceptance-criteria sweep, regression-first gate enforcement, grep checks for non-negotiables | `verifier` |
| Plan edit (data-model row, API surface row, deliverable bullet) | `plan-keeper` |

Now create a TodoWrite list with one todo per subagent dispatch. Keep todo descriptions specific (not "do db work" — say "create `0004_m3_channels.py` with all tables in m3-channels.md § Data model"). Mark the first phase-1 todo as `in_progress` and present the full list to the user before launching anything.

### Phase 2 — Confirm with the user

Before dispatching any subagent, surface the dispatch plan as a brief table:

- Phase 1 (sequential): list of `db-architect` invocations with one-line task each.
- Phase 2 (parallel where possible): `fastapi-engineer` and `realtime-engineer` invocations.
- Phase 3 (sequential after Phase 2): `svelte-engineer` invocations.
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
4. Specify what to return: list of files created/changed, any tests added, anything it deferred or refused.

Mark each TodoWrite item `completed` as soon as its subagent returns, and update the next one to `in_progress`.

### Phase 4 — Drift sweep and verification

After all implementation subagents return:

1. If any subagent reported it added a column/index/route/event/store that wasn't in the plan, dispatch `plan-keeper` with the diff. `plan-keeper` updates the milestone plan; never let implementation subagents edit plans.
2. Dispatch `verifier` with the full list of changes from this run. Wait for its three-bucket report (Verified and passing / Claimed but incomplete or broken / Risks not blocking).
3. If `verifier` flags incomplete work, do not auto-fix. Surface the report to the user and ask whether to re-dispatch the relevant specialist or accept the gap.

### Phase 5 — Final report to the user

Summarise in this shape:

- **Scope implemented** — bullet list, mapped to plan sections.
- **Subagents dispatched** — table of subagent name, task summary, status (succeeded / partial / failed).
- **Files changed** — grouped by directory (`rebuild/backend/app/models/`, `rebuild/backend/alembic/versions/`, `rebuild/frontend/src/routes/`, etc.).
- **Verifier outcome** — copy the three-bucket summary.
- **Plan drift** — what `plan-keeper` updated, if anything.
- **Deferred** — anything the user scoped out, anything subagents declined to do, anything left for a follow-up.

Do not commit changes unless the user explicitly asks. The repo's `AGENTS.md` requires `make format` before commit; if the user does ask to commit, dispatch `verifier` once more after running it.

## Worked example (M2 sharing)

User says: `implement m2`.

Phase 0: read `rebuild/plans/m2-sharing.md` and `rebuild.md` §9.

Phase 1 dispatch plan:

- `db-architect`: create `0003_m2_sharing.py` with the `shared_chat` table (token-only, snapshot history JSON, no access table per `rebuild.md` §3); add `share_id?` column to `chat`.
- `fastapi-engineer`: add `POST /api/chats/{id}/share`, `DELETE /api/chats/{id}/share`, `GET /s/{token}` per the m2-sharing.md API surface section. Token generation uses `secrets.token_urlsafe(32)`.
- `svelte-engineer`: add `(public)/s/[token]/+page.svelte` route reusing the M1 message renderer in read-only mode; add a Share button on the chat header that calls the new endpoints and copies the URL to clipboard.
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
- **Do not let an implementation subagent edit `rebuild/plans/`.** Only `plan-keeper` touches plans.
- **Do not silently rescope.** If you implemented less than the user asked, the final report's *Deferred* section names every gap.
