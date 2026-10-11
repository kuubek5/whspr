"""Mutes other apps' audio while recording (Windows audio sessions). Moved verbatim out of flow.py."""

import os

import flow


# ---------------- Duck other apps while recording ----------------
# PIDs we muted, so we only unmute what we actually silenced and leave apps the
# user had already muted alone.
_ducked_pids: set[int] = set()


def _audio_sessions():
    """Yield (pid, ISimpleAudioVolume) for every other app playing audio.

    COM must be initialised per thread; start/stop run on the pynput listener
    thread, not the main one. Returns nothing if pycaw is missing so a bare
    install still dictates fine — ducking is a convenience, not a requirement."""
    try:
        import comtypes
        from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
    except ImportError:
        return
    try:
        comtypes.CoInitialize()
    except Exception:
        pass
    me = os.getpid()
    try:
        for s in AudioUtilities.GetAllSessions():
            if s.Process is None or s.Process.pid == me:
                continue  # never mute our own beeps
            try:
                yield s.Process.pid, s._ctl.QueryInterface(ISimpleAudioVolume)
            except Exception:
                continue
    except Exception as e:
        flow.log(f"audio session enumeration failed ({e.__class__.__name__}: {e})")


def duck_others(mute: bool) -> None:
    """Mute other apps' audio while dictating so playback doesn't bleed into the
    mic (or into the user's ears). Restores only what we muted."""
    # gate only the mute path on the setting: an unmute must always run, or
    # toggling the option off mid-recording would leave apps muted forever
    if mute and not flow.config.get("mute_others", True):
        return
    global _ducked_pids
    try:
        if mute:
            hit = set()
            for pid, vol in _audio_sessions():
                if vol.GetMute():
                    continue  # already muted by the user — leave it
                vol.SetMute(1, None)
                hit.add(pid)
            _ducked_pids = hit
            if hit:
                flow.log(f"muted {len(hit)} app(s) while recording")
        else:
            if not _ducked_pids:
                return
            for pid, vol in _audio_sessions():
                if pid in _ducked_pids:
                    vol.SetMute(0, None)
            flow.log(f"unmuted {len(_ducked_pids)} app(s)")
            _ducked_pids = set()
    except Exception as e:
        flow.log(f"audio ducking failed ({e.__class__.__name__}: {e})")
