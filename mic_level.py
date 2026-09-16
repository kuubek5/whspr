# mic_level.py — raise the Windows *capture endpoint* volume for the mic.
#
# Why this exists: the app was recording at ~0.004-0.006 RMS and flow.py had to
# compensate with up to x12 software gain, which amplifies room noise and makes
# Whisper hallucinate or return empty transcripts. Software gain cannot add
# signal that was never captured; the real fix is the Windows input-level
# slider, i.e. the IAudioEndpointVolume master volume on the capture endpoint.
# Until now the user had to open Windows sound settings and drag it by hand.
#
# This module NEVER changes that system setting on its own initiative: there is
# no auto-run, no timer and no import-time call. raise_level() only does
# anything when something explicitly calls it (a button, an explicit consent).
#
# Every public function is failure-tolerant: a missing pycaw/comtypes, a machine
# with no microphone, or an endpoint that refuses SetMasterVolumeLevelScalar all
# degrade to a falsy return. Dictation must keep working without any of this.

from __future__ import annotations

from typing import Any, Callable


# ---------------- Logging ----------------
# flow.py owns log(); importing it here would be circular and would drag in the
# whole heavy module (whisper, sounddevice, GUI). So the host injects its logger
# and we default to a no-op, which also keeps bench.py imports silent.
def _noop(msg: str) -> None:
    pass


_log: Callable[[str], None] = _noop


def set_logger(fn: Callable[[str], None]) -> None:
    """Install the host's logger (flow.log). Safe to call more than once."""
    global _log
    _log = fn if callable(fn) else _noop


# ---------------- Core Audio plumbing ----------------
def _endpoint() -> Any | None:
    """Return IAudioEndpointVolume for the default *capture* device, or None.

    Deliberately not cached: the user can unplug a headset or switch default mic
    between calls, and a stale endpoint pointer would then silently drive the
    wrong (or a dead) device. These calls happen at most once per user action,
    so re-activating every time costs nothing worth saving."""
    try:
        import comtypes
        from comtypes import CLSCTX_ALL, POINTER, cast
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    except Exception as e:  # normally ImportError, but a broken install varies
        _log(f"mic level unavailable ({e.__class__.__name__}: {e})")
        return None
    # COM must be initialised per thread: flow.py calls audio code from the
    # pynput listener thread, not main (same reason _audio_sessions() does it).
    # An already-initialised thread answers S_FALSE, and a thread that joined a
    # different apartment raises RPC_E_CHANGED_MODE — both are harmless here,
    # because we then just use whichever apartment that thread already has.
    try:
        comtypes.CoInitialize()
    except Exception:
        pass
    try:
        # GetMicrophone() = default eCapture/eMultimedia endpoint. GetSpeakers()
        # would give the render side, i.e. the wrong slider entirely.
        dev = AudioUtilities.GetMicrophone()
        if dev is None:
            _log("mic level: no default capture device")
            return None
        iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(iface, POINTER(IAudioEndpointVolume))
    except Exception as e:
        # Activate() fails on endpoints that expose no volume control at all
        # (some USB interfaces, virtual/loopback devices, Bluetooth handsfree).
        _log(f"mic endpoint activation failed ({e.__class__.__name__}: {e})")
        return None


# ---------------- Public API ----------------
def get_level() -> float | None:
    """Current capture-endpoint master volume as a 0.0-1.0 scalar, or None if it
    can't be read (pycaw missing, no capture device, no volume control)."""
    vol = _endpoint()
    if vol is None:
        return None
    try:
        # Scalar, not dB: the scalar is what the Windows slider shows, so 0.85
        # here is the "85" the user would see in sound settings. The dB scale is
        # device-specific, so a dB target would mean something different on
        # every machine.
        return float(vol.GetMasterVolumeLevelScalar())
    except Exception as e:
        _log(f"mic level read failed ({e.__class__.__name__}: {e})")
        return None


def set_level(scalar: float) -> bool:
    """Set capture-endpoint master volume to a 0.0-1.0 scalar. Returns True on
    success, False on any failure. Never raises."""
    vol = _endpoint()
    if vol is None:
        return False
    try:
        # Clamp before the COM call: out-of-range values make
        # SetMasterVolumeLevelScalar return E_INVALIDARG, and a caller that
        # computed 1.02 from some ratio deserves a working 100%, not an error.
        target = max(0.0, min(1.0, float(scalar)))
        vol.SetMasterVolumeLevelScalar(target, None)  # None = no event GUID
        return True
    except Exception as e:
        _log(f"mic level write failed ({e.__class__.__name__}: {e})")
        return False


def is_boost_available() -> bool:
    """True if the endpoint exposes a settable master volume."""
    vol = _endpoint()
    if vol is None:
        return False
    try:
        # Read-probe only. Re-writing the current value would be a more literal
        # test of "settable", but this module must never touch a system setting
        # unasked — and in practice an endpoint that hands out a readable master
        # scalar accepts writes to it.
        vol.GetMasterVolumeLevelScalar()
        return hasattr(vol, "SetMasterVolumeLevelScalar")
    except Exception as e:
        _log(f"mic boost probe failed ({e.__class__.__name__}: {e})")
        return False


def raise_level(target: float = 0.85) -> dict:
    """Raise the capture endpoint to `target` if it currently sits below it.

    Never lowers an already-loud mic: the user may have turned it down on
    purpose for a hot microphone, and silently quieting it would be a worse bug
    than the quiet-input one we are fixing. Returns:
        {"ok": bool, "before": float|None, "after": float|None,
         "changed": bool, "reason": str}
    `reason` is a short Ukrainian string for the UI. Never raises."""
    result: dict = {
        "ok": False,
        "before": None,
        "after": None,
        "changed": False,
        "reason": "Не вдалося змінити гучність мікрофона.",
    }
    try:
        target = max(0.0, min(1.0, float(target)))
    except Exception:
        target = 0.85  # a caller passing junk still gets the sane default
    try:
        before = get_level()
        result["before"] = before
        if before is None:
            # get_level() already logged the real cause; the UI only needs the
            # user-actionable part, which is "plug in / pick a microphone".
            result["reason"] = "Не вдалося знайти пристрій запису."
            return result
        result["after"] = before
        # 1% slack: the driver quantises scalar -> dB -> scalar, so a mic set to
        # exactly the target can read back as 0.8499, and we do not want to
        # "raise" it on every single call because of that rounding.
        if before >= target - 0.01:
            result["ok"] = True
            result["reason"] = f"Мікрофон уже достатньо гучний ({round(before * 100)}%)."
            return result
        if not set_level(target):
            result["reason"] = "Windows не дозволив змінити гучність мікрофона."
            return result
        # Read back instead of trusting the write: after quantisation the actual
        # value may differ, and the number shown to the user should be the real
        # one. If the read fails, fall back to what we asked for.
        after = get_level()
        result["after"] = after if after is not None else target
        result["ok"] = True
        result["changed"] = True
        result["reason"] = (
            f"Рівень мікрофона піднято з {round(before * 100)}% "
            f"до {round(result['after'] * 100)}%."
        )
        _log(f"capture endpoint volume raised {before:.2f} -> {result['after']:.2f}")
        return result
    except Exception as e:
        _log(f"mic level raise failed ({e.__class__.__name__}: {e})")
        return result
