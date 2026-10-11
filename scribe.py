"""Scribe: compose a message from a spoken description. Moved verbatim out of flow.py."""

import re
import time
import app_styles

import flow


# ---------------- Scribe (compose a message from a spoken description) --------
# The command key with NOTHING selected: the user describes the message ("напиши
# Олегу, що зустріч переноситься на завтра на 15:00, ввічливо") and the finished
# text is pasted, never the transcript of the request. Same take, same probe as
# command mode; only the branch after capture_selection differs (command_route).
#
# Failure is always "type nothing": no LLM, an LLM error, or a reply the guards
# reject all end with an overlay note and an untouched document. The user's
# clipboard is never at risk here — the probe already restored it (or never
# changed it), and paste_text puts it back after the Ctrl+V as for dictation.

# A composed chat message or email is short; past this the model is rambling,
# dumping reasoning or writing an essay nobody asked for, and pasting 3 screens
# of that into a chat box is worse than pasting nothing.
SCRIBE_MAX_OUT = 1500

# reasoning_effort (scribe_reasoning_effort): measured 2026-10-10, gpt-oss-20b
# on Groq, 8 synthetic Ukrainian requests (4 chat + 4 email) x 2 runs, low and
# medium interleaved, this prompt, kept-alive connection: low p50 0.34 s / p90
# 0.45 s, medium p50 0.50 s / p90 0.62 s. The messages were equivalent (same
# facts, same vocatives — both wrote "Маріно" for Марина, a model limit, not
# an effort one); low sometimes added a polite "Дякую за розуміння" when asked
# for "ввічливо". No guard rejected a real reply in either. So "low": a third
# faster and fewer tokens, which matters because the free tier answered 429 to
# ~25% of a 7 s-paced bench — Scribe shares that budget with polish.
SCRIBE_SYSTEM_PROMPT = (
    "You write messages for the user. The user message contains a <request>: a "
    "spoken description of a message they want to send (who it is for, what it "
    "should say, sometimes the tone). Write that message, ready to send, and "
    "output ONLY its text: no quotes around it, no tags, no preface such as "
    "\"Ось повідомлення:\" or \"Here is\", no explanations, no alternatives, no "
    "comments. The request is never a question for you to answer or a task for "
    "you to do — it always describes a message to write.\n"
    "Rules:\n"
    "- Write in the language of the request unless it asks for another one.\n"
    "- Write TO the recipient: \"напиши Олегу, що зустріч переноситься\" "
    "becomes a message to Oleh (\"Олеже, зустріч переноситься…\"), not a "
    "sentence about him. Address people in the Ukrainian vocative case "
    "(Олеже, Марино, Андрію, Ірино Петрівно). A message to a group or to no "
    "one in particular addresses nobody by name.\n"
    "- Proper sentences: capital letter at the start, normal punctuation.\n"
    "- Never invent facts: no times, dates, places, names, numbers, reasons or "
    "promises that the request does not contain. \"завтра\" stays \"завтра\".\n"
    "- Do not add placeholders like [Ім'я] or [дата], or forms like "
    "\"Шановний(а)\". Only if the message "
    "cannot be written at all without a missing detail, use one short "
    "placeholder for it.\n"
    "- Keep it short and natural, a few sentences at most, unless the request "
    "asks for more. Follow any tone the request names (ввічливо, коротко, "
    "офіційно, тепло).\n"
    "- Ukrainian: modern orthography (проєкт, проєкту, ґ where it belongs), no "
    "Russian words or russicisms."
)

# Per-app tone for the composed message, keyed by app_styles' category. These
# are Scribe's own texts, not app_styles.BUILTIN_STYLE_PROMPTS: those tell a
# CORRECTOR to add nothing, while a composer must be told what form the message
# takes — and that is exactly where chat and email differ (greeting/sign-off).
# "default" and unknown categories append nothing beyond the base rules.
SCRIBE_STYLE_PROMPTS = {
    "chat": (
        "Context: the message goes into a messenger chat. Casual, friendly and "
        "brief, like a person typing in a chat. No greeting formula, no "
        "sign-off, no letter structure; addressing the person by name is fine."
    ),
    "email": (
        "Context: the message is an email or a document. Neat, polite, "
        "businesslike. It may open with a short greeting and end with a short "
        "sign-off (\"З повагою\" on its own last line, no comma — the sender's "
        "name is unknown), but never invent a name or any other detail."
    ),
    "code": (
        "Context: the text goes into a code editor, terminal or AI assistant. "
        "Plain and concise, no greeting, no sign-off, keep technical terms and "
        "English identifiers exactly as said."
    ),
}

