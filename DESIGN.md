---
name: Open WebUI (Canva Fork)
description: An internal AI workspace where agents, not models, are the primary noun.
colors:
  paper-white: "oklch(0.98 0 0)"
  page-fill: "oklch(0.94 0 0)"
  divider: "oklch(0.92 0 0)"
  hairline: "oklch(0.85 0 0)"
  placeholder: "oklch(0.77 0 0)"
  muted-ink: "oklch(0.69 0 0)"
  secondary-ink: "oklch(0.51 0 0)"
  body-ink: "oklch(0.42 0 0)"
  strong-ink: "oklch(0.32 0 0)"
  panel-dark: "oklch(0.27 0 0)"
  workshop-dark: "oklch(0.2 0 0)"
  ink-black: "oklch(0.16 0 0)"
  mention-sky: "oklch(0.69 0.17 237)"
  signal-blue: "oklch(0.62 0.19 259)"
  signal-blue-pressed: "oklch(0.54 0.21 262)"
  status-success: "oklch(0.72 0.21 149)"
  status-warning: "oklch(0.79 0.17 70)"
  status-danger: "oklch(0.64 0.24 25)"
typography:
  display:
    fontFamily: "Archivo, Vazirmatn, sans-serif"
    fontSize: "clamp(1.75rem, 2.5vw, 2.25rem)"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "Archivo, Vazirmatn, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.005em"
  title:
    fontFamily: "Inter, Vazirmatn, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: "normal"
  body:
    fontFamily: "Inter, Vazirmatn, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  label:
    fontFamily: "Inter, Vazirmatn, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "0.02em"
  code:
    fontFamily: "JetBrainsMono, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "0.85em"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  serif-accent:
    fontFamily: "InstrumentSerif, serif"
    fontSize: "1.5rem"
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: "normal"
rounded:
  sm: "4px"
  md: "8px"
  lg: "12px"
  xl: "16px"
  "2xl": "20px"
  "3xl": "24px"
  "4xl": "32px"
  full: "9999px"
spacing:
  row: "6px"
  row-x: "11px"
  card: "16px"
  dialog: "28px"
components:
  button-primary:
    backgroundColor: "{colors.workshop-dark}"
    textColor: "{colors.page-fill}"
    rounded: "{rounded.3xl}"
    padding: "8px 16px"
    typography: "{typography.body}"
  button-primary-hover:
    backgroundColor: "{colors.panel-dark}"
    textColor: "{colors.page-fill}"
    rounded: "{rounded.3xl}"
    padding: "8px 16px"
  button-secondary:
    backgroundColor: "{colors.page-fill}"
    textColor: "{colors.strong-ink}"
    rounded: "{rounded.3xl}"
    padding: "8px 16px"
    typography: "{typography.body}"
  button-secondary-hover:
    backgroundColor: "{colors.divider}"
    textColor: "{colors.strong-ink}"
    rounded: "{rounded.3xl}"
    padding: "8px 16px"
  sidebar-item:
    backgroundColor: "transparent"
    textColor: "{colors.body-ink}"
    rounded: "{rounded.xl}"
    padding: "6px 11px"
    typography: "{typography.body}"
  sidebar-item-active:
    backgroundColor: "{colors.page-fill}"
    textColor: "{colors.ink-black}"
    rounded: "{rounded.xl}"
    padding: "6px 11px"
  input-pill:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.body-ink}"
    rounded: "{rounded.lg}"
    padding: "8px 16px"
    typography: "{typography.body}"
  message-input:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.body-ink}"
    rounded: "{rounded.3xl}"
    padding: "8px 12px"
    typography: "{typography.body}"
  modal-surface:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.body-ink}"
    rounded: "{rounded.4xl}"
    padding: "24px 28px"
  badge-info:
    backgroundColor: "{colors.mention-sky}"
    textColor: "{colors.workshop-dark}"
    rounded: "{rounded.lg}"
    padding: "0px 5px"
    typography: "{typography.label}"
