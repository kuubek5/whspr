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
            "gpu": self.gpu,
            "hotkey": flow.hotkey_label(c.get("hotkey", "f9")),
            "status": flow.state["status"],
            "stats": {
                "wordsToday": s["words_today"], "dictations": s["total"],
                "wordsTotal": s["words"], "wpm": round(s["wpm"]),
            },
            "recent": [{"time": self._pretty_time(ts), "text": text}
                       for _id, ts, lang, dur, text in rows[:4]],
            "history": [{"id": _id, "time": ts[11:16], "lang": lang,
                         "duration": f"{dur:.1f}с", "text": text}
                        for _id, ts, lang, dur, text in rows],
            "settings": {
                "autostart": c.get("autostart", False),
                "floatingPanel": c.get("overlay", True),
                "sound": c.get("sound", False),
                "autoLang": c.get("auto_lang", False),
                "model": c.get("model_uk", "stock"),
                "gpuDevice": self.gpu,
                "device": c.get("device", "cuda"),
                "inputDevice": c.get("input_device", ""),
                "micOnDemand": c.get("mic_on_demand", False),
                "backupKey": "", "backupKeyVisible": False,
            },
            "devices": flow.list_input_devices(),
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

    # ---- live ----
    def get_status(self):
        return flow.state["status"]

    def get_pill(self):
        import time
        st = flow.state["status"]
        if st in ("recording", "transcribing", "loading"):
            return {"state": st}
        if time.time() - flow.state.get("pill_done_at", 0) < 2.5:
            return {"state": "done", "text": flow.state.get("pill_text", "")}
        return {"state": "idle", "hotkey": flow.hotkey_label(flow.config.get("hotkey", "f9"))}

    def set_theme(self, theme):
        flow.config["theme"] = theme
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
        old_model = c.get("model_uk", "stock")
        c["autostart"] = bool(s.get("autostart"))
        c["overlay"] = bool(s.get("floatingPanel"))
        c["sound"] = bool(s.get("sound"))
        c["auto_lang"] = bool(s.get("autoLang"))
        c["model_uk"] = s.get("model", "stock")
        c["device"] = "cpu" if s.get("device") == "cpu" else "cuda"
        c["input_device"] = s.get("inputDevice", "") or ""
        c["mic_on_demand"] = bool(s.get("micOnDemand"))
        flow.save_config(c)
        flow.set_autostart(c["autostart"])
        if c["input_device"] != old_dev or c["mic_on_demand"] != old_mode:
            flow.restart_stream()
        if c["device"] != old_device or c["model_uk"] != old_model:
            flow.reload_models()
        return True

    def list_devices(self):
        return flow.list_input_devices()

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
    api = Api()
    window = webview.create_window(
        "whspr", os.path.join(WEB_DIR, "index.html"),
        js_api=api, width=980, height=660, min_size=(880, 600),
        background_color="#0E0E12",
    )
    flow.state["webview_window"] = window

    # The floating status pill lives in a Tkinter overlay (flow._start_overlay),
    # not a pywebview window: WebView2 on Windows can't render a transparent,
    # rounded, always-on-top capsule, so Tk with -transparentcolor handles it.

    webview.start()
