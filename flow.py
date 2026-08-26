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
import shutil
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


def prime_platform_cache() -> None:
    """Fill platform.uname()'s cache from cheap local calls.

    On Python 3.12 platform.uname() asks WMI for the Windows version, and a
    wedged WMI service makes that query hang forever. sounddevice calls
    platform.system() at import time, so whspr would hang on its very first
    import — before any logging existed to show why, and invisibly under
    pythonw. sys.getwindowsversion() reads the same facts from the PEB without
    touching WMI, so priming the cache keeps startup independent of it."""
    import platform
    if getattr(platform, "_uname_cache", None) is not None:
        return
    try:
        v = sys.getwindowsversion()
        # Windows 11 still reports major 10; the build number is the real tell
        release = "11" if (v.major == 10 and v.build >= 22000) else str(v.major)
        platform._uname_cache = platform.uname_result(
            system="Windows",
            node=os.environ.get("COMPUTERNAME", ""),
            release=release,
            version=f"{v.major}.{v.minor}.{v.build}",
            machine=os.environ.get("PROCESSOR_ARCHITECTURE", "AMD64"),
        )
    except Exception:
        pass  # non-Windows or a changed platform internal: let stdlib do it


prime_platform_cache()

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
# Local CT2 models the user can pick, fastest/lightest last. Systran hosts every
# plain size, but its large-v3-turbo repo 401s — turbo comes from the deepdml
# mirror. Each is downloaded on first use and cached by faster-whisper.
# "en" marks English-only weights: they are never used for Ukrainian.
MODELS = {
    "stock": {"repo": MODEL_NAME, "label": "Large v3 Turbo",
              "size": "1.5 GB", "note": "швидка, за замовчуванням"},
    "uk-ft": {"repo": "skypro1111/whisper-large-v3-turbo-ukrainian-ukraine-3percent-ct2",
              "label": "Large v3 Turbo UA", "size": "1.5 GB",
              "note": "донавчена на розмовній українській"},
    "large-v3": {"repo": "Systran/faster-whisper-large-v3", "label": "Large v3",
                 "size": "2.9 GB", "note": "найточніша, найповільніша"},
    "distil-large-v3": {"repo": "Systran/faster-distil-whisper-large-v3",
                        "label": "Distil Large v3", "size": "1.5 GB",
                        "note": "швидша за Large v3", "en": True},
    "medium": {"repo": "Systran/faster-whisper-medium", "label": "Medium",
               "size": "1.4 GB", "note": "компроміс точність/швидкість"},
    "small": {"repo": "Systran/faster-whisper-small", "label": "Small",
              "size": "465 MB", "note": "легка, слабший GPU"},
    "base": {"repo": "Systran/faster-whisper-base", "label": "Base",
             "size": "141 MB", "note": "дуже легка, помітно гірша якість"},
    "tiny": {"repo": "Systran/faster-whisper-tiny", "label": "Tiny",
             "size": "74 MB", "note": "найшвидша, найгірша якість"},
}
# key -> repo, kept under the old name for the classic GUI and saved configs
UK_MODELS = {k: v["repo"] for k, v in MODELS.items() if not v.get("en")}
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
    # weak mics record faint audio Whisper reads as silence. Quiet clips are
    # scaled up toward target_rms before transcription; max_gain caps the boost
    # so near-silent hiss isn't amplified into hallucinations.
    "target_rms": 0.06,
    "max_gain": 12.0,
    "beam_size": 5,
    "overlay": True,
    # mic input device name; "" = system default
    "input_device": "",
    # open the mic only while recording (removes the always-on tray mic
    # indicator, at the cost of pre-roll and a tiny start-up delay)
    "mic_on_demand": False,
    # mute other apps' audio while recording so playback doesn't bleed into the
    # mic; only sessions we muted are restored on release
    "mute_others": True,
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
    # turn dictated "кома"/"крапка"/"знак питання" into , . ?
    "spoken_punctuation": True,
    # fold spoken number words into digits: "триста п'ятдесят два" -> "352"
    "normalize_numbers": True,
    # act on spoken commands ("великими літерами", "переклади англійською")
    # that edit the previous dictation instead of typing the words
    "voice_commands": True,
    # hands-free: tap the hotkey to start, auto-stop after silence (or tap again)
    "hands_free": False,
    "silence_stop_s": 1.5,   # silence this long ends a hands-free take
    "max_utterance_s": 60,   # hard cap so a noisy mic can't record forever
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
# after a failed polish, stop trying for this long so a stopped Ollama or a bad
# API key doesn't add a connection timeout to every dictation
LLM_BACKOFF_S = 60
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
def llm_available() -> bool:
    mode = config.get("llm", "off")
    if mode == "groq":
        return bool(config.get("groq_api_key"))
    return mode == "ollama"


