# flow.py — Wispr Flow clone for Windows
# Hold the dictation key (default F9) to record, release to transcribe and
# paste into the window that was focused at release. F10 toggles uk <-> en.
# Run with --no-ui for headless mode (tray/overlay off, prints only).
#
# Designed to run under pythonw.exe (no console): all logging goes to
# whspr.log, print() is best-effort.

import os
import re
import sys
import json
import time
import sqlite3
import threading
import collections
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
FROZEN = getattr(sys, "frozen", False)

# Launched as `python flow.py`, this module is "__main__". Register it as "flow"
# as well so that webview_app's `import flow` reuses THIS instance (with the live
# audio/model/status state) instead of creating a SECOND flow module whose state
# never leaves "loading" — which made the UI hang on "Завантаження моделі…".
if __name__ == "__main__":
    sys.modules.setdefault("flow", sys.modules["__main__"])


def _data_dir() -> str:
    """Writable per-user location for config/db/log/models/cuda. When installed
    to Program Files the app folder is read-only, so a frozen build stores its
    data under %LOCALAPPDATA%\\whspr. From source, keep everything in the repo."""
    d = os.path.join(os.environ.get("LOCALAPPDATA", BASE), "whspr") if FROZEN else BASE
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


DATA_DIR = _data_dir()
# installed build: keep the HuggingFace model cache in our writable data dir
# (set before faster_whisper is imported). From source, leave HF's default
# (~/.cache/huggingface) so dev doesn't re-download gigabytes.
if FROZEN:
    os.environ.setdefault("HF_HOME", os.path.join(DATA_DIR, "models"))


def register_cuda_dlls() -> bool:
    """Expose cuBLAS/cuDNN to ctranslate2. Dev builds use the venv; installed
    builds use the runtime-downloaded copy in <data>/cuda. Returns True if any
    CUDA dir was found and registered."""
    found = False
    roots = [
        os.path.join(BASE, ".venv", "Lib", "site-packages", "nvidia"),
        os.path.join(DATA_DIR, "cuda", "nvidia"),
    ]
    for root in roots:
        for sub in ("cublas/bin", "cudnn/bin"):
            p = os.path.join(root, *sub.split("/"))
            if os.path.isdir(p):
                os.add_dll_directory(p)
                os.environ["PATH"] = p + os.pathsep + os.environ["PATH"]
                found = True
    return found


register_cuda_dlls()

import ctypes
import numpy as np
import sounddevice as sd
import pyperclip
from pynput import keyboard
from faster_whisper import WhisperModel

# ---------------- Config ----------------
APP_VERSION = "1.0.0"
GITHUB_REPO = "kuubek5/whspr"  # for the update check
# Default Systran repo is 401 on HF now; deepdml is the working CT2 mirror.
MODEL_NAME = "deepdml/faster-whisper-large-v3-turbo-ct2"
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LOG_PATH = os.path.join(DATA_DIR, "whspr.log")
DB_PATH = os.path.join(DATA_DIR, "history.db")
LNK_NAME = "whspr.lnk"
UK_MODELS = {
    "stock": MODEL_NAME,
    "uk-ft": "skypro1111/whisper-large-v3-turbo-ukrainian-ukraine-3percent-ct2",
}
DEFAULTS = {
    "hotkey": "f9",           # any key or combo, e.g. "ctrl+space", "alt+vk81"
    "lang_hotkey": "f10",     # tap to toggle uk/en
    "language": "uk",
    "theme": "dark",          # web UI theme: dark | light
    # which model handles Ukrainian: "stock" or "uk-ft" (fine-tune, downloaded)
    "model_uk": "stock",
    # compute device: "cuda" (GPU, fast) or "cpu" (fallback, slow)
    "device": "cuda",
    "rms_threshold": 0.003,
    "beam_size": 5,
    "overlay": True,
    # mic input device name; "" = system default
    "input_device": "",
    # open the mic only while recording (removes the always-on tray mic
    # indicator, at the cost of pre-roll and a tiny start-up delay)
    "mic_on_demand": False,
    # dictionary: comma/newline-separated terms fed to whisper as hotwords
    "dictionary": "",
    # voice commands replaced in the final text (case-insensitive)
    "replacements": {
        "новий рядок": "\n",
        "з нового рядка": "\n",
        "new line": "\n",
        "новий абзац": "\n\n",
        "new paragraph": "\n\n",
    },
    # LLM post-processing: "off" | "groq" | "ollama"
    "llm": "off",
    "groq_api_key": "",
    "groq_model": "llama-3.3-70b-versatile",
    "ollama_model": "qwen2.5:7b",
    "autostart": False,
}
SAMPLE_RATE = 16000
PRE_ROLL_S = 0.5
MIN_DURATION_S = 0.3
LANGUAGES = ["uk", "en"]
HOTKEY_LANG = keyboard.Key.f10
BLOCK = 512
# Whisper invents these on short/quiet clips (YouTube training artifacts).
# Dropped when they are the ENTIRE transcript of a short recording.
HALLUCINATIONS = {
    "дякую за перегляд", "дякую за перегляд!", "субтитри створені спільнотою amara.org",
    "продовження в наступній серії", "підпишіться на канал",
    "thanks for watching", "thank you for watching", "you",
}
# Nudges Whisper toward Ukrainian tokens — kills phonetic drift into Russian
# ("чотири п'ять" heard as "четыре пять"). Russian-only letters never appear.
UK_INITIAL_PROMPT = "Розмова українською мовою. Привіт, як твої справи? Один, два, три, чотири, п'ять."
RU_ONLY_CHARS = set("ыэъёЫЭЪЁ")
LLM_PROMPT = (
    "Ти — коректор диктовки. Виправ пунктуацію та очевидні помилки розпізнавання "
    "мовлення, прибери слова-паразити (ем, еее, ну от, um, uh). Збережи мову, зміст "
    "і стиль. Поверни ЛИШЕ виправлений текст без пояснень і лапок."
)
# -----------------------------------------


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass  # pythonw has no stdout
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


