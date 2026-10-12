# kuubwave.spec — PyInstaller one-folder build.
#
# Deliberately does NOT bundle the nvidia CUDA libraries (excludes=['nvidia'])
# or any HuggingFace model. Those are fetched at first run (see cuda_setup.py
# and faster-whisper's auto-download), keeping the installer small.
#
# Build from the repo root:
#   .venv\Scripts\pyinstaller packaging\kuubwave.spec --noconfirm

import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.dirname(SPECPATH)  # spec lives in packaging/, code in repo root

datas = [(os.path.join(ROOT, "web"), "web"),
         (os.path.join(ROOT, "kuubwave.ico"), "."),
         (os.path.join(ROOT, "kuubwave_tray.png"), ".")]
binaries = []
hiddenimports = ["comtypes", "pystray._win32", "cuda_setup", "webview_app",
                 "ui", "licensing", "pycaw", "pycaw.pycaw",
                 # text_fixes is a plain top-level import in flow.py and would be
                 # found anyway; mic_level is imported lazily inside main(), so
                 # static analysis misses it and the packaged build would silently
                 # lose the "raise the mic level" button. Both listed explicitly.
                 # term_suggest is imported lazily by webview_app for the same
                 # reason ("Знайти проблемні слова").
                 "text_fixes", "mic_level", "app_styles", "term_suggest",
                 "latency", "style_profile",
                 # flow.py split (step 1): these four are imported by flow.py at
                 # the position of their old sections, so list them explicitly.
                 "history_store", "autostart", "updater", "cloud_stt",
                 # flow.py split (step 2): same reason as step 1.
                 "model_library", "license_gate", "parakeet_engine", "audio_duck",
                 # flow.py split (step 3): same reason as step 1.
                 "llm_polish", "text_passes", "voice_commands", "command_mode", "scribe",
                 # flow.py split (step 4): same reason as step 1.
                 "single_instance", "whisper_model", "audio_input", "paste",
                 # flow.py split (step 5): same reason as step 1.
                 "live_preview", "transcription",
                 # flow.py split (step 6): same reason as step 1.
                 "hotkeys"]

# pull in data files / dylibs / submodules for the tricky native packages.
# onnx_asr + onnxruntime are for the optional Parakeet engine: flow.py imports
# onnx_asr only inside load_parakeet(), so static analysis never sees it, and
# onnx_asr loads its mel-preprocessor graphs (onnx_asr/preprocessors/data/*.onnx)
# from package data — collect_all brings both the submodules and those files.
# onnxruntime is listed explicitly because faster_whisper also imports it only
# lazily (Silero VAD); its DLLs must be in the bundle for either feature. If the
# packages are missing at build time the try/except skips them and the build
# simply ships without Parakeet (the app then falls back to Whisper).
# Smart Turn (hands-free end-of-turn) needs nothing extra here: it runs on the
# same onnxruntime, takes its log-mel from faster_whisper.feature_extractor
# (pure numpy, covered by collect_all("faster_whisper")) and fetches its 8 MB
# onnx at runtime via huggingface_hub into the models cache, not the bundle.
for pkg in ("webview", "ctranslate2", "faster_whisper", "sounddevice",
            "tokenizers", "huggingface_hub", "av", "onnxruntime", "onnx_asr"):
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
    name="KuubWave",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # windowed app, no console
    icon=os.path.join(ROOT, "kuubwave.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="KuubWave",
)