def _llm_request(system_prompt: str, user_text: str, label: str) -> str | None:
    """One chat call to the configured provider. Returns the reply, or None on
    any failure (with a shared back-off so an unreachable provider doesn't add a
    connection timeout to every request)."""
    mode = config.get("llm", "off")
    if mode == "off" or not user_text:
        return None
    if time.time() < state.get("llm_down_until", 0):
        return None
    try:
        if mode == "groq":
            if not config.get("groq_api_key"):
                return None
            url = "https://api.groq.com/openai/v1/chat/completions"
            model = config.get("groq_model", DEFAULTS["groq_model"])
            headers = {"Content-Type": "application/json",
                       "Authorization": f"Bearer {config['groq_api_key']}"}
        elif mode == "ollama":
            # 127.0.0.1, not localhost: the latter resolves to ::1 first and
            # doubles the wait when nothing is listening
            url = "http://127.0.0.1:11434/v1/chat/completions"
            model = config.get("ollama_model", DEFAULTS["ollama_model"])
            headers = {"Content-Type": "application/json"}
        else:
            return None
        payload = {"model": model, "temperature": 0.2, "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}]}
        req = urllib.request.Request(
            url, json.dumps(payload).encode("utf-8"), headers=headers)
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=15) as resp:
            out = json.load(resp)["choices"][0]["message"]["content"].strip()
        log(f"llm {label} ({mode}): {time.time() - t0:.2f}s")
        state["llm_down_until"] = 0
        return out or None
    except Exception as e:
        state["llm_down_until"] = time.time() + LLM_BACKOFF_S
        log(f"llm {label} failed ({e.__class__.__name__}: {e}); "
            f"skipping llm for {LLM_BACKOFF_S}s")
        return None


def llm_polish(text: str, lang: str) -> str:
    """Optional cleanup pass. Any failure returns the raw text."""
    return _llm_request(LLM_PROMPT, text, "polish") or text


# ---------------- Voice commands ----------------
def apply_replacements(text: str) -> str:
    for phrase, repl in config.get("replacements", {}).items():
        # eat surrounding punctuation/spaces so "Привіт. Новий рядок. Бувай"
        # becomes "Привіт.\nБувай"
        pattern = r"[,.!?]?\s*" + re.escape(phrase) + r"[,.!?]?\s*"
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return text.strip()


def _norm_apos(s: str) -> str:
    return s.replace("’", "'").replace("ʼ", "'").replace("`", "'")


# Ukrainian + English cardinals, common declensions folded in (Whisper emits
# whatever case was spoken). Values 1-900; scales handled separately.
_NUM_WORDS = {
    "нуль": 0, "zero": 0,
    "один": 1, "одна": 1, "одне": 1, "одно": 1, "один": 1, "one": 1,
    "два": 2, "дві": 2, "two": 2,
    "три": 3, "three": 3, "чотири": 4, "four": 4,
    "п'ять": 5, "five": 5, "шість": 6, "six": 6, "сім": 7, "seven": 7,
    "вісім": 8, "eight": 8, "дев'ять": 9, "nine": 9,
    "десять": 10, "ten": 10, "одинадцять": 11, "eleven": 11,
    "дванадцять": 12, "twelve": 12, "тринадцять": 13, "thirteen": 13,
    "чотирнадцять": 14, "fourteen": 14, "п'ятнадцять": 15, "fifteen": 15,
    "шістнадцять": 16, "sixteen": 16, "сімнадцять": 17, "seventeen": 17,
    "вісімнадцять": 18, "eighteen": 18, "дев'ятнадцять": 19, "nineteen": 19,
    "двадцять": 20, "twenty": 20, "тридцять": 30, "thirty": 30,
    "сорок": 40, "forty": 40, "п'ятдесят": 50, "fifty": 50,
    "шістдесят": 60, "sixty": 60, "сімдесят": 70, "seventy": 70,
    "вісімдесят": 80, "eighty": 80, "дев'яносто": 90, "ninety": 90,
    "сто": 100, "hundred": 100, "двісті": 200, "триста": 300, "чотириста": 400,
    "п'ятсот": 500, "шістсот": 600, "сімсот": 700, "вісімсот": 800,
    "дев'ятсот": 900,
}
_NUM_SCALE = {
    "тисяча": 1000, "тисячі": 1000, "тисяч": 1000, "thousand": 1000,
    "мільйон": 1_000_000, "мільйони": 1_000_000, "мільйонів": 1_000_000,
    "million": 1_000_000,
}
# lone "один/одна/one" is far more often the article "a/one" than a digit, so
# a single isolated such word is left as a word; inside a bigger number it counts
_LONE_KEEP = {"один", "одна", "одне", "одно", "one"}