---

# Design System: Open WebUI (Canva Fork)

## 1. Overview

**Creative North Star: "The Agent Workshop"**

This is a craftsman's bench, not a showroom. The surface is where a Canva employee sits down with their **named agents** — picks one up, uses it, puts it back — alongside their tools, history, and context. Nothing is on display; everything is within reach. Density and calm coexist because that's how real workshops feel: organized, instrumented, unhurried. The shell recedes so the work stays visible.

The aesthetic philosophy is strict tonal minimalism. A single 12-step neutral ramp, tuned in OKLCH with zero chroma, carries almost every surface. Color enters the system only where it has a job: `Mention Sky` for live indicators and `@`-mentions, a narrow semantic palette for status badges, a near-black primary button that inverts in dark mode. The accent budget is small on purpose — the absence of color is what lets density stop feeling noisy.

This system explicitly rejects ChatGPT's centered-prompt void, model-forward chrome (long slug IDs used as labels), SaaS hero-metric dashboards, crypto-neon, consumer-social warmth, and the "everything is a document" flatness of Notion when it fights app density. Where other AI surfaces perform excitement, this one performs competence.

**Key Characteristics:**
- Zero-chroma neutral ramp with a sparse sky/semantic accent layer.
- Hybrid elevation: flat at rest, blurred-and-lifted for modals and popovers only.
- Inter as the working face; Archivo for chrome headlines; InstrumentSerif held in reserve.
- Radius language runs from 4px utility up to 32px for modal envelopes — large radii signal "floating," tight radii signal "embedded."
- Motion is under 200ms, functional, eased out. No bounce, no choreography.

## 2. Colors: The Ink-and-Paper Palette

A monochrome stack tuned in OKLCH. Light mode is paper; dark mode is pressed ink. Accents are rationed — the palette earns its character from ramp precision, not from hue.

### Primary
- **Workshop Dark** (`oklch(0.2 0 0)`): the primary button fill in light mode, the body surface in dark mode (`#171717`). This is the color of the workshop itself. Any "primary action" reads as this near-black mass, never as a colored accent.

### Secondary
- **Mention Sky** (`oklch(0.69 0.17 237)`): the only decorative color in the chrome. Used on live-generation dots, `@`-mentions, and interactive inline suggestions. **Not** used on primary CTAs, not used on hover states, not used to decorate panels.

### Tertiary (semantic status only)
- **Signal Blue** (`oklch(0.62 0.19 259)`): info badges, checked checkbox fill.
- **Status Success** (`oklch(0.72 0.21 149)`): success badges and positive telemetry.
- **Status Warning** (`oklch(0.79 0.17 70)`): warning badges.
- **Status Danger** (`oklch(0.64 0.24 25)`): error badges and destructive confirmation.

Status hues appear exclusively at **20% opacity fill with 700-weight text in light / 200-weight text in dark**. They are informational, never decorative, and never adjacent to each other.

### Neutral (the working ramp, light → dark)
- **Paper White** (`oklch(0.98 0 0)`): app body background in light mode; modal fills at 95% opacity.
- **Page Fill** (`oklch(0.94 0 0)`): sidebar-item active fill, secondary button fill, hover states.
- **Divider** (`oklch(0.92 0 0)`): default border color applied globally via `@layer base`.
- **Hairline** (`oklch(0.85 0 0)`): input stroke, dashed borders on placeholder regions.
- **Placeholder** (`oklch(0.77 0 0)`): input placeholder text; disabled state ink.
- **Muted Ink** (`oklch(0.69 0 0)`): secondary body copy, metadata timestamps.
- **Secondary Ink** (`oklch(0.51 0 0)`): labels and supporting UI text.
- **Body Ink** (`oklch(0.42 0 0)`): default body text in light mode.
- **Strong Ink** (`oklch(0.32 0 0)`): strong emphasis, button-secondary text.
- **Panel Dark** (`oklch(0.27 0 0)`): dark-mode modal border, dark-mode sidebar hover, selected-row fill in dark mode — the in-between step that keeps depth legible.
- **Workshop Dark** (`oklch(0.2 0 0)`): dark-mode body surface and light-mode primary button.
- **Ink Black** (`oklch(0.16 0 0)`): dark-mode deepest surface; near-black text in light mode.

