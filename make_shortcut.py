# make_shortcut.py — create KuubWave.lnk pointing at this checkout, using the
# venv's pythonw (no console window). Paths are resolved relative to this file,
# so the shortcut works wherever the repo is cloned.
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
pythonw = os.path.join(BASE, ".venv", "Scripts", "pythonw.exe")
target_py = os.path.join(BASE, "flow.py")
icon = os.path.join(BASE, "kuubwave.ico")
lnk = os.path.join(BASE, "KuubWave.lnk")

if not os.path.isfile(pythonw):
    sys.exit(f"venv not found at {pythonw} — create it first (see README).")

vbs = f'''
Set ws = CreateObject("WScript.Shell")
Set lnk = ws.CreateShortcut("{lnk}")
lnk.TargetPath = "{pythonw}"
lnk.Arguments = """{target_py}"""
lnk.WorkingDirectory = "{BASE}"
lnk.IconLocation = "{icon}"
lnk.Description = "KuubWave — голосова диктовка"
lnk.Save
'''
vbs_path = os.path.join(BASE, "_mk.vbs")
with open(vbs_path, "w", encoding="cp1251") as f:
    f.write(vbs)
try:
    subprocess.run(["cscript", "//nologo", vbs_path], check=True, timeout=60)
    print(f"created {lnk}")
finally:
    os.remove(vbs_path)
