"""Hotkeys: the hold-to-talk listener (keyboard and mouse side buttons), hotkey parsing and labels, the hands-free and command-mode triggers, capturing a new hotkey, and AppContext, the bridge the GUI calls. Moved verbatim out of flow.py."""

import threading
import time

from pynput import keyboard, mouse

import latency

import flow


# ---------------- Hotkeys ----------------
MODS = ("ctrl", "alt", "shift", "cmd")
# vk -> readable name for display/capture (letters, digits, common keys)
VK_NAMES = {**{0x41 + i: chr(ord("A") + i) for i in range(26)},
            **{0x30 + i: str(i) for i in range(10)},
            **{0x60 + i: f"Num{i}" for i in range(10)}}
NAME_VK = {v.lower(): k for k, v in VK_NAMES.items()}


def canon(key) -> str:
    """Canonical, layout-independent token for one key event."""
    if isinstance(key, keyboard.Key):
        name = key.name
        for m in MODS:
            if name.startswith(m):
                return m
        return name  # f9, space, tab, scroll_lock, pause, ...
    # KeyCode: use physical vk (char depends on active layout)
    vk = getattr(key, "vk", None)
    return f"vk{vk}" if vk is not None else str(key)


def canon_mouse(button) -> str | None:
    """Bindable mouse buttons -> token; None for left/right (needed for normal
    clicking, never safe to steal for a hotkey)."""
    name = getattr(button, "name", "")
    return f"mouse_{name}" if name in ("x1", "x2", "middle") else None


MOUSE_LABELS = {"mouse_x1": "Бокова 1", "mouse_x2": "Бокова 2",
                "mouse_middle": "Середня кнопка"}


def parse_hotkey(spec: str) -> frozenset:
    """'ctrl+space' / 'f9' / 'alt+vk81' -> frozenset of canonical tokens."""
    out = set()
    for part in (spec or "f9").lower().split("+"):
        part = part.strip()
        if not part:
            continue
        if part in NAME_VK:            # 'q' -> vk81
            out.add(f"vk{NAME_VK[part]}")
        else:
            out.add(part)
    return frozenset(out)


def hotkey_label(spec: str) -> str:
    """Pretty form for the UI: 'ctrl+vk81' -> 'Ctrl + Q'."""
    parts = []
    for t in sorted(parse_hotkey(spec), key=lambda x: (x not in MODS, x)):
        if t in MODS:
            parts.append(t.capitalize())
        elif t.startswith("mouse_"):
            parts.append(MOUSE_LABELS.get(t, t))
        elif t.startswith("vk"):
            parts.append(VK_NAMES.get(int(t[2:]), t.upper()))
        else:
            parts.append(t.replace("_", " ").title())
    return " + ".join(parts)


