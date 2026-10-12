"""Second launch -> the running copy shows its window.

Uses a real Windows named event (under a test-only name, so a KuubWave that is
actually running on this machine is never poked) and a real second process for
the cross-process case, because that is exactly the path a shortcut click takes.
"""
import os
import subprocess
import sys
import threading
import unittest
import uuid

import flow


class ShowOnSecondLaunch(unittest.TestCase):
    def setUp(self):
        self._orig = flow._SHOW_EVENT_NAME
        flow._SHOW_EVENT_NAME = f"Local\\KuubWave_test_show_{uuid.uuid4().hex}"

    def tearDown(self):
        flow._SHOW_EVENT_NAME = self._orig

    def test_no_listener_means_no_signal(self):
        # an older running build never created the event: the second launch
        # must just exit as before
        self.assertFalse(flow._signal_show_running())

    def test_signal_shows_window_same_process(self):
        shown = threading.Event()
        flow.start_show_listener(shown.set)
        self.assertTrue(flow._signal_show_running())
        self.assertTrue(shown.wait(2), "on_show was not called")

    def test_repeated_signals_each_show(self):
        calls = []
        done = threading.Event()

        def on_show():
            calls.append(1)
            if len(calls) == 2:
                done.set()

        flow.start_show_listener(on_show)
        self.assertTrue(flow._signal_show_running())
        # auto-reset event: wait for the first wake-up before signalling again
        for _ in range(200):
            if calls:
                break
            threading.Event().wait(0.01)
        self.assertTrue(flow._signal_show_running())
        self.assertTrue(done.wait(2), f"expected 2 shows, got {len(calls)}")

    def test_signal_from_another_process(self):
        shown = threading.Event()
        flow.start_show_listener(shown.set)
        # the exact call a second launch makes, from a separate process
        code = ("import ctypes,sys;"
                "k=ctypes.windll.kernel32;k.OpenEventW.restype=ctypes.c_void_p;"
                f"h=k.OpenEventW(2,False,{flow._SHOW_EVENT_NAME!r});"
                "sys.exit(0 if h and k.SetEvent(ctypes.c_void_p(h)) else 1)")
        r = subprocess.run([sys.executable, "-c", code], timeout=30)
        self.assertEqual(r.returncode, 0, "second process could not open/set the event")
        self.assertTrue(shown.wait(2), "running copy did not react to the other process")

    def test_on_show_error_does_not_kill_listener(self):
        calls = []
        done = threading.Event()

        def on_show():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("window not ready yet")
            done.set()

        flow.start_show_listener(on_show)
        flow._signal_show_running()
        for _ in range(200):
            if calls:
                break
            threading.Event().wait(0.01)
        flow._signal_show_running()
        self.assertTrue(done.wait(2), "listener died after a failing on_show")


if __name__ == "__main__":
    unittest.main()
