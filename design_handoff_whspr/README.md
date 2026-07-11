# Handoff: whspr — Desktop Voice Dictation App UI

## Overview
"whspr" is a local, privacy-first push-to-talk voice dictation tool for Windows (everything runs on-device/GPU, nothing touches the cloud). This bundle contains a high-fidelity interactive prototype of the desktop app shell: a 960×620 app window with sidebar navigation across 4 pages, plus a standalone floating "pill" overlay component (the always-on-top recording indicator).

## About the Design Files
The file in this bundle (`whspr.dc.html`) is a **design reference built as a self-contained HTML/React prototype** — it demonstrates intended look, layout, states, and interaction/motion timing. It is NOT production code to copy verbatim. The task is to **recreate this UI in the target codebase's real environment** (this is a Windows desktop app, so most likely a WPF/WinUI/Electron/Tauri + React or native stack — use whatever the existing whspr codebase already uses, or pick the best fit if none exists yet) using that stack's own component/state patterns, while preserving the visual design, copy, states, and motion described below exactly.

To view/inspect the prototype: open `whspr.dc.html` in a browser (it's a single self-contained file — a `<script>`-driven component, view source for exact inline styles, copy, and logic).

## Fidelity
**High-fidelity.** Colors, type, spacing, radii, and motion timings below are final — implement pixel-for-pixel where the target stack allows.

## Design Tokens

### Colors — Dark theme (default)
- App background: `#0E0E12`
- Surface 1 (cards/sidebar): `#16161C`
- Surface 2 (inputs/pills/track-off): `#1E1E26`
- Surface 3 (active nav pill/chips): `#262630`
- Hairline border: `rgba(255,255,255,0.08)`; strong border: `rgba(255,255,255,0.16)`
- Text primary: `#F2F2F5`; secondary: `#9B9BA5`; tertiary: `#6B6B75`
- Outer backdrop (behind app window): radial gradient `#131318 → #08080A`

### Colors — Light theme (mirrored)
- App background: `#FAFAFB`; Surface 1: `#FFFFFF`; Surface 2: `#F3F3F5`; Surface 3: `#ECECEF`
- Hairline border: `rgba(0,0,0,0.08)`; strong: `rgba(0,0,0,0.14)`
- Text primary: `#16161C`; secondary: `#6B6B75`; tertiary: `#9B9BA5`
- Outer backdrop: radial gradient `#F1F1F3 → #E3E3E7`

### Accent (used ONLY for recording state + primary actions — never decorative)
- Coral: `#F0555C`; hover: `#E14750`
- Soft coral background (dark): `rgba(240,85,92,0.16)`; (light): `rgba(240,85,92,0.10)`
- Soft coral strong border: `rgba(240,85,92,0.28)`
- Success green (privacy note, done-state check, GPU-active dot): `#4CAF6D`

### Typography
- UI font: **Inter** (400/500/600/700/800)
- Monospace (transcripts, timers, stat numbers, hotkey chips): **JetBrains Mono** (400/500/600/700), always `font-variant-numeric: tabular-nums`
- Base UI sizes: nav/labels 13px, section titles 13.5–14px, body/hints 11.5–12.5px, hero title 15px, stat values 19px mono, recording timer 26px mono bold

### Spacing / shape
- 8px spacing grid throughout
- Card radius: 12–14px (14px for hero card, 12px for standard cards)
- Sidebar width: 204px; app shell: 960×620, radius 16px
- Shadows: dark `0 24px 70px rgba(0,0,0,0.6), 0 2px 10px rgba(0,0,0,0.45)`; light equivalent at lower opacity

## Screens / Views

### 1. App Shell (persistent)
- **Layout**: flex row — left sidebar (204px, fixed) + main content area (flex:1, column: 52px topbar + scrollable page body).
- **Sidebar**: brand mark (mic icon in 24px rounded-7px chip) + "whspr" wordmark at top; 4 nav items (Home, History, Dictionary, Settings), each 36px tall row with icon + label; active item highlighted by a sliding background pill (`top` animates 220ms spring cubic-bezier(0.34,1.56,0.64,1)) sitting behind the active label/icon (z-index layering, indicator z:0, content z:1). Footer shows a small GPU status badge: green dot + "Локально · {gpu model}" in mono 11px.
- **Topbar**: page title (secondary text, 13px/600) left; theme toggle button (sun/moon icon, 30×30 rounded-8 chip) right.
- **Floating pill overlay**: NOT part of the app window — rendered as a separate, standalone always-on-top OS-level capsule (in the prototype it sits in normal document flow just below the app window purely for demo viewing; in the real product it is a separate always-on-top OS window). See "Signature Piece" below.

### 2. Home
- **Hero status card** (top of page body): centered content, 3 mutually exclusive states:
  - **Idle**: breathing 6px dot (opacity/scale pulse, 2.6s ease-in-out infinite) above a mic icon, title "Натисніть і утримуйте Fn" (15px/600), subtitle "щоб почати диктування будь-де на екрані" (12.5px, tertiary).
  - **Recording**: large mono timer (26px/600, tabular-nums, mm:ss counting up every 1s), animated waveform (40 vertical coral bars, 3px wide, each `scaleY` keyframe 0.25↔1, staggered per-bar delay/duration for organic motion), label row with pulsing coral dot ("pulseCoral" ring keyframe 1.6s) + "Запис · відпустіть Fn, щоб завершити".
  - **Transcribing**: two shimmer skeleton bars (220px and 140px, 14px tall, rounded, diagonal shimmer sweep 1.4s ease-in-out infinite background-position sweep), label "Розпізнаю мовлення на GPU…".
  - Below the state area: 3 small pill buttons ("Очікування" / "Запис" / "Розпізнавання") let you preview each state live — active button gets coral soft background + coral text.
- **Stat tiles**: 4-column grid, each tile = label (11px tertiary) + mono value (19px/600). Metrics: **Слів сьогодні**, **Диктовок**, **Слів усього**, **Слів/хв**. Values count up from 0 to target on page load via an eased ramp (~1.4s, cubic ease-out, stepped every ~35ms) — targets used in the prototype: 2481 words today, 37 dictations, 184920 words total, 132 wpm.
- **"Останні диктовки" feed**: card containing an uppercase section header + up to 4 rows, each row = fixed-width mono timestamp (11px, e.g. "Сьогодні, 14:32") + Ukrainian transcript text in mono (12.5px), separated by hairline dividers.

### 3. History
- Header row: count of dictations (mono, tertiary).
- Stack of cards (12px radius), each:
  - Meta row (mono 11.5px, tertiary): time · language chip "UK" (small rounded chip) · duration.
  - Transcript text (mono 13px, primary, line-height 1.6).
  - Copy + delete icon buttons (25×25 rounded-7 chips) positioned top-right of the card; copy shows a check + turns green for ~1.4s after click (and calls the OS clipboard) then reverts; delete removes the card from the list immediately.

### 4. Dictionary
- **Hotwords card**: title "Хотворди" + helper copy explaining these are priority terms for recognition; a full-width textarea (mono 12.5px) holding a comma-separated term list (editable, controlled).
- **Voice commands card**: title "Голосові команди" + helper copy ("нова думка" = ⏎ example) + "+ Додати" button (adds a blank row). Each row = phrase input (flex, mono) + "=" + result input (fixed 110px, centered, mono) + delete (×) button. Fully editable/addable/removable list, seeded with: нова думка→⏎⏎, нова строка→⏎, кома→",", крапка→".", знак питання→"?", стерти слово→"⌫ (слово)".

### 5. Settings
Four grouped cards, each row = label (13px/500) + hint (11.5px tertiary) on the left, control on the right, hairline divider between rows (last row in each card has no divider):
- **Загальні**: 4 toggle switches — "Запускати з Windows" (default ON), "Показувати плаваючу панель" (ON), "Звук при завершенні диктовки" (OFF), "Автоматичне визначення мови" (ON). Toggle = 38×22 pill track (coral when on, gray track-off color when off) + 16px white thumb sliding with a 180ms spring.
- **Гаряча клавіша**: "Натисніть клавіші" hotkey-capture button — shows current combo (default "Fn") in a mono chip; clicking puts it into "Слухаю…" state with a coral border + coral glow (`box-shadow: 0 0 0 3px accent-soft`) and captures the next real keydown (via a document-level listener) to set the new combo, e.g. "Ctrl+Space".
- **Модель розпізнавання**: two dropdowns — "Модель для української" (options: `stock-large-v3`, `uk-ft-v2 (рекомендовано)`, default uk-ft) and "Пристрій обробки" (options: RTX 4070 [default], RTX 4090, CPU (запасний варіант)).
- **Приватність**: a green privacy note pill ("Диктовки ніколи не залишають цей пристрій") + a masked API-key-style field labeled "Ключ шифрування резервної копії" (optional local backup encryption key) with a show/hide eye-icon toggle button.

## Signature Piece — Floating Pill Overlay
A small, capsule-shaped (20px radius, 40px tall) always-on-top indicator — the core "alive" moment of the product. 4 states, auto-cycling every ~4.2s in the prototype (real product drives this from actual mic/transcription state, and a manual interaction — e.g. a settings action — should be able to stop the auto-cycle):
1. **Idle**: breathing gray dot + "Fn для диктування" (secondary text).
2. **Recording**: pulsing coral dot + small animated waveform (16 thin coral bars) + running mono timer, coral-tinted border.
3. **Transcribing**: neutral dot + shimmering-text "Розпізнаю…" (text-clip gradient sweep).
4. **Done**: small green circular checkmark + mono preview of the pasted text in quotes, e.g. «зателефонувати Оксані до п'ятниці» (truncates with ellipsis if long).
Below it (demo-only, not part of the real overlay) are 4 buttons to jump directly to each state for review.

## Interactions & Behavior Summary
- Sidebar nav click → switches page instantly, active-state indicator slides with a springy 220ms ease.
- Theme toggle → swaps entire palette (dark ⇄ light) instantly, no transition needed beyond what's naturally covered by re-render.
- Home hero preview buttons → force homeState between idle/recording/transcribing; recording starts a 1Hz mm:ss counter reset to 0.
- Stat tiles animate a one-time count-up on initial page mount only.
- History copy button → writes transcript to OS clipboard, shows a 1.4s success checkmark; delete removes the item.
- Dictionary textarea and command rows are fully editable/controlled state; "+ Додати" appends an empty row; × removes a row.
- Hotkey capture button → enters a "listening" state (coral glow) and binds the very next keydown (with modifiers) as the new combo, then exits listening automatically.
- All 4 settings toggles are simple boolean flips with a spring-animated thumb.
- Password-style eye toggle flips the backup-key field between masked/plain text.

## State Management (for the real implementation)
Minimal state shape suggested:
```
theme: 'dark' | 'light'
page: 'home' | 'history' | 'dictionary' | 'settings'
homeState: 'idle' | 'recording' | 'transcribing'   // driven by real mic events in production
recordSecs: number
stats: { wordsToday, dictations, wordsTotal, wpm }   // real usage data
hotkey: { combo: string, listening: boolean }
settings: { autostart, floatingPanel, sound, autoLang, model, gpuDevice, backupKey, backupKeyVisible }
dictionary: { hotwords: string, commands: { phrase, result }[] }
history: { id, time, duration, text }[]
pill: { state: 'idle'|'recording'|'transcribing'|'done', lastText }   // separate always-on-top window/process in production
```

## Assets
No external images/icons — all icons are hand-drawn inline SVGs in a thin-line (1.5–1.7px stroke) style matching Lucide's icon set (mic, clock/history, book, gear, sun, moon, copy, trash, chevron, eye/eye-off, check, x, plus, shield). Fonts loaded from Google Fonts: Inter and JetBrains Mono.

## Files
- `whspr.dc.html` — the full interactive prototype (open directly in a browser). View source for exact inline style values, copy strings, and animation keyframes (`waveScale`, `breathe`, `pulseCoral`, `shimmerSweep`) defined in its `<style>` block.
