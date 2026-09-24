# webview_app.py — pywebview front-end. Serves web/index.html in a native
# WebView2 window and bridges JS ↔ the flow.py core via the Api class.
# flow.py imports this lazily inside main() so there's no import cycle.

import os
import sys
import json
import subprocess
import threading
import webview

import flow

# frozen (PyInstaller) builds unpack bundled data under sys._MEIPASS
BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(BASE, "web")


def detect_gpu() -> str:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        name = out.stdout.strip().splitlines()[0].strip()
        # "NVIDIA GeForce RTX 3070" -> "RTX 3070"
        return name.replace("NVIDIA GeForce ", "").replace("NVIDIA ", "") or "GPU"
    except Exception:
        return "CPU"


class Api:
    """Methods here are callable from JS as window.pywebview.api.<name>(...)."""

    def __init__(self):
        self.gpu = detect_gpu()

    # ---- bootstrap ----
    def bootstrap(self):
        c = flow.config
        s = flow.history_stats()
        rows = flow.history_last(200)  # single query; recent is a slice of it
        return {
            "theme": c.get("theme", "dark"),
            # first-run flag for the onboarding wizard. Defaults to True so a
            # pre-existing config that predates the key is treated as already
            # onboarded; only a fresh install (see flow.load_config) sends False.
            "onboarded": c.get("onboarded", True),
            "version": flow.APP_VERSION,
            "license": flow.license_status(),
            "gpu": self.gpu,
            "hotkey": flow.hotkey_label(c.get("hotkey", "f9")),
            "status": flow.state["status"],
            "stats": {
                "wordsToday": s["words_today"], "dictations": s["total"],
                "wordsTotal": s["words"], "wpm": round(s["wpm"]),
            },
            "recent": [{"time": self._pretty_time(ts), "text": text}
                       for _id, ts, lang, dur, text in rows[:4]],
            "history": [{"id": _id, "time": ts[11:16], "day": self._day_label(ts),
                         "lang": lang, "duration": f"{dur:.1f}с", "text": text}
                        for _id, ts, lang, dur, text in rows],
            "settings": {
                "autostart": c.get("autostart", False),
                "floatingPanel": c.get("overlay", True),
                # placement is either a preset name or {"x","y"} in percent of
                # the free space on each axis; ui.parse_position owns the
                # meaning of both shapes, so it travels to the UI untouched
                "overlayPosition": c.get("overlay_position", "bottom-center"),
                # "pill" | "orb" | "dock" — ui.StatusOverlay owns the meaning
                "overlayStyle": c.get("overlay_style", "pill"),
                "overlayScale": c.get("overlay_scale", 100),
                "overlayOpacity": c.get("overlay_opacity", 82),
                "sound": c.get("sound", False),
                "autoLang": c.get("auto_lang", False),
                "model": c.get("model_uk", "stock"),
                "gpuDevice": self.gpu,
                "device": c.get("device", "cuda"),
                "inputDevice": c.get("input_device", ""),
                "micOnDemand": c.get("mic_on_demand", False),
                "muteOthers": c.get("mute_others", True),
                "vad": c.get("vad", False),
                "spokenPunctuation": c.get("spoken_punctuation", True),
                "normalizeNumbers": c.get("normalize_numbers", True),
                "voiceCommands": c.get("voice_commands", True),
                "handsFree": c.get("hands_free", False),
                "llm": c.get("llm", "off"),
                "groqKey": c.get("groq_api_key", ""),
                "groqModel": c.get("groq_model", ""),
                "ollamaModel": c.get("ollama_model", ""),
                "groqKeyVisible": False,
                # cloud recognition (BYOK)
                "sttBackend": c.get("stt_backend", "local"),
                "sttProvider": c.get("stt_provider", "groq"),
                "sttModel": c.get("stt_model", "whisper-large-v3"),
                "openaiKey": c.get("openai_api_key", ""),
                "elevenlabsKey": c.get("elevenlabs_api_key", ""),
                # admin-editable corrector instruction; blank means the UI shows
                # (and the app uses) the shipped default, exposed alongside so
                # the settings page can prefill it and offer a reset
                "llmPrompt": c.get("llm_prompt", ""),
                "llmPromptDefault": flow.LLM_PROMPT,
            },
            "devices": flow.list_input_devices(),
            "models": flow.models_status(),
            "dictionary": {
                "hotwords": c.get("dictionary", ""),
                "commands": [{"phrase": k, "result": v}
                             for k, v in c.get("replacements", {}).items()],
            },
        }

    @staticmethod
    def _pretty_time(ts):
        import time
        today = time.strftime("%Y-%m-%d")
        if ts.startswith(today):
            return f"Сьогодні, {ts[11:16]}"
        return ts[5:16].replace("-", ".")

    # Ukrainian genitive month names for the history day headers.
    _MONTHS_UK = ("січня", "лютого", "березня", "квітня", "травня", "червня",
                  "липня", "серпня", "вересня", "жовтня", "листопада", "грудня")

    @classmethod
    def _day_label(cls, ts):
        """Real calendar day for a history row: 'Сьогодні' / 'Вчора' / '12 вересня'.

        The list groups by this exact string, so grouping no longer has to be
        guessed from the clock rising between rows. `ts` is 'YYYY-MM-DD HH:MM:…';
        a malformed one just falls back to its own date slice."""
        import datetime
        try:
            d = datetime.date.fromisoformat(ts[:10])
        except (ValueError, TypeError):
            return ts[:10]
        today = datetime.date.today()
        if d == today:
            return "Сьогодні"
        if d == today - datetime.timedelta(days=1):
            return "Вчора"
        label = f"{d.day} {cls._MONTHS_UK[d.month - 1]}"
        return label if d.year == today.year else f"{label} {d.year}"

    # ---- live ----
    def get_status(self):
        return flow.state["status"]

    def get_download(self):
        d = dict(flow.state.get("download", {"active": False}))
        # downloading is the authoritative in-progress flag: `active` only flips
        # true once the HF cache starts growing, so a fresh download reads as
        # inactive for a moment while snapshot_download resolves the revision
        d["downloading"] = flow.state.get("downloading") is not None
        d["error"] = flow.state.get("download_error")
        return d

    def get_input_level(self):
        return flow.state.get("input_level", 0.0)

    def mic_test(self, on):
        return flow.mic_test(bool(on))


    def _mic_endpoint_state(self, quiet: bool):
        """(can_fix, level) for the banner. Currently always (False, None).

        DISABLED, and the reason is worth keeping. Probing the capture endpoint
        means activating COM objects from the pywebview JS-bridge thread, and on
        this machine that kills the process outright: pythonw died with
        0xc0000374 (heap corruption in ntdll) and 0xc0000005 in _ctypes.pyd at
        the same +0x784d offset, every time within seconds of the probe running.
        Rate-limiting it to once a minute only made the crash rarer, not absent —
        the frequency was never the problem, the bridge thread's COM apartment
        is. duck_others() gets away with the same pycaw calls because it only
        ever runs on the pynput listener thread.

        The banner itself still works and still carries the measured RMS; it just
        offers advice instead of a button. On the machine this was built for that
        costs nothing, because its endpoint already sits at 100% and the button
        could never have helped — the headroom is in the driver's Microphone
        Boost. mic_level.py stays in the tree and is correct when called from an
        ordinary thread; re-wiring it needs a dedicated COM thread that owns the
        endpoint for the process lifetime, which is a change worth making
        deliberately rather than in a hotfix."""
        return False, None

    def get_mic_warning(self):
        """{"quiet": bool, "rms": float|None, "canFix": bool, "level": float|None}
        for the Home banner. flow.py sets mic_too_quiet when the software boost
        pins at its ceiling — that mic is amplifying room noise and Whisper
        answers with junk. `level` is the Windows capture slider (0..1): at 1.0
        with a quiet signal the remaining headroom is in the driver's separate
        "Microphone Boost", which Core Audio's master scalar cannot reach, so the
        UI has to stop offering a button that would do nothing."""
        quiet = bool(flow.state.get("mic_too_quiet", False))
        can_fix, level = self._mic_endpoint_state(quiet)
        rms = flow.state.get("mic_rms")
        return {
            "quiet": quiet,
            # None until the first take has actually been measured
            "rms": float(rms) if isinstance(rms, (int, float)) else None,
            "canFix": can_fix,
            "level": float(level) if isinstance(level, (int, float)) else None,
        }

    def fix_mic_level(self):
        """Tell the user where the Windows slider is. Deliberately does NOT
        touch COM — see _mic_endpoint_state for why that crashes the process.

        _mic_endpoint_state returns canFix=False, so the banner never renders
        the button that would call this; the method stays so an older cached
        page cannot reach a missing API, and so re-enabling the feature later is
        a one-place change."""
        return {"ok": False, "changed": False,
                "reason": "Підніміть гучність мікрофона у Windows: "
                          "Звук → Ввід → Властивості → Рівні. Якщо повзунок уже "
                          "на максимумі, шукайте «Підсилення мікрофона» "
                          "(Microphone Boost) там само."}

    def get_license(self):
        return flow.license_status()

    def activate_license(self, key):
        return flow.activate_license(key or "")

    def verify_stt(self):
        # persists first via save_settings, so this reads the just-entered key
        return flow.verify_stt()

    def check_update(self):
        return flow.check_update()

    def install_update(self, url):
        ok = flow.download_update(url)
        if ok:
            def bye():
                import time
                time.sleep(1.5)
                flow.quit_app()
            threading.Thread(target=bye, daemon=True).start()
        return ok

    def get_pill(self):
        import time
        st = flow.state["status"]
        # These are the exact names flow.set_status() emits; anything else falls
        # through to the "done"/"idle" pill below. Matching on a name flow.py
        # never sends (e.g. "transcribing") silently blanks the pill mid-work.
        if st in ("recording", "processing", "loading"):
            return {"state": st}
        if time.time() - flow.state.get("pill_done_at", 0) < 2.5:
            return {"state": "done", "text": flow.state.get("pill_text", "")}
        return {"state": "idle", "hotkey": flow.hotkey_label(flow.config.get("hotkey", "f9"))}

    def set_theme(self, theme):
        flow.config["theme"] = theme
        flow.save_config(flow.config)
        return True

    def finish_onboarding(self):
        """Mark the first-run wizard as done and persist it. Called by the web UI
        when onboarding completes (Done) or is skipped. Deliberately its own
        method rather than an overload of save_settings: it must write the gate
        even when the user changed no setting, and must never touch anything
        else. Once True, bootstrap() will never send onboarded=False again."""
        flow.config["onboarded"] = True
        flow.save_config(flow.config)
        return True

    def toggle_lang(self):
        st = flow.state
        st["lang"] = (st["lang"] + 1) % len(flow.LANGUAGES)
        return flow.LANGUAGES[st["lang"]]

    # ---- settings ----
    def save_settings(self, s):
        c = flow.config
        old_dev = c.get("input_device", "")
        old_mode = c.get("mic_on_demand", False)
        old_device = c.get("device", "cuda")
        c["autostart"] = bool(s.get("autostart"))
        c["overlay"] = bool(s.get("floatingPanel"))
        old_pill = (c.get("overlay_position"), c.get("overlay_scale"),
                    c.get("overlay_style"), c.get("overlay_opacity"))
        # overlay style: exactly one of the three shapes the overlay can draw;
        # anything else (junk, a future name) keeps the current value rather
        # than landing an unrenderable style in config.json
        style = s.get("overlayStyle")
        if style in ("pill", "orb", "dock"):
            c["overlay_style"] = style
        # ui.parse_position is the single source of truth for what a placement
        # means, so only obviously unusable shapes are refused here — a bad
        # value keeps the old one instead of landing in config.json
        pos = s.get("overlayPosition")
        if isinstance(pos, dict):
            try:
                c["overlay_position"] = {
                    "x": min(100.0, max(0.0, float(pos.get("x", 50)))),
                    "y": min(100.0, max(0.0, float(pos.get("y", 100)))),
                }
            except (TypeError, ValueError):
                pass
        elif isinstance(pos, str) and pos.strip():
            c["overlay_position"] = pos.strip()
        try:
            c["overlay_scale"] = min(140, max(80, int(s.get("overlayScale", 100))))
        except (TypeError, ValueError):
            pass
        try:
            c["overlay_opacity"] = min(100, max(40, int(s.get("overlayOpacity", 82))))
        except (TypeError, ValueError):
            pass
        c["sound"] = bool(s.get("sound"))
        c["auto_lang"] = bool(s.get("autoLang"))
        # model_uk is deliberately not touched here: activate_model() owns it.
        # Writing it from this payload too meant a stale value in the UI state
        # could reset the model whenever any unrelated toggle was flipped.
        c["device"] = "cpu" if s.get("device") == "cpu" else "cuda"
        c["input_device"] = s.get("inputDevice", "") or ""
        c["mic_on_demand"] = bool(s.get("micOnDemand"))
        c["mute_others"] = bool(s.get("muteOthers"))
        # vad needs neither restart_stream() nor reload_models(): it is read from
        # config on every transcribe() call as the vad_filter argument, so the
        # next dictation already sees the new value. Reloading here would throw
        # away the warm model and stall that dictation for several seconds.
        c["vad"] = bool(s.get("vad"))
        c["spoken_punctuation"] = bool(s.get("spokenPunctuation"))
        c["normalize_numbers"] = bool(s.get("normalizeNumbers"))
        c["voice_commands"] = bool(s.get("voiceCommands"))
        c["hands_free"] = bool(s.get("handsFree"))
        if s.get("llm") in ("off", "groq", "ollama"):
            c["llm"] = s["llm"]
        # blank model fields fall back to the shipped defaults rather than
        # writing "" and silently breaking the request
        c["groq_api_key"] = s.get("groqKey", "") or ""
        c["groq_model"] = s.get("groqModel", "") or flow.DEFAULTS["groq_model"]
        c["ollama_model"] = s.get("ollamaModel", "") or flow.DEFAULTS["ollama_model"]
        # cloud recognition (BYOK). Read on every transcribe() call, so no reload
        # or stream restart is needed for a change to take effect.
        c["stt_backend"] = "cloud" if s.get("sttBackend") == "cloud" else "local"
        if s.get("sttProvider") in ("groq", "openai", "elevenlabs"):
            c["stt_provider"] = s["sttProvider"]
        c["stt_model"] = s.get("sttModel", "") or flow.DEFAULTS["stt_model"]
        c["openai_api_key"] = s.get("openaiKey", "") or ""
        c["elevenlabs_api_key"] = s.get("elevenlabsKey", "") or ""
        # blank (or exactly the default) stores "" so the built-in prompt — and
        # its future improvements — keep applying; a real edit is stored verbatim
        prompt = (s.get("llmPrompt") or "").strip()
        c["llm_prompt"] = "" if prompt == flow.LLM_PROMPT.strip() else prompt
        flow.save_config(c)
        flow.set_autostart(c["autostart"])
        # the pill bakes size and placement in when it is built, so it only
        # moves if we rebuild it — and only bother when those two actually changed
        if (c.get("overlay_position"), c.get("overlay_scale"),
                c.get("overlay_style"), c.get("overlay_opacity")) != old_pill:
            flow.apply_overlay_config()
        if c["input_device"] != old_dev or c["mic_on_demand"] != old_mode:
            flow.restart_stream()
        if c["device"] != old_device:
            flow.reload_models()
        return True

    def list_devices(self):
        return flow.list_input_devices()

    # ---- model library ----
    def list_models(self):
        return flow.models_status()

    def download_model(self, key):
        return flow.download_model(key)

    def delete_model(self, key):
        return flow.delete_model(key)

    def activate_model(self, key):
        """Switch the active model, but only to one that is already on disk —
        activating a missing model would stall the next dictation on a download."""
        if key not in flow.MODELS:
            return {"ok": False, "error": "невідома модель"}
        if not flow.model_installed(flow.MODELS[key]["repo"]):
            return {"ok": False, "error": "модель не завантажена"}
        c = flow.config
        if c.get("model_uk") == key:
            return {"ok": True}
        c["model_uk"] = key
        flow.save_config(c)
        flow.reload_models()
        return {"ok": True}

    def save_dictionary(self, hotwords, commands):
        c = flow.config
        c["dictionary"] = hotwords or ""
        c["replacements"] = {cm["phrase"]: cm["result"]
                             for cm in commands if cm.get("phrase")}
        flow.save_config(c)
        return True

    # ---- history ----
    def history_copy(self, row_id):
        for _id, ts, lang, dur, text in flow.history_last(500):
            if _id == row_id:
                import pyperclip
                pyperclip.copy(text)
                return True
        return False

    def history_delete(self, row_id):
        flow.history_delete(row_id)
        return True

    def history_clear(self):
        flow.history_clear()
        return True

    # ---- hotkey capture ----
    def capture_hotkey(self):
        result = {}
        done = threading.Event()

        def on_done(spec):
            flow.config["hotkey"] = spec
            flow.save_config(flow.config)
            flow.restart_listener()
            result["label"] = flow.hotkey_label(spec)
            done.set()

        flow.capture_hotkey(on_done)
        done.wait(timeout=10)
        return result.get("label", flow.hotkey_label(flow.config.get("hotkey", "f9")))


