"""Auto-update check and silent installer download via GitHub Releases. Moved verbatim out of flow.py."""

import json
import os
import re
import subprocess
import urllib.error
import urllib.request

import flow

# ---------------- Auto-update ----------------
def _version_tuple(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0"))


def check_update() -> dict:
    """Query GitHub Releases for a newer version. Returns
    {available, version, url} — never raises."""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{flow.GITHUB_REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "KuubWave"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        tag = (data.get("tag_name") or "").lstrip("v")
        asset = next((a["browser_download_url"] for a in data.get("assets", [])
                      if a.get("name", "").endswith(".exe")), "")
        newer = _version_tuple(tag) > _version_tuple(flow.APP_VERSION)
        return {"available": bool(newer and asset), "version": tag, "url": asset}
    except urllib.error.HTTPError as e:
        # GITHUB_REPO has no published releases yet, so /releases/latest answers
        # 404 on every launch. That is the expected steady state, not a failure:
        # report "no update" silently instead of filling the log with errors.
        # Everything else (403 rate limit, 5xx, ...) is a real fault and is logged.
        if e.code != 404:
            flow.log(f"update check failed (HTTPError: {e})")
        return {"available": False, "version": "", "url": ""}
    except Exception as e:
        flow.log(f"update check failed ({e.__class__.__name__}: {e})")
        return {"available": False, "version": "", "url": ""}


def download_update(url: str) -> bool:
    """Download the installer to a temp file and run it SILENTLY. The running app
    should quit right after so the installer can replace its files; the installer
    relaunches KuubWave when it finishes (see kuubwave.iss [Run])."""
    try:
        import tempfile
        fd, path = tempfile.mkstemp(suffix="-kuubwave-setup.exe")
        os.close(fd)
        with urllib.request.urlopen(url, timeout=900) as r:
            total = int(r.headers.get("Content-Length", 0))
            done = 0
            with open(path, "wb") as f:
                while True:
                    c = r.read(1 << 20)
                    if not c:
                        break
                    f.write(c)
                    done += len(c)
                    flow.set_download(True, "Оновлення", mb=done >> 20,
                                 total_mb=(total >> 20) if total else 0)
        flow.set_download(False)
        # Inno silent flags: no wizard, no message boxes, close the running app so
        # its files unlock, and don't reboot. The app quits itself just after.
        subprocess.Popen([path, "/VERYSILENT", "/SUPPRESSMSGBOXES",
                          "/NORESTART", "/FORCECLOSEAPPLICATIONS"])
        return True
    except Exception as e:
        flow.log(f"update download failed ({e.__class__.__name__}: {e})")
        flow.set_download(False)
        return False
