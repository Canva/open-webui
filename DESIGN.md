---
name: Open WebUI (Canva Fork)
description: An internal AI workspace where agents, not models, are the primary noun. Dark by default, themed with the Tokyo Night family.
defaultTheme: 'tokyo-night'
themePresets:
  tokyo-day:
    label: 'Tokyo Day'
    mode: 'light'
    osPreference: 'light'
  tokyo-storm:
    label: 'Tokyo Storm'
    mode: 'dark'
    osPreference: null
  tokyo-moon:
    label: 'Tokyo Moon'
    mode: 'dark'
    osPreference: null
  tokyo-night:
    label: 'Tokyo Night'
    mode: 'dark'
    osPreference: 'dark'
colors:
  # The canonical palette below is "Tokyo Night" (the deepest of the four
  # presets and the dark-mode default). Every preset exports the same set of
  # named tokens; switching the preset re-points each token. Token names are
  # role-based (background-app, background-sidebar, accent-selection, …) so
  # components never reach for a hex; they reach for a role.
  background-app: 'oklch(0.235 0.026 270)'              # #1a1b26 — message-pane background
  background-sidebar: 'oklch(0.205 0.025 268)'          # #16161e — sidebar pane (one ramp step deeper than app)
  background-topbar: 'oklch(0.255 0.030 270)'           # #1f2335 — top bar (one ramp step lighter than app)
  background-elevated: 'oklch(0.285 0.034 268)'         # #24283b — popovers, modals, message-input lift
  background-code: 'oklch(0.190 0.022 268)'             # #13141c — code blocks (deepest, embeds in messages)
  background-mention: 'oklch(0.310 0.060 240)'          # mention pill fill (cyan-tinted at 30% lightness)
  hairline: 'oklch(0.330 0.030 268)'                    # #2a2e44 — 1px borders, dividers
  hairline-strong: 'oklch(0.420 0.034 268)'             # #3b4261 — focused border, hairline on hover
  ink-placeholder: 'oklch(0.520 0.022 270)'             # #565f89 — placeholder, disabled
  ink-muted: 'oklch(0.660 0.045 244)'                   # #7aa2f7-derived muted (timestamps, metadata)
  ink-secondary: 'oklch(0.770 0.030 254)'               # #a9b1d6 — secondary body
  ink-body: 'oklch(0.840 0.030 252)'                    # #c0caf5 — primary body text
  ink-strong: 'oklch(0.920 0.022 240)'                  # #d5d6db — emphasis, modal title
  accent-selection: 'oklch(0.770 0.130 220)'            # #7dcfff — focus ring, selection, primary CTA fill
  accent-selection-pressed: 'oklch(0.690 0.140 222)'    # #45a4d6 — primary CTA hover/pressed
  accent-mention: 'oklch(0.770 0.150 245)'              # #7aa2f7 — @-mentions, links
  accent-headline: 'oklch(0.760 0.165 322)'             # #bb9af7 — markdown H1/H2/H3 inside messages
  accent-stream: 'oklch(0.820 0.160 145)'               # #9ece6a — live-stream dot, "agent is typing" pulse
  status-success: 'oklch(0.795 0.155 145)'              # #9ece6a — success badge, positive telemetry
  status-warning: 'oklch(0.810 0.135 80)'               # #e0af68 — warning badge
  status-danger: 'oklch(0.690 0.190 24)'                # #f7768e — error badge, destructive confirm
  status-info: 'oklch(0.755 0.155 245)'                 # #7aa2f7 — info badge
  # Code/mermaid swatches — one per primary syntax token. Mirrored from the
  # Tokyo Night editor palette and used by the Shiki theme + the Mermaid theme
  # block below. Components never read these directly; the highlighter does.
  syntax-keyword: 'oklch(0.760 0.165 322)'              # #bb9af7
  syntax-string: 'oklch(0.820 0.160 145)'               # #9ece6a
  syntax-comment: 'oklch(0.520 0.022 270)'              # #565f89 (= ink-placeholder)
  syntax-function: 'oklch(0.770 0.150 245)'             # #7aa2f7
  syntax-number: 'oklch(0.795 0.150 80)'                # #ff9e64
  syntax-tag: 'oklch(0.690 0.190 24)'                   # #f7768e
