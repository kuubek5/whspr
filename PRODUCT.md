# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

<!-- The shipping app is a Windows desktop app (pywebview shell around this web
UI). The UI itself is plain HTML/CSS/JS in web/, rendered in WebView2, so design
work is web. Native-OS surfaces (tray, hotkey, overlay pill) live in Python. -->

## Users

Broad audience of people who dictate text instead of typing — notes, messages,
emails, code comments — on Windows. They speak Ukrainian or English and switch
between them. Many are privacy-minded and run a local NVIDIA GPU, but the product
targets general dictation users, not a narrow professional niche.

## Product Purpose

KuubWave turns speech into text anywhere on the screen: hold a hotkey, speak,
release, and the recognized text is pasted into whatever window had focus. It
exists to make dictation fast, private, and Ukrainian-first, without sending
audio to the cloud.

## Positioning

Fully local, private dictation with a Ukrainian focus: recognition runs on the
user's own GPU (Whisper + a Ukrainian fine-tune, anti-russification, ru-retry),
so no audio or text leaves the machine. A global hotkey makes it work in any app,
not just one editor. This local + Ukrainian-first combination is the mechanism a
cloud dictation tool cannot truthfully copy.

## Operating Context

Runs resident in the Windows tray. The user holds a configurable hotkey (e.g.
middle mouse button / Fn) to record, sees a small floating overlay pill while
speaking, releases to transcribe and auto-paste. Works over any foreground app.
First-run onboarding, per-user history, and a custom vocabulary support daily use.

## Capabilities and Constraints

- Push-to-talk and hands-free dictation; auto language detection (uk/en).
- GPU (CUDA) or CPU recognition; CUDA libs fetched on first run, not bundled.
- Spoken punctuation, number normalization, voice commands, optional LLM polish.
- Floating overlay (pill / orb / dock) with adjustable position, scale, opacity.
- System tray, autostart, in-app auto-update from public GitHub releases.
- Offline: recognition makes no external calls; data stays on the device.

## Brand Commitments

- Name: **KuubWave** (Kuub brand family; renamed from "whspr").
- Logo: coral→aqua radial audio-waveform ring around a coral 'k' monogram.
- "Soft Studio" visual system: coral (#FF6B5E) + aqua (#33CBBB) accents on a
  warm-dark surface, IBM Plex Sans (bundled, offline), light and dark themes.
- Ukrainian-first UI copy.

## Evidence on Hand

Real running app and web UI in web/; brand assets in brand/. No testimonials,
customer names, benchmarks, or pricing exist yet — future work must not fabricate
them.

## Product Principles

1. Private by default — recognition and data never leave the device.
2. Ukrainian-first, English-capable — never degrade Ukrainian to serve English.
3. Works everywhere — a global hotkey over any app, not a single editor.
4. Stay out of the way — resident, quiet, a small overlay; the focus is the text.
5. Honest, plain communication — no cloud claims, no invented proof.

## Accessibility & Inclusion

Ukrainian-language UI; AAA contrast targeted in the UI (prior work). No further
product-specific standard established yet.