### Named Rules

**The One-Accent Rule.** Mention Sky is the *only* decorative color permitted in the chrome. If a new feature needs a decorative accent, use weight, size, ink contrast, or white space — not a second hue.

**The Model-Name Exile Rule.** Raw model identifiers (`gpt-4o-2024-08-06`, `claude-3-5-sonnet-*`) must never sit in primary chrome. If a model string is surfaced at all, it is secondary metadata under the agent's name, in Muted Ink at label scale.

**The Zero-Chroma Default Rule.** Grayscale is literally zero chroma. Do not drift neutrals toward a warm or cool tint unless a feature explicitly requires it and documents why. The palette's coldness is intentional.

## 3. Typography

**Display Font:** Archivo (with Vazirmatn for RTL, sans-serif fallback)
**Body Font:** Inter (with Vazirmatn, ui-sans-serif, system-ui fallback chain)
**Label/Mono Font:** JetBrainsMono (with ui-monospace fallback)
**Reserve accent:** InstrumentSerif (rare; used only for named editorial moments, never in app chrome)

**Character:** Archivo carries headlines with a humanist-geometric snap that reads more "tool" than "app." Inter does the heavy lifting for body and UI — neutral, tight, legible at 13–14px. Vazirmatn is specified on both so RTL surfaces don't fall back to a mismatched system font.

### Hierarchy
- **Display** (Archivo 600, `clamp(1.75rem, 2.5vw, 2.25rem)`, line-height 1.15): workspace landing headers, section titles on marketing-adjacent surfaces. Rare in the app shell.
- **Headline** (Archivo 600, 1.25rem, line-height 1.25): page-level titles inside the app — workspace headers, settings pages, modal titles above body.
- **Title** (Inter 500, 1.125rem, line-height 1.3): card and section titles. Modal title row uses this weight.
- **Body** (Inter 400, 0.875rem / 14px, line-height 1.5): the dominant UI text size. Chat messages, list rows, form labels. Cap prose at 65–75ch where long-form content appears.
- **Label** (Inter 500, 0.75rem / 12px, line-height 1.4, letter-spacing 0.02em): badge text (uppercase), metadata, hotkey hints, timestamps.
- **Code** (JetBrainsMono 400, 0.85em inline / 0.85rem block, line-height 1.5): inline code spans and fenced code blocks.

### Named Rules

**The Serif-In-Reserve Rule.** InstrumentSerif (`.font-secondary`) exists in the app and must stay rare. It is reserved for named editorial moments — never for generic emphasis, never for body, never for labels.

**The RTL-First Rule.** Every font stack includes `Vazirmatn`. New stacks must include it. RTL parity is a latent requirement of this surface.

**The Scale-Text-Scale Rule.** The app supports `--app-text-scale` on `:root`. Custom line-heights and min-heights declared in pixel units must multiply through this variable (see `app.css` `#sidebar-chat-item`). Hard-coding pixel line-heights outside the scale system is forbidden.

## 4. Elevation

This system is **flat by default, blurred-and-lifted on demand**. Application surfaces — sidebar, main pane, chat rows, settings — carry no shadow. Floating layers earn their lift: modals, popovers, tooltips, and the primary message input use a specific vocabulary.