typography:
  display:
    fontFamily: 'Archivo, Vazirmatn, sans-serif'
    fontSize: 'clamp(1.75rem, 2.5vw, 2.25rem)'
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: '-0.01em'
    color: '{colors.ink-strong}'
  headline:
    fontFamily: 'Archivo, Vazirmatn, sans-serif'
    fontSize: '1.25rem'
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: '-0.005em'
    color: '{colors.ink-strong}'
  title:
    fontFamily: 'Inter, Vazirmatn, ui-sans-serif, system-ui, sans-serif'
    fontSize: '1.125rem'
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: 'normal'
    color: '{colors.ink-strong}'
  body:
    fontFamily: 'Inter, Vazirmatn, ui-sans-serif, system-ui, sans-serif'
    fontSize: '0.875rem'
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 'normal'
    color: '{colors.ink-body}'
  label:
    fontFamily: 'Inter, Vazirmatn, ui-sans-serif, system-ui, sans-serif'
    fontSize: '0.75rem'
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: '0.02em'
    color: '{colors.ink-secondary}'
  code:
    fontFamily: 'JetBrainsMono, ui-monospace, SFMono-Regular, Menlo, monospace'
    fontSize: '0.85em'
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 'normal'
    color: '{colors.ink-body}'
  serif-accent:
    fontFamily: 'InstrumentSerif, serif'
    fontSize: '1.5rem'
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: 'normal'
    color: '{colors.accent-headline}'
  markdown-h1:
    fontFamily: 'Archivo, Vazirmatn, sans-serif'
    fontSize: '1.5rem'
    fontWeight: 600
    lineHeight: 1.2
    color: '{colors.accent-headline}'
  markdown-h2:
    fontFamily: 'Archivo, Vazirmatn, sans-serif'
    fontSize: '1.25rem'
    fontWeight: 600
    lineHeight: 1.25
    color: '{colors.accent-headline}'
  markdown-h3:
    fontFamily: 'Inter, Vazirmatn, sans-serif'
    fontSize: '1.0625rem'
    fontWeight: 600
    lineHeight: 1.3
    color: '{colors.ink-strong}'
rounded:
  sm: '4px'
  md: '8px'
  lg: '12px'
  xl: '16px'
  '2xl': '20px'
  '3xl': '24px'
  '4xl': '32px'
  full: '9999px'
spacing:
  row: '6px'
  row-x: '11px'
  card: '16px'
  dialog: '28px'
components:
  button-primary:
    backgroundColor: '{colors.accent-selection}'
    textColor: '{colors.background-app}'
    rounded: '{rounded.3xl}'
    padding: '8px 16px'
    typography: '{typography.body}'
  button-primary-hover:
    backgroundColor: '{colors.accent-selection-pressed}'
    textColor: '{colors.background-app}'
    rounded: '{rounded.3xl}'
    padding: '8px 16px'
  button-secondary:
    backgroundColor: '{colors.background-elevated}'
    textColor: '{colors.ink-body}'
    rounded: '{rounded.3xl}'
    padding: '8px 16px'
    typography: '{typography.body}'
  button-secondary-hover:
    backgroundColor: '{colors.background-topbar}'
    textColor: '{colors.ink-strong}'
    rounded: '{rounded.3xl}'
    padding: '8px 16px'
  sidebar-item:
    backgroundColor: 'transparent'
    textColor: '{colors.ink-secondary}'
    rounded: '{rounded.xl}'
    padding: '6px 11px'
    typography: '{typography.body}'
  sidebar-item-active:
    backgroundColor: '{colors.background-elevated}'
    textColor: '{colors.ink-strong}'
    rounded: '{rounded.xl}'
    padding: '6px 11px'
  input-pill:
    backgroundColor: '{colors.background-app}'
    textColor: '{colors.ink-body}'
    borderColor: '{colors.hairline}'
    rounded: '{rounded.lg}'
    padding: '8px 16px'
    typography: '{typography.body}'
  message-input:
    backgroundColor: '{colors.background-elevated}'
    textColor: '{colors.ink-body}'
    borderColor: '{colors.hairline}'
    rounded: '{rounded.3xl}'
    padding: '8px 12px'
    typography: '{typography.body}'
  modal-surface:
    backgroundColor: '{colors.background-elevated}'
    textColor: '{colors.ink-body}'
    borderColor: '{colors.hairline-strong}'
    rounded: '{rounded.4xl}'
    padding: '24px 28px'
  badge-info:
    backgroundColor: '{colors.background-mention}'
    textColor: '{colors.accent-mention}'
    rounded: '{rounded.lg}'
    padding: '0px 5px'
    typography: '{typography.label}'
  code-block:
    backgroundColor: '{colors.background-code}'
    textColor: '{colors.ink-body}'
    borderColor: '{colors.hairline}'
    rounded: '{rounded.lg}'
    padding: '12px 16px'
    typography: '{typography.code}'
