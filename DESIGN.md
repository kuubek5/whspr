---
name: KuubWave
description: Private, Ukrainian-first voice dictation — a calm warm-dark studio with coral energy and a single aqua success note.
colors:
  coral: "#FF6B5E"
  coral-deep: "#F0574C"
  coral-ink: "#FF9488"
  aqua: "#33CBBB"
  violet: "#9784F5"
  amber: "#F0B429"
  danger: "#FF6169"
  bg: "#171319"
  bg2: "#1F1A22"
  card: "#221C29"
  ink: "#F4EEF2"
  muted: "#B0A6B4"
  muted2: "#A69CAC"
  line: "rgba(255,255,255,.09)"
  line2: "rgba(255,255,255,.16)"
  field: "#2A2331"
typography:
  display:
    fontFamily: "IBM Plex Sans, system-ui, 'Segoe UI', sans-serif"
    fontSize: "clamp(1.9rem, 3.5vw, 2.4rem)"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  title:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "1.05rem"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  body:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "0.95rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "0.72rem"
    fontWeight: 600
    letterSpacing: "0.04em"
  mono:
    fontFamily: "JetBrains Mono, 'Cascadia Code', Consolas, monospace"
    fontSize: "0.85rem"
    fontWeight: 400
rounded:
  sm: "12px"
  md: "16px"
  lg: "22px"
  pill: "999px"
spacing:
  xs: "6px"
  sm: "9px"
  md: "15px"
  lg: "18px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.coral}"
    textColor: "#20141A"
    rounded: "{rounded.sm}"
    padding: "11px 18px"
  button-ghost:
    backgroundColor: "{colors.card}"
    textColor: "{colors.muted}"
    rounded: "{rounded.sm}"
    padding: "11px 14px"
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "22px 24px"
  panel:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "22px 24px"
---

# Design System: KuubWave

## Overview

**Creative North Star: "The Soft Studio"**

KuubWave feels like a calm, premium recording studio you keep in the corner of
your screen: warm-dark surfaces, generous rounding, soft shadows, and one live
coral energy that only appears where sound and action happen. It is an Operate
surface — the job is dictation, so the interface stays quiet and scannable and
lets the text be the hero. Personality lives in precise details: the tabular-mono
timers, the equalizer wave, the single aqua note reserved for success.