def start_listener() -> "_Listeners":
    """Hold-to-talk listener supporting single keys, combos, AND mouse side
    buttons. Rebuilt on the fly by restart_listener() when the hotkey changes."""
    required = parse_hotkey(flow.config["hotkey"])
    lang_key = parse_hotkey(flow.config.get("lang_hotkey", "f10"))
    # command mode's own trigger (empty = disabled); see run_selection_command
    cmd_key = flow.command_trigger(flow.config.get("command_hotkey", ""),
                              flow.config.get("command_mode_enabled", True), required)
    pressed: set[str] = set()
    # which kind of take is recording: "dictate" or "command". Set at start,
    # read once at stop — the two kinds share the whole audio path.
    flow.state["take_kind"] = "dictate"

    def start_rec():
        if not flow.is_licensed():
            flow.log("dictation locked — no valid license")
            return
        if flow.state["model"] is None:
            flow.log("model still loading, try again in a moment")
            return
        if flow.config.get("mic_on_demand") and flow.state.get("stream") is None:
            flow.state["stream"] = flow.open_input_stream()
            if flow.state["stream"] is None:
                flow.log("cannot record: no input device")
                return
        # drop anything left from an aborted take, but KEEP pre_roll: it holds
        # the audio captured just before this key press, which is the point of
        # it. A take still transcribing has already detached its own copy.
        with flow._buf_lock:
            flow.chunks.clear()
        # remember where the user was when they started talking: a dictation
        # pastes THERE, even if focus wanders during the take (see
        # dictation_paste_target). Command takes keep their own command_hwnd.
        flow.state["start_hwnd"] = flow.user32.GetForegroundWindow()
        flow.state["take_id"] = flow.state.get("take_id", 0) + 1
        flow.state["recording"] = True
        flow.duck_others(True)
        flow.set_status("recording")
        flow.log("recording...")
        # words-as-you-speak in the pill; dictations only (a command take's
        # instruction is not text the user wants to watch being typed)
        if flow.state.get("take_kind") == "dictate" and flow.live_preview_enabled():
            threading.Thread(target=flow.live_preview_loop, args=(flow.state["take_id"],),
                             daemon=True).start()
        # TLS handshake to the LLM while the user talks, not after (see
        # _http_pool); background thread, no request sent, no-op without Groq
        flow._llm_prewarm()

    def stop_rec(dec=None):
        """`dec` = the hands-free auto-stop decider when IT ended the take, so
        the latency trace can start at the real end of speech instead of at the
        stop. Push-to-talk and manual taps pass nothing: release is the end."""
        if not flow.state["recording"]:
            return
        flow.state["recording"] = False
        trace = latency.Trace()
        # restore playback now: no reason to keep other apps silent through
        # transcription, which runs on its own thread below
        flow.duck_others(False)
        # Detach the audio HERE, on the listener thread, while recording is
        # provably over and start_rec() cannot yet have run again. If we left
        # this to the worker thread, the gap between spawning it and the OS
        # scheduling it is enough for the user to press the hotkey again:
        # start_rec() would clear `chunks` (destroying THIS take) and the worker
        # would then wake up and steal the next take's half-recorded audio.
        pre, cur = flow.take_audio()
        ago = None
        if dec is not None:
            try:
                ago = dec.silence_ago(sum(len(c) for c in cur) / flow.SAMPLE_RATE,
                                      time.time())
            except Exception:
                ago = None  # timing is diagnostics; never cost the take
        trace.stopped(ago)
        # the pause the auto-stop fired on, so the decode can reuse a
        # speculative pass made during that same pause (see _speculate)
        since = getattr(dec, "silent_since", None)
        stop_info = (flow.state.get("take_id"), since) if since is not None else None
        command = flow.state.get("take_kind") == "command"
        flow.state["take_kind"] = "dictate"
        # a command edits the window whose selection was there when the key
        # went DOWN (unchanged); a dictation pastes into the window focused at
        # its START, falling back to the current one (dictation_paste_target)
        start_hwnd = flow.state.pop("start_hwnd", None)
        if command:
            hwnd = flow.state.get("command_hwnd") or flow.user32.GetForegroundWindow()
        else:
            hwnd = flow.dictation_paste_target(start_hwnd)
        threading.Thread(target=flow.transcribe_and_paste,
                         args=(pre, cur, hwnd, command, trace, stop_info),
                         daemon=True).start()
        if flow.config.get("mic_on_demand"):
            flow.close_stream()

    def cancel_rec(why: str):
        """End the take WITHOUT transcribing it: nothing is pasted, no history.
        Same teardown as stop_rec otherwise."""
        if not flow.state["recording"]:
            return
        flow.state["recording"] = False
        flow.duck_others(False)
        flow.take_audio()  # discard
        flow.state["take_kind"] = "dictate"
        flow.state.pop("start_hwnd", None)
        flow.log(f"take cancelled — {why}")
        flow.set_status("idle")
        flow._overlay_flash("не почув голосу", False)
        if flow.config.get("mic_on_demand"):
            flow.close_stream()

    def silence_watch():
        """Hands-free: stop recording once the user has stopped talking. The
        decision lives in VadAutoStop / RmsAutoStop (see make_autostop); this
        loop only feeds them. Auto-stop arms only after real speech, so it never
        fires on the opening pause; max_utterance_s is a hard cap either way."""
        time.sleep(0.3)  # let the stream fill before judging anything
        gap = float(flow.config.get("silence_stop_s", 1.5))
        hard_max = flow.config.get("max_utterance_s", 60)
        no_speech_s = float(flow.config.get("no_speech_cancel_s", 10) or 0)
        t_start = time.time()
        dec = flow.make_autostop(gap)
        vad = flow._vad_model if dec.name == "vad" else None
        fed = 0  # frames of this take already scored by the VAD
        # Smart Turn rides on the VAD's silence clock; (None, None) = off, not
        # loaded yet, or rms engine — the loop below is then exactly VAD-only
        st_model, st_gate = flow.make_smart_turn_gate(dec, gap)
        st_note = (f" smart-turn ask@{st_gate.gap}s thr={st_gate.threshold}"
                   if st_gate else "")
        flow.log(f"hands-free: auto-stop engine={dec.name} gap={gap}s{st_note}")
        spec_key = None  # the pause already being decoded speculatively
        while flow.state["recording"]:
            stop = smart = False
            if vad is not None:
                try:
                    stop, fed = flow.vad_poll(vad, dec, fed)
                except Exception as e:
                    # never let a VAD hiccup end or wedge dictation: finish THIS
                    # take on the loudness heuristic instead
                    flow.log(f"hands-free: VAD failed mid-take ({e.__class__.__name__}: "
                        f"{e}) — rms auto-stop for this take")
                    dec, vad, st_gate = flow.RmsAutoStop(gap), None, None
                if not stop and st_gate is not None and vad is not None:
                    stop = smart = flow.smart_turn_poll(st_model, st_gate, dec)
            else:
                stop = dec.feed(flow.state.get("input_level", 0.0), time.time())
            if stop and flow.state["recording"]:
                why = "smart-turn" if smart else "silence"
                flow.log(f"hands-free: {why} -> auto stop ({dec.describe()})")
                stop_rec(dec)
                return
            # a pause long enough to be the end: recognise it now, while the
            # auto-stop is still waiting (VAD only — it alone knows where the
            # pause began, which is what makes the result safe to reuse)
            since = getattr(dec, "silent_since", None) if vad is not None else None
            if (since is not None and dec.silence_s() >= flow.SPEC_AFTER_S
                    and (flow.state.get("take_id"), since) != spec_key
                    and flow.speculative_enabled()):
                spec_key = (flow.state.get("take_id"), since)
                with flow._buf_lock:
                    snap_pre, snap_cur = list(flow.pre_roll), flow.chunks[:]
                threading.Thread(target=flow._speculate,
                                 args=(spec_key, snap_pre, snap_cur),
                                 daemon=True).start()
            # VAD only: it alone can say "not one word yet" (the rms engine
            # would count room noise as speech on a boosted quiet mic)
            if (vad is not None and no_speech_s > 0 and not dec.armed
                    and time.time() - t_start >= no_speech_s):
                cancel_rec(f"no speech in {no_speech_s:g}s ({dec.describe()})")
                return
            if time.time() - t_start >= hard_max:
                flow.log(f"hands-free: {hard_max}s cap -> auto stop ({dec.describe()})")
                stop_rec()
                return
            time.sleep(0.1)
        # The user tapped the hotkey themselves. Logged with the engine's state
        # so a trailing take ("had to stop it by hand") is visible in the log
        # as evidence, not just the auto-stops.
        flow.log(f"hands-free: manual stop ({dec.describe()})")

    def toggle_hands_free():
        # debounce key auto-repeat and accidental double taps
        now = time.time()
        if now - flow.state.get("hf_last_toggle", 0) < 0.4:
            return
        flow.state["hf_last_toggle"] = now
        if flow.state["recording"]:
            stop_rec()
        else:
            start_rec()
            if flow.state["recording"]:
                threading.Thread(target=silence_watch, daemon=True).start()

    def start_command_rec():
        """Start a command-mode take. Refused up front (with an overlay note)
        when no LLM is configured, so the user is not asked to speak an
        instruction that can never be carried out."""
        if not flow.llm_available():
            flow.log("command mode: no LLM configured")
            flow._overlay_flash("редагування потребує AI (Groq/Ollama)", False)
            return
        flow.state["take_kind"] = "command"
        flow.state["command_hwnd"] = flow.user32.GetForegroundWindow()
        start_rec()
        if not flow.state["recording"]:
            flow.state["take_kind"] = "dictate"
            return
        flow.log("command mode: listening for an instruction")

    def command_pressed():
        if flow.config.get("hands_free"):
            now = time.time()
            if now - flow.state.get("hf_last_toggle", 0) < 0.4:
                return
            flow.state["hf_last_toggle"] = now
            if flow.state["recording"]:
                # tapping the command key ends a command take; it never cuts a
                # dictation short (that one is ended by its own key or silence)
                if flow.state.get("take_kind") == "command":
                    stop_rec()
                return
            start_command_rec()
            if flow.state["recording"]:
                threading.Thread(target=silence_watch, daemon=True).start()
        elif not flow.state["recording"]:
            start_command_rec()

    # keyboard and mouse events arrive on two threads that share `pressed`;
    # a lock keeps the trigger check and the set mutation consistent
    lock = threading.Lock()

    def handle_press(tok):
        with lock:
            # auto-repeat re-fires press for a held key with no release in
            # between; a real new keystroke isn't in `pressed` yet. Only a fresh
            # completing keystroke should toggle, else holding it cycles.
            fresh = tok not in pressed
            pressed.add(tok)
            cmd_trig = bool(cmd_key) and cmd_key <= pressed and fresh \
                and tok in cmd_key
            # the command combo wins when the dictation key is a subset of it
            # (dictation "ctrl+space" inside command "ctrl+alt+space")
            trig = required and required <= pressed and fresh and not cmd_trig
            lang_hit = (lang_key and lang_key <= pressed and tok in lang_key
                        and not (lang_key & MODS_SET))
        if cmd_trig:
            command_pressed()
        elif trig:
            if flow.config.get("hands_free"):
                toggle_hands_free()
            elif not flow.state["recording"]:
                start_rec()
        elif lang_hit:
            # simple lang toggle only for non-combo lang key (avoid double-fire)
            flow.state["lang"] = (flow.state["lang"] + 1) % len(flow.LANGUAGES)
            flow.set_status(flow.state["status"])
            flow.log(f"language -> {flow.LANGUAGES[flow.state['lang']]}")

    def handle_release(tok):
        with lock:
            # hold-to-talk: each kind of take ends on releasing its OWN key
            keys = cmd_key if flow.state.get("take_kind") == "command" else required
            stop = (not flow.config.get("hands_free") and flow.state["recording"]
                    and tok in keys)
            pressed.discard(tok)
        # hold-to-talk stops on release; hands-free ignores release (tap toggles)
        if stop:
            stop_rec()

    def on_press(key):
        handle_press(canon(key))

    def on_release(key):
        handle_release(canon(key))

    def on_click(x, y, button, is_press):
        tok = canon_mouse(button)
        if tok is None:      # left/right stay normal clicks
            return
        (handle_press if is_press else handle_release)(tok)

    kbd = keyboard.Listener(on_press=on_press, on_release=on_release)
    ms = mouse.Listener(on_click=on_click)
    kbd.start()
    ms.start()
    return _Listeners(kbd, ms)


