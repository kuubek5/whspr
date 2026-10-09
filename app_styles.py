"""Per-app writing style for the LLM polish ("context-aware polish").

The same dictation wants different treatment depending on where it lands: a
Telegram message should stay casual and short, an email should come out neat,
and a prompt typed into a terminal or an AI coding assistant must not be
rephrased at all — "rename the fetch_user helper" turned into nicer prose is a
broken instruction. The window that will receive the paste is already known
(flow.stop_rec captures target_hwnd), so we map its process name to a style
category and APPEND that category's instruction to the corrector prompt.

Appending, not replacing, is deliberate: the core correction rules (don't
change word forms, never answer the text, return only the text) live in the
base prompt — shipped LLM_PROMPT or the user's own llm_prompt — and every style
must keep obeying them. The "default" category appends nothing, so an unknown
app gets byte-for-byte the prompt it got before this feature existed.

Everything here is pure data plus one ctypes lookup; it never raises, because a
failed lookup must degrade to "default", never to a lost dictation.
"""
import os
import ctypes

try:
    from ctypes import wintypes
    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Private WinDLL instances rather than ctypes.windll: setting argtypes on the
    # shared windll.user32 would change how flow.py's own calls marshal.
    _u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _u32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _u32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _u32.EnumChildWindows.argtypes = [wintypes.HWND, _ENUM_PROC, wintypes.LPARAM]
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
except (AttributeError, OSError):  # not Windows — resolver just returns ""
    _u32 = _k32 = None

# Enough to read the image path of any process, including elevated ones and
# most protected ones, without asking for rights we don't need.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

DEFAULT = "default"

# exe name (lower-case) -> category. Users extend/override this through the
# "app_styles" config key; their entries win, and "default" there switches a
# built-in app back to the plain prompt.
BUILTIN_APP_STYLES = {
    # chat: messengers
    "telegram.exe": "chat", "whatsapp.exe": "chat", "whatsapp.root.exe": "chat",
    "discord.exe": "chat", "slack.exe": "chat", "viber.exe": "chat",
    "signal.exe": "chat", "ms-teams.exe": "chat", "teams.exe": "chat",
    # email / documents
    "outlook.exe": "email", "olk.exe": "email", "hxoutlook.exe": "email",
    "thunderbird.exe": "email", "winword.exe": "email",
    # code / terminals. Claude desktop (claude.exe) is deliberately NOT here:
    # it is dictated to in plain sentences, and the conservative code style kept
    # recognition errors ("викинано" for "виконано") that the default polish fixes.
    "code.exe": "code", "cursor.exe": "code", "windsurf.exe": "code",
    "windowsterminal.exe": "code", "wt.exe": "code", "openconsole.exe": "code",
    "conhost.exe": "code", "cmd.exe": "code", "powershell.exe": "code",
    "pwsh.exe": "code", "idea64.exe": "code", "pycharm64.exe": "code",
    "webstorm64.exe": "code", "devenv.exe": "code", "zed.exe": "code",
    "wezterm-gui.exe": "code", "alacritty.exe": "code",
    "mintty.exe": "code",
}

# A browser hosts everything, so its exe says nothing; the tab title does.
# Checked in order, case-insensitive substring of the window title.
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
            "opera.exe", "vivaldi.exe", "arc.exe"}
BROWSER_TITLE_STYLES = [
    ("gmail", "email"), ("outlook", "email"), ("proton mail", "email"),
    ("google docs", "email"), ("документи google", "email"),
    ("telegram", "chat"), ("whatsapp", "chat"), ("discord", "chat"),
    ("slack", "chat"),
]

# Appended to the base corrector prompt. Written in Ukrainian like LLM_PROMPT,
# and each one restates "add nothing" because a style hint like "be neat" is
# exactly what tempts a model into inventing greetings and sign-offs.
BUILTIN_STYLE_PROMPTS = {
    "chat": (
        "Контекст: текст піде в месенджер (чат). Тон розмовний і короткий — "
        "не роби його офіційнішим. Не додавай привітань, підписів чи ввічливих "
        "формул. Пунктуацію змінюй мінімально: лише там, де без неї незрозуміло."
    ),
    "email": (
        "Контекст: текст піде в лист або документ. Розстав повну, акуратну "
        "пунктуацію й великі літери, чітко розділи речення. Тон охайний і "
        "нейтрально-діловий, але не додавай привітань, підписів чи слів, "
        "яких не було."
    ),
    "code": (
        "Контекст: текст піде в редактор коду, термінал або AI-асистента. "
        "НЕ перефразовуй і не переставляй слова. Виправляй лише очевидні збої "
        "розпізнавання та пунктуацію. Технічні терміни, англійські слова, назви "
        "файлів, команд, функцій і змінних залиш точно як є — те саме написання "
        "й регістр, без перекладу."
    ),
}

