"""Guard tests for flow._schedule_llm_polish. Every keystroke-sending call is
stubbed — this must never touch the real keyboard or clipboard."""
import os, sys, time, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flow


class FakeUser32:
    def __init__(self, hwnd): self.hwnd = hwnd
    def GetForegroundWindow(self): return self.hwnd


class AsyncPolishGuards(unittest.TestCase):
    HWND = 4242

    def setUp(self):
        self.bs, self.pasted, self.updated = [], [], []
        self._orig = (flow.llm_polish, flow._send_backspaces, flow.paste_text,
                      flow.history_update_text, flow.user32, dict(flow.state))
        flow._send_backspaces = lambda n: self.bs.append(n)
        flow.paste_text = lambda t, h: (self.pasted.append((t, h)) or True)
        flow.history_update_text = lambda r, t: self.updated.append((r, t))
        flow.user32 = FakeUser32(self.HWND)
        flow.state["recording"] = False
        flow.config["llm"] = "groq"
        flow.config["groq_api_key"] = "x"

    def tearDown(self):
        (flow.llm_polish, flow._send_backspaces, flow.paste_text,
         flow.history_update_text, flow.user32, st) = self._orig
        flow.state.clear(); flow.state.update(st)

    def run_polish(self, raw, polished, hwnd=None, at=None):
        flow.llm_polish = lambda t, l: polished
        hwnd = self.HWND if hwnd is None else hwnd
        flow.state["last_output"] = {"text": raw, "hwnd": hwnd,
                                     "at": time.time() if at is None else at}
        flow._schedule_llm_polish(raw, "uk", self.HWND, 7)
        time.sleep(0.4)

    def test_happy_path_rewrites(self):
        self.run_polish("привіт як справи", "Привіт, як справи?")
        self.assertEqual(self.bs, [len("привіт як справи")])
        self.assertEqual(self.pasted, [("Привіт, як справи?", self.HWND)])
        self.assertEqual(self.updated, [(7, "Привіт, як справи?")])
        self.assertEqual(flow.state["last_output"]["text"], "Привіт, як справи?")

    def test_identical_result_does_nothing(self):
        self.run_polish("вже ідеально", "вже ідеально")
        self.assertEqual((self.bs, self.pasted, self.updated), ([], [], []))

    def test_stale_last_output_skips(self):
        flow.llm_polish = lambda t, l: "Полірований."
        flow.state["last_output"] = {"text": "інший текст", "hwnd": self.HWND,
                                     "at": time.time()}
        flow._schedule_llm_polish("наш текст", "uk", self.HWND, 7)
        time.sleep(0.4)
        self.assertEqual(self.bs, [])

    def test_other_window_skips(self):
        self.run_polish("текст", "Текст.", hwnd=999)
        self.assertEqual(self.bs, [])

    def test_focus_moved_away_skips(self):
        flow.user32 = FakeUser32(999)
        self.run_polish("текст", "Текст.")
        self.assertEqual(self.bs, [])

    def test_stale_by_time_skips(self):
        self.run_polish("текст", "Текст.",
                        at=time.time() - flow.ASYNC_REWRITE_WINDOW_S - 1)
        self.assertEqual(self.bs, [])

    def test_recording_in_progress_skips(self):
        flow.state["recording"] = True
        self.run_polish("текст", "Текст.")
        self.assertEqual(self.bs, [])

    def test_too_long_never_starts(self):
        long = "а" * (flow.ASYNC_REWRITE_MAX_CHARS + 1)
        self.run_polish(long, "Б" * 10)
        self.assertEqual(self.bs, [])

    def test_long_result_skips(self):
        self.run_polish("коротко", "б" * (flow.ASYNC_REWRITE_MAX_CHARS + 1))
        self.assertEqual(self.bs, [])

    def test_transcribe_lock_held_skips(self):
        flow._transcribe_lock.acquire()
        try:
            self.run_polish("текст", "Текст.")
        finally:
            flow._transcribe_lock.release()
        self.assertEqual(self.bs, [])

    def test_lock_released_after_run(self):
        self.run_polish("текст", "Текст.")
        self.assertTrue(flow._transcribe_lock.acquire(blocking=False))
        flow._transcribe_lock.release()

    def test_llm_failure_leaves_raw(self):
        self.run_polish("сирий текст", None)
        self.assertEqual((self.bs, self.pasted), ([], []))
        self.assertEqual(flow.state["last_output"]["text"], "сирий текст")


if __name__ == "__main__":
    unittest.main(verbosity=2)