MODS_SET = frozenset(MODS)


class _Listeners:
    """Bundle the keyboard + mouse listeners so one .stop() tears down both."""
    def __init__(self, *listeners):
        self._listeners = listeners

    def stop(self):
        for l in self._listeners:
            try:
                l.stop()
            except Exception:
                pass

    def join(self):
        """Block until the listeners exit. Headless mode (--no-ui) has no
        mainloop to park the main thread in, so it joins here instead."""
        for l in self._listeners:
            try:
                l.join()
            except Exception:
                pass


def restart_listener() -> None:
    """Apply a changed hotkey without restarting the whole app."""
    try:
        if flow._listener is not None:
            flow._listener.stop()
    except Exception:
        pass
    flow._listener = start_listener()
    flow.log(f"hotkey -> {hotkey_label(flow.config['hotkey'])}")
    cmd = flow.command_trigger(flow.config.get("command_hotkey", ""),
                          flow.config.get("command_mode_enabled", True),
                          parse_hotkey(flow.config["hotkey"]))
    flow.log(f"command hotkey -> {hotkey_label(flow.config['command_hotkey']) if cmd else 'off'}")


def capture_hotkey(on_done) -> None:
    """Listen for the next key combo OR mouse side button the user presses; call
    on_done(spec). Fires on a non-modifier key (with whatever mods are held), a
    lone modifier release, or a bindable mouse button."""
    held: list[str] = []
    listeners: list = []

    def finish(tokens):
        for l in listeners:
            try:
                l.stop()
            except Exception:
                pass
        spec = "+".join(sorted(tokens, key=lambda x: (x not in MODS, x)))
        on_done(spec)

    def press(tok):
        if tok not in held:
            held.append(tok)
        if tok not in MODS_SET:  # a real key / mouse button -> combo complete
            finish(list(held))
            return False

    def on_press(key):
        return press(canon(key))

    def on_release(key):
        if held and all(t in MODS_SET for t in held):  # only mods, released one
            finish(list(held))
            return False

    def on_click(x, y, button, is_press):
        tok = canon_mouse(button)
        if is_press and tok is not None:  # ignore left/right and releases
            return press(tok)

    kb = keyboard.Listener(on_press=on_press, on_release=on_release)
    ms = mouse.Listener(on_click=on_click)
    listeners += [kb, ms]
    kb.start()
    ms.start()


