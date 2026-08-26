# whspr.spec — PyInstaller one-folder build.
#
# Deliberately does NOT bundle the nvidia CUDA libraries (excludes=['nvidia'])
# or any HuggingFace model. Those are fetched at first run (see cuda_setup.py
# and faster-whisper's auto-download), keeping the installer small.
#
# Build from the repo root:
#   .venv\Scripts\pyinstaller packaging\whspr.spec --noconfirm

import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.dirname(SPECPATH)  # spec lives in packaging/, code in repo root

datas = [(os.path.join(ROOT, "web"), "web"), (os.path.join(ROOT, "whspr.ico"), ".")]
binaries = []
hiddenimports = ["comtypes", "pystray._win32", "cuda_setup", "webview_app",
                 "ui", "licensing", "pycaw", "pycaw.pycaw"]

# pull in data files / dylibs / submodules for the tricky native packages
for pkg in ("webview", "ctranslate2", "faster_whisper", "sounddevice",
            "tokenizers", "huggingface_hub", "av"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    [os.path.join(ROOT, "flow.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["nvidia"],  # CUDA libs are downloaded at first run, not shipped
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="whspr",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # windowed app, no console
    icon=os.path.join(ROOT, "whspr.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="whspr",
)