def run() -> None:
    """Create the native window(s) and start the webview loop (blocks)."""
    # Keep WebView2 rendering while the window is hidden in the tray. Without
    # this, Chromium's native occlusion detection suspends the compositor once
    # the window is hidden/occluded, and restoring it from the tray after a while
    # shows a black screen until a repaint — the classic "only a restart fixes
    # it" symptom. Disabling occlusion calculation keeps the surface painted.
    prev_args = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
    flags = "--disable-features=CalculateNativeWinOcclusion " \
            "--disable-backgrounding-occluded-windows"
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (prev_args + " " + flags).strip()

    api = Api()
    window = webview.create_window(
        "KuubWave", os.path.join(WEB_DIR, "index.html"),
        # the Soft Studio layout (216px sidebar + roomy content) is cramped at
        # the old compact size; this opens comfortably on a 1080p screen while
        # min_size still lets it shrink. background matches the dark plateau the
        # UI paints, so there is no near-black flash before the page loads.
        js_api=api, width=1360, height=900, min_size=(900, 640),
        background_color="#171319",
    )
    flow.state["webview_window"] = window

    # Closing the window hides it to the tray instead of quitting — dictation
    # keeps working in the background. Quit via the tray menu ("Вихід").
    # Without a tray icon there would be no way back to the window and no way
    # to quit, so in that case let the close actually close.
    def _on_closing():
        if flow.tray_icon is None:
            flow.log("no tray icon — closing the window quits")
            return True
        try:
            window.hide()
        except Exception:
            pass
        return False  # cancel the real close

    try:
        window.events.closing += _on_closing
    except Exception:
        pass

    # Open large and centred (not maximized — full screen is too much). Size to a
    # generous share of the monitor's work area, capped, so the window is roomy
    # without covering everything and never lands under the sidebar-collapse
    # breakpoint. Runs on every launch.
    def _size_on_load():
        try:
            dims = window.evaluate_js(
                "[window.screen.availWidth, window.screen.availHeight]")
            aw, ah = int(dims[0]), int(dims[1])
            w = min(1440, max(1100, int(aw * 0.82)))
            h = min(940, max(720, int(ah * 0.86)))
            window.resize(w, h)
            window.move(max(0, (aw - w) // 2), max(0, (ah - h) // 2))
        except Exception as e:
            flow.log(f"window sizing skipped ({e.__class__.__name__}: {e})")
    try:
        window.events.loaded += _size_on_load
    except Exception:
        pass

    # The floating status pill lives in a Tkinter overlay (flow._start_overlay),
    # not a pywebview window: WebView2 on Windows can't render a transparent,
    # rounded, always-on-top capsule, so Tk with -transparentcolor handles it.

    # icon= is what puts kuubwave.ico on the window, and the taskbar button draws
    # the window's icon — without it the button fell back to pythonw.exe's, which
    # is the generic Python icon that showed up there. create_window() has no
    # icon parameter in pywebview 6.x; it belongs on start(). Verified by reading
    # the pixels back off the live window: with icon= the button's bitmap matches
    # kuubwave.ico, without it it does not. (The AppUserModelID set in flow.main()
    # is a separate concern — grouping and pinning, not which icon is drawn.)
    try:
        webview.start(icon=flow._icon_path())
    except TypeError:
        # older pywebview without the icon parameter — a plain window beats no
        # window at all
        flow.log("pywebview build has no icon= support — window icon skipped")
        webview.start()