---

# Design System: Open WebUI (Canva Fork)

## 1. Overview

**Creative North Star: "The Lit Workshop"**

This is a craftsman's bench at night. The surface is where a Canva employee sits down with their **named agents** — picks one up, uses it, puts it back — alongside their tools, history, and context. The room is dim and the work is what is lit. Distinct surfaces (top bar, sidebar, message pane, code block) sit at distinct ramp steps within the chosen palette so the eye reads "rooms" rather than a single flat plane. Density and calm coexist because the colour does the spatial work that uniform padding and walls of cards used to do.

The aesthetic philosophy is **deep dark base, ramped panel surfaces, saturated accents on a budget**. The default palette is **Tokyo Night** ([source](https://github.com/tcmmichaelb139/obsidian-tokyonight)) — a navy/indigo dark base with cyan, magenta, green, orange, and a soft red accent set, all muted by the OKLCH lightness of the base so they read as *informed* rather than *neon*. Four presets ship in M1: **Tokyo Day** (the only light variant; OS-mapped when `prefers-color-scheme: light`), **Tokyo Storm** (slate-blue dark), **Tokyo Moon** (warmer dark), **Tokyo Night** (deepest dark, OS-default for `prefers-color-scheme: dark`).

Colour does three jobs in this system, and only these three:

1. **Information** — status (success / warning / danger / info), `@`-mentions, live-stream dot, focus ring.
2. **Atmosphere** — which room you are in. The sidebar, the top bar, and the message pane each get a distinct ramp step from the same palette; modals and popovers lift to a fourth step.
3. **Personalisation** — which preset you chose. The four presets are functionally interchangeable (every component renders against the same role-based tokens) but tonally distinct.

This system explicitly rejects ChatGPT's centered-prompt void, model-forward chrome (long slug IDs used as labels), SaaS hero-metric dashboards, crypto-neon (saturated *and* gradient *and* glow — we are saturated *only*), consumer-social warmth (Discord purple, confetti, sparkle emoji), Notion's "everything is a document" flatness when it fights app density, and pure-greyscale "minimalism" (which reads as draft, not restraint). Where other AI surfaces perform excitement, this one performs competence — but it dresses for the work.

**Key Characteristics:**

- Tokyo Night palette family as the canonical reference; four shipping presets (Day / Storm / Moon / Night).
- Distinct ramp step per surface (top bar, sidebar, message pane, elevated) within every preset.
- Dark-by-default; `prefers-color-scheme` honoured for the page-load default; user's explicit theme always wins.
- Saturated accents on a budget — five named accent tokens (`selection`, `mention`, `headline`, `stream`, plus the four `status-*` semantic hues). No second-tier decorative colour.
- Hybrid elevation: flat at rest, blurred-and-lifted for modals and popovers; shadow strength is *low* because the depth comes from the ramp-step contrast.
- Inter as the working face; Archivo for chrome headlines; JetBrainsMono for code; InstrumentSerif held in reserve.
- Radius language runs from 4px utility up to 32px for modal envelopes — large radii signal "floating," tight radii signal "embedded."
- Motion is under 200ms, functional, eased out. No bounce, no choreography. Theme switches are *instant* — no fade — so the user reads the palette change as deliberate.

## 2. Theme Presets

The four presets are the only theme choices the user sees. Each preset is a complete, self-contained set of values for every token in the `colors:` block above. Components never reach for a preset name; they reach for a role token (`background-sidebar`, `accent-selection`, etc.) and the active preset binds the token.

| Preset | Mode | OS-mapped when | Mood | Typical user |
|---|---|---|---|---|
| **Tokyo Day** | light | `prefers-color-scheme: light` | Crisp paper with restrained ink and saturated accents. The only light variant. | Outdoor café day, projector demo. |
| **Tokyo Storm** | dark | — (explicit choice) | Slate-blue dark; less saturated than Night, more contrast than Moon. | Office monitor in mixed lighting. |
| **Tokyo Moon** | dark | — (explicit choice) | Warmer dark with a softer ramp; the calmest of the four. | Long focus sessions. |
| **Tokyo Night** | dark | `prefers-color-scheme: dark` | Deepest dark with the most saturated accents. The default for the dark OS preference. | Late-night work; the brand-canonical look. |

**Resolution order (canonical, locked by [`rebuild/docs/plans/m1-theming.md`](rebuild/docs/plans/m1-theming.md)):**

1. If the user has explicitly chosen a theme this device, use it.
2. Otherwise, read `prefers-color-scheme`: `light` → `tokyo-day`, `dark` → `tokyo-night`.
3. Otherwise (UA does not report a preference), use `tokyo-night`.

The choice is **persisted client-side per device** (a cookie for SSR-correct first paint, mirrored to `localStorage` as the client source of truth). It is **never** persisted to the server database. A user switching devices intentionally re-picks. See [`rebuild/docs/plans/m1-theming.md` § Persistence](rebuild/docs/plans/m1-theming.md#persistence).

## 3. Colour Tokens

Every token below exists in *every* preset. Components ALWAYS reference the role token, never the literal value.

### Surface ramp (one row = one room)

| Token | Job |
|---|---|
| `background-app` | The message pane — the surface where the user is working. |
| `background-sidebar` | The conversation/channel/automation sidebar. One ramp step deeper than `background-app` so the eye reads a panel. |
| `background-topbar` | The top bar / page header. One ramp step lighter than `background-app` so the chrome reads as "elevated above" the work. |
| `background-elevated` | Modals, popovers, the message-input lift, dropdown menus. The "floating" surface. |
| `background-code` | Code blocks inside chat messages. Deepest of the surface ramp so the code reads as embedded. |
| `background-mention` | The fill behind `@`-mention pills. Sits at the same lightness as `background-elevated` but tinted toward the `accent-mention` hue. |

### Hairlines and ink

| Token | Job |
|---|---|
| `hairline` | 1px borders, dividers, message bubbles, code-block edges. Low contrast against the parent surface. |
| `hairline-strong` | Modal edge, focused input border, hover'd hairline. One step up from `hairline`. |
| `ink-placeholder` | Input placeholder, disabled body text. |
| `ink-muted` | Timestamps, metadata, "shared by" sublines. |
| `ink-secondary` | Sidebar items at rest, secondary body, supporting UI. |
| `ink-body` | Default body text. The reading surface. |
| `ink-strong` | Emphasis, modal titles, button-secondary text, sidebar-item active text. |

### Accents (used on a budget — never decorative)

| Token | Job | Allowed surfaces |
|---|---|---|
| `accent-selection` | Primary CTA fill, focus ring, selected-row left-edge cap, range selection. | Buttons, focus rings. Never: chrome decoration. |
| `accent-mention` | `@`-mention pill text, in-prose links, click-targets in markdown. | `@`-mention pills, hyperlinks. Never: button fills. |
| `accent-headline` | Markdown `#`/`##`/`###` headings *inside chat messages*. | Markdown content only. Never: chrome titles, navigation labels. |
| `accent-stream` | Live-stream dot, "agent is typing" pulse, the "streaming" SSE animation. | Realtime indicators only. |

### Status hues (semantic, never decorative)

| Token | Job |
|---|---|
| `status-success` | Success badge, positive telemetry, completed automation run. |
| `status-warning` | Warning badge, rate-limit nudge, "you have unsaved changes." |
| `status-danger` | Error badge, destructive-action confirm, failed automation run. |
| `status-info` | Info badge, "did you know" tip. |

Status hues appear at **20% opacity fill with the same hue at full saturation for the text** (e.g. `bg-{status-success}/20 text-{status-success}`). They are informational, never decorative, and never adjacent to each other.

### Named Rules

**The Role-Token Rule.** Components reference `background-app`, `accent-selection`, `ink-body`. They never reference a Tokyo Night hex value, never reference a preset name. This is what makes the four presets interchangeable.

**The One-Surface-Per-Room Rule.** Top bar, sidebar, message pane, elevated, code each get *one* ramp step. New surfaces map to one of the existing five — they don't introduce a sixth ramp step.

**The Accent-Budget Rule.** Four accent tokens (`selection`, `mention`, `headline`, `stream`) plus four semantic status hues. That's the entire decorative palette. New "decorative" colour requirements get rejected; the answer is weight, size, ink contrast, or one of the existing accents.

**The Model-Name Exile Rule.** Raw model identifiers (`gpt-4o-2024-08-06`, `claude-3-5-sonnet-*`) must never sit in primary chrome. If a model string is surfaced at all, it is secondary metadata under the agent's name, in `ink-muted` at label scale.

**The No-Greyscale-Default Rule.** Greyscale is *not* the canonical look. Every shipping preset has chroma in its base. Pull-requests that revert a coloured token to a zero-chroma neutral need a documented reason.

## 4. Typography

**Display Font:** Archivo (with Vazirmatn for RTL, sans-serif fallback)
**Body Font:** Inter (with Vazirmatn, ui-sans-serif, system-ui fallback chain)
**Label/Mono Font:** JetBrainsMono (with ui-monospace fallback)
**Markdown-heading accent:** `accent-headline` from the active preset (Tokyo Night → soft magenta `#bb9af7`)
**Reserve accent:** InstrumentSerif (rare; used only for named editorial moments, never in app chrome)

**Character:** Archivo carries chrome headlines with a humanist-geometric snap that reads more "tool" than "app." Inter does the heavy lifting for body and UI — neutral, tight, legible at 13–14px. Vazirmatn is specified on both so RTL surfaces don't fall back to a mismatched system font.

### Hierarchy

- **Display** (Archivo 600, `clamp(1.75rem, 2.5vw, 2.25rem)`, line-height 1.15, `ink-strong`): workspace landing headers, section titles on marketing-adjacent surfaces. Rare in the app shell.
- **Headline** (Archivo 600, 1.25rem, line-height 1.25, `ink-strong`): page-level titles inside the app — workspace headers, settings pages, modal titles above body.
- **Title** (Inter 500, 1.125rem, line-height 1.3, `ink-strong`): card and section titles. Modal title row uses this weight.
- **Body** (Inter 400, 0.875rem / 14px, line-height 1.5, `ink-body`): the dominant UI text size. Chat messages, list rows, form labels. Cap prose at 65–75ch where long-form content appears.
- **Label** (Inter 500, 0.75rem / 12px, line-height 1.4, letter-spacing 0.02em, `ink-secondary`): badge text (uppercase), metadata, hotkey hints, timestamps.
- **Code** (JetBrainsMono 400, 0.85em inline / 0.85rem block, line-height 1.5, `ink-body` on `background-code`): inline code spans and fenced code blocks. Syntax highlighting per § 8.
- **Markdown H1/H2** (`accent-headline`, weights and sizes per the YAML front-matter): markdown heading levels *inside chat messages*. The colour is the differentiator; in Tokyo Night this is the soft magenta `#bb9af7`. H3+ falls back to `ink-strong`.

### Named Rules

**The Serif-In-Reserve Rule.** InstrumentSerif (`.font-secondary`) exists in the app and must stay rare. It is reserved for named editorial moments — never for generic emphasis, never for body, never for labels.

**The RTL-First Rule.** Every font stack includes `Vazirmatn`. New stacks must include it. RTL parity is a latent requirement of this surface.

**The Scale-Text-Scale Rule.** The app supports `--app-text-scale` on `:root`. Custom line-heights and min-heights declared in pixel units must multiply through this variable. Hard-coding pixel line-heights outside the scale system is forbidden.

**The Markdown-Heading-Hue Rule.** Chat messages render markdown `#` and `##` in `accent-headline`. This is the *only* place an accent hue is used as text colour in body content (mentions and links use `accent-mention`, but those are inline atoms; headings are block-level). The value swaps with the preset.

## 5. Elevation

This system is **flat by default, blurred-and-lifted on demand**. Application surfaces — sidebar, main pane, chat rows, settings — carry no shadow; depth is conveyed by the ramp-step contrast in the colour system. Floating layers earn their lift: modals, popovers, tooltips, and the primary message input use a specific vocabulary.

### Shadow Vocabulary

- **Message Input Lift** (`box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.35), 0 4px 6px -4px rgb(0 0 0 / 0.35)` in dark presets; halved alpha in `tokyo-day`): the composing surface sits just above the chat with a gentle soft shadow. Signals "this is where you act." Shadow alpha is preset-aware so the dark presets get the deeper shadow they need to read above an already-dark base.
- **Modal Lift** (Tailwind `shadow-3xl` paired with `backdrop-blur-sm` and a 1px `hairline-strong` border on `background-elevated`): the primary modal envelope. The blur is the actual depth cue; the shadow is supporting; the ramp-step jump from `background-app` to `background-elevated` does most of the work.
- **Popover Blur** (`background-elevated/90` + `backdrop-blur-2xl`): tooltip-adjacent popovers (drag previews, transient hint cards). Very rarely used for persistent surfaces.

### Named Rules

**The Flat-Until-Floating Rule.** If a surface stays on the page flow, it is flat. Shadows exist only on elements that _detach_ from the flow (dialogs, menus, the message input, drag previews). A card that sits in a grid does not get a shadow — it gets a ramp-step background instead.

**The Ramp-Is-The-Depth Rule.** Our primary depth cue is the colour-ramp step between adjacent surfaces (sidebar deeper than app, top bar lighter than app, modal lifted via `background-elevated`). Reach for the ramp before reaching for a shadow.

**The Ghost-Border Rule.** Modals carry a 1px border of `hairline-strong`. This hairline replaces what a larger shadow would otherwise do — it defines the edge against the blurred backdrop without shouting.

## 6. Components

Components feel **tactile and confident**: crisp edges, decisive state changes, clear inversion on primary actions. Hover is visible. Selected state is unambiguous. Transitions are under 200ms.

### Buttons

- **Shape:** Pill radius for dialog actions (`rounded-3xl`, 24px); rounded-rectangle for compact inline buttons (`rounded-lg`, 8px); full-round only for icon chips.
- **Primary:** `accent-selection` background with `background-app` text — the primary CTA carries the active preset's selection accent (cyan in Tokyo Night). The text colour reaches for `background-app` (not white) so the contrast plays nicely against the saturated accent in every preset.
- **Hover / Focus:** Background shifts to `accent-selection-pressed` (one step deeper in chroma + lightness). No scale, no shadow change, no glow. Transition 150ms ease-out on background only.
- **Secondary:** `background-elevated` with `ink-body` text. Used for cancel, dismiss, and "less weighty" companions to a primary.
- **Tertiary / Ghost:** transparent at rest, `background-elevated` on hover. Used inside dense rows where a filled button would be too loud.

### Chips / Badges

- **Style:** `bg-{status}/20` (20% opacity) with text at the full status hue (e.g. `bg-status-success/20 text-status-success`); uppercase; `rounded-lg`; `text-xs` (label scale); `px-[5px]`. Same shape across all four presets — the hue swaps via the `status-*` tokens.
- **State:** Badges are not interactive. Use chip-style buttons (same shape, solid fill, hover-darken) when interactivity is needed.

### Cards / Containers

- **Corner Style:** `rounded-xl` (16px) for row-level containers; `rounded-2xl` (20px) for pane-level cards; `rounded-3xl` (24px) for large composing surfaces.
- **Background:** `background-app` for the primary surface; subcontainers step to `background-elevated`. Sidebar uses `background-sidebar`; top bar uses `background-topbar`. The ramp does the spatial work — adjacent surfaces are *always* one ramp step apart.
- **Shadow Strategy:** None by default. See § 5 Elevation.
- **Border:** Inherited from `@layer base` as `hairline` (1px). Cards that need stronger separation use `hairline-strong`. Thick or coloured borders are forbidden — depth comes from the ramp.
- **Internal Padding:** `px-[11px] py-[6px]` for list rows, `p-4` for compact cards, `px-[1.75rem] py-6` for dialog interior.

### Inputs / Fields

- **Style:** `background-app` background (so an input embedded in a card on `background-elevated` reads as inset, not lifted). `rounded-lg` for form fields, `rounded-3xl` for the large composing surface. Border is `hairline` at 1px.
- **Focus:** Border steps to `accent-selection`; no glow, no outer ring. Placeholder in `ink-placeholder`.
- **Error / Disabled:** Disabled inputs drop to 50% text opacity; error states use the `status-danger` ring at 1.5px.

### Navigation (Sidebar)

- **Style:** `background-sidebar` panel. Items are full-width rows with `rounded-xl` corners, `px-[11px] py-[6px]` padding, `ink-secondary` text at body scale. Selected row fills with `background-elevated` and lifts text to `ink-strong`; on hover (unselected) row fills with `background-elevated` at 50% to telegraph the interaction without committing.
- **Typography:** Body scale, weight 400. Active item does not bold — the background fill is the tell.
- **Mobile treatment:** Sidebar becomes a drawer; hit targets remain at the 32px min-height.

### Top Bar

- **Style:** `background-topbar` (one ramp step lighter than `background-app`) with `hairline` bottom border. 48px tall. Carries the agent name on the left, the model selector + share + settings on the right.
- **Typography:** Title (Inter 500, 1.125rem) for the agent name; Body for the model metadata under it.

### Signature Component — The Agent Message Input

The composing surface is the single most distinctive element in the app. `rounded-3xl` with `background-elevated`, `backdrop-blur-sm`, a `shadow-lg` lift (alpha tuned per preset), and a hairline border that shifts from `hairline/30` at rest to `hairline` on hover and `accent-selection` on focus-within. It sits above the chat without carving into it, and it answers to the agent — not a model dropdown. Model identifiers, when surfaced, appear as secondary metadata only.

### Signature Component — The Agent Chip

An agent's avatar appears at `size-[2.7rem]` with a `rounded-full` crop and a 1px `hairline` ring. Overlapping avatar stacks use `-space-x-4` to suggest a small roster. This chip is the primary identity marker for the agent-over-model hierarchy.

### Signature Component — The Theme Picker

A small dropdown in Settings (and reachable from the command palette as `Theme: …`). Renders the four presets as a 2×2 grid of preview tiles, each tile showing a miniature of the chosen preset's surface ramp + accent. The active preset is outlined in `accent-selection`. Switching is **instant** — no fade — so the user reads the change as deliberate. The picker is a settings-tier affordance, not an onboarding moment.

## 7. Code, Markdown, and Mermaid

Code blocks, markdown headings, and mermaid diagrams swap their palette with the chrome. The same `accent-headline`, `syntax-*`, and surface tokens drive Shiki's syntax highlighter and Mermaid's theme block. There is no "always-on" highlighter theme; the highlighter is a function of the active preset.

### Code blocks

- **Surface:** `background-code` (the deepest ramp step), `rounded-lg`, `hairline` border.
- **Inline `code`:** `ink-body` on `background-code` at 50% opacity; no border.
- **Fenced blocks:** Shiki theme `tokyo-night-{preset}` for each preset; the four bundled themes match the four presets, generated from the source palette so chrome and content harmonise.
- **Copy button:** ghost button at top-right; appears on row hover; `ink-muted` → `ink-body` on hover.

### Markdown headings inside chat

- `# H1` and `## H2` render in `accent-headline` (soft magenta in Tokyo Night). The hue swaps with the preset.
- `### H3` and below render in `ink-strong`. (We don't want a wall of magenta on a long doc paste.)

### Mermaid

A `mermaid.initialize({ theme: 'base', themeVariables: { … } })` block is generated from the active preset's tokens. `primaryColor` → `accent-selection`, `lineColor` → `hairline-strong`, `textColor` → `ink-body`, `mainBkg` → `background-elevated`. The same generator runs on every preset switch; mermaid re-renders the visible diagrams.

## 8. Do's and Don'ts

### Do:

- **Do** reach for role tokens (`background-app`, `accent-selection`, `ink-body`) in every component. Never hard-code a Tokyo Night hex.
- **Do** ship Tokyo Night as the dark default and Tokyo Day as the light default; honour `prefers-color-scheme` for the page-load default.
- **Do** keep the four-accent budget (`selection`, `mention`, `headline`, `stream`) plus four semantic status hues. New decorative colour requests get rejected; the answer is weight, size, ink contrast, or one of the existing accents.
- **Do** use `Workshop`-grade depth via the ramp-step contrast. Sidebar deeper than app; top bar lighter than app; elevated for floating; code deepest.
- **Do** cap body prose at 65–75ch where long-form content appears.
- **Do** use large radii (`rounded-3xl`, `rounded-4xl`) to signal "this surface is floating" (modals, input pills), and small radii (`rounded-lg`) to signal "this surface is embedded" (inputs, badges).
- **Do** name agents in the chrome. The model is metadata under the agent, never the primary title.
- **Do** include `Vazirmatn` in every new font stack for RTL parity.
- **Do** respect `prefers-reduced-motion` — transitions should become instant, not merely slower.
- **Do** swap the Shiki and Mermaid palette with the chrome. A code block on a Tokyo Storm chrome should feel like the same room.
- **Do** make theme switches instant (no crossfade). Deliberate change reads as user agency; fade reads as "the system is loading."

### Don't:

- **Don't** introduce a fifth decorative hue. The four-accent budget is the rule.
- **Don't** put raw model identifiers (`gpt-4o-…`, `claude-3-5-sonnet-…`) in primary chrome. The model is metadata under the agent's name, in `ink-muted` at label scale.
- **Don't** recreate the ChatGPT "centered prompt in a void" landing. Sidebar stays. History is structured. Agents are named.
- **Don't** reach for a **hero-metric dashboard** layout (big number + three stat cards + gradient CTA) when building admin or settings surfaces.
- **Don't** use **gradient anything**. No gradient text, no gradient buttons, no gradient backgrounds. Tokyo Night is *saturated*; it is not *neon*. Solid colour only.
- **Don't** use **side-stripe borders** (`border-left` greater than 1px as a coloured accent) for status. Use full hairlines, background tints, or leading icons instead.
- **Don't** reach for a **modal as the first thought**. Exhaust inline and progressive disclosure before adding a dialog.
- **Don't** apply shadows to surfaces that sit in the page flow. Flat-until-floating; ramp-step is the depth.
- **Don't** revert any of the role tokens to a zero-chroma neutral without a documented reason. Greyscale is a fallback, not the look.
- **Don't** introduce confetti, emoji bursts, celebratory bounces, or any **consumer-social warmth** (Discord-style purple-on-purple, sparkle-emoji chrome, rounded-everything). Wrong register for a work tool.
- **Don't** break RTL by hard-coding left/right. Use logical properties (`inline-start`, `inline-end`) or Tailwind's `ms-` / `me-` utilities.
- **Don't** animate CSS layout properties. Transform and opacity only.
- **Don't** persist the user's theme choice to the server database. It is a per-device preference; cookie + localStorage is the entire storage surface.
- **Don't** show a theme-switch onboarding popup on first load. The theme picker lives in Settings and the command palette; the OS-mapped default is correct for ~95% of users on first paint.
