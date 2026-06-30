---
name: Dj-Skeleton
description: Production-ready Django starter — Tailwind v4, DaisyUI v5, dual-theme, VPS-ready.
colors:
  signal-indigo: "#6366f1"
  signal-indigo-deep: "#4f46e5"
  signal-indigo-deeper: "#4338ca"
  signal-indigo-muted: "#818cf8"
  sky-accent: "#0ea5e9"
  sky-accent-bright: "#38bdf8"
  ink: "#000000"
  ink-secondary: "#45484d"
  ink-tertiary: "#6b7280"
  surface: "#ffffff"
  surface-raised: "#e6e6e6"
  surface-sunken: "#cccccc"
  surface-dark: "#3a3a3e"
  surface-dark-deeper: "#2e2e32"
  surface-dark-raised: "#4a4a50"
  ink-on-dark: "#e8e8ed"
  ink-secondary-on-dark: "#8e8e93"
  success: "#10b981"
  warning: "#f59e0b"
  error: "#ea580c"
  info: "#0ea5e9"
typography:
  display:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "1.875rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  title:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.005em"
  body:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1.4
  mono:
    fontFamily: "ui-monospace, Menlo, Monaco, 'Cascadia Code', 'Segoe UI Mono', monospace"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  sm: "4px"
  md: "8px"
  lg: "16px"
  pill: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  2xl: "48px"
components:
  button-primary:
    backgroundColor: "{colors.signal-indigo}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "10px 20px"
  button-primary-hover:
    backgroundColor: "{colors.signal-indigo-deep}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    padding: "10px 20px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.signal-indigo}"
    rounded: "{rounded.md}"
    padding: "10px 20px"
  input-base:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "10px 14px"
  card-base:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "24px"
---

# Design System: Dj-Skeleton

## 1. Overview

**Creative North Star: "The Confident Default"**

This is a design system built on the premise that the best defaults don't require justification. Signal Indigo (`#6366f1`) is the one accent; the surface is either white or dark charcoal (`#3a3a3e`); the type is the system font stack. None of this is lazy — it is deliberate. The skeleton has made its decisions, documented them, and trusts the developer to override what needs overriding.

The tone is tool-like: dense where density serves the user, clear where clarity earns trust. A developer looking at a screen built on this system should feel oriented immediately — not charmed, not wowed. The interface disappears into the task. Decoration is disqualified by default; every visual element must answer for its presence.

Dark mode is not a toggle bolted on after the fact. It is a first-class sibling. The dark theme (`#3a3a3e` / `#2e2e32` / `#4a4a50`) has its own tonal ramp, its own ink (`#e8e8ed`), and its own primary (`#818cf8`). Both themes share the same spatial grammar; only the color values change.

**Key Characteristics:**
- Single sans family (system-ui) across all roles — no display/body split
- Signal Indigo used exclusively for primary actions, current selection, focus rings — not decoration
- Elevation via tonal layers (base-100 / base-200 / base-300), never drop-shadows
- Compact scale ratio (1.125) — product density, not editorial rhythm
- Semantic color vocabulary (success / warning / error / info) standardized across both themes

## 2. Colors: The Signal Palette

A restrained palette with a single accent that earns its intensity by appearing rarely.

### Primary

- **Signal Indigo** (`#6366f1` light / `#818cf8` dark): Primary actions, active navigation states, focus rings, and progress indicators. Used on ≤10% of any given screen — its rarity is what makes it a signal, not noise.
- **Signal Indigo Deep** (`#4f46e5`): Hover state for primary buttons. Never used at rest.
- **Signal Indigo Deeper** (`#4338ca`): Pressed/active state. Appears for 100ms maximum.

### Secondary

- **Sky Accent** (`#0ea5e9` light / `#38bdf8` dark): Information states, external links, and secondary interactive elements. Distinct from Signal Indigo enough to carry semantic weight (info ≠ action).

### Neutral

- **Ink** (`#000000`): Primary content on light surfaces. Used for headings, body copy, and data.
- **Ink Secondary** (`#45484d`): Supporting text, metadata, secondary labels.
- **Ink Tertiary** (`#6b7280`): Placeholders, disabled labels, timestamps. Never used for body content.
- **Surface** (`#ffffff`): Primary content surface, light theme.
- **Surface Raised** (`#e6e6e6`): Background layer behind content cards. Sidebar backgrounds, page shells.
- **Surface Sunken** (`#cccccc`): Dividers, input borders at rest.
- **Surface Dark** (`#3a3a3e`): Primary content surface, dark theme. Warm-tinted charcoal (hue ~270), not blue-gray.
- **Surface Dark Deeper** (`#2e2e32`): Background layer in dark mode. Sidebars, page shells.
- **Surface Dark Raised** (`#4a4a50`): Borders, hovered items in dark mode.
- **Ink on Dark** (`#e8e8ed`): Primary content text in dark mode.