### Shadow Vocabulary
- **Message Input Lift** (`box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)` — Tailwind `shadow-lg`): the composing surface sits just above the chat with a gentle soft shadow. Signals "this is where you act."
- **Modal Lift** (Tailwind `shadow-3xl` paired with `backdrop-blur-sm` and a 1px `paper-white / panel-dark` border): the primary modal envelope. The blur is the actual depth cue; the shadow is supporting.
- **Popover Blur** (`bg-black/80` + `backdrop-blur-2xl`): dark tooltip-adjacent popovers (drag previews, transient hint cards). Very rarely used for persistent surfaces.

### Named Rules

**The Flat-Until-Floating Rule.** If a surface stays on the page flow, it is flat. Shadows exist only on elements that *detach* from the flow (dialogs, menus, the message input, drag previews). A card that sits in a grid does not get a shadow.

**The Blur-Is-The-Depth Rule.** Our lift comes from `backdrop-blur` against a translucent fill (`bg-white/95 dark:bg-gray-900/95`), not from heavy drop shadows. If a surface needs to feel "above," increase the blur strength before increasing the shadow strength.

**The Ghost-Border Rule.** Modals carry a 1px border of `paper-white` (light) / `panel-dark` (dark). This hairline replaces what a larger shadow would otherwise do — it defines the edge against the blurred backdrop without shouting.

## 5. Components

Components feel **tactile and confident**: crisp edges, decisive state changes, clear inversion on primary actions. Hover is visible. Selected state is unambiguous. Transitions are under 200ms.

### Buttons
- **Shape:** Pill radius for dialog actions (`rounded-3xl`, 24px); rounded-rectangle for compact inline buttons (`rounded-lg`, 8px); full-round only for icon chips.
- **Primary:** `Workshop Dark` background with `Page Fill` text in light mode. **Inverts in dark mode** to `Page Fill` background with `Strong Ink` text. Padding `8px 16px`; dialog-scale variants fill the dialog's button row. Typography: body weight 500.
- **Hover / Focus:** Background shifts one ramp step (`Workshop Dark` → `Panel Dark` in light; `Page Fill` → `Paper White` in dark). No scale, no shadow change, no glow. Transition 150ms ease-out on background only.
- **Secondary:** `Page Fill` background with `Strong Ink` text in light; `Panel Dark` / `Paper White` in dark. Used for cancel, dismiss, and "less weighty" companions to a primary.

### Chips / Badges
- **Style:** `bg-{hue}-500/20` (20% opacity) with text at the 700 weight in light / 200 weight in dark; uppercase; `rounded-lg`; `text-xs` (label scale); `px-[5px]`.
- **State:** Badges are not interactive. Use chip-style buttons (same shape, solid fill, hover-darken) when interactivity is needed.

### Cards / Containers
- **Corner Style:** `rounded-xl` (16px) for row-level containers; `rounded-2xl` (20px) for pane-level cards; `rounded-3xl` (24px) for large composing surfaces.
- **Background:** `Paper White` in light / `Workshop Dark` in dark for the primary surface. Subcontainers step by one ramp (`Page Fill` / `Ink Black`).
- **Shadow Strategy:** None by default. See Elevation.
- **Border:** Inherited from `@layer base` as `Divider` (1px). Cards that need stronger separation use `Hairline`. Thick or colored borders are forbidden.
- **Internal Padding:** `px-[11px] py-[6px]` for list rows, `p-4` for compact cards, `px-[1.75rem] py-6` for dialog interior.

### Inputs / Fields
- **Style:** `Paper White` background in light / `Workshop Dark` in dark. `rounded-lg` for form fields, `rounded-3xl` for the large composing surface. Border is `Divider` at 1px in light, none in dark (the surface contrast carries the edge).
- **Focus:** Border steps to `Hairline` (light) / `Strong Ink` (dark). No glow, no outer ring. Placeholder in `Placeholder` color.
- **Error / Disabled:** Disabled inputs drop to 50% text opacity; error states use the `Status Danger` ring at 1.5px.