config = load_config()
state = {
    "lang": LANGUAGES.index(config["language"]) if config["language"] in LANGUAGES else 0,
    "recording": False,
    "status": "loading",
    "model": None,
    "models": {},  # model name -> WhisperModel (lazy cache)
}
chunks: list[np.ndarray] = []
pre_roll = collections.deque(maxlen=int(PRE_ROLL_S * SAMPLE_RATE / BLOCK) + 1)
kb = keyboard.Controller()
user32 = ctypes.windll.user32
tray_icon = None
overlay = None  # StatusOverlay | None


# ---------------- Single instance ----------------
def ensure_single_instance() -> None:
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW(None, False, "whspr_single_instance_mutex")
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        log("another whspr instance is already running — exiting")
        sys.exit(0)


# ---------------- History (SQLite) ----------------
def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS history ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, lang TEXT, "
        "duration REAL, text TEXT)"
    )
    return con


def history_add(text: str, lang: str, duration: float) -> None:
    try:
        with _db() as con:
            con.execute(
                "INSERT INTO history (ts, lang, duration, text) VALUES (?,?,?,?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"), lang, round(duration, 1), text),
            )
    except sqlite3.Error as e:
        log(f"history write failed: {e}")


def history_last(n: int = 100) -> list[tuple]:
    try:
        with _db() as con:
            return con.execute(
                "SELECT id, ts, lang, duration, text FROM history ORDER BY id DESC LIMIT ?", (n,)
            ).fetchall()
    except sqlite3.Error:
        return []


def history_delete(row_id: int) -> None:
    try:
        with _db() as con:
            con.execute("DELETE FROM history WHERE id=?", (row_id,))
    except sqlite3.Error as e:
        log(f"history delete failed: {e}")


def history_clear() -> None:
    try:
        with _db() as con:
            con.execute("DELETE FROM history")
    except sqlite3.Error as e:
        log(f"history clear failed: {e}")


def history_stats() -> dict:
    """Aggregate numbers for the dashboard."""
    today = time.strftime("%Y-%m-%d")
    try:
        with _db() as con:
            rows = con.execute("SELECT ts, duration, text FROM history").fetchall()
    except sqlite3.Error:
        rows = []
    total = len(rows)
    words = sum(len(t.split()) for _, _, t in rows)
    words_today = sum(len(t.split()) for ts, _, t in rows if ts.startswith(today))
    dictations_today = sum(1 for ts, _, _ in rows if ts.startswith(today))
    secs = sum(d for _, d, _ in rows if d)
    # words per minute across all dictated audio time
    wpm = (words / (secs / 60)) if secs else 0
    return {
        "total": total, "words": words, "words_today": words_today,
        "dictations_today": dictations_today, "seconds": secs, "wpm": wpm,
    }


