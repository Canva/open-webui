# Impeccable — Project Overlay (Open WebUI Canva Fork)

This file scopes the global impeccable skill to this repository. Read it **after** `SKILL.md` and **before** any `reference/*.md` file. Where this overlay disagrees with `SKILL.md`, this overlay wins.

## Register: locked to `product`

Every surface in this repo is a product surface (app shell, chat, channels, settings, admin). There is no brand surface. Skip register detection and skip [reference/brand.md](reference/brand.md). Always load [reference/product.md](reference/product.md).

## Context loading

Do **not** run `scripts/load-context.mjs`. The repo has no Node dependency on it and subagents may run in environments without `node` on `PATH`. Instead, read the project context files directly:

1. `.cursor/skills/impeccable/project/PRODUCT.md` — users, brand personality, anti-references, design principles.
2. `.cursor/skills/impeccable/project/DESIGN.md` — colors, typography, elevation, components, do's/don'ts.
3. `.cursor/skills/impeccable/project/DESIGN.json` — machine-readable token table for color and component values.

The repo root also has `PRODUCT.md`, `DESIGN.md`, `DESIGN.json` — these are the canonical sources, mirrored here so the skill is self-contained. If the root files have diverged from the project copies, prefer the root files and dispatch `plan-keeper` to reconcile.

`scripts/live.mjs`, `scripts/pin.mjs`, and `scripts/load-context.mjs` are kept for completeness but are **not** part of the rebuild's workflow. The rebuild relies on the human dev server (`make dev`) and Playwright visual baselines for iteration, not on the live-injection harness.

## Project-specific absolute bans

These are layered **on top of** the global bans in `SKILL.md` § Absolute bans. They are lifted directly from `PRODUCT.md` anti-references and `DESIGN.md` don'ts. Treat them as build-blocking.

- **No ChatGPT-clone layout.** No centered prompt-in-a-void landing. The sidebar stays. History stays structured. Agent identity stays in the chrome. If a new route looks like `chat.openai.com`'s home, rework it.
- **No model-forward chrome.** Raw model identifiers (`gpt-4o-2024-08-06`, `claude-3-5-sonnet-*`) never sit in primary chrome. Surface them only as Muted Ink label-scale metadata under the agent's name. The agent is the noun; the model is an attribute.
- **No SaaS hero-metric template.** Big number + three stat cards + gradient CTA is forbidden on every admin and dashboard surface.
- **No second decorative hue.** `Mention Sky` (`oklch(0.69 0.17 237)`) is the only decorative color in the chrome. New features get weight contrast or ramp contrast for emphasis, never a second hue. Status hues (`Success`, `Warning`, `Danger`, `Signal Blue`) are semantic-only and never adjacent.
- **No tinted neutrals.** The gray ramp is literally zero chroma. Do not drift warm or cool. The coldness is intentional.
- **No `#000` or `#fff`.** Use the `Ink Black` / `Paper White` tokens from `DESIGN.json`.
- **No gradient text.** `background-clip: text` over a gradient is banned. Solid ink only.
- **No side-stripe borders.** `border-left` or `border-right` greater than 1px as a colored accent is banned. Use full hairlines, background tints, or leading icons.
- **No glassmorphism as default.** Blur is the depth cue for **modals, popovers, and the message input only** — not for cards in the page flow. See `DESIGN.md` § Flat-Until-Floating.
- **No drop shadows on flowing surfaces.** A card sitting in a grid does not get a shadow. Shadows belong to elements that detach from flow (dialogs, menus, message input, drag previews).
- **No layout-property animation.** Transform and opacity only. No animated `width`, `height`, `top`, `padding`. Respect `prefers-reduced-motion`.
- **No bouncy / elastic / consumer-warmth motion.** Ease out with exponential curves under 200ms. No confetti, no celebratory bounces, no purple Discord warmth.
- **No em dashes (`—`) or `--` in copy.** Use commas, colons, semicolons, periods, or parentheses. (The `SKILL.md` already bans this; restating because it's the most common slip.)
- **No hard-coded `left`/`right` in layout.** Use logical properties (`inline-start`, `inline-end`) or Tailwind `ms-*` / `me-*`. RTL is a latent requirement (`Vazirmatn` is bundled).
- **No `Vazirmatn`-less font stacks.** Every new font stack includes `Vazirmatn`. New stacks without it fail review.
- **No InstrumentSerif outside named editorial moments.** It exists in the app and stays rare. Never used for body, labels, or generic emphasis.
- **No hard-coded pixel line-heights outside the `--app-text-scale` system.** See `DESIGN.md` § Scale-Text-Scale Rule.

## Token-first styling

`DESIGN.md` and `DESIGN.json` define the named tokens (`Workshop Dark`, `Page Fill`, `Body Ink`, `Mention Sky`, `rounded.3xl`, `spacing.row-x`, etc.). Use them. Ad-hoc Tailwind classes that bypass the token vocabulary (`bg-gray-900`, `text-blue-500`, `rounded-[14px]`, `p-[7px]`) are slop unless `DESIGN.md` cannot express the rule and you've documented the gap inline.

When porting from `src/lib/components/`, replace upstream's color and radius classes with token-aligned ones as you go. Do not preserve `bg-white dark:bg-gray-900` if `bg-paper-white dark:bg-workshop-dark` (or the equivalent CSS-variable form used by the rebuild's Tailwind 4 config) is the right answer.

