# Product

## Register

product

## Users

Canva employees — primarily engineers, designers, analysts, and operations — using this as an internal AI workspace. The context is "day job": usually a second-or-third tab during focused work, occasionally the primary tab for longer sessions (agent runs, RAG against internal docs, drafting, analysis). Users are technically fluent, expect keyboard-first ergonomics, and are comparing the surface against the tools they already love (Linear, Figma, Raycast, Obsidian, Cursor, internal Canva tooling).

The job to be done is "let me get real work done with agents and internal context, inside a surface Canva controls." Not "let me explore what an LLM can do." That framing drives every UI decision below.

## Product Purpose

A Canva-owned fork of open-webui, shaped into an internal AI workspace. The fork exists because Canva needs:

- A self-hosted chat surface where data boundaries are explicit and internal.
- The ability to customize — branding, defaults, workspace structure, integrations — without waiting on upstream.
- A home for **agents** (named, purposeful, composable) rather than a zoo of raw model endpoints.

Success looks like: employees choose this over external AI tools for internal work, not because policy forces them to, but because it's the better tool for the job.

## Brand Personality

Expert, confident, quiet — but not joyless. Four words: **precise, composed, kinetic, coloured.**

- **Precise** — every affordance earns its place. Labels are exact. Defaults are opinionated.
- **Composed** — the surface never performs excitement. No bouncing emoji, no celebratory confetti, no glow cores. The calm comes from rhythm and restraint, not from refusing to use colour.
- **Kinetic** — things happen fast. Keyboard-first. Latency perceived as zero. Motion is functional, not decorative.
- **Coloured** — this is a tool people stare at for hours, on a deep base, with saturated accents that earn their place. Think of an editor theme on an engineer's primary monitor: the colour _is_ the calm. The default presentation is dark, the palette is rich, and individual surfaces are tuned distinctly so the eye knows where the chrome ends and the work begins. Colour carries information (status, mention, code), atmosphere (which room you are in), and personalisation (which preset you chose). Greyscale-everything reads as "draft," not "considered."

The voice is a senior engineer who knows exactly what you're trying to do, respects your time, and has good taste in editor themes.

## References (the surfaces we want to feel adjacent to)