def _num_key(tok: str) -> str:
    return _norm_apos(tok).lower()


def _is_num(tok: str) -> bool:
    k = _num_key(tok)
    return k in _NUM_WORDS or k in _NUM_SCALE


def _run_to_digits(keys: list[str]) -> str:
    total, current = 0, 0
    for k in keys:
        if k in _NUM_SCALE:
            total += (current or 1) * _NUM_SCALE[k]
            current = 0
        else:
            current += _NUM_WORDS[k]
    return str(total + current)


def normalize_numbers(text: str) -> str:
    """Fold spoken number words into digits: "триста п'ятдесят два" -> "352",
    "дві тисячі двадцять чотири" -> "2024". A run of number words joined only by
    single spaces becomes one number; anything else (punctuation, other words)
    breaks the run and passes through untouched."""
    if not config.get("normalize_numbers", True) or not text:
        return text
    # apostrophe kept inside words so "п'ять" stays one token; \W-runs (spaces,
    # punctuation) are tokens too, so original spacing survives verbatim
    tokens = re.findall(r"[^\W_]+(?:['][^\W_]+)*|\W+|_", _norm_apos(text))
    out, i, n = [], 0, len(tokens)
    while i < n:
        if _is_num(tokens[i]):
            keys, j = [_num_key(tokens[i])], i + 1
            while j + 1 < n and tokens[j].isspace() and " " in tokens[j] \
                    and _is_num(tokens[j + 1]):
                keys.append(_num_key(tokens[j + 1]))
                j += 2
            # a single lone article-like "один" stays a word
            if len(keys) == 1 and keys[0] in _LONE_KEEP:
                out.append(tokens[i])
            elif len(keys) >= 2 and all(_NUM_WORDS.get(k, 99) < 10 for k in keys):
                # a run of single digits is a sequence (code/phone/pin/year read
                # digit by digit), not a sum: "три чотири п'ять" -> "345", not 12
                out.append("".join(str(_NUM_WORDS[k]) for k in keys))
            else:
                # has a ten/hundred/thousand word -> compose arithmetically:
                # "триста п'ятдесят два" -> 352, "дві тисячі" -> 2000
                out.append(_run_to_digits(keys))
            i = j
        else:
            out.append(tokens[i])
            i += 1
    return "".join(out)


# Spoken words -> punctuation, longest phrase first so "крапка з комою" wins
# over "крапка". Whisper often already writes . and , ; this turns the words a
# user says out loud ("привіт кома як справи") into the mark instead.
# Only phrases unlikely to appear as ordinary dictated words. Deliberately
# omitted because they collide with common speech: "кому" (dative of "хто"),
# "крапку" (idiom "поставити крапку"), English "period"/"colon"/"dash". The
# feature is a toggle, so a user who needs even these literally can switch it off.
SPOKEN_PUNCT = [
    ("крапка з комою", ";"),
    ("знак питання", "?"), ("знак оклику", "!"),
    ("двокрапка", ":"), ("тире", " — "),
    ("три крапки", "…"), ("багатокрапка", "…"),
    ("кома", ","),
    ("крапка", "."),
    # English, for en dictation — multi-word forms only, to avoid common nouns
    ("semicolon", ";"), ("question mark", "?"), ("exclamation mark", "!"),
    ("ellipsis", "…"),
    ("comma", ","), ("full stop", "."),
]
_SENTENCE_END = ".!?…"


def apply_spoken_punctuation(text: str) -> str:
    """Turn dictated punctuation words into marks with correct spacing.

    "привіт кома як справи знак питання" -> "привіт, як справи?". Spacing is
    fixed up afterwards so marks hug the previous word and are followed by one
    space, which is why this can't reuse the freeform replacements pass."""
    if not config.get("spoken_punctuation", True) or not text:
        return text
    for phrase, mark in SPOKEN_PUNCT:
        # \b around a Cyrillic phrase works: in Python 3 \w is Unicode by default
        text = re.sub(r"\s*\b" + re.escape(phrase) + r"\b\s*", mark,
                      text, flags=re.IGNORECASE)
    # tighten: no space before a mark, exactly one space after it
    text = re.sub(r"\s+([,;:!?.…])", r"\1", text)
    # collapse duplicates: Whisper may punctuate AND transcribe the spoken word,
    # so "готово. крапка" -> "готово. ." -> "готово."
    text = re.sub(r"([,;:!?.…])(?:\s*\1)+", r"\1", text)
    text = re.sub(r"([,;:!?.…])(?=[^\s\d])", r"\1 ", text)  # keep 3.14 intact
    text = re.sub(r"[ \t]{2,}", " ", text)
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