# ---------------- Autostart ----------------
def startup_dir() -> str:
    return os.path.join(os.environ["APPDATA"],
                        r"Microsoft\Windows\Start Menu\Programs\Startup")


def set_autostart(enable: bool) -> None:
    """Toggle launch-at-login. Installed build uses the HKCU Run registry key
    pointing at the exe; from source we copy the launcher .lnk into Startup."""
    if FROZEN:
        try:
            import winreg
            key = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0,
                                winreg.KEY_SET_VALUE) as k:
                if enable:
                    winreg.SetValueEx(k, "whspr", 0, winreg.REG_SZ,
                                      f'"{sys.executable}"')
                    log("autostart enabled (registry)")
                else:
                    try:
                        winreg.DeleteValue(k, "whspr")
                        log("autostart disabled")
                    except FileNotFoundError:
                        pass
        except OSError as e:
            log(f"autostart failed: {e}")
        return

    import shutil
    src = os.path.join(BASE, LNK_NAME)
    dst = os.path.join(startup_dir(), LNK_NAME)
    try:
        if enable:
            if os.path.isfile(src):
                shutil.copyfile(src, dst)
                log("autostart enabled")
            else:
                log(f"autostart: {src} not found — create the shortcut first")
        elif os.path.isfile(dst):
            os.remove(dst)
            log("autostart disabled")
    except OSError as e:
        log(f"autostart failed: {e}")


# ---------------- LLM post-processing ----------------
def llm_polish(text: str, lang: str) -> str:
    """Optional cleanup pass. Any failure returns the raw text."""
    mode = config.get("llm", "off")
    if mode == "off" or not text:
        return text
    try:
        if mode == "groq":
            if not config.get("groq_api_key"):
                return text
            url = "https://api.groq.com/openai/v1/chat/completions"
            payload = {
                "model": config.get("groq_model", DEFAULTS["groq_model"]),
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": LLM_PROMPT},
                    {"role": "user", "content": text},
                ],
            }
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config['groq_api_key']}",
            }
        elif mode == "ollama":
            url = "http://localhost:11434/v1/chat/completions"
            payload = {
                "model": config.get("ollama_model", DEFAULTS["ollama_model"]),
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": LLM_PROMPT},
                    {"role": "user", "content": text},
                ],
            }
            headers = {"Content-Type": "application/json"}
        else:
            return text
        req = urllib.request.Request(
            url, json.dumps(payload).encode("utf-8"), headers=headers
        )
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=15) as resp:
            out = json.load(resp)["choices"][0]["message"]["content"].strip()
        log(f"llm polish ({mode}): {time.time() - t0:.2f}s")
        return out or text
    except Exception as e:
        log(f"llm polish failed ({e.__class__.__name__}: {e}) — using raw text")
        return text


# ---------------- Voice commands ----------------
def apply_replacements(text: str) -> str:
    for phrase, repl in config.get("replacements", {}).items():
        # eat surrounding punctuation/spaces so "Привіт. Новий рядок. Бувай"
        # becomes "Привіт.\nБувай"
        pattern = r"[,.!?]?\s*" + re.escape(phrase) + r"[,.!?]?\s*"
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return text.strip()


# ---------------- Download progress ----------------
def set_download(active: bool, label: str = "", mb: int = 0,
                 total_mb: int = 0) -> None:
    pct = round(mb / total_mb * 100) if total_mb else None
    state["download"] = {"active": active, "label": label,
                         "mb": mb, "totalMb": total_mb, "pct": pct}