### Semantic

- **Success** (`#10b981` light / `#34d399` dark): Confirmations, positive states.
- **Warning** (`#f59e0b` light / `#fbbf24` dark): Cautionary states. Warning content text is `#000` in dark to maintain contrast.
- **Error** (`#ea580c` light / `#fb923c` dark): Validation errors, destructive action confirmation.
- **Info** (`#0ea5e9` / `#38bdf8`): Informational alerts. Shares value with Sky Accent.

### Named Rules

**The One Signal Rule.** Signal Indigo is used on ≤10% of any screen at rest. A screen where everything is indigo has no signals. Reserve it for what matters: the primary button, the active nav item, the focus ring.

**The No-Decoration Rule.** Color is semantic here, not aesthetic. If a color is not carrying meaning (action, state, severity), it is not on the screen.

## 3. Typography

**Primary Font:** system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif  
**Code/Mono Font:** ui-monospace, Menlo, Monaco, 'Cascadia Code', 'Segoe UI Mono', monospace

**Character:** One family, all weights, no pairing. This is intentional — developer tools don't benefit from editorial contrast. The system font resolves to the OS's native sans (SF Pro on macOS, Segoe UI on Windows, Roboto on Android), which means the interface feels native on every platform and loads at zero cost.

### Hierarchy

- **Display** (700, 1.875rem / 30px, line-height 1.2, tracking −0.01em): Page titles, error page headings, modal titles. Use `text-wrap: balance`. Max one per view.
- **Title** (600, 1.25rem / 20px, line-height 1.3, tracking −0.005em): Section headings, card titles, sidebar section labels.
- **Body** (400, 1rem / 16px, line-height 1.5): All prose content. Cap at 65–75ch for readability. Use `text-wrap: pretty` on multi-paragraph blocks.
- **Label** (500, 0.875rem / 14px, line-height 1.4): UI labels, button text, nav links, table headers. Weight 500 distinguishes from body without shouting.
- **Mono** (400, 0.875rem / 14px, line-height 1.6): Code snippets, env var names, shell commands, file paths. Line-height 1.6 for readability in multi-line blocks.

### Named Rules

**The Single Stack Rule.** One font family, no exceptions. No display face imported for headings — the scale and weight carry all necessary hierarchy. Import cost: zero. Consistency: guaranteed.

**The Label Floor Rule.** No UI text below 0.8125rem (13px). Below that, text stops being readable at arm's length; it's just visual texture.

## 4. Elevation

This system is flat by default. Depth is conveyed entirely through tonal layering — stacking lighter surfaces on darker ones in light mode, and darker surfaces on lighter ones in dark mode — not through shadows.

The three-step tonal scale (`base-100` / `base-200` / `base-300`) maps to:
- **Base-100** (`#ffffff` / `#3a3a3e`): Content surface — cards, inputs, main panels
- **Base-200** (`#e6e6e6` / `#2e2e32`): Background layer — page shell, sidebar, table backgrounds
- **Base-300** (`#cccccc` / `#4a4a50`): Borders, dividers, input strokes at rest

The only exception is **floating UI** (modals, dropdowns, tooltips, toasts), which may carry a shadow to convey their detachment from the document flow. These shadows are structural, not decorative.

### Shadow Vocabulary

- **Floating** (`box-shadow: 0 4px 24px rgba(0,0,0,0.12), 0 1px 4px rgba(0,0,0,0.08)`): Modals, command palette, dropdowns. Communicates "this surface is above the page."
- **Toast** (`box-shadow: 0 2px 12px rgba(0,0,0,0.10)`): Notification banners. Lighter than floating; stays contextual.

### Named Rules

**The Flat-by-Default Rule.** Surfaces at rest have no shadow. If you're reaching for `shadow-xl` on a card that's not floating, stop. Use `bg-base-200` as the background instead.

**The Float Exception.** Shadows appear only when a surface is genuinely detached from flow: modals, dropdowns, tooltips, toasts. Not cards. Not sidebars. Not hero sections.

## 5. Components

### Buttons

Clean, medium-weighted, immediately legible. No gradient fills, no animated glow, no decorative border radius surprise.

- **Shape:** Gently rounded (8px / 0.5rem). Recognizable as a button at a glance without being pill-shaped.
- **Primary** (`bg: #6366f1`, `text: #fff`, `padding: 10px 20px`, min-height: 40px): The only fully saturated element on most screens. Used for the single most important action per view.
- **Primary Hover** (`bg: #4f46e5`): Darkens 10%. No movement, no scale. State is communicated through color.
- **Focus ring:** `outline: 2px solid #6366f1; outline-offset: 2px`. Visible against both white and dark surfaces.
- **Ghost** (`bg: transparent`, `text: #6366f1`, hover `bg: rgba(99,102,241,0.10)`): Secondary actions that share the screen with a primary. Keeps visual weight down.
- **Base** (`bg: transparent`, `text: ink`, hover `bg: base-200`): Tertiary actions, table row actions. Low contrast by design.
- **Disabled:** 40% opacity, cursor `not-allowed`. Never grayed-out text on white — use opacity on the whole button.