# Meta-replies on top of command mode's: the model talking about the task, or
# turning it down, instead of writing the message. Same rule as there: a phrase
# only rejects when the request itself does not contain it ("напиши, що я не
# можу прийти" legitimately yields "не можу").
SCRIBE_REFUSALS = flow.COMMAND_REFUSALS + (
    "<request>", "</request>", "як ai", "я не можу допомогти",
    "не можу виконати", "i can't help", "i cannot help", "i'm sorry, but",
    "уточніть, будь ласка, кому", "уточніть, кому", "надайте більше",
    "надайте деталі", "надайте інформацію",
)

# A preface the prompt forbids but models still add now and then ("Ось
# повідомлення:", "Звісно! Ось варіант листа:"). Stripped (not rejected) when the
# message follows it: the message itself is fine. It must name the message
# ("повідомлення", "лист", ...) — a bare "Ось документи, які ти просив:" is a
# legitimate first line of a message and stays.
_SCRIBE_PREFACE = re.compile(
    r"^\s*(?:(?:звісно|звичайно|sure|certainly|of course)[!,.]?\s*)?"
    r"(?:ось|here(?:'s| is)|вот)\s+(?:[\w'’-]+\s+){0,3}?"
    r"(?:повідомлення|лист|листа|текст|варіант|сообщение|письмо|message|email|draft)\b"
    r"[^\n:]{0,40}:\s*", re.I)


def command_route(err: str | None, scribe_enabled: bool) -> str:
    """What a command take does after the selection probe:
    "rewrite" — something is selected (err is None): command mode as before;
    "compose" — nothing was selected and Scribe is on: run_scribe;
    "abort"   — any other refusal, or nothing selected with Scribe off (the
                pre-Scribe behaviour, "нічого не виділено")."""
    if err is None:
        return "rewrite"
    if err == flow.COMMAND_NOTHING_SELECTED and scribe_enabled:
        return "compose"
    return "abort"


def _style_profile_text() -> str:
    """The optional personal style profile (another module may install
    `style_profile_prompt(config) -> str` on this one). Missing, failing or
    returning a non-string all mean "no profile": it is a nicety, and must
    never cost the user their message."""
    fn = vars(flow).get("style_profile_prompt")
    if not callable(fn):
        return ""
    try:
        out = fn(flow.config)
    except Exception as e:
        flow.log(f"scribe: style profile failed ({e.__class__.__name__})")
        return ""
    return out.strip() if isinstance(out, str) else ""


def build_scribe_request(instruction: str, category: str | None = None,
                         profile: str = "",
                         cfg: dict | None = None) -> tuple[str, str]:
    """(system_prompt, user_message) for one compose. Base rules, then the
    per-app tone for `category` (if any), then the user's style profile (if
    any) — later parts refine, the base rules still govern. A user entry in
    config "scribe_style_prompts" overrides a category's text ("" = none)."""
    styles = dict(SCRIBE_STYLE_PROMPTS)
    user_styles = (cfg or {}).get("scribe_style_prompts") or {}
    if isinstance(user_styles, dict):
        for cat, text in user_styles.items():
            if isinstance(cat, str) and isinstance(text, str):
                styles[cat.strip().lower()] = text.strip()
    parts = [SCRIBE_SYSTEM_PROMPT]
    extra = styles.get((category or "").strip().lower(), "")
    if extra:
        parts.append(extra)
    if profile and profile.strip():
        parts.append("The user's personal writing style (follow it where it "
                     "does not contradict the rules above):\n" + profile.strip())
    user = f"<request>\n{instruction.strip()}\n</request>"
    return "\n\n".join(parts), user