# ---------------- Model library ----------------
# Models are pulled on demand from the Models page instead of being bundled or
# silently fetched mid-dictation: a 3 GB surprise download while the user waits
# for their first transcript is worse than an explicit button.
def _hf_cache() -> str:
    try:
        from huggingface_hub import constants
        return constants.HF_HUB_CACHE
    except Exception:
        return os.environ.get("HF_HUB_CACHE") or os.path.join(
            os.path.expanduser("~"), ".cache", "huggingface", "hub")


def _repo_cache_dir(repo: str) -> str:
    """Where huggingface_hub keeps a repo: <cache>/models--org--name."""
    return os.path.join(_hf_cache(), "models--" + repo.replace("/", "--"))


def model_installed(repo: str) -> bool:
    d = _repo_cache_dir(repo)
    # a bare dir can linger after a failed pull; require actual weights
    return os.path.isdir(d) and _dir_size_mb(d) > 20


def models_status() -> list[dict]:
    """Registry plus what is actually on disk, for the Models page."""
    active = config.get("model_uk", "stock")
    out = []
    for key, spec in MODELS.items():
        repo = spec["repo"]
        installed = model_installed(repo)
        out.append({
            "id": key, "label": spec["label"], "note": spec.get("note", ""),
            "size": spec["size"], "en": spec.get("en", False), "repo": repo,
            "installed": installed, "active": key == active,
            # real footprint: on Windows the cache keeps blobs *and* snapshot
            # copies, so this runs well above the advertised download size
            "diskMb": _dir_size_mb(_repo_cache_dir(repo)) if installed else 0,
        })
    return out


def download_model(key: str) -> dict:
    """Fetch a model in the background. Returns immediately; progress shows up
    in state['download'] the same way the first-run model pull does."""
    spec = MODELS.get(key)
    if spec is None:
        return {"ok": False, "error": "невідома модель"}
    if state.get("downloading"):
        return {"ok": False, "error": "вже качається інша модель"}
    repo = spec["repo"]
    if model_installed(repo):
        return {"ok": True, "already": True}

    def run():
        state["downloading"] = key
        state["download_error"] = None  # clear any error from a previous attempt
        stop = threading.Event()
        threading.Thread(target=_watch_model_download,
                         args=(spec["label"], stop), daemon=True).start()
        try:
            from huggingface_hub import snapshot_download
            snapshot_download(repo_id=repo)
            log(f"downloaded {repo}")
            ensure_tokenizer(repo)  # repair repos that ship without one
        except Exception as e:
            log(f"download failed for {repo} ({e.__class__.__name__}: {e})")
            state["download_error"] = str(e)
        finally:
            stop.set()
            set_download(False)
            state["downloading"] = None

    threading.Thread(target=run, daemon=True).start()
    return {"ok": True}


def delete_model(key: str) -> dict:
    """Remove a downloaded model's cache directory to reclaim disk."""
    spec = MODELS.get(key)
    if spec is None:
        return {"ok": False, "error": "невідома модель"}
    if key == config.get("model_uk", "stock"):
        # deleting the active model would break the next dictation
        return {"ok": False, "error": "спершу оберіть іншу активну модель"}
    if spec["repo"] == MODEL_NAME:
        # the default is the universal fallback: model_name_for() and auto-lang
        # drop to it, so deleting it would trigger a silent 1.5 GB re-download
        # mid-dictation under the model lock
        return {"ok": False, "error": "базову модель видалити не можна"}
    d = _repo_cache_dir(spec["repo"])
    # only ever delete inside the HF cache, and only a dir we generated the
    # name for — never a path that arrived from the UI
    if not os.path.isdir(d) or os.path.dirname(d) != _hf_cache():
        return {"ok": False, "error": "не знайдено на диску"}
    try:
        shutil.rmtree(d)
        state["models"].pop(spec["repo"], None)  # drop any cached instance
        log(f"deleted {spec['repo']}")
        return {"ok": True}
    except Exception as e:
        log(f"delete failed for {spec['repo']} ({e.__class__.__name__}: {e})")
        return {"ok": False, "error": str(e)}


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


STATUS_COLORS = {"idle": (120, 120, 128), "recording": (229, 72, 77),
                 "processing": (240, 180, 41), "loading": (100, 100, 220)}


