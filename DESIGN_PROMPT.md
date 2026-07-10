# whspr — Design Prompt

Готовий промт для генеративних дизайн-інструментів (v0.dev, Lovable, Figma AI,
Galileo) та візуальних (Midjourney/чат-моделі). Копіюй потрібну секцію.

---

## 1. Основний промт (для v0 / Lovable / Figma AI / дизайн-ШІ)

```
Design a premium desktop app UI called "whspr" — a local, privacy-first
push-to-talk voice dictation tool for Windows (a self-hosted alternative to
Wispr Flow). The whole value prop: everything runs locally on the user's GPU,
nothing goes to the cloud. The design must feel like a flagship developer-tool
product — quiet, confident, fast.

DESIGN NORTH STAR
Match the craft level of Linear, Raycast, Arc Browser, Superhuman, and Vercel.
Restrained, information-dense but never cluttered, spatial depth over decoration.
Dark-first, with an equally polished light theme. No skeuomorphism, no glass
gimmicks, no neon. Elegance through spacing, hierarchy, and motion — not effects.

VISUAL LANGUAGE
- Theme: dark-first. Background is a near-black with a subtle cool tint
  (#0E0E12 → #16161C), NOT pure black. Surfaces layer with 3–4 elevation steps
  using very low-contrast fills (#1A1A22, #22222B) and 1px hairline borders at
  ~8% white. Light theme mirrors it (off-white #FAFAFB, soft gray cards).
- Accent: a single confident signal color used sparingly — a warm coral/red
  (#F0555C) reserved almost exclusively for the RECORDING state and primary CTA.
  Everything else is grayscale. The accent must feel earned, not sprayed.
- Typographic scale: Inter or Geist for UI; a mono (JetBrains Mono / Geist Mono)
  for transcript text, stats numbers, and hotkey chips. Tight tracking on large
  headings, generous line-height on body. Numbers are tabular.
- Spacing: 8px base grid, generous padding (20–28px in cards), lots of breathing
  room. Radius: 12–16px on cards, 8–10px on controls, fully round on the pill.
- Depth: soft, large, low-opacity shadows (never harsh). One or two ambient
  radial glows behind the hero status area, very subtle.
- Iconography: thin, consistent line icons (Lucide/Phosphor), 1.5px stroke.

CORE SCREENS
1. Main window — left sidebar nav (Home, History, Dictionary, Settings) +
   content area. Sidebar is quiet: app wordmark, nav items with icon+label,
   a live status dot pinned to the bottom.
2. Home / Dashboard — a HERO status card at top: a large state indicator
   (Idle / Recording with a live waveform or pulsing ring + timer / Transcribing
   with a shimmer). Below it a row of stat tiles (words today, dictations,
   total words, words-per-minute) as clean number-forward cards. Under that, a
   "Recent dictations" feed — timestamp + transcript, monospace, subtle dividers.
3. Floating pill overlay — a small, always-on-top capsule that appears near the
   bottom-center of the screen while dictating. States: a red dot + waveform +
   timer (recording) → animated shimmer "Transcribing…" → a green check with the
   pasted text preview → auto-dismiss. This is the signature UI moment — make it
   feel alive and effortless, like Superhuman's command bar or macOS Dynamic Island.
4. History — a scannable list of past dictations, each a card with meta row
   (time · language · duration) and the transcript. Hover reveals copy/delete.
5. Settings — grouped rows in cards: a "Press keys" hotkey capture control that
   glows the accent while listening, toggles as refined switches, dropdowns,
   an API-key field. Section headers, plenty of whitespace.

MICRO-INTERACTIONS
- The recording pill uses a live audio waveform (thin animated bars) reacting to
  voice level. Idle → Recording transition is a smooth morph, not a pop.
- Status dot breathes softly when idle; pulses on the accent when recording.
- Stat numbers count up on load. Nav selection slides a subtle indicator.
- Everything eases with fast, springy motion (150–250ms), never sluggish.

TONE
Ukrainian + English UI copy is expected (labels like "Головна", "Історія",
"Розпізнаю…"). Keep chrome minimal — the app should feel like a quiet utility
that gets out of the way, then delights in the split second of dictation.

DELIVER
Full dark theme main window (Dashboard), the floating recording pill in its
3 states, and the Settings screen. Then the light theme of the Dashboard.
Pixel-crisp, production-grade, desktop proportions (~900×600 window).
```

---

## 2. Короткий візуальний промт (Midjourney / чат-моделі для мокапів)

```
Ultra-modern desktop app UI for "whspr", a local voice-dictation tool, dark
theme, near-black cool-tinted background (#0E0E12), layered charcoal cards with
1px hairline borders, single warm coral accent (#F0555C) only on the recording
state, Inter + mono typography, tabular stat numbers, thin Lucide line icons,
left sidebar navigation, a hero status card with a live audio waveform, a
floating rounded pill overlay showing a red dot + waveform + timer, soft ambient
radial glow, generous spacing, 14px radius, premium developer-tool aesthetic in
the spirit of Linear, Raycast, Arc and Superhuman, crisp, elegant, minimal,
Figma mockup, 8k --ar 16:10
```

---

## 3. Нотатки щодо реалізації

- **customtkinter** (поточний стек) дасть ~70% цього вигляду: темні картки,
  скруглення, switch-контроли, кастомні шрифти. Обмеження: складна анімація
  (live-waveform, морфінг пігулки, shimmer) незручна.
- Для **повної свободи дизайну** — перейти на **PyWebView** (HTML/CSS/JS у
  вбудованому webview, Python-бекенд через bridge) або **Tauri** (Rust+web).
  Тоді весь промт вище реалізовний 1:1: CSS-анімації, Web Audio для waveform,
  справжні springи. Ядро (`flow.py`) лишається — міняється лише шар UI.
- **Компромісний шлях:** головне вікно на PyWebView (гарне), пігулку-оверлей —
  теж прозоре webview-вікно завжди-зверху з canvas-waveform. Трей і хоткеї — як є.

## 4. Дизайн-токени (стартові, під будь-який стек)

```
--bg:            #0E0E12    (dark) / #FAFAFB (light)
--surface-1:     #16161C / #FFFFFF
--surface-2:     #1E1E26 / #F2F2F4
--surface-3:     #262630 / #E8E8EC
--border:        rgba(255,255,255,.08) / rgba(0,0,0,.08)
--text:          #ECECF2 / #1A1A20
--text-muted:    #8A8A98 / #6A6A76
--accent:        #F0555C   (recording / primary CTA — використовувати скупо)
--ok:            #46A758
--warn:          #F0B429
--radius-card:   14px   --radius-ctl: 9px
--space-base:    8px    --pad-card: 22px
--font-ui:       Inter / Geist
--font-mono:     JetBrains Mono / Geist Mono (транскрипт, числа, хоткеї)
--ease:          cubic-bezier(.2,.8,.2,1)   --dur: 180ms
```