The system ships **both a warm-dark and a warm-light theme** from the same
tokens. Dark is the signature (deep plum-black #171319 surfaces); light is a warm
off-white (#FBF7F5) that keeps the same coral and a deeper aqua for contrast.
Color is used sparingly: most of the screen is neutral, coral carries energy and
primary action, and the accent statistics borrow violet and aqua only as small
categorical highlights.

**Key Characteristics:**
- Warm-dark-first, with a matching warm-light theme from one token set.
- Coral is the one energy color; aqua means success only.
- Big soft rounding (16–22px) and diffuse shadows; nothing hard-edged.
- IBM Plex Sans throughout, bundled and offline; mono only for numbers.
- Quiet by default — the hero recording card is the one loud surface.

## Colors

A warm neutral field with a single coral energy accent, a reserved aqua success
note, and small categorical highlights (violet, amber) for statistics.

### Primary
- **Coral** (#FF6B5E; dark theme #FF7A6E): the brand energy — the record button,
  primary actions, the recording waveform, the logo, active hotkey chips. Used on
  a small fraction of any screen; its rarity is the point.
- **Coral Deep** (#F0574C) / **Coral Ink** (#FF9488 on dark, #CC3226 on light):
  pressed states and coral-on-surface text that must stay legible.

### Secondary
- **Aqua** (#33CBBB on dark, #0FA598 on light): success and completion only — the
  done checkmark, a finished dictation. Never decorative.

### Tertiary
- **Violet** (#9784F5) and **Amber** (#F0B429): small categorical accents for the
  statistics row and occasional highlights, never for primary action.

### Neutral
- **Surface / plum-black** (bg #171319, bg2 #1F1A22, card #221C29): the stacked
  warm-dark grounds. Light theme: #FBF7F5 / #F4EEEB / #FFFFFF.
- **Ink** (#F4EEF2 on dark, #1B1720 on light): primary text.
- **Muted** (#B0A6B4 / #A69CAC): secondary text and quiet, colorless states.
- **Lines** (white .09 / .16 on dark; ink .09 / .15 on light): hairline borders
  and dividers.

### Named Rules
**The One Energy Rule.** Coral is the only energy color and covers ≤10% of a
screen. **The Aqua-Means-Done Rule.** Aqua appears only on success/completion —
never as decoration or a second brand color.

## Typography

**Display / Body / Label Font:** IBM Plex Sans (with system-ui, Segoe UI).
**Numeric / Mono Font:** JetBrains Mono (with Cascadia Code, Consolas).

**Character:** One humanist sans carries the whole UI — friendly but precise,
tight negative tracking on headings for confidence. Numbers (timers, stats,
durations) switch to tabular mono so they never jitter.

### Hierarchy
- **Display** (700, clamp 1.9–2.4rem, -0.02em): page titles ("Готові диктувати?").
- **Title** (700, ~1.05rem): panel and card headings.
- **Body** (400, ~0.95rem, 1.5): descriptions and list content.
- **Label** (600, ~0.72rem, 0.04em, often uppercase): chip captions, field labels.
- **Mono** (400, ~0.85rem, tabular): timers, stat figures, durations.

### Named Rules
**The Tabular-Numbers Rule.** Every changing number renders in tabular mono so
counters and timers never shift width.

## Layout

Fixed left sidebar (nav + brand) beside a scrolling content column; the sidebar
collapses to icons on narrow widths. Content sits in a comfortable max-width
column of stacked cards and panels. Rhythm runs on a ~6/9/15/18/24px spacing
scale; panels use 22–24px internal padding. Density is comfortable, not dense —
generous whitespace around the hero and between cards.

## Elevation & Depth

Soft, diffuse, low-contrast shadows convey a gentle lift; surfaces are layered by
tone (bg → bg2 → card) as much as by shadow. Nothing uses hard borders for depth.

### Shadow Vocabulary
- **Small** (`--sh-sm`, e.g. `0 1px 2px …,.06 / 0 4px 12px …,.05`): cards, chips,
  quiet controls.
- **Standard** (`--sh`): panels and modals.
- **Hero** (`--sh-hero`, coral-tinted on light, deep on dark): only the recording
  hero card, so its glow reads as coral energy.

### Named Rules
**The Tonal-First Rule.** Prefer tonal layering (bg/bg2/card) over borders;
shadows stay soft and diffuse, never sharp.

## Shapes

Generously rounded, pill-friendly geometry. Cards and panels use 22px (lg),
buttons and fields ~12–16px, chips and the overlay are full pills (999px). No
sharp corners anywhere; hairline borders are near-transparent, not structural.

## Components

### Buttons
- **Shape:** rounded 12px (sm).
- **Primary:** coral background, dark ink text, ~11×18px padding — the record
  action and confirmations.
- **Ghost:** card background, muted text, hairline — secondary actions ("Змінити",
  "Перевірити оновлення").
- **Hover / Focus:** slight lift and background shift; visible focus ring.

### Cards / Containers
- **Corner Style:** 22px (lg).
- **Background:** card (#221C29 dark / #FFFFFF light).
- **Shadow Strategy:** small by default; the hero card uses the coral-tinted hero
  shadow.
- **Internal Padding:** 22–24px.

### Inputs / Fields
- **Style:** filled field surface, hairline border, ~12px radius.
- **Focus:** coral-tinted border/glow.

### Toggles & Chips
- Pill switches with a coral "on" state; small labeled chips (device, language,
  hotkey) with uppercase micro-labels over a value.

### Navigation
- Left sidebar list: icon + label rows, muted at rest, coral-tinted active row on
  a raised surface; collapses to icons on narrow widths.

### Signature: The Recording Hero + Overlay Pill
- The home hero is the one loud surface: a coral gradient card with the record
  button, a live equalizer waveform, and status chips.
- The floating overlay pill (also drawn natively) is a dark rounded capsule with
  a state dot, coral wave, and tabular timer; adjustable opacity, position, scale.

### Signature: Brand Mark
- Coral→aqua radial audio-waveform ring around a coral 'k'; self-colored, reads
  on both themes.

## Do's and Don'ts

### Do:
- **Do** keep coral scarce — record button, primary action, live audio, logo.
- **Do** reserve aqua strictly for success/completion.
- **Do** render every changing number in tabular mono.
- **Do** use soft diffuse shadows and tonal layering; rounding 12–22px.
- **Do** keep both themes in sync from the shared token set.

### Don't:
- **Don't** introduce a second brand color or use aqua decoratively.
- **Don't** use hard borders or sharp corners for structure.
- **Don't** make more than one surface per screen "loud" (the hero owns that).
- **Don't** fetch webfonts — IBM Plex is bundled; the app is offline by design.