def _icon_path() -> str:
    """whspr.ico next to the source, or inside the PyInstaller bundle."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "whspr.ico")


def tray_image(status: str):
    """App icon with a status dot in the corner. Falls back to a bare dot if the
    icon file is missing, so the tray never fails to appear — without it there
    is no way to reopen or quit the app."""
    from PIL import Image, ImageDraw
    color = STATUS_COLORS.get(status, STATUS_COLORS["idle"])
    size = 64
    try:
        img = Image.open(_icon_path()).convert("RGBA").resize(
            (size, size), Image.LANCZOS)
    except Exception:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse((8, 8, 56, 56), fill=color)
        return img
    # status dot, bottom-right, with a transparent gap so it reads on any theme
    d = ImageDraw.Draw(img)
    r = size // 3
    box = (size - r - 2, size - r - 2, size - 2, size - 2)
    d.ellipse((box[0] - 3, box[1] - 3, box[2] + 3, box[3] + 3), fill=(0, 0, 0, 0))
    d.ellipse(box, fill=color)
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


def force_quit() -> None:
    """Quit for real, even if the tray is wedged.

    Quit is normally triggered from the tray menu, whose callback runs on
    pystray's own thread. Calling icon.stop() from inside that callback can
    block forever on Windows, which used to strand the app: the window was
    already hidden to the tray, so a stuck stop() left no way out but Task
    Manager. The watchdog fires the exit regardless of whether stop() returns."""
    def watchdog():
        time.sleep(1.5)
        log("tray shutdown hung — forcing exit")
        os._exit(0)

    threading.Thread(target=watchdog, daemon=True).start()
    duck_others(False)  # never leave other apps muted behind us
    try:
        if tray_icon is not None:
            tray_icon.stop()
    except Exception as e:
        log(f"tray stop failed ({e.__class__.__name__}: {e})")
    os._exit(0)


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


def _snapshot_dir(repo: str) -> str:
    """Newest snapshot dir for a cached repo, or "" if it isn't downloaded."""
    snaps = os.path.join(_repo_cache_dir(repo), "snapshots")
    if not os.path.isdir(snaps):
        return ""
    dirs = [os.path.join(snaps, d) for d in os.listdir(snaps)]
    dirs = [d for d in dirs if os.path.isdir(d)]
    return max(dirs, key=os.path.getmtime) if dirs else ""


def ensure_tokenizer(repo: str) -> None:
    """Give a model its tokenizer.json if the upstream repo forgot to ship one.

    Some community CT2 conversions (the Ukrainian fine-tune among them) publish
    model.bin without tokenizer.json. faster-whisper then silently falls back to
    openai/whisper-tiny's tokenizer, whose vocabulary is 51865 against
    large-v3's 51866 — off by exactly one token.

    Plain transcription survives that shift, which is what makes it so easy to
    miss. initial_prompt and hotwords do not: they get encoded to wrong ids and
    poison the decoder, so the model returns punctuation, digit soup, or
    nothing. whspr always passes initial_prompt for Ukrainian, so the fine-tune
    looked completely deaf while the stock model worked.

    The default (large-v3 turbo, vocab 51866) is only a valid donor for another
    large-v3 model. medium/small/base/tiny use a 51865 vocab, so the tokenizer
    must NOT be lent across sizes — we copy only when vocabulary.json matches."""
    if repo == MODEL_NAME:
        return
    snap = _snapshot_dir(repo)
    if not snap or os.path.isfile(os.path.join(snap, "tokenizer.json")):
        return
    src_snap = _snapshot_dir(MODEL_NAME)
    src = os.path.join(src_snap, "tokenizer.json") if src_snap else ""
    if not src or not os.path.isfile(src):
        log(f"{repo} ships no tokenizer.json and the default model isn't "
            f"downloaded to lend one — prompts/hotwords will misbehave")
        return
    if _vocab_size(snap) != _vocab_size(src_snap):
        log(f"{repo} has a different vocabulary than the default model — not "
            f"lending an incompatible tokenizer")
        return
    try:
        shutil.copyfile(src, os.path.join(snap, "tokenizer.json"))
        log(f"supplied missing tokenizer.json to {repo}")
    except OSError as e:
        log(f"could not supply tokenizer for {repo} ({e.__class__.__name__}: {e})")


def _vocab_size(snapshot_dir: str) -> int:
    """Token count from a CT2 model's vocabulary.json (-1 if unreadable). Used to
    confirm two models share a vocabulary before lending a tokenizer."""
    path = os.path.join(snapshot_dir, "vocabulary.json") if snapshot_dir else ""
    try:
        with open(path, encoding="utf-8") as f:
            return len(json.load(f))
    except Exception:
        return -1


def _load_model_locked(name: str) -> WhisperModel:
    if name in state["models"]:
        return state["models"][name]
    ensure_tokenizer(name)
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


