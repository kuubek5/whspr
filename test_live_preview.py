"""Live preview: the pill shows the tail of the words so far, and the preview
never runs where it would cost money (cloud STT) or has nowhere to show."""
import os, sys, unittest
import tkinter as tk
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flow
import ui


class LivePreviewGate(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(flow.config)
        self._overlay = flow.overlay
        flow.overlay = object()

    def tearDown(self):
        flow.config.clear()
        flow.config.update(self._cfg)
        flow.overlay = self._overlay

    def test_on_for_local(self):
        flow.config.update(live_preview=True, overlay=True, stt_backend="local")
        self.assertTrue(flow.live_preview_enabled())

    def test_off_for_cloud(self):
        flow.config.update(live_preview=True, overlay=True, stt_backend="cloud")
        self.assertFalse(flow.live_preview_enabled())

    def test_off_when_disabled_or_no_overlay(self):
        flow.config.update(live_preview=False, overlay=True, stt_backend="local")
        self.assertFalse(flow.live_preview_enabled())
        flow.config.update(live_preview=True)
        flow.overlay = None
        self.assertFalse(flow.live_preview_enabled())


class PillTail(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        cls.o = ui._LayeredOverlay(cls.root, {"overlay_style": "pill"})

    @classmethod
    def tearDownClass(cls):
        cls.o.destroy()
        cls.root.destroy()

    def test_short_text_untouched(self):
        self.assertEqual(self.o._fit_tail("Привіт", 300, self.o._label_font),
                         "Привіт")

    def test_long_text_keeps_the_end(self):
        text = "Привіт, це перевірка живого тексту під час диктовки " * 3
        out = self.o._fit_tail(text.strip(), 300, self.o._label_font)
        self.assertTrue(out.startswith("…"))
        self.assertTrue(text.strip().endswith(out[1:]))
        self.assertLessEqual(self.o._measure(self.o._label_font, out), 300)

    def test_width_fixed_once_text_arrives(self):
        o = self.o
        o._state = "rec"
        o.live("Привіт")
        w1 = o._win_w()
        o.live("Привіт, це значно довший шматок живого тексту для пігулки")
        self.assertEqual(w1, o._win_w())
        o.live("")
        self.assertLess(o._win_w(), w1)


class Speculative(unittest.TestCase):
    """The pause-time decode is reused only for the pause the take stopped on."""
    NAMES = ("_recognize", "paste_text", "history_add", "set_status", "log",
             "llm_available")

    def setUp(self):
        self._orig = {n: getattr(flow, n) for n in self.NAMES}
        self._cfg = dict(flow.config)
        self._state = dict(flow.state)
        self.calls, self.pasted = [], []
        flow._recognize = lambda audio, dur: (
            self.calls.append(len(audio)) or (f"текст {len(self.calls)}", -0.2, 0.0, "uk"))
        flow.paste_text = lambda t, h, restore=None: (self.pasted.append(t) or True)
        flow.history_add = lambda t, l, d: 1
        flow.set_status = lambda s: None
        flow.log = lambda *a, **k: None
        flow.llm_available = lambda: False
        flow.config.update({"stt_backend": "local", "overlay": False,
                            "speculative_decode": True, "app_styles_enabled": False,
                            "snippets_enabled": False, "voice_commands": False,
                            "dictionary": ""})
        flow.state["take_id"] = 7
        flow.state["last_output"] = None
        flow._spec_result.clear()
        flow._spec_taken = None

    def tearDown(self):
        for n, f in self._orig.items():
            setattr(flow, n, f)
        flow.config.clear(); flow.config.update(self._cfg)
        flow.state.clear(); flow.state.update(self._state)
        flow._spec_result.clear()
        flow._spec_taken = None

    def audio(self, s=1.0):
        return [np.full((int(flow.SAMPLE_RATE * s), 1), 0.1, dtype=np.float32)]

    def test_same_pause_reuses(self):
        flow._speculate((7, 2.0), [], self.audio())
        flow._transcribe_impl([], self.audio(1.5), 1, stop_info=(7, 2.0))
        self.assertEqual(len(self.calls), 1)          # no second decode
        self.assertEqual(self.pasted, ["Текст 1"])

    def test_new_speech_after_pause_decodes_again(self):
        flow._speculate((7, 2.0), [], self.audio())
        flow._transcribe_impl([], self.audio(3.0), 1, stop_info=(7, 4.1))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.pasted, ["Текст 2"])

    def test_manual_stop_never_reuses(self):
        flow._speculate((7, 2.0), [], self.audio())
        flow._transcribe_impl([], self.audio(1.5), 1, stop_info=None)
        self.assertEqual(len(self.calls), 2)

    def test_late_speculation_after_final_is_dropped(self):
        flow._transcribe_impl([], self.audio(1.5), 1, stop_info=(7, 2.0))
        flow._speculate((7, 2.0), [], self.audio())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(flow._spec_result, {})

    def test_off_in_cloud(self):
        flow.config["stt_backend"] = "cloud"
        self.assertFalse(flow.speculative_enabled())


if __name__ == "__main__":
    unittest.main()