def _dir_size_mb(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total >> 20


def _watch_model_download(label: str, stop: threading.Event) -> None:
    """Report growth of the HF cache dir while a model downloads (its total is
    unknown up front, so we show MB pulled)."""
    cache = os.environ.get("HF_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache", "huggingface")
    base = _dir_size_mb(cache)
    while not stop.is_set():
        grown = _dir_size_mb(cache) - base
        if grown > 3:  # ignore tiny metadata churn
            set_download(True, label, mb=grown)
        stop.wait(0.6)


# ---------------- Auto-update ----------------
def _version_tuple(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0"))


def check_update() -> dict:
    """Query GitHub Releases for a newer version. Returns
    {available, version, url} — never raises."""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "whspr"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        tag = (data.get("tag_name") or "").lstrip("v")
        asset = next((a["browser_download_url"] for a in data.get("assets", [])
                      if a.get("name", "").endswith(".exe")), "")
        newer = _version_tuple(tag) > _version_tuple(APP_VERSION)
        return {"available": bool(newer and asset), "version": tag, "url": asset}
    except Exception as e:
        log(f"update check failed ({e.__class__.__name__}: {e})")
        return {"available": False, "version": "", "url": ""}


def download_update(url: str) -> bool:
    """Download the installer to a temp file and launch it. The running app
    should quit afterwards so the installer can replace its files."""
    try:
        import tempfile
        fd, path = tempfile.mkstemp(suffix="-whspr-setup.exe")
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
                    set_download(True, "Оновлення", mb=done >> 20,
                                 total_mb=(total >> 20) if total else 0)
        set_download(False)
        os.startfile(path)  # noqa: launch the installer (Windows)
        return True
    except Exception as e:
        log(f"update download failed ({e.__class__.__name__}: {e})")
        set_download(False)
        return False


# ---------------- Licensing ----------------
def license_status() -> dict:
    try:
        import licensing
        state["license"] = licensing.status(DATA_DIR)
    except Exception as e:
        log(f"license check failed ({e.__class__.__name__}: {e})")
        state["license"] = {"licensed": False, "reason": "error",
                            "exp": "", "daysLeft": 0}
    return state["license"]


def activate_license(key: str) -> dict:
    try:
        import licensing
        res = licensing.activate(DATA_DIR, key)
    except Exception as e:
        log(f"activation failed ({e.__class__.__name__}: {e})")
        return {"ok": False, "error": "Помилка активації"}
    license_status()
    return res


def is_licensed() -> bool:
    return bool(state.get("license", {}).get("licensed"))


# ---------------- UI plumbing ----------------
def set_status(s: str) -> None:
    state["status"] = s
    if tray_icon is not None:
        tray_icon.icon = tray_image(s)
        tray_icon.title = f"whspr: {s} [{LANGUAGES[state['lang']]}]"
    if overlay is not None and config.get("overlay", True):
        try:
            if s == "recording":
                overlay.recording()
            elif s == "processing":
                overlay.processing()
            elif s == "loading":
                overlay.loading()
            elif s == "idle":
                overlay.hide()
        except Exception as e:
            log(f"overlay update failed ({e.__class__.__name__}: {e})")


def tray_image(status: str):
    from PIL import Image, ImageDraw
    color = {"idle": (90, 90, 90), "recording": (229, 72, 77),
             "processing": (240, 180, 41), "loading": (100, 100, 220)}.get(status, (90, 90, 90))
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((8, 8, 56, 56), fill=color)
    return img


def start_tray(on_open, on_quit) -> None:
    global tray_icon
    try:
        import pystray
    except ImportError:
        log("pystray not installed — running without tray icon")
        return
    tray_icon = pystray.Icon(
        "whspr", tray_image(state["status"]), "whspr: loading",
        menu=pystray.Menu(
            pystray.MenuItem("Відкрити whspr", lambda i, it: on_open(), default=True),
            pystray.MenuItem("Вихід", lambda i, it: on_quit()),
        ),
    )
    threading.Thread(target=tray_icon.run, daemon=True).start()


# ---------------- Model ----------------
_model_lock = threading.Lock()


def load_model(name: str = MODEL_NAME) -> WhisperModel:
    with _model_lock:
        return _load_model_locked(name)


def _build_model(name: str, device: str, compute_type: str) -> WhisperModel:
    # If the model is already cached, load it offline — otherwise faster-whisper
    # does an HF revision check that can hang for a long time on a slow/blocked
    # network (e.g. behind a VPN), which looked like an endless "loading model".
    try:
        return WhisperModel(name, device=device, compute_type=compute_type,
                            local_files_only=True)
    except Exception:
        return WhisperModel(name, device=device, compute_type=compute_type)


def _load_model_locked(name: str) -> WhisperModel:
    if name in state["models"]:
        return state["models"][name]
    if config.get("device") == "cpu":
        m = _build_model(name, "cpu", "int8")
        log(f"model {name} on CPU (forced)")
    else:
        try:
            m = _build_model(name, "cuda", "int8_float16")
            log(f"model {name} on CUDA")
        except Exception as e:
            log(f"CUDA failed ({e.__class__.__name__}: {e}), falling back to CPU")
            m = _build_model(name, "cpu", "int8")
            log(f"model {name} on CPU")
    t0 = time.time()
    list(m.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), language="en")[0])
    log(f"warm-up done ({time.time() - t0:.1f}s)")
    state["models"][name] = m
    return m