def model_name_for(lang: str) -> str:
    """Resolve the picked model's repo id for a language.

    One picker drives both languages, with two guards: an English-only model
    never handles Ukrainian, and the Ukrainian fine-tune never handles English.
    Either mismatch — or a stale key from an older config — falls back to the
    multilingual default."""
    key = config.get("model_uk", "stock")
    spec = MODELS.get(key)
    if spec is None:
        return MODEL_NAME
    if lang == "uk" and spec.get("en"):
        return MODEL_NAME
    if lang != "uk" and key == "uk-ft":
        return MODEL_NAME
    return spec["repo"]


def model_for(lang: str) -> WhisperModel:
    return load_model(model_name_for(lang))


def capitalize_sentences(text: str) -> str:
    # uk fine-tune tends to lowercase sentence starts
    return re.sub(
        r"(^|[.!?]\s+)([а-яґєіїa-z])",
        lambda m: m.group(1) + m.group(2).upper(),
        text,
    )


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
        log(f"audio session enumeration failed ({e.__class__.__name__}: {e})")


def duck_others(mute: bool) -> None:
    """Mute other apps' audio while dictating so playback doesn't bleed into the
    mic (or into the user's ears). Restores only what we muted."""
    # gate only the mute path on the setting: an unmute must always run, or
    # toggling the option off mid-recording would leave apps muted forever
    if mute and not config.get("mute_others", True):
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
                log(f"muted {len(hit)} app(s) while recording")
        else:
            if not _ducked_pids:
                return
            for pid, vol in _audio_sessions():
                if pid in _ducked_pids:
                    vol.SetMute(0, None)
            log(f"unmuted {len(_ducked_pids)} app(s)")
            _ducked_pids = set()
    except Exception as e:
        log(f"audio ducking failed ({e.__class__.__name__}: {e})")


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
# ---------------- Voice commands ----------------
# A spoken command edits the LAST thing whspr typed: it backspaces over that text
# and types the corrected version. It fires only when the WHOLE utterance matches
# a known trigger, so ordinary dictation is never mistaken for a command. Editing
# targets the last output in the same window; if the user has since typed or moved
# the caret, the command is refused rather than risking a wrong-place edit.
def _cmd_upper(t: str) -> str:
    return t.upper()


def _cmd_lower(t: str) -> str:
    return t.lower()


def _cmd_capitalize(t: str) -> str:
    s = t.lstrip()
    return s[:1].upper() + s[1:] if s else t


# (triggers, kind, payload). kind: "edit" fn(text)->text | "delete" | "llm" instruction
VOICE_COMMANDS = [
    (("великими літерами", "усе великими", "капсом", "uppercase", "caps"),
     "edit", _cmd_upper),
    (("маленькими літерами", "з малої літери", "lowercase"),
     "edit", _cmd_lower),
    (("з великої літери", "з великої букви", "capitalize"),
     "edit", _cmd_capitalize),
    (("видали останнє", "видали це", "скасуй останнє", "скасуй це", "стерти",
      "прибери це", "delete that", "scratch that", "undo that"),
     "delete", None),
    (("переклади англійською", "translate to english"), "llm",
     "Translate the text to English. Return only the translation, nothing else."),
    (("переклади українською", "translate to ukrainian"), "llm",
     "Translate the text to Ukrainian. Return only the translation, nothing else."),
    (("перепиши формально", "зроби формальним", "make it formal"), "llm",
     "Rewrite the text in a formal, professional tone. Keep the original "
     "language. Return only the rewritten text."),
    (("коротше", "скороти", "make it shorter", "shorten"), "llm",
     "Make the text more concise while keeping its meaning and language. "
     "Return only the result."),
    (("виправ помилки", "виправ граматику", "fix grammar"), "llm",
     "Fix grammar, spelling and punctuation. Keep the language, meaning and "
     "style. Return only the corrected text."),
]


def _norm_cmd(s: str) -> str:
    return re.sub(r"[\s.,!?…]+", " ", _norm_apos(s).lower()).strip()


_voice_lookup: dict | None = None


def match_voice_command(transcript: str):
    """Return (kind, payload) if the whole utterance is a command, else None."""
    global _voice_lookup
    if not config.get("voice_commands", True) or not transcript:
        return None
    if _voice_lookup is None:
        _voice_lookup = {}
        for triggers, kind, payload in VOICE_COMMANDS:
            for t in triggers:
                _voice_lookup[_norm_cmd(t)] = (kind, payload)
    return _voice_lookup.get(_norm_cmd(transcript))


def _send_backspaces(n: int) -> None:
    bs = keyboard.Key.backspace
    for _ in range(n):
        kb.press(bs)
        kb.release(bs)