class AppContext:
    """Bridge passed to the GUI: config + data + actions, no GUI deps here."""
    config = flow.config
    # exposed so the GUI can fall back to the real default of a setting instead
    # of repeating the literal in its own code — a duplicated beam_size fallback
    # of 5 survived in app_gui long after DEFAULTS had moved to 1
    DEFAULTS = flow.DEFAULTS
    LANGUAGES = flow.LANGUAGES
    UK_MODELS = flow.UK_MODELS
    MODELS = flow.MODELS
    model_installed = staticmethod(flow.model_installed)
    HOTKEYS = ["f8", "f9", "scroll_lock", "pause"]
    history_last = staticmethod(flow.history_last)
    history_delete = staticmethod(flow.history_delete)
    history_clear = staticmethod(flow.history_clear)
    history_stats = staticmethod(flow.history_stats)
    set_autostart = staticmethod(flow.set_autostart)
    hotkey_label = staticmethod(hotkey_label)
    capture_hotkey = staticmethod(capture_hotkey)

    def status(self):
        return flow.state["status"]

    def lang(self):
        return flow.LANGUAGES[flow.state["lang"]]

    def toggle_lang(self):
        flow.state["lang"] = (flow.state["lang"] + 1) % len(flow.LANGUAGES)
        flow.set_status(flow.state["status"])
        flow.log(f"language -> {flow.LANGUAGES[flow.state['lang']]}")

    def save_config(self, cfg):
        flow.save_config(cfg)
        if cfg.get("language") in flow.LANGUAGES:
            flow.state["lang"] = flow.LANGUAGES.index(cfg["language"])
        restart_listener()  # apply hotkey change immediately, no app restart
        flow.log("settings saved")

    def quit(self):
        flow.force_quit()
