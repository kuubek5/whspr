"""Paste: choosing the window a take goes into and pasting text through the clipboard. Moved verbatim out of flow.py."""

import ctypes
import os
import threading
import time

from pynput import keyboard

import app_styles

import flow


# ---------------- Paste ----------------
_READ_CLIPBOARD = object()  # paste_text default: restore whatever is there now


def choose_paste_target(start_hwnd, stop_hwnd, is_valid, is_ours):
    """Which window a dictation take pastes into. Pure: the Win32 checks come in
    as callables so this is unit-testable without a desktop.

    The window focused when the take STARTED wins: that is where the user was
    looking when they began talking. Taking it at the stop instead lost the text
    whenever focus drifted mid-take — restoring KuubWave from the tray, a toast,
    the overlay — and a hands-free take runs 10-60 s, so drift is the norm.
    The start window is skipped when it is gone/minimized or is one of our own
    windows (main UI, overlay): pasting into KuubWave itself is never intended.
    Then the stop-time window is used — also our own or not, exactly as before,
    so paste_text's "focus lost — text left in clipboard" path still covers the
    case where neither is usable."""
    if start_hwnd and is_valid(start_hwnd) and not is_ours(start_hwnd):
        return start_hwnd
    return stop_hwnd


def _hwnd_pid(hwnd) -> int:
    pid = ctypes.c_ulong(0)
    flow.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _hwnd_is_ours(hwnd) -> bool:
    """Our own process owns it: pywebview main window, overlay pill, dialogs.
    Matching the pid is robust where titles/classes are not (WebView2 child
    windows, the window being renamed with the brand)."""
    try:
        return bool(hwnd) and _hwnd_pid(hwnd) == os.getpid()
    except Exception:
        return False


def _hwnd_usable(hwnd) -> bool:
    # a minimized window is excluded: SetForegroundWindow activates it without
    # restoring it, and Ctrl+V into an invisible window is a silent loss
    try:
        return bool(hwnd) and bool(flow.user32.IsWindow(hwnd)) \
            and not flow.user32.IsIconic(hwnd)
    except Exception:
        return False


def _hwnd_label(hwnd) -> str:
    exe, title = app_styles.window_app(hwnd)
    title = title if len(title) <= 40 else title[:39] + "…"
    return f"{exe or '?'}/{title!r}"


def dictation_paste_target(start_hwnd):
    """stop_rec's paste target for a dictation take: the start-time window if it
    is still usable, else whatever is focused now (see choose_paste_target).
    Logs only when the two differ, so a mis-paste report can be traced."""
    stop_hwnd = flow.user32.GetForegroundWindow()
    hwnd = choose_paste_target(start_hwnd, stop_hwnd, _hwnd_usable, _hwnd_is_ours)
    if start_hwnd and start_hwnd != stop_hwnd:
        try:
            flow.log(f"paste target: start={_hwnd_label(start_hwnd)} "
                f"stop={_hwnd_label(stop_hwnd)} -> using "
                f"{'start' if hwnd == start_hwnd else 'stop'}")
        except Exception:
            pass
    return hwnd


def paste_text(text: str, target_hwnd: int, restore=_READ_CLIPBOARD) -> bool:
    """Paste `text` into target_hwnd via the clipboard, then put the clipboard
    back. `restore` is what goes back: by default the clipboard as it is right
    now. Command mode passes the user's ORIGINAL clipboard explicitly, because by
    the time it pastes, the clipboard holds the selection its own Ctrl+C copied —
    restoring that would leave the user with their old selected text instead of
    whatever they had copied themselves."""
    # if user alt-tabbed away while we transcribed, go back to the window
    # that was focused when the key was released
    if target_hwnd and flow.user32.GetForegroundWindow() != target_hwnd:
        flow.user32.SetForegroundWindow(target_hwnd)
        time.sleep(0.15)
        if flow.user32.GetForegroundWindow() != target_hwnd:
            flow.log("target window lost focus and refocus failed — text left in clipboard")
            flow.pyperclip.copy(text)
            return False

    old = None
    if restore is not _READ_CLIPBOARD:
        old = restore
    else:
        try:
            old = flow.pyperclip.paste()
        except Exception:
            pass
    flow.pyperclip.copy(text)
    time.sleep(0.05)
    # physical VK 0x56 ('V'), NOT the char 'v': on a Cyrillic layout the char
    # 'v' maps to no key (VkKeyScan -> 0xFF) and pynput's Ctrl+'v' silently
    # fails — the whole reason paste didn't work while dictating Ukrainian.
    v_key = keyboard.KeyCode.from_vk(0x56)
    with flow.kb.pressed(keyboard.Key.ctrl):
        flow.kb.press(v_key)
        flow.kb.release(v_key)
    if old is not None:
        def restore():
            time.sleep(0.5)
            # only put the old value back if the clipboard is still OURS. If the
            # user copied something in that half-second window, restoring would
            # silently destroy their copy — leaving our dictation there instead
            # is the lesser evil, and they can always copy again.
            try:
                if flow.pyperclip.paste() != text:
                    return
            except Exception:
                return  # can't tell whose it is — don't gamble on the user's copy
            try:
                flow.pyperclip.copy(old)
            except Exception:
                pass
        threading.Thread(target=restore, daemon=True).start()
    return True
