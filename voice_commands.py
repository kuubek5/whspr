"""Voice commands and snippets: matching a spoken command and running it. Moved verbatim out of flow.py."""

import re
import time
from pynput import keyboard
import text_fixes

import flow


# ---------------- Voice commands ----------------
# A spoken command edits the LAST thing KuubWave typed: it backspaces over that text
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
    return re.sub(r"[\s.,!?…]+", " ", flow._norm_apos(s).lower()).strip()


_voice_lookup: dict | None = None


def match_voice_command(transcript: str):
    """Return (kind, payload) if the whole utterance is a command, else None."""
    global _voice_lookup
    if not flow.config.get("voice_commands", True) or not transcript:
        return None
    if _voice_lookup is None:
        _voice_lookup = {}
        for triggers, kind, payload in VOICE_COMMANDS:
            for t in triggers:
                _voice_lookup[_norm_cmd(t)] = (kind, payload)
    return _voice_lookup.get(_norm_cmd(transcript))


def match_snippet(text: str):
    """(trigger, body) if this whole take is a saved snippet trigger, else None.

    Precedence against voice commands: a snippet trigger the user typed in
    EXACTLY wins over a built-in command with the same words — it is their own,
    deliberate choice. But the fuzzy fallback is switched off whenever the take
    is a built-in voice command, so a near-miss snippet can never steal
    "видали це" or "капсом"."""
    if not flow.config.get("snippets_enabled", True):
        return None
    snippets = flow.config.get("snippets") or {}
    if not snippets:
        return None
    fuzzy = match_voice_command(text) is None
    return text_fixes.match_snippet(text, snippets, fuzzy=fuzzy)


def run_snippet(trigger: str, body: str, lang: str, dur: float,
                target_hwnd: int) -> tuple[str, bool]:
    """Paste a snippet body exactly as stored. Every text pass (numbers, spoken
    punctuation, LLM, replacements, capitalisation, per-app style) is skipped on
    purpose: the user wrote this block by hand and wants it byte for byte."""
    flow.log(f"snippet: {trigger!r} ({len(body)} chars)")
    flow.history_add(body, lang, dur)
    pasted = flow.paste_text(body, target_hwnd)
    flow.state["pill_text"] = body
    flow.state["pill_done_at"] = time.time()
    if not pasted:
        return "фокус втрачено — текст у буфері", False
    # so "видали це" / "капсом" can act on the snippet like on any dictation
    flow.state["last_output"] = {"text": body, "hwnd": target_hwnd, "at": time.time()}
    return body, True


def _send_backspaces(n: int) -> None:
    bs = keyboard.Key.backspace
    for _ in range(n):
        flow.kb.press(bs)
        flow.kb.release(bs)


def run_voice_command(kind, payload, target_hwnd: int) -> tuple[str | None, bool]:
    """Execute a matched command against state['last_output']. Returns
    (message_for_overlay, ok)."""
    last = flow.state.get("last_output")
    if not last or not last.get("text"):
        return "нема що змінити", False
    # refuse if the caret is likely elsewhere now: different window than we typed into
    if last.get("hwnd") and target_hwnd and last["hwnd"] != target_hwnd:
        return "команда скасована — інше вікно", False
    old = last["text"]
    if target_hwnd and flow.user32.GetForegroundWindow() != target_hwnd:
        flow.user32.SetForegroundWindow(target_hwnd)
        time.sleep(0.15)
        if flow.user32.GetForegroundWindow() != target_hwnd:
            return "команда скасована — вікно втрачено", False

    if kind == "delete":
        flow._send_backspaces(len(old))
        flow.state["last_output"] = None
        return "видалено", True

    if kind == "edit":
        new = payload(old)
    else:  # llm
        if not flow.llm_available():
            return "команда потребує LLM (Groq/Ollama)", False
        new = flow._llm_request(
            "You transform dictated text on command. Output ONLY the result "
            "text with no quotes, labels or explanation.\n" + payload, old, "command")
        if not new:
            return "LLM недоступний", False
    if new == old:
        return old, True
    flow._send_backspaces(len(old))
    # the old text is already deleted; if the paste can't land, say so and keep
    # last_output pointing at the new text (which is now on the clipboard) rather
    # than reporting success over a window that just ate the original
    pasted = flow.paste_text(new, target_hwnd)
    flow.state["last_output"] = {"text": new, "hwnd": target_hwnd, "at": time.time()}
    if not pasted:
        return "фокус втрачено — текст у буфері", False
    return new, True
