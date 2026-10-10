"""Paste target of a dictation take: the window focused at the START wins.
Pure choice logic + the stop_rec wiring with user32 stubbed — this must never
touch the real keyboard, clipboard or windows."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flow

START, STOP, OURS = 101, 202, 303


class ChooseTarget(unittest.TestCase):
    def pick(self, start, stop, valid=(START, STOP, OURS), ours=(OURS,)):
        return flow.choose_paste_target(start, stop, lambda h: h in valid,
                                        lambda h: h in ours)

    def test_start_valid_wins(self):
        self.assertEqual(self.pick(START, STOP), START)

    def test_start_invalid_falls_back_to_stop(self):
        self.assertEqual(self.pick(START, STOP, valid=(STOP,)), STOP)

    def test_start_ours_falls_back_to_stop(self):
        self.assertEqual(self.pick(OURS, STOP), STOP)

    def test_both_ours_keeps_old_behaviour(self):
        self.assertEqual(self.pick(OURS, OURS + 1, ours=(OURS, OURS + 1)), OURS + 1)

    def test_same_window(self):
        self.assertEqual(self.pick(START, START), START)

    def test_no_start_window(self):
        self.assertEqual(self.pick(None, STOP), STOP)
        self.assertEqual(self.pick(0, STOP), STOP)


class FakeUser32:
    """Foreground = STOP; START is a live window of another process; OURS
    belongs to this process; 999 no longer exists; 404 is minimized."""
    def __init__(self): self.fg = STOP
    def GetForegroundWindow(self): return self.fg
    def IsWindow(self, h): return h in (START, STOP, OURS, 404)
    def IsIconic(self, h): return h == 404
    def GetWindowThreadProcessId(self, h, pid_ref):
        pid_ref._obj.value = os.getpid() if h == OURS else 1
        return 1


class DictationWiring(unittest.TestCase):
    def setUp(self):
        self._orig = (flow.user32, flow.log, flow.app_styles.window_app)
        self.logs = []
        flow.user32 = FakeUser32()
        flow.log = lambda m, *a, **k: self.logs.append(m)
        flow.app_styles.window_app = lambda h: ("app.exe", "x" * 80)

    def tearDown(self):
        flow.user32, flow.log, flow.app_styles.window_app = self._orig

    def test_uses_start_and_logs_short_titles(self):
        self.assertEqual(flow.dictation_paste_target(START), START)
        self.assertEqual(len(self.logs), 1)
        self.assertIn("-> using start", self.logs[0])
        self.assertNotIn("x" * 41, self.logs[0])

    def test_closed_start_window(self):
        self.assertEqual(flow.dictation_paste_target(999), STOP)
        self.assertIn("-> using stop", self.logs[0])

    def test_minimized_start_window(self):
        self.assertEqual(flow.dictation_paste_target(404), STOP)

    def test_own_start_window(self):
        self.assertEqual(flow.dictation_paste_target(OURS), STOP)

    def test_both_ours_returns_stop(self):
        flow.user32.fg = OURS
        self.assertEqual(flow.dictation_paste_target(OURS), OURS)

    def test_same_window_no_log(self):
        flow.user32.fg = START
        self.assertEqual(flow.dictation_paste_target(START), START)
        self.assertEqual(self.logs, [])

    def test_stop_rec_routes_through_target_picker(self):
        # stop_rec is a closure inside start_listener; guard the wiring at the
        # source level: dictation takes go through dictation_paste_target with
        # the start-time hwnd, command takes keep command_hwnd.
        import inspect
        src = inspect.getsource(flow.start_listener)
        self.assertIn('state["start_hwnd"] = user32.GetForegroundWindow()', src)
        self.assertIn('start_hwnd = state.pop("start_hwnd", None)', src)
        self.assertIn("hwnd = dictation_paste_target(start_hwnd)", src)
        self.assertIn('hwnd = state.get("command_hwnd") or user32.GetForegroundWindow()', src)


if __name__ == "__main__":
    unittest.main()