### Cards / Containers

- **Corner Style:** Large radius (16px / 1rem). Signals "grouping container" as distinct from interactive element (8px).
- **Background:** `bg-base-100` — always one layer above the page background.
- **Shadow Strategy:** No shadow. Place on `bg-base-200` to create visual separation without elevation.
- **Border:** Optional `border border-base-300` when the background contrast alone is insufficient (e.g. base-100 cards on base-100 background in light mode).
- **Internal Padding:** 24px (1.5rem) standard. 16px for compact variants (data tables, tight sidebars).

### Inputs / Fields

- **Style:** Outlined. `border: 1px solid #cccccc` at rest. Background `#ffffff` light / `#3a3a3e` dark.
- **Radius:** 8px — same as buttons. Consistent vocabulary across interactive elements.
- **Min-height:** 48px for touch-target compliance.
- **Focus:** `border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99,102,241,0.15)`. Glow communicates intent without an extra outline layer.
- **Placeholder:** `color: #6b7280`. Meets WCAG AA (4.58:1 on white).
- **Error State:** `border-color: #ea580c; box-shadow: 0 0 0 3px rgba(234,88,12,0.15)`. No icon required; the ring is the signal.
- **Disabled:** `opacity: 0.5; cursor: not-allowed; pointer-events: none`.

### Navigation

- **Top bar style:** White background, `border-bottom: 1px solid #e6e6e6`. Height 56px. Never shadowed.
- **Brand:** Font-weight 700, tracking −0.01em. `#000` in light mode.
- **Nav links:** 500 weight, 0.875rem, `color: #45484d`. Active state: `color: #6366f1; background: rgba(99,102,241,0.08)`. Hover: `background: #f3f4f6`.
- **Mobile:** Collapses to hamburger menu. DaisyUI `drawer` pattern is the default.

### Code Snippets (Signature Component)

This is a developer tool — code blocks appear frequently and must be legible.

- **Background:** `bg-base-200` (sunken surface). One tonal layer below the card it sits in.
- **Font:** `ui-monospace` stack, 0.875rem, line-height 1.6.
- **Padding:** 16px.
- **Radius:** 8px — consistent with inputs.
- **Inline code:** `background: rgba(99,102,241,0.10); color: #4f46e5; border-radius: 4px; padding: 1px 6px`.

## 6. Do's and Don'ts

### Do:

- **Do** use `bg-base-200` as the page shell so `bg-base-100` cards visually float without any shadow.
- **Do** cap body text at 65–75ch with `max-w-prose` or an equivalent constraint.
- **Do** use the three-level tonal scale consistently: base-300 for borders/dividers, base-200 for backgrounds, base-100 for content surfaces.
- **Do** apply `text-wrap: balance` to all `<h1>` through `<h3>` headings to prevent awkward single-word orphan lines.
- **Do** include every interactive state (hover, focus, active, disabled) before marking a component done. A component without focus-visible is inaccessible.
- **Do** use monospace for any string the developer will copy — env var names, commands, file paths, token values.
- **Do** test contrast in both light and dark themes. The dark palette has its own contrast checks; don't assume light-mode passes imply dark-mode passes.

### Don't:

- **Don't** use `border-left` or `border-right` wider than 1px as a colored accent stripe on cards, callouts, or alerts. This is the generic bootstrap template pattern — exactly what this skeleton is not. Use a full border, background tint, or a leading icon instead.
- **Don't** use gradient fills on buttons, headings, or backgrounds. `background-clip: text` with a gradient is prohibited. Solid color or nothing.
- **Don't** apply glassmorphism effects (backdrop-filter blur on cards, translucent panels) as decoration. If it's floating, a shadow is sufficient.
- **Don't** build a feature-grid card section with identical-sized cards sharing an icon + heading + text structure and no variation. This is the inflated SaaS landing page pattern. If features must be listed, vary density or use a table.
- **Don't** use tiny all-caps tracked eyebrows above every section heading. One named kicker used deliberately is a design choice; eyebrows on every section is AI grammar.
- **Don't** use numbered section markers (01 / 02 / 03) as scaffolding. Numbers earn their place when the sequence actually matters.
- **Don't** let body text, placeholders, or labels fall below 4.5:1 contrast against their background. `#6b7280` on `#ffffff` passes (4.58:1); anything lighter than that does not.
- **Don't** reach for a modal as the first solution for any secondary flow. Exhaust inline, drawer, and progressive-disclosure alternatives first.
- **Don't** ship a loading state as a spinner centered in a content area. Use skeleton states that match the shape of the content that will appear.
