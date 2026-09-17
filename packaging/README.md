# Building the KuubWave installer

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
# 1. freeze the app -> dist\KuubWave\  (one folder, ~270 MB)
.venv\Scripts\pyinstaller packaging\kuubwave.spec --noconfirm --distpath dist --workpath build

# 2. package -> packaging\Output\kuubwave-setup.exe
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\kuubwave.iss
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
- All runtime data lives in `%LOCALAPPDATA%\KuubWave` (config, history, log,
  `models\`, `cuda\`). Program files stay read-only.

## First-run notes

- First launch needs internet to pull the model (and CUDA on NVIDIA PCs).
  Progress is written to `%LOCALAPPDATA%\KuubWave\kuubwave.log`.
- WebView2 runtime is required; it is preinstalled on current Windows 10/11.
  If missing, install the Evergreen runtime from Microsoft.

## Licensing (offline monthly keys)

KuubWave uses offline Ed25519-signed license keys. The app ships only the public
key (`licensing.py`); keys can be issued solely with your private key.

**One-time setup** (already done if `keys\whspr_ed25519.pem` exists):
```
python make_license.py genkey
```
This writes the private key to `keys\whspr_ed25519.pem` and prints the public
key to embed in `licensing.py` (`LICENSE_PUBKEY_HEX`).

> ⚠️ **Back up `keys\whspr_ed25519.pem` somewhere safe and never commit it.**
> It is git-ignored. If you lose it you cannot issue keys that match the public
> key already shipped in the app, and every installed copy would need a rebuild
> with a new key.

**Issue a monthly key for a buyer:**
```
python make_license.py issue --days 30 --id "buyer@example.com"
```
Send the printed key string to the customer. They paste it into
**Settings → Ліцензія → Активувати**. Dictation is locked until a valid,
unexpired key is entered; after expiry the app asks for a new one.

Notes:
- Clock-rollback is guarded (a stored last-seen date), so winding the system
  clock back does not revive an expired key.
- This is client-side DRM — it deters casual sharing and enforces the window,
  but is not tamper-proof against a determined attacker with the binary.
- Keys are **not** bound to a machine in this build (a key works on any PC).
  Add hardware binding later if needed.

## Known items to validate on a clean PC

- GPU path: ctranslate2 bundles a `cudnn64_9.dll`; the runtime download also
  provides cuDNN 9.1.0.70 (pinned to avoid SM86 kernel recompilation). Confirm
  the pinned copy wins on the DLL search path (it is prepended via
  `add_dll_directory`). If first GPU transcribe stalls for minutes, remove the
  bundled `dist\KuubWave\_internal\ctranslate2\cudnn64_9.dll`.
- Tray icon, floating pill, and dictation end-to-end.