# Ukrainian labels for the read-only Settings list, in display order.
CATEGORY_LABELS = [
    ("chat", "Месенджери", "Розмовно й коротко, без привітань і підписів"),
    ("email", "Пошта й документи", "Акуратна пунктуація, охайний тон"),
    ("code", "Код і термінал", "Без перефразування — лише збої й пунктуація"),
]


def app_table(cfg: dict | None) -> dict:
    """Built-in exe->category map with the user's "app_styles" laid on top.
    Keys are lower-cased so "Telegram.exe" in config still matches."""
    table = dict(BUILTIN_APP_STYLES)
    user = (cfg or {}).get("app_styles") or {}
    if isinstance(user, dict):
        for exe, cat in user.items():
            if isinstance(exe, str) and isinstance(cat, str) and exe.strip():
                table[exe.strip().lower()] = cat.strip().lower() or DEFAULT
    return table


def prompt_table(cfg: dict | None) -> dict:
    """Built-in category->instruction map with the user's "style_prompts" on
    top. A user entry set to "" disables that category's addition."""
    table = dict(BUILTIN_STYLE_PROMPTS)
    user = (cfg or {}).get("style_prompts") or {}
    if isinstance(user, dict):
        for cat, text in user.items():
            if isinstance(cat, str) and isinstance(text, str):
                table[cat.strip().lower()] = text.strip()
    return table


def classify(exe: str, title: str = "", cfg: dict | None = None) -> str:
    """Category for a process name (+ window title for browsers)."""
    exe = (exe or "").strip().lower()
    if not exe:
        return DEFAULT
    table = app_table(cfg)
    if exe in table:
        return table[exe] or DEFAULT
    if exe in BROWSERS and title:
        t = title.lower()
        for needle, cat in BROWSER_TITLE_STYLES:
            if needle in t:
                return cat
    return DEFAULT


def compose_prompt(base: str, category: str | None, cfg: dict | None = None) -> str:
    """Base prompt plus the category's instruction. Unknown/default category,
    or one whose instruction is blank, returns `base` unchanged."""
    if not category or category == DEFAULT:
        return base
    extra = prompt_table(cfg).get(category, "")
    if not extra:
        return base
    return f"{base}\n\n{extra}"


def _exe_of_pid(pid: int) -> str:
    h = _k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return ""
        return os.path.basename(buf.value).lower()
    finally:
        _k32.CloseHandle(h)


def _pid_of(hwnd) -> int:
    pid = wintypes.DWORD(0)
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def window_app(hwnd) -> tuple[str, str]:
    """(exe name lower-case, window title) for a top-level window, or ("", "")
    on any failure. Never raises."""
    if not hwnd or _u32 is None:
        return "", ""
    try:
        n = _u32.GetWindowTextLengthW(hwnd)
        tbuf = ctypes.create_unicode_buffer(max(n, 0) + 1)
        _u32.GetWindowTextW(hwnd, tbuf, len(tbuf))
        title = tbuf.value
        own = _pid_of(hwnd)
        exe = _exe_of_pid(own) if own else ""
        if exe == "applicationframehost.exe":
            # Store (UWP) apps are drawn inside a frame owned by
            # ApplicationFrameHost; the real app is a child window from a
            # different process, so look one level down for it.
            found = []

            def cb(child, _):
                p = _pid_of(child)
                if p and p != own:
                    found.append(p)
                    return False
                return True
            _u32.EnumChildWindows(hwnd, _ENUM_PROC(cb), 0)
            if found:
                exe = _exe_of_pid(found[0]) or exe
        return exe, title
    except Exception:
        return "", ""


def resolve_style(hwnd, cfg: dict | None) -> tuple[str, str]:
    """(category, exe) for the paste target. Feature off or lookup failed ->
    ("default", ...), which leaves the prompt exactly as it was."""
    if not (cfg or {}).get("app_styles_enabled", True):
        return DEFAULT, ""
    try:
        exe, title = window_app(hwnd)
        return classify(exe, title, cfg), exe
    except Exception:
        return DEFAULT, ""


def describe(cfg: dict | None) -> list[dict]:
    """Read-only summary for the Settings list: each category with its apps
    (user overrides included) and whether browser tabs can land in it."""
    table = app_table(cfg)
    out = []
    for cat, label, hint in CATEGORY_LABELS:
        apps = sorted(exe for exe, c in table.items() if c == cat)
        web = [needle for needle, c in BROWSER_TITLE_STYLES if c == cat]
        out.append({"id": cat, "label": label, "hint": hint,
                    "apps": apps, "web": web})
    # categories a user invented in config get listed too, without a label
    known = {c for c, _, _ in CATEGORY_LABELS} | {DEFAULT}
    for cat in sorted(set(table.values()) - known):
        out.append({"id": cat, "label": cat, "hint": "",
                    "apps": sorted(e for e, c in table.items() if c == cat), "web": []})
    return out
