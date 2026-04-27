# Product

## Register

product

## Users

Canva employees — primarily engineers, designers, analysts, and operations — using this as an internal AI workspace. The context is "day job": usually a second-or-third tab during focused work, occasionally the primary tab for longer sessions (agent runs, RAG against internal docs, drafting, analysis). Users are technically fluent, expect keyboard-first ergonomics, and are comparing the surface against the tools they already love (Linear, Figma, Raycast, internal Canva tooling).

The job to be done is "let me get real work done with agents and internal context, inside a surface Canva controls." Not "let me explore what an LLM can do." That framing drives every UI decision below.

## Product Purpose

A Canva-owned fork of open-webui, shaped into an internal AI workspace. The fork exists because Canva needs:

- A self-hosted chat surface where data boundaries are explicit and internal.
- The ability to customize — branding, defaults, workspace structure, integrations — without waiting on upstream.
- A home for **agents** (named, purposeful, composable) rather than a zoo of raw model endpoints.

Success looks like: employees choose this over external AI tools for internal work, not because policy forces them to, but because it's the better tool for the job.

## Brand Personality

Expert, confident, quiet. Three words: **precise, composed, kinetic.**

- **Precise** — every affordance earns its place. Labels are exact. Defaults are opinionated.
- **Composed** — the surface never performs excitement. No gradients-on-gradients, no bouncing emoji, no celebratory confetti. Visual calm is the tell of a serious tool.
- **Kinetic** — things happen fast. Keyboard-first. Latency perceived as zero. Motion is functional, not decorative.

The voice is a senior engineer who knows exactly what you're trying to do and respects your time.

## Anti-references

- **ChatGPT's consumer surface.** The "ask me anything" void with a centered prompt and a beige gradient is the explicit foil. We are not a general assistant; we are a workspace with agents, context, and history as first-class citizens. Any layout that reads as "ChatGPT clone" is a miss.
- **Model-forward UI.** Surfacing model names (`gpt-4o-2024-08-06`, `claude-3-5-sonnet-20241022`) as the primary identity of a conversation is upstream's default and we want to deprecate that framing. Agents are the user's mental model; the model underneath is an implementation detail exposed only when it needs to be.
- **Generic SaaS dashboard.** Hero metric, three stat cards, call-to-action gradient. No.
- **Crypto/AI-neon.** Glow cores, black backgrounds with magenta-cyan gradients, grid floors. Reads as hype, not craft.
- **Discord / consumer-social warmth.** Rounded everything, purple accents, confetti. Wrong register for work.
- **Notion's "everything is a document" flatness** when it gets in the way of app-shell density. We steal Notion's calm, not its paginated editor-ness.

## Design Principles

1. **Agents over models.** The primary noun is the agent (its name, purpose, tools, memory). The model is a secondary attribute, surfaced where it matters (capability, cost, context window) and hidden where it doesn't. Every surface that currently reads "which model?" should be reconsidered as "which agent?"
2. **Density with air.** Expert tools earn their keep by showing more, not less. Pack information, but space it with deliberate rhythm — not with uniform padding, not with walls of cards. Reach for full-width rows, tight lists, and inline affordances before reaching for modals or grids.
3. **Keyboard is a first-class surface.** Every frequent action has a shortcut. The command palette is canonical. Mouse paths are parallel affordances, not the primary one.
4. **Distinctly not-ChatGPT.** When in doubt about a visual decision, pick the one that makes this look less like the consumer chat template and more like a tool. Sidebar stays. History is structured. Agents are named in the chrome.
5. **Customize without forking forever.** Branding, defaults, and workspace conventions should live in clearly-named configuration layers, not scattered inline overrides. Every divergence from upstream should be intentional, defensible, and easy to identify when pulling from upstream.

## Accessibility & Inclusion

No formal WCAG target committed. Pragmatic baseline to hold while we don't have one:

- Don't rely on color alone to convey meaning — pair with icon, text, or shape.
- Keep text contrast readable in both light and dark themes; favor tinted neutrals over pure black/white.
- Preserve keyboard focus visibility; don't strip outlines without replacing them.
- RTL is already a latent concern — `Vazirmatn` is bundled. Don't introduce layout that breaks in RTL.
- Respect `prefers-reduced-motion` for any non-trivial motion added.

Revisit if and when a formal commitment is set.