- **Linear.** The benchmark for keyboard ergonomics, command palette canon, and "calm density" — list rows, restrained chrome, motion that means something. Linear sets the _behavioural_ baseline for the app shell.
- **Obsidian, themed with [Tokyo Night](https://github.com/tcmmichaelb139/obsidian-tokyonight).** The benchmark for _colour with intent_. A deep navy/indigo base, distinct panel tints (sidebar / editor / status bar each occupy their own ramp step), and a small saturated accent palette (cyan for the active selection, soft magenta for headings, green for success, orange for warnings) used sparingly but consistently. Tokyo Night is what we look like, in spirit and in default palette: dark by default, four named variants (`Day`, `Storm`, `Moon`, `Night`), and a code/markdown highlighting theme that descends from the same palette so the chrome and the content harmonise. Reference repo: <https://github.com/tcmmichaelb139/obsidian-tokyonight>.
- **Cursor / a good IDE theme.** The expectation that an "expert tool" lets the user pick the room they sit in. Theme choice is a personal-preference setting, not a marketing surface.

## Anti-references

- **ChatGPT's consumer surface.** The "ask me anything" void with a centered prompt and a beige gradient is the explicit foil. We are not a general assistant; we are a workspace with agents, context, and history as first-class citizens. Any layout that reads as "ChatGPT clone" is a miss.
- **Model-forward UI.** Surfacing model names (`gpt-4o-2024-08-06`, `claude-3-5-sonnet-20241022`) as the primary identity of a conversation is upstream's default and we want to deprecate that framing. Agents are the user's mental model; the model underneath is an implementation detail exposed only when it needs to be.
- **Generic SaaS dashboard.** Hero metric, three stat cards, call-to-action gradient. No.
- **Crypto/AI-neon.** Glow cores, magenta-cyan rainbow gradients, grid floors with bloom. Tokyo Night is _saturated_ without being _neon_ — the difference is that ours is muted by the OKLCH lightness of the base, and we never gradient our accents. Reads as hype, not craft.
- **Discord / consumer-social warmth.** Rounded everything, purple-on-purple, confetti, "✨" sparkles in chrome. Wrong register for work.
- **Notion's "everything is a document" flatness** when it gets in the way of app-shell density. We steal Notion's calm, not its paginated editor-ness.
- **Pure greyscale "minimalism."** Slack's circa-2018 grey-on-grey, Apple's macOS Mail, the "just remove all colour" school of design. That's not restraint, that's vacuum. We removed gratuitous colour, not all colour.

## Design Principles

1. **Agents over models.** The primary noun is the agent (its name, purpose, tools, memory). The model is a secondary attribute, surfaced where it matters (capability, cost, context window) and hidden where it doesn't. Every surface that currently reads "which model?" should be reconsidered as "which agent?"
2. **Density with air.** Expert tools earn their keep by showing more, not less. Pack information, but space it with deliberate rhythm — not with uniform padding, not with walls of cards. Reach for full-width rows, tight lists, and inline affordances before reaching for modals or grids.
3. **Keyboard is a first-class surface.** Every frequent action has a shortcut. The command palette is canonical. Mouse paths are parallel affordances, not the primary one.
4. **Distinctly not-ChatGPT.** When in doubt about a visual decision, pick the one that makes this look less like the consumer chat template and more like a tool. Sidebar stays. History is structured. Agents are named in the chrome.
5. **Colour with intent — dark by default.** The default presentation is dark (`prefers-color-scheme` honoured: dark → Tokyo Night, light → Tokyo Day). Saturated accents (cyan, magenta, green, orange, yellow) carry meaning — selection, mention, success, warning, info — and never decorate for decoration's sake. Distinct surfaces (top bar, sidebar, message pane, code block, popover) sit at distinct ramp steps within the chosen palette so the eye reads "rooms," not a single flat plane. Greyscale is a _fallback_, not the goal.
6. **Personalisation is a respected affordance.** Every Canva employee gets to pick the room they sit in: a small set of curated theme presets (Tokyo Day / Storm / Moon / Night to start) is a settings-tier choice, persisted client-side per device. Default is OS-mapped; the user override beats the OS preference; both beat the page-load default. Theme choice is _not_ a marketing surface — it lives in a quiet settings dropdown, not a popup or onboarding flow.
7. **Customize without forking forever.** Branding, defaults, and workspace conventions should live in clearly-named configuration layers, not scattered inline overrides. Every divergence from upstream should be intentional, defensible, and easy to identify when pulling from upstream.

## Accessibility & Inclusion

No formal WCAG target committed. Pragmatic baseline to hold while we don't have one:

- Don't rely on color alone to convey meaning — pair with icon, text, or shape. (Tokyo Night's accents are _signals_, not the only signal.)
- Every theme preset carries a contrast budget: body ink ≥ 4.5:1 against the message-pane background; secondary ink ≥ 3:1; status badge text ≥ 4.5:1 against its tinted fill. The four shipping presets (Day, Storm, Moon, Night) all clear this bar; new presets must clear it before they ship.
- Respect `prefers-color-scheme` for the _default_ (dark → Night, light → Day). The user's explicit choice always wins over the OS, and it persists per device.
- Preserve keyboard focus visibility; don't strip outlines without replacing them. The selection accent (cyan in the Tokyo Night family) is the focus colour by default.
- RTL is already a latent concern — `Vazirmatn` is bundled. Don't introduce layout that breaks in RTL.
- Respect `prefers-reduced-motion` for any non-trivial motion added.

Revisit if and when a formal commitment is set.