### Navigation (Sidebar)
- **Style:** `Paper White` panel in light, `Workshop Dark` in dark. Items are full-width rows with `rounded-xl` corners, `px-[11px] py-[6px]` padding, `Body Ink` text at body scale. Selected row fills with `Page Fill` (light) / `Workshop Dark` → `Panel Dark` on hover (dark).
- **Typography:** Body scale, weight 400. Active item does not bold — the background fill is the tell.
- **Mobile treatment:** Sidebar becomes a drawer; hit targets remain at the 32px min-height set via `#sidebar-chat-item`.

### Signature Component — The Agent Message Input
The composing surface is the single most distinctive element in the app. `rounded-3xl` with a translucent fill (`bg-white/5 dark:bg-gray-500/5`), `backdrop-blur-sm`, a `shadow-lg` lift, and a hairline border that shifts from `Divider/30` at rest to `Divider` on hover and `Divider` on focus-within. It sits above the chat without carving into it, and it answers to the agent — not a model dropdown. Model identifiers, when surfaced, appear as secondary metadata only.

### Signature Component — The Agent Chip
An agent's avatar appears at `size-[2.7rem]` with a `rounded-full` crop and a 1px `Divider` ring in light mode / no ring in dark. Overlapping avatar stacks use `-space-x-4` to suggest a small roster. This chip is the primary identity marker for the agent-over-model hierarchy.

## 6. Do's and Don'ts

### Do:
- **Do** use `Workshop Dark` as the primary button fill in light mode, inverted to `Page Fill` in dark mode.
- **Do** reserve `Mention Sky` (`oklch(0.69 0.17 237)`) for `@`-mentions and live-state dots. Nothing else.
- **Do** cap body prose at 65–75ch where long-form content appears.
- **Do** use large radii (`rounded-3xl`, `rounded-4xl`) to signal "this surface is floating" (modals, input pills), and small radii (`rounded-lg`) to signal "this surface is embedded" (inputs, badges).
- **Do** compose elevation with `backdrop-blur` against translucent fills, not with heavy drop shadows.
- **Do** name agents in the chrome. The model is metadata under the agent, never the primary title.
- **Do** include `Vazirmatn` in every new font stack for RTL parity.
- **Do** respect `prefers-reduced-motion` — transitions should become instant, not merely slower.

### Don't:
- **Don't** introduce a second decorative hue. The one-accent rule (`Mention Sky` only) is the rule. If a feature wants color, it gets weight contrast or ramp contrast instead.
- **Don't** put raw model identifiers (`gpt-4o-…`, `claude-3-5-sonnet-…`) in primary chrome. That's the model-forward UI PRODUCT.md explicitly exiles.
- **Don't** recreate the ChatGPT "centered prompt in a void" landing. Sidebar stays. History is structured. Agents are named.
- **Don't** reach for a **hero-metric dashboard** layout (big number + three stat cards + gradient CTA) when building admin or settings surfaces.
- **Don't** use **crypto-neon** gradients, magenta-cyan glow cores, or black-grid floors. That reads as hype, not craft.
- **Don't** use **gradient text** (`background-clip: text` with a gradient). Solid ink only. Emphasis via weight or size.
- **Don't** use **side-stripe borders** (`border-left` greater than 1px as a colored accent). Use full hairlines, background tints, or leading icons instead.
- **Don't** reach for a **modal as the first thought**. Exhaust inline and progressive disclosure before adding a dialog.
- **Don't** apply shadows to surfaces that sit in the page flow. Flat-until-floating.
- **Don't** drift the gray ramp toward warm or cool tints. Zero chroma is the signature.
- **Don't** introduce confetti, emoji bursts, celebratory bounces, or any **consumer-social warmth** (Discord, purple accents, rounded-everything). Wrong register for a work tool.
- **Don't** break RTL by hard-coding left/right. Use logical properties (`inline-start`, `inline-end`) or Tailwind's `ms-` / `me-` utilities.
- **Don't** animate CSS layout properties. Transform and opacity only.