def run_voice_command(kind, payload, target_hwnd: int) -> tuple[str | None, bool]:
    """Execute a matched command against state['last_output']. Returns
    (message_for_overlay, ok)."""
    last = state.get("last_output")
    if not last or not last.get("text"):
        return "нема що змінити", False
    # refuse if the caret is likely elsewhere now: different window than we typed into
    if last.get("hwnd") and target_hwnd and last["hwnd"] != target_hwnd:
        return "команда скасована — інше вікно", False
    old = last["text"]
    if target_hwnd and user32.GetForegroundWindow() != target_hwnd:
        user32.SetForegroundWindow(target_hwnd)
        time.sleep(0.15)
        if user32.GetForegroundWindow() != target_hwnd:
            return "команда скасована — вікно втрачено", False

    if kind == "delete":
        _send_backspaces(len(old))
        state["last_output"] = None
        return "видалено", True

    if kind == "edit":
        new = payload(old)
    else:  # llm
        if not llm_available():
            return "команда потребує LLM (Groq/Ollama)", False
        new = _llm_request(
            "You transform dictated text on command. Output ONLY the result "
            "text with no quotes, labels or explanation.\n" + payload, old, "command")
        if not new:
            return "LLM недоступний", False
    if new == old:
        return old, True
    _send_backspaces(len(old))
    # the old text is already deleted; if the paste can't land, say so and keep
    # last_output pointing at the new text (which is now on the clipboard) rather
    # than reporting success over a window that just ate the original
    pasted = paste_text(new, target_hwnd)
    state["last_output"] = {"text": new, "hwnd": target_hwnd, "at": time.time()}
    if not pasted:
        return "фокус втрачено — текст у буфері", False
    return new, True