## Command routing for `svelte-engineer`

The svelte-engineer subagent picks one impeccable command per task, based on the work shape. Pick before coding; do not switch mid-task.

| Work shape | Command | Notes |
|---|---|---|
| Net-new visually-significant route or component (no upstream equivalent) | `craft` | Run `shape` first. Skip Step 3 (north-star image generation) — the rebuild has no image tool and the design system is already authored. |
| Net-new component that is a small variation of an existing one | `polish` | Build to spec, then run polish. Don't `craft` minor variants. |
| Legacy port from `src/lib/components/{chat,channel,automations}/` | `polish` then `harden` | Strip dead imports + violate-bans first; then handle empty/loading/error/edge states. **Do not** `craft` a port — that is scope creep into redesign. |
| Style refresh on existing rebuild surface | `polish` (or `bolder` / `quieter` / `distill` if explicitly briefed) | Targeted, no rewrite. |
| Bug fix with no visual delta | none | Skip the design loop. Mechanical rules from `svelte-best-practises.md` still apply. |
| Pre-milestone sweep across multiple surfaces | `audit` then `polish` per finding | Generate the checklist first, then fix. |
| Adding empty states, error states, first-run flows | `onboard` then `harden` | Production-readiness pass. |
| Adapting a component for new viewports | `adapt` | Don't just shrink — redesign for the new context. |
| UI feels slow or janky | `optimize` | Diagnose before changing. |
| Copy / labels / error message work | `clarify` | UX writing pass. |

## Workflow alignment with `svelte-engineer.md`

When `svelte-engineer.md` says "load impeccable context", that means:

1. Read `.cursor/skills/impeccable/SKILL.md` for the global laws and command surface.
2. Read this file (`.cursor/skills/impeccable/PROJECT.md`) for the register lock and project bans.
3. Read `.cursor/skills/impeccable/project/PRODUCT.md` and `project/DESIGN.md` for the brand context and design system.
4. Read the matching `reference/` file for the impeccable command picked from the routing table above. At minimum always read `reference/product.md`. Add `reference/spatial-design.md` and `reference/typography.md` for any visual change. Layer in `reference/motion-design.md`, `reference/responsive-design.md`, `reference/color-and-contrast.md`, `reference/interaction-design.md`, `reference/ux-writing.md` based on the task.

Skip step 3 if the same set of files was already loaded earlier in the session and neither root file has been touched since.

## Conflict resolution

When you have to pick between sources, this is the order of authority for `svelte-engineer`:

1. **Milestone plan** in `rebuild/plans/` — wins on **scope, file paths, API contracts, deliverables**.
2. **`rebuild.md` § 9 (locked decisions)** — wins on **architectural facts** (UUID source, datetime helper, no access tables for share, etc.).
3. **`PRODUCT.md` + `DESIGN.md` + this file** — win on **visual decisions, copy, component structure**.
4. **`SKILL.md` + `reference/`** — win on **craft technique** (color theory, type scale, motion curves, AI-slop test).
5. **`svelte-best-practises.md` + `sveltekit-best-practises.md`** — win on **runes, store, TS mechanics**.
6. **Upstream `src/` patterns** — never authoritative. They are reference for what to *port*, never for what is *correct*.

If two of (3) (4) (5) conflict, pick the answer that scores highest on the AI-slop test and the category-reflex check from `SKILL.md`. If that doesn't break the tie, surface the conflict in the handoff message and let the orchestrator decide.

## Self-critique before handoff

The svelte-engineer's design self-critique step runs the following checks against the new or changed surface, and the handoff message lists the result of each:

1. **AI-slop test** — would a designer say "AI made that" without doubt? If yes, fix.
2. **Category-reflex check** — could the theme/palette be guessed from the domain alone (chat → ChatGPT clone, admin → SaaS dashboard)? If yes, rework the scene sentence and color strategy.
3. **Token compliance** — every color, radius, spacing, typography choice traces to `DESIGN.json`. List any deliberate deviations with one-line justification.
4. **Absolute-bans pass** — none of the global or project-specific bans triggered. List any that needed an exception (with justification).
5. **State coverage** — empty, loading, error, overflow, first-run states are present and feel intentional.
6. **Responsive coverage** — the surface adapts (not just shrinks) at the breakpoints `DESIGN.md` calls out for this surface type.
7. **RTL parity** — no hard-coded directional layout; `Vazirmatn` present in any new font stack.
8. **`prefers-reduced-motion`** — any added motion is gated.

This self-critique is **independent** from `verifier`'s lint/typecheck/test gates. Both must pass before the work is considered done.