def reload_models() -> None:
    """Drop cached models and re-warm the default on the new compute device."""
    set_status("loading")
    with _model_lock:
        state["models"].clear()
        state["model"] = None

    def boot():
        try:
            state["model"] = model_for(LANGUAGES[state["lang"]])
            set_status("idle")
            log("model reloaded on " + config.get("device", "cuda"))
        except Exception as e:
            log(f"model reload failed ({e.__class__.__name__}: {e})")
            set_status("idle")

    threading.Thread(target=boot, daemon=True).start()


def model_for(lang: str) -> WhisperModel:
    if lang == "uk":
        name = UK_MODELS.get(config.get("model_uk", "stock"), MODEL_NAME)
    else:
        name = MODEL_NAME
    return load_model(name)


def capitalize_sentences(text: str) -> str:
    # uk fine-tune tends to lowercase sentence starts
    return re.sub(
        r"(^|[.!?]\s+)([а-яґєіїa-z])",
        lambda m: m.group(1) + m.group(2).upper(),
        text,
    )


# ---------------- Audio ----------------
def audio_callback(indata, frames, t, status):
    if state["recording"]:
        chunks.append(indata.copy())
    else:
        pre_roll.append(indata.copy())
    # cheap live input level for the mic meter / test
    try:
        state["input_level"] = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
    except Exception:
        pass


def mic_test(enable: bool) -> bool:
    """Open the mic (if needed) so the settings meter can show a live level.
    Returns True if a stream is available."""
    if enable:
        if state.get("stream") is None:
            state["stream"] = open_input_stream()
        state["mic_test"] = True
        return state.get("stream") is not None
    state["mic_test"] = False
    if config.get("mic_on_demand") and not state["recording"]:
        close_stream()
    return True


def _make_stream(device):
    return sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="float32",
        blocksize=BLOCK, callback=audio_callback, device=device,
    )


def open_input_stream():
    """Open the mic stream on the configured device, falling back to the system
    default. Never raises: returns None if no input device is usable, so a
    missing/unplugged mic degrades to 'dictation disabled' instead of a crash."""
    dev = config.get("input_device") or None
    for target in (dev, None) if dev is not None else (None,):
        try:
            s = _make_stream(target)
            s.start()
            name = sd.query_devices(target)["name"] if target is not None else "system default"
            log(f"input device: {name}")
            return s
        except Exception as e:
            log(f"input device {target!r} failed ({e.__class__.__name__}: {e})")
    log("no usable input device — dictation disabled until one is connected")
    return None


def close_stream() -> None:
    old = state.get("stream")
    if old is not None:
        try:
            old.stop()
            old.close()
        except Exception:
            pass
    state["stream"] = None


def restart_stream() -> None:
    """Reopen the mic stream after a device / mic-mode change. In on-demand mode
    the stream stays closed until the next recording."""
    close_stream()
    if not config.get("mic_on_demand"):
        state["stream"] = open_input_stream()


def list_input_devices() -> list[dict]:
    """Unique input-capable devices for the settings picker."""
    out, seen = [], set()
    try:
        for d in sd.query_devices():
            name = d.get("name", "")
            if d.get("max_input_channels", 0) > 0 and name and name not in seen:
                seen.add(name)
                out.append({"name": name})
    except Exception as e:
        log(f"device enumeration failed: {e}")
    return out


# ---------------- Paste ----------------
def paste_text(text: str, target_hwnd: int) -> bool:
    # if user alt-tabbed away while we transcribed, go back to the window
    # that was focused when the key was released
    if target_hwnd and user32.GetForegroundWindow() != target_hwnd:
        user32.SetForegroundWindow(target_hwnd)
        time.sleep(0.15)
        if user32.GetForegroundWindow() != target_hwnd:
            log("target window lost focus and refocus failed — text left in clipboard")
            pyperclip.copy(text)
            return False

    old = None
    try:
        old = pyperclip.paste()
    except Exception:
        pass
    pyperclip.copy(text)
    time.sleep(0.05)
    # physical VK 0x56 ('V'), NOT the char 'v': on a Cyrillic layout the char
    # 'v' maps to no key (VkKeyScan -> 0xFF) and pynput's Ctrl+'v' silently
    # fails — the whole reason paste didn't work while dictating Ukrainian.
    v_key = keyboard.KeyCode.from_vk(0x56)
    with kb.pressed(keyboard.Key.ctrl):
        kb.press(v_key)
        kb.release(v_key)
    if old is not None:
        def restore():
            time.sleep(0.5)
            try:
                pyperclip.copy(old)
            except Exception:
                pass
        threading.Thread(target=restore, daemon=True).start()
    return True


