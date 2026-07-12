# Building the whspr installer

Produces a small (~270 MB) per-user Windows installer. The heavy parts —
the recognition model and (on NVIDIA machines) the CUDA runtime — are
downloaded on first launch, so the installer stays lean and works on any
64-bit Windows 10/11 PC.

## Prerequisites

- The project venv with all deps (`requirements.txt`) **plus** PyInstaller:
  ```
  .venv\Scripts\pip install pyinstaller
  ```
- [Inno Setup 6](https://jrsoftware.org/isdl.php) (for the `.exe` installer).
  Default path: `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`.

## Build

From the repo root:

```powershell
# 1. freeze the app -> dist\whspr\  (one folder, ~270 MB)
.venv\Scripts\pyinstaller packaging\whspr.spec --noconfirm --distpath dist --workpath build

# 2. package -> packaging\Output\whspr-setup.exe
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\whspr.iss
```

Or run `packaging\build.ps1` which does both.

## What ships vs. what downloads

| Component | Shipped in installer | Fetched on first run |
|-----------|:--------------------:|:--------------------:|
| App + Python runtime + ctranslate2 | ✅ | |
| Web UI (`web/`) | ✅ | |
| Whisper model (~1.5 GB) | | ✅ HuggingFace |
| CUDA cuBLAS/cuDNN (~0.9 GB) | | ✅ PyPI, **only if NVIDIA GPU** |

- No GPU → runs on CPU automatically (slower, no download).
- All runtime data lives in `%LOCALAPPDATA%\whspr` (config, history, log,
  `models\`, `cuda\`). Program files stay read-only.

## First-run notes

- First launch needs internet to pull the model (and CUDA on NVIDIA PCs).
  Progress is written to `%LOCALAPPDATA%\whspr\whspr.log`.
- WebView2 runtime is required; it is preinstalled on current Windows 10/11.
  If missing, install the Evergreen runtime from Microsoft.

## Known items to validate on a clean PC

- GPU path: ctranslate2 bundles a `cudnn64_9.dll`; the runtime download also
  provides cuDNN 9.1.0.70 (pinned to avoid SM86 kernel recompilation). Confirm
  the pinned copy wins on the DLL search path (it is prepended via
  `add_dll_directory`). If first GPU transcribe stalls for minutes, remove the
  bundled `dist\whspr\_internal\ctranslate2\cudnn64_9.dll`.
- Tray icon, floating pill, and dictation end-to-end.
