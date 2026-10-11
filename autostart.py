"""Launch-at-login toggle (HKCU Run key for installs, Startup shortcut from source). Moved verbatim out of flow.py."""

import os
import sys

import flow

# ---------------- Autostart ----------------
# Name of the HKCU ...\Run value for a frozen build.
AUTOSTART_VALUE = "KuubWave"


def startup_dir() -> str:
    return os.path.join(os.environ["APPDATA"],
                        r"Microsoft\Windows\Start Menu\Programs\Startup")


def set_autostart(enable: bool) -> None:
    """Toggle launch-at-login. Installed build uses the HKCU Run registry key
    pointing at the exe; from source we copy the launcher .lnk into Startup."""
    if flow.FROZEN:
        try:
            import winreg
            key = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0,
                                winreg.KEY_SET_VALUE) as k:
                # Pre-rename value name. It points at the OLD exe path, which
                # the rename removes, so a leftover would make Windows try to
                # launch a missing file at every login. Cleared on both
                # branches, not just on disable — a user who only ever turns
                # autostart ON must not keep the dead entry.
                try:
                    winreg.DeleteValue(k, "whspr")
                    flow.log("removed stale 'whspr' autostart entry")
                except FileNotFoundError:
                    pass  # nothing to clean up: the normal case
                if enable:
                    winreg.SetValueEx(k, AUTOSTART_VALUE, 0, winreg.REG_SZ,
                                      f'"{sys.executable}"')
                    flow.log("autostart enabled (registry)")
                else:
                    try:
                        winreg.DeleteValue(k, AUTOSTART_VALUE)
                        flow.log("autostart disabled")
                    except FileNotFoundError:
                        pass
        except OSError as e:
            flow.log(f"autostart failed: {e}")
        return

    import shutil
    src = os.path.join(flow.BASE, flow.LNK_NAME)
    dst = os.path.join(startup_dir(), flow.LNK_NAME)
    try:
        if enable:
            if os.path.isfile(src):
                shutil.copyfile(src, dst)
                flow.log("autostart enabled")
            else:
                flow.log(f"autostart: {src} not found — create the shortcut first")
        elif os.path.isfile(dst):
            os.remove(dst)
            flow.log("autostart disabled")
    except OSError as e:
        flow.log(f"autostart failed: {e}")