# ---------------- Pipeline ----------------
def transcribe_and_paste(target_hwnd: int) -> None:
    set_status("processing")
    done_msg, ok = None, True
    try:
        if not chunks:
            return
        audio = np.concatenate(list(pre_roll) + chunks).flatten().astype(np.float32)
        chunks.clear()
        dur = len(audio) / SAMPLE_RATE
        if dur < MIN_DURATION_S + PRE_ROLL_S:
            return
        # cheap silence gate instead of Silero VAD: onnxruntime import hangs
        # for minutes on this machine, and push-to-talk audio has speech anyway
        rms = float(np.sqrt(np.mean(audio**2)))
        log(f"level rms={rms:.4f} (threshold {config['rms_threshold']})")
        if rms < config["rms_threshold"]:
            log(f"skipped: too quiet (rms={rms:.4f})")
            done_msg, ok = "тиша", False
            return
        lang = LANGUAGES[state["lang"]]
        hotwords = " ".join(
            t.strip() for t in re.split(r"[,\n]", config.get("dictionary", "")) if t.strip()
        ) or None
        t0 = time.time()
        initial_prompt = UK_INITIAL_PROMPT if lang == "uk" else None
        segments, _ = model_for(lang).transcribe(
            audio, language=lang, vad_filter=False,
            beam_size=config["beam_size"], hotwords=hotwords,
            initial_prompt=initial_prompt,
            condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        ru = "".join(sorted(set(text) & RU_ONLY_CHARS))
        log(f"{dur:.1f}s audio -> {time.time() - t0:.2f}s transcribe [{lang}]"
            f"{' RU-chars:' + ru if ru else ''}: {text!r}")
        if not text:
            done_msg, ok = "порожньо", False
            return
        if dur < 4.0 and text.lower().strip(" .!?") in {
            h.strip(" .!?") for h in HALLUCINATIONS
        }:
            log("dropped as hallucination")
            done_msg, ok = "не розчув", False
            return
        text = llm_polish(text, lang)
        text = apply_replacements(text)
        text = capitalize_sentences(text)
        history_add(text, lang, dur)
        pasted = paste_text(text, target_hwnd)
        done_msg, ok = (text, True) if pasted else ("фокус втрачено — текст у буфері", False)
        state["pill_text"] = text
        state["pill_done_at"] = time.time()
    finally:
        set_status("idle")
        if overlay is not None and config.get("overlay", True):
            try:
                if done_msg is not None:
                    overlay.flash(done_msg, ok)
                else:
                    overlay.hide()
            except Exception as e:
                log(f"overlay flash failed ({e.__class__.__name__}: {e})")


# ---------------- Hotkeys ----------------
MODS = ("ctrl", "alt", "shift", "cmd")
# vk -> readable name for display/capture (letters, digits, common keys)
VK_NAMES = {**{0x41 + i: chr(ord("A") + i) for i in range(26)},
            **{0x30 + i: str(i) for i in range(10)},
            **{0x60 + i: f"Num{i}" for i in range(10)}}
NAME_VK = {v.lower(): k for k, v in VK_NAMES.items()}


def canon(key) -> str:
    """Canonical, layout-independent token for one key event."""
    if isinstance(key, keyboard.Key):
        name = key.name
        for m in MODS:
            if name.startswith(m):
                return m
        return name  # f9, space, tab, scroll_lock, pause, ...
    # KeyCode: use physical vk (char depends on active layout)
    vk = getattr(key, "vk", None)
    return f"vk{vk}" if vk is not None else str(key)


def parse_hotkey(spec: str) -> frozenset:
    """'ctrl+space' / 'f9' / 'alt+vk81' -> frozenset of canonical tokens."""
    out = set()
    for part in (spec or "f9").lower().split("+"):
        part = part.strip()
        if not part:
            continue
        if part in NAME_VK:            # 'q' -> vk81
            out.add(f"vk{NAME_VK[part]}")
        else:
            out.add(part)
    return frozenset(out)


def hotkey_label(spec: str) -> str:
    """Pretty form for the UI: 'ctrl+vk81' -> 'Ctrl + Q'."""
    parts = []
    for t in sorted(parse_hotkey(spec), key=lambda x: (x not in MODS, x)):
        if t in MODS:
            parts.append(t.capitalize())
        elif t.startswith("vk"):
            parts.append(VK_NAMES.get(int(t[2:]), t.upper()))
        else:
            parts.append(t.replace("_", " ").title())
    return " + ".join(parts)


def start_listener() -> keyboard.Listener:
    """Hold-to-talk listener supporting single keys AND combos. Rebuilt on the
    fly by restart_listener() when the user changes the hotkey."""
    required = parse_hotkey(config["hotkey"])
    lang_key = parse_hotkey(config.get("lang_hotkey", "f10"))
    pressed: set[str] = set()

    def start_rec():
        if not is_licensed():
            log("dictation locked — no valid license")
            return
        if state["model"] is None:
            log("model still loading, try again in a moment")
            return
        if config.get("mic_on_demand") and state.get("stream") is None:
            state["stream"] = open_input_stream()
            if state["stream"] is None:
                log("cannot record: no input device")
                return
        chunks.clear()
        state["recording"] = True
        set_status("recording")
        log("recording...")

    def stop_rec():
        state["recording"] = False
        hwnd = user32.GetForegroundWindow()
        threading.Thread(target=transcribe_and_paste, args=(hwnd,), daemon=True).start()
        if config.get("mic_on_demand"):
            close_stream()

    def on_press(key):
        tok = canon(key)
        pressed.add(tok)
        if required and required <= pressed and not state["recording"]:
            start_rec()
        elif lang_key and lang_key <= pressed and tok in lang_key and not (lang_key & MODS_SET):
            # simple lang toggle only for non-combo lang key (avoid double-fire)
            state["lang"] = (state["lang"] + 1) % len(LANGUAGES)
            set_status(state["status"])
            log(f"language -> {LANGUAGES[state['lang']]}")

    def on_release(key):
        tok = canon(key)
        if state["recording"] and tok in required:
            stop_rec()
        pressed.discard(tok)

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    return listener


MODS_SET = frozenset(MODS)


def restart_listener() -> None:
    """Apply a changed hotkey without restarting the whole app."""
    global _listener
    try:
        if _listener is not None:
            _listener.stop()
    except Exception:
        pass
    _listener = start_listener()
    log(f"hotkey -> {hotkey_label(config['hotkey'])}")


_listener = None


def capture_hotkey(on_done) -> None:
    """Listen for the next key combo the user presses; call on_done(spec).
    Fires when a non-modifier key is pressed (with whatever mods are held),
    or when a lone modifier is released."""
    held: list[str] = []

    def finish(listener, tokens):
        listener.stop()
        spec = "+".join(sorted(tokens, key=lambda x: (x not in MODS, x)))
        on_done(spec)

    def on_press(key):
        tok = canon(key)
        if tok not in held:
            held.append(tok)
        if tok not in MODS_SET:  # a real key -> combo complete
            finish(cap, list(held))
            return False

    def on_release(key):
        tok = canon(key)
        if held and all(t in MODS_SET for t in held):  # only mods, released one
            finish(cap, list(held))
            return False

    cap = keyboard.Listener(on_press=on_press, on_release=on_release)
    cap.start()


class AppContext:
    """Bridge passed to the GUI: config + data + actions, no GUI deps here."""
    config = config
    LANGUAGES = LANGUAGES
    UK_MODELS = UK_MODELS
    HOTKEYS = ["f8", "f9", "scroll_lock", "pause"]
    history_last = staticmethod(history_last)
    history_delete = staticmethod(history_delete)
    history_clear = staticmethod(history_clear)
    history_stats = staticmethod(history_stats)
    set_autostart = staticmethod(set_autostart)
    hotkey_label = staticmethod(hotkey_label)
    capture_hotkey = staticmethod(capture_hotkey)

    def status(self):
        return state["status"]

    def lang(self):
        return LANGUAGES[state["lang"]]

    def toggle_lang(self):
        state["lang"] = (state["lang"] + 1) % len(LANGUAGES)
        set_status(state["status"])
        log(f"language -> {LANGUAGES[state['lang']]}")

    def save_config(self, cfg):
        save_config(cfg)
        if cfg.get("language") in LANGUAGES:
            state["lang"] = LANGUAGES.index(cfg["language"])
        restart_listener()  # apply hotkey change immediately, no app restart
        log("settings saved")

    def quit(self):
        if tray_icon is not None:
            tray_icon.stop()
        os._exit(0)


# ---------------- Main ----------------
def _mode() -> str:
    if "--no-ui" in sys.argv:
        return "headless"
    if "--classic" in sys.argv:
        return "classic"
    return "web"  # default: new pywebview design


def quit_app():
    if tray_icon is not None:
        tray_icon.stop()
    os._exit(0)


def _start_overlay() -> None:
    """Run the Tkinter status pill in its own thread with its own Tk loop.

    Kept separate from pywebview's main loop; all pill updates are marshalled
    onto this thread via root.after() (see StatusOverlay). Used in web mode,
    where the main window is pywebview but the overlay needs Tk transparency."""
    if not config.get("overlay", True):
        return

    def run():
        global overlay
        try:
            import tkinter as tk
            from ui import StatusOverlay
            root = tk.Tk()
            root.withdraw()
            overlay = StatusOverlay(root)
            set_status(state["status"])  # reflect current state (e.g. loading)
            root.mainloop()
        except Exception as e:
            overlay = None
            log(f"overlay unavailable ({e.__class__.__name__}: {e}) — running without pill")

    threading.Thread(target=run, daemon=True).start()


def _start_core() -> None:
    """Audio stream, model warm-up, hotkey listener — shared by all modes."""
    license_status()  # populate state["license"] before any dictation attempt

    def boot():
        try:
            # installed build ships without CUDA libs — fetch them once if this
            # machine has an NVIDIA GPU, then make them visible to ctranslate2
            if FROZEN and config.get("device") != "cpu":
                try:
                    import cuda_setup

                    def cuda_prog(done, total):
                        set_download(True, "Драйвери GPU", mb=done >> 20,
                                     total_mb=(total >> 20) if total else 0)

                    if cuda_setup.ensure_cuda(DATA_DIR, log, cuda_prog):
                        register_cuda_dlls()
                except Exception as e:
                    log(f"cuda provisioning skipped ({e.__class__.__name__}: {e})")
                finally:
                    set_download(False)
            # warm the model for the CURRENT language, not just the default en
            # one — otherwise the first Ukrainian dictation eats a ~3s load
            stop = threading.Event()
            threading.Thread(target=_watch_model_download,
                             args=("Модель розпізнавання", stop), daemon=True).start()
            try:
                state["model"] = model_for(LANGUAGES[state["lang"]])
            finally:
                stop.set()
                set_download(False)
            set_status("idle")
            log(f"ready. hold {hotkey_label(config['hotkey'])} = dictate "
                f"({LANGUAGES[state['lang']]})")
        except Exception as e:
            log(f"model load failed ({e.__class__.__name__}: {e}) — "
                f"dictation unavailable")
            set_status("idle")

    threading.Thread(target=boot, daemon=True).start()
    state["stream"] = None if config.get("mic_on_demand") else open_input_stream()
    restart_listener()


def main() -> None:
    global overlay
    ensure_single_instance()
    mode = _mode()

    if mode == "web":
        try:
            import webview_app
        except ImportError as e:
            log(f"pywebview unavailable ({e}); falling back to --classic")
            mode = "classic"

    if mode == "web":
        def on_open():
            win = state.get("webview_window")
            if win is not None:
                try:
                    win.show()
                except Exception:
                    pass
        start_tray(on_open=on_open, on_quit=quit_app)
        _start_overlay()
        _start_core()
        webview_app.run()  # blocks until window closed
        # closing the window quits the app (tray also offers Quit)
        quit_app()
        return

    if mode == "classic":
        import customtkinter as ctk
        from ui import StatusOverlay
        from app_gui import WhsprApp
        root = ctk.CTk()
        root.withdraw()
        overlay = StatusOverlay(root)
        ctx = AppContext()
        app = WhsprApp(root, ctx)
        start_tray(on_open=app.show, on_quit=quit_app)
        if not os.path.isfile(CONFIG_PATH):
            root.after(300, app.show)
        _start_core()
        try:
            root.mainloop()
        except KeyboardInterrupt:
            pass
        return

    # headless
    _start_core()
    try:
        _listener.join()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