def transcribe_and_paste(target_hwnd: int) -> None:
    set_status("processing")
    done_msg, ok = None, True
    try:
        if not chunks:
            return
        # measure what the user actually said, separately from the pre-roll:
        # in mic-on-demand mode the stream is closed between recordings, so
        # pre_roll is empty and a combined threshold would silently swallow
        # every phrase shorter than MIN_DURATION_S + PRE_ROLL_S
        spoken = sum(len(c) for c in chunks) / SAMPLE_RATE
        audio = np.concatenate(list(pre_roll) + chunks).flatten().astype(np.float32)
        chunks.clear()
        dur = len(audio) / SAMPLE_RATE
        if spoken < MIN_DURATION_S:
            return
        # cheap silence gate instead of Silero VAD: onnxruntime import hangs
        # for minutes on this machine, and push-to-talk audio has speech anyway
        rms = float(np.sqrt(np.mean(audio**2)))
        log(f"level rms={rms:.4f} (threshold {config['rms_threshold']})")
        if rms < config["rms_threshold"]:
            log(f"skipped: too quiet (rms={rms:.4f})")
            done_msg, ok = "тиша", False
            return
        # weak mics record at ~0.01 RMS. That clears the silence gate but is
        # still too faint for Whisper, which then returns an empty transcript.
        # Scale up to a healthy target so quiet speech transcribes. Cap the gain
        # so a near-silent clip of pure hiss isn't blown up into hallucinations.
        target_rms = config.get("target_rms", 0.06)
        if 0 < rms < target_rms:
            gain = min(target_rms / rms, config.get("max_gain", 12.0))
            audio = np.clip(audio * gain, -1.0, 1.0)
            log(f"boosted x{gain:.1f} -> rms {float(np.sqrt(np.mean(audio**2))):.4f}")
        hotwords = " ".join(
            t.strip() for t in re.split(r"[,\n]", config.get("dictionary", "")) if t.strip()
        ) or None
        t0 = time.time()
        # auto language: let Whisper detect instead of the manual F10 choice.
        # Detection needs the multilingual stock model and no Ukrainian prompt
        # bias, so auto mode trades the uk fine-tune for hands-off language.
        auto = config.get("auto_lang", False)
        if auto:
            model = load_model(MODEL_NAME)
            tr_lang, initial_prompt = None, None
        else:
            lang = LANGUAGES[state["lang"]]
            model = model_for(lang)
            tr_lang = lang
            initial_prompt = UK_INITIAL_PROMPT if lang == "uk" else None
        segments, info = model.transcribe(
            audio, language=tr_lang, vad_filter=False,
            beam_size=config["beam_size"], hotwords=hotwords,
            initial_prompt=initial_prompt,
            condition_on_previous_text=False,
            # anti-hallucination guards that are OFF by default in faster-whisper.
            # The temperature fallback and compression/no-speech thresholds are
            # already on by default; these three are the ones that were not:
            #   no_repeat_ngram_size — blocks "4 4 4 4 4" / "піп піп піп" loops
            #   repetition_penalty   — discourages the model repeating itself
            #   hallucination_silence_threshold — drops text invented over gaps
            #   (needs word_timestamps to locate those silent spans)
            no_repeat_ngram_size=3,
            repetition_penalty=1.1,
            word_timestamps=True,
            hallucination_silence_threshold=2.0,
        )
        if auto:
            # keep the detected language if it's one we support, else stay put
            lang = info.language if info.language in LANGUAGES else LANGUAGES[state["lang"]]
            state["lang"] = LANGUAGES.index(lang)
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
        # a whole-utterance command edits the previous dictation instead of
        # typing new text; checked before normalization so triggers match cleanly
        cmd = match_voice_command(text)
        if cmd:
            log(f"voice command: {text!r}")
            done_msg, ok = run_voice_command(cmd[0], cmd[1], target_hwnd)
            return
        # deterministic passes first, so the LLM (if any) sees clean digits and
        # marks instead of spelled-out numbers and dictated "кома"/"крапка"
        text = normalize_numbers(text)
        text = apply_spoken_punctuation(text)
        text = llm_polish(text, lang)
        text = apply_replacements(text)
        text = capitalize_sentences(text)
        history_add(text, lang, dur)
        pasted = paste_text(text, target_hwnd)
        done_msg, ok = (text, True) if pasted else ("фокус втрачено — текст у буфері", False)
        state["pill_text"] = text
        state["pill_done_at"] = time.time()
        # remember what we typed and where, so a follow-up voice command can edit it
        if pasted:
            state["last_output"] = {"text": text, "hwnd": target_hwnd, "at": time.time()}
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
        duck_others(True)
        set_status("recording")
        log("recording...")

    def stop_rec():
        if not state["recording"]:
            return
        state["recording"] = False
        # restore playback now: no reason to keep other apps silent through
        # transcription, which runs on its own thread below
        duck_others(False)
        hwnd = user32.GetForegroundWindow()
        threading.Thread(target=transcribe_and_paste, args=(hwnd,), daemon=True).start()
        if config.get("mic_on_demand"):
            close_stream()

    def silence_watch():
        """Hands-free: stop recording after a stretch of silence. The threshold
        is a fraction of the loudest level seen this take, so it adapts to the
        mic instead of relying on a fixed cutoff. Auto-stop is only armed once
        the user has actually spoken, so it never fires on the opening pause."""
        time.sleep(0.3)  # let the stream fill before judging levels
        peak, silent_since, t_start = 0.0, None, time.time()
        gap = config.get("silence_stop_s", 1.5)
        hard_max = config.get("max_utterance_s", 60)
        while state["recording"]:
            lvl = state.get("input_level", 0.0)
            peak = max(peak, lvl)
            spoke = peak > 0.015  # armed only after real speech
            floor = max(0.008, peak * 0.2)
            if spoke and lvl < floor:
                silent_since = silent_since or time.time()
                if time.time() - silent_since >= gap:
                    log("hands-free: silence -> auto stop")
                    stop_rec()
                    return
            else:
                silent_since = None
            if time.time() - t_start >= hard_max:
                log(f"hands-free: {hard_max}s cap -> auto stop")
                stop_rec()
                return
            time.sleep(0.1)

    def toggle_hands_free():
        # debounce key auto-repeat and accidental double taps
        now = time.time()
        if now - state.get("hf_last_toggle", 0) < 0.4:
            return
        state["hf_last_toggle"] = now
        if state["recording"]:
            stop_rec()
        else:
            start_rec()
            if state["recording"]:
                threading.Thread(target=silence_watch, daemon=True).start()

    def on_press(key):
        tok = canon(key)
        # auto-repeat re-fires on_press for a held key with no on_release in
        # between; a real new keystroke isn't in `pressed` yet. Only a fresh
        # completing keystroke should toggle, else holding the key cycles it.
        fresh = tok not in pressed
        pressed.add(tok)
        if required and required <= pressed and fresh:
            if config.get("hands_free"):
                toggle_hands_free()
            elif not state["recording"]:
                start_rec()
        elif lang_key and lang_key <= pressed and tok in lang_key and not (lang_key & MODS_SET):
            # simple lang toggle only for non-combo lang key (avoid double-fire)
            state["lang"] = (state["lang"] + 1) % len(LANGUAGES)
            set_status(state["status"])
            log(f"language -> {LANGUAGES[state['lang']]}")

    def on_release(key):
        tok = canon(key)
        # hold-to-talk stops on release; hands-free ignores release (tap toggles)
        if not config.get("hands_free") and state["recording"] and tok in required:
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
    MODELS = MODELS
    model_installed = staticmethod(model_installed)
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
        force_quit()


# ---------------- Main ----------------
def _mode() -> str:
    if "--no-ui" in sys.argv:
        return "headless"
    if "--classic" in sys.argv:
        return "classic"
    return "web"  # default: new pywebview design


def quit_app():
    force_quit()


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
