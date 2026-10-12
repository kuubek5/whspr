"""Single instance: one running copy of KuubWave, and the show-window signal a second launch sends it. Moved verbatim out of flow.py."""

import ctypes
import sys
import threading

import flow


# ---------------- Single instance ----------------
def ensure_single_instance() -> None:
    kernel32 = ctypes.windll.kernel32
    # Name deliberately unchanged across the whspr -> KuubWave rename: an
    # in-place upgrade can leave the old build running, and keeping one mutex
    # name means the new build still refuses to start a second recorder on the
    # same microphone instead of fighting it for the hotkey.
    kernel32.CreateMutexW(None, False, "whspr_single_instance_mutex")
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        # Launching the app again (desktop / taskbar shortcut) while it sits in
        # the tray used to exit silently, so the click did nothing at all. Ask
        # the running copy to show its window first. An older running build
        # never created the event; OpenEventW then fails and we just exit as
        # before.
        if _signal_show_running():
            flow.log("another KuubWave instance is already running — asked it to show its window")
        else:
            flow.log("another KuubWave instance is already running — exiting")
        sys.exit(0)


# Named auto-reset event a second launch sets to bring the running copy's window
# up. Per-session ("Local\") so another Windows user's KuubWave is never poked.
_SHOW_EVENT_NAME = "Local\\KuubWave_show_window"


def _signal_show_running() -> bool:
    """Set the running instance's show event. True if one was listening."""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenEventW.restype = ctypes.c_void_p
        EVENT_MODIFY_STATE = 0x0002
        h = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, flow._SHOW_EVENT_NAME)
        if not h:
            return False
        ok = bool(kernel32.SetEvent(ctypes.c_void_p(h)))
        kernel32.CloseHandle(ctypes.c_void_p(h))
        return ok
    except Exception:
        return False


def start_show_listener(on_show) -> None:
    """Call on_show() whenever a second launch signals the show event.

    Runs on its own daemon thread, blocked in WaitForSingleObject, so it costs
    nothing while idle. on_show is the same callback the tray's "Відкрити"
    item uses, so a shortcut click and the tray restore behave identically.
    Never fatal: without the event the app works exactly as before, only a
    repeat launch can't surface the window."""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateEventW.restype = ctypes.c_void_p
        # auto-reset, initially non-signalled
        h = kernel32.CreateEventW(None, False, False, flow._SHOW_EVENT_NAME)
        if not h:
            flow.log("show-window event unavailable — repeat launches can't open the window")
            return
    except Exception as e:
        flow.log(f"show-window event failed ({e.__class__.__name__}: {e})")
        return

    def wait_loop():
        INFINITE = 0xFFFFFFFF
        WAIT_OBJECT_0 = 0
        while True:
            if kernel32.WaitForSingleObject(ctypes.c_void_p(h), INFINITE) != WAIT_OBJECT_0:
                return
            flow.log("second launch -> showing window")
            try:
                on_show()
            except Exception as e:
                flow.log(f"show on second launch failed ({e.__class__.__name__}: {e})")

    threading.Thread(target=wait_loop, daemon=True).start()