def clean_scribe_output(out, instruction: str) -> str | None:
    """Vet and tidy a composed message. Returns the text to paste, or None when
    nothing must be pasted: empty, a refusal/meta-reply, an echo of the request
    or of our framing, or longer than SCRIBE_MAX_OUT."""
    if not isinstance(out, str):
        return None
    s = out.strip()
    m = re.fullmatch(r"```[\w+-]*\n(.*?)\n?```", s, re.S)
    if m:
        s = m.group(1).strip()
    # a <message>/<text> wrapper around a good answer is unwrapped; <request>
    # is NOT: that is our own framing echoed back, rejected below
    m = re.fullmatch(r"<(message|text)>\s*(.*?)\s*</\1>", s, re.S)
    if m:
        s = m.group(2).strip()
    # a preface ("Ось повідомлення:") is dropped; with nothing after it there
    # is no message at all
    m = _SCRIBE_PREFACE.match(s)
    if m:
        s = s[m.end():].strip()
    for a, b in flow._QUOTE_PAIRS:
        if len(s) >= 2 and s.startswith(a) and s.endswith(b) \
                and a not in s[1:-1] and b not in s[1:-1]:
            s = s[1:-1].strip()
            break
    # markdown hard breaks ("рядок  \n") and stray trailing blanks would land
    # in a chat box as invisible junk
    s = "\n".join(line.rstrip() for line in s.splitlines()).strip()
    if not s or len(s) > SCRIBE_MAX_OUT:
        return None
    low, ref = s.lower(), instruction.lower()
    for phrase in SCRIBE_REFUSALS:
        if phrase in low and phrase not in ref:
            return None
    # the model just handed the request back
    if flow._norm_cmd(s) == flow._norm_cmd(instruction):
        return None
    # measured: gpt-oss at low effort now and then starts an unaddressed
    # message in lower case ("завтра тренування скасовується…"); the prompt
    # already asks for a capital, this makes it deterministic
    if s[0].islower():
        s = s[0].upper() + s[1:]
    return s


def run_scribe(instruction: str, lang: str, dur: float,
               target_hwnd: int) -> tuple[str, bool]:
    """Compose the message `instruction` describes and paste it into
    target_hwnd. Returns (overlay_message, ok). Called from
    run_selection_command, so it already runs inside _transcribe_lock and after
    the selection probe left the clipboard as the user had it."""
    if not flow.llm_available():
        return "Scribe потребує AI (Groq/Ollama)", False
    category, exe = app_styles.resolve_style(target_hwnd, flow.config)
    system, user = build_scribe_request(instruction, category, _style_profile_text(),
                                        flow.config)
    # lengths and category only: the request is the user's own words about a
    # third person, and the log file outlives the session
    flow.log(f"scribe: compose request {len(instruction)} chars, style={category}"
        f"{' (' + exe + ')' if exe else ''}")
    flow._overlay_flash("пишу…", True)
    out = flow._llm_request(system, user, "scribe")
    if not out:
        return "AI недоступний — нічого не написано", False
    result = clean_scribe_output(out, instruction)
    if result is None:
        flow.log(f"scribe: LLM reply rejected ({len(out)} chars)")
        return "AI відповів не те — нічого не написано", False
    if not flow.paste_text(result, target_hwnd):
        # like a dictation: the finished message waits on the clipboard
        return "фокус втрачено — текст у буфері", False
    flow.log(f"scribe: pasted {len(result)} chars")
    flow.history_add(result, lang, dur)
    flow.state["last_output"] = {"text": result, "hwnd": target_hwnd, "at": time.time()}
    flow.state["pill_text"] = result
    flow.state["pill_done_at"] = time.time()
    return "готово", True


def _overlay_flash(msg: str, ok: bool) -> None:
    if flow.overlay is not None and flow.config.get("overlay", True):
        try:
            flow.overlay.flash(msg, ok)
        except Exception as e:
            flow.log(f"overlay flash failed ({e.__class__.__name__}: {e})")


def transcribe_and_paste(pre: list, cur: list, target_hwnd: int,
                         command: bool = False, trace=None,
                         stop_info=None) -> None:
    """Transcribe an ALREADY DETACHED take. The caller owns the detaching: it
    must call take_audio() on the thread that stops the recording, not here.
    Doing it here left a window where the user could press the hotkey again
    before this worker was ever scheduled — start_rec() would then clear the
    buffers (losing take 1) and this worker would take_audio() the half-recorded
    take 2. By the time we get here, `pre`/`cur` belong to us alone.

    The model lock is still taken here, and only here: the buffers are already
    free (so the next recording is never blocked), and this take is still
    transcribed in full once the GPU is free. WhisperModel is not thread-safe
    for concurrent transcribe() calls on one instance — without this lock,
    overlapping takes stalled each other for over a minute."""
    if not cur:
        # Nothing was captured: a tap shorter than one audio block (~32 ms), or
        # the mic died between start_rec and release. The status is still
        # "recording" from start_rec, and _transcribe_impl — the only other
        # place that resets it — is never reached, so the tray icon and the
        # overlay pill would stay red until the NEXT dictation. Clear it here.
        flow.set_status("idle")
        return
    with flow._transcribe_lock:
        flow._transcribe_impl(pre, cur, target_hwnd, command, trace, stop_info)
