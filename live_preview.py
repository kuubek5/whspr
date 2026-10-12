"""Live preview: while a dictation records, the words so far are re-decoded on a timer and shown in the pill. Display only: nothing here pastes or touches the history. Moved verbatim out of flow.py."""

import re
import threading
import time

import numpy as np

import text_fixes

import flow


# ---------------- Live preview ----------------
# While a dictation records, the words so far are re-decoded on a timer and the
# tail is shown in the pill. Display only: nothing here pastes, touches the
# history or feeds the final decode, which still runs on the whole take after
# release exactly as before.
LIVE_TICK_S = 0.7      # how often the preview wakes up
LIVE_MIN_NEW_S = 0.5   # ...and re-decodes only once this much new audio arrived
LIVE_WINDOW_S = 20.0   # newest audio decoded per pass (Whisper's window is 30 s)


def live_preview_enabled() -> bool:
    return bool(flow.config.get("live_preview", True) and flow.overlay is not None
                and flow.config.get("overlay", True)
                and flow.config.get("stt_backend", "local") != "cloud")


def _live_decode(audio: np.ndarray) -> str:
    """One cheap preview pass: greedy, no temperature fallback, no timestamps,
    no hotwords. Same model and language as the final decode, so the preview
    and the pasted text rarely disagree by more than a word."""
    lang = flow.LANGUAGES[flow.state["lang"]]
    auto = flow.config.get("auto_lang", False)
    if flow.local_engine_for(lang, auto) == "parakeet":
        try:
            return flow.parakeet_transcribe(audio)
        except Exception:
            pass  # same fallback as the final decode: Whisper is always there
    if auto:
        model, tr_lang, prompt = flow.load_model(flow.MODEL_NAME), None, None
    else:
        model, tr_lang = flow.model_for(lang), lang
        prompt = flow.UK_INITIAL_PROMPT if lang == "uk" else None
    segments, _ = model.transcribe(
        audio, language=tr_lang, beam_size=1, temperature=0.0,
        initial_prompt=prompt, condition_on_previous_text=False,
        without_timestamps=True, no_repeat_ngram_size=3, repetition_penalty=1.1)
    text, lp, ns = _segment_stats(list(segments))
    # "дякую за перегляд" over a pause must not flicker into the pill either
    return "" if _hallucination_reason(text, lp, ns) else text


def live_preview_loop(take_id: int) -> None:
    """Runs for one take; exits as soon as that take stops recording.

    Shares _transcribe_lock with the real decode but only ever TRIES it: if the
    model is busy (the previous take still transcribing) this tick is skipped.
    The cost the other way is bounded by one preview pass — a release that lands
    mid-pass waits for it, ~0.2 s greedy on the GPU."""
    def same_take():
        return flow.state["recording"] and flow.state.get("take_id") == take_id

    last_n = 0
    passes, spent = 0, 0.0
    try:
        while same_take():
            time.sleep(LIVE_TICK_S)
            if not same_take():
                break
            with flow._buf_lock:
                cur = flow.chunks[:]
            n = sum(len(c) for c in cur)
            if (n < flow.MIN_DURATION_S * flow.SAMPLE_RATE
                    or n - last_n < LIVE_MIN_NEW_S * flow.SAMPLE_RATE):
                continue
            audio = np.concatenate(cur).flatten().astype(np.float32)
            new = audio[last_n:]
            last_n = n
            # Nothing said since the last pass (a pause, or the hands-free
            # trailing silence before auto-stop): the text cannot have changed,
            # so skip it. This also keeps the model free at the moment the take
            # ends, so the final decode does not queue behind a preview pass.
            # "Quiet" is relative to the take itself: a fixed floor alone would
            # count room noise on a boosted quiet mic as speech.
            audio = audio[-int(LIVE_WINDOW_S * flow.SAMPLE_RATE):]
            rms = float(np.sqrt(np.mean(audio ** 2)))
            new_rms = float(np.sqrt(np.mean(new ** 2)))
            if new_rms < max(flow.config["rms_threshold"], 0.35 * rms):
                continue
            # same boost as the final decode, or a quiet mic previews nothing
            target_rms = flow.config.get("target_rms", 0.06)
            if rms < target_rms:
                gain = min(target_rms / rms, flow.config.get("max_gain", 12.0))
                audio = np.clip(audio * gain, -1.0, 1.0)
            if not flow._transcribe_lock.acquire(blocking=False):
                continue
            try:
                if not same_take():
                    break
                t0 = time.time()
                text = _live_decode(audio).strip()
                passes += 1
                spent += time.time() - t0
            finally:
                flow._transcribe_lock.release()
            if text and same_take():
                flow.overlay.live(text)
    except Exception as e:
        # a broken preview must never cost the dictation itself
        flow.log(f"live preview stopped ({e.__class__.__name__}: {e})")
    if passes:
        flow.log(f"live preview: {passes} passes, avg {spent / passes:.2f}s")


def _build_hotwords(raw: str) -> str | None:
    """Turn the user's comma/newline dictionary into a hotwords string.

    Whatever ends up here is fed straight to the decoder as a bias, so junk in
    the dictionary is junk pushed into every transcript. The live dictionary
    had a trailing comma (an empty term), a malformed "Бекенді.бекенд" and a
    typo — hence the defensive cleaning: strip surrounding whitespace and
    punctuation, drop what is left empty, and de-duplicate case-insensitively
    while preserving the user's order.

    Terms are NOT filtered by length: "n8n" is three characters and entirely
    legitimate. Very short terms are only warned about, never dropped — hotwords
    match inside longer words, so "ші" biases the decoder on every "наші", but
    it is the user's data and silently deleting it would be worse than the bias.
    """
    raw = raw or ""
    seen, terms = set(), []
    for t in re.split(r"[,\n]", raw):
        # strip whitespace and any surrounding punctuation, but keep what is
        # inside a term intact: "n8n", "Wi-Fi" and "п'ять" must survive
        t = t.strip().strip(".,;:!?()[]{}\"'«»„“”-–—…")
        if not t:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append(t)
    if raw != flow._hotwords_warned_for:
        flow._hotwords_warned_for = raw
        short = [t for t in terms if len(t) <= 2]
        if short:
            flow.log("dictionary warning: term(s) of 2 characters or fewer bias the "
                "decoder inside longer words (e.g. \"ші\" matches in \"наші\") "
                f"and rarely help — consider removing: {', '.join(short)}")
    return " ".join(terms) or None


def _segment_stats(segs: list) -> tuple[str, float, float]:
    """Joined text plus the two confidence numbers faster-whisper exposes.

    The segment generator can only be consumed once, so the caller materialises
    it into a list and this reads that list — the joined text is byte-identical
    to the old `" ".join(s.text.strip() for s in segments)`.

    avg_logprob is averaged weighted by segment DURATION, not per segment: a
    0.3 s "дякую" tacked onto a real 8 s sentence must not drag the mean down as
    hard as the sentence pulls it up. no_speech_prob is taken as the MAX across
    segments — one segment the model thinks is silence is enough to be
    suspicious, and short takes are usually a single segment anyway."""
    text = " ".join(s.text.strip() for s in segs).strip()
    if not segs:
        return text, 0.0, 0.0
    weights = [max(float(getattr(s, "end", 0.0)) - float(getattr(s, "start", 0.0)), 0.0)
               for s in segs]
    logps = [float(getattr(s, "avg_logprob", 0.0) or 0.0) for s in segs]
    total_w = sum(weights)
    if total_w > 0:
        avg_logprob = sum(w * lp for w, lp in zip(weights, logps)) / total_w
    else:
        # zero-length segments (VAD can produce them): fall back to a plain mean
        avg_logprob = sum(logps) / len(logps)
    no_speech = max(float(getattr(s, "no_speech_prob", 0.0) or 0.0) for s in segs)
    return text, avg_logprob, no_speech


def _hallucination_reason(text: str, avg_logprob: float,
                          no_speech_prob: float) -> str | None:
    """Why this transcript should be thrown away, or None to keep it.

    Two deliberately separate rules:

    1. A known non-speech artifact (HALLUCINATIONS) is never legitimate
       dictation, so it goes at any duration and at any confidence.

    2. Short AND low-confidence. Both halves are required. "дякую" is the single
       most frequent hallucination in the user's history (15 takes) but is also
       an ordinary word they genuinely dictate, so it cannot be blacklisted —
       the model's own confidence is what separates the two cases. A confidently
       decoded "так" / "добре" / "дякую" therefore passes untouched, while the
       same word decoded out of amplified room noise (low avg_logprob or high
       no_speech_prob) is dropped.

    The returned reason carries the numbers so the log can be audited: if this
    filter ever eats a real dictation, the line says exactly which threshold did
    it and by how much."""
    stripped = text.lower().strip(" .!?")
    if not stripped:
        return None
    # text_fixes strips a wider set of trailing punctuation than the old
    # inline comparison did, so "Дякую за перегляд…" with an ellipsis is now
    # caught too. Same rule, fewer ways to slip past it.
    if text_fixes.is_pure_artifact(text):
        return (f"known non-speech artifact: {text!r} "
                f"(avg_logprob={avg_logprob:.2f}, no_speech={no_speech_prob:.2f})")
    words = len(text.split())
    max_words = flow.config.get("hallucination_max_words",
                           flow.DEFAULTS["hallucination_max_words"])
    min_logprob = flow.config.get("hallucination_logprob",
                             flow.DEFAULTS["hallucination_logprob"])
    max_no_speech = flow.config.get("hallucination_no_speech",
                               flow.DEFAULTS["hallucination_no_speech"])
    if words <= max_words and (avg_logprob < min_logprob
                               or no_speech_prob > max_no_speech):
        return (f"low-confidence short output: {text!r} words={words}<={max_words}, "
                f"avg_logprob={avg_logprob:.2f} (drop below {min_logprob}), "
                f"no_speech={no_speech_prob:.2f} (drop above {max_no_speech})")
    return None


# Async LLM polish safety limits. The rewrite works by backspacing over what we
# pasted and pasting the polished version, so its blast radius is exactly the
# characters it deletes — every bound here exists to keep that radius small and
# to make sure we only ever delete text we are still certain is ours.
#
# 400 chars: a rewrite sends one backspace per character through pynput. At ~1 ms
# each that is 0.4 s of synthetic keystrokes, already at the edge of what feels
# like the app glitching rather than correcting itself. Longer takes keep the raw
# transcript, which is a correct result, just an unpolished one.
ASYNC_REWRITE_MAX_CHARS = 400
# 15 s: past this the user has almost certainly moved on, and last_output is no
# longer good evidence that our text is still sitting untouched under the caret.
ASYNC_REWRITE_WINDOW_S = 15.0
# How long a finished polish waits for the model lock (held for a moment by the
# live preview / speculative decode of a take now recording) before giving up.
ASYNC_LOCK_WAIT_S = 3.0


def _schedule_llm_polish(raw: str, lang: str, target_hwnd: int,
                         row_id: int | None, style: str | None = None) -> None:
    """Polish an ALREADY-PASTED transcript in the background, then rewrite it.

    This is the whole point of llm_async: the measured cost of the polish call
    is p50 0.63 s / p90 1.10 s / max 3.07 s on top of a 0.43 s transcribe, so
    waiting for it inline more than doubles the time before the user sees a
    single character. Here they see the raw text immediately and the polished
    wording replaces it a moment later.

    Rewriting means deleting characters the user can see, so the bar for doing it
    is deliberately high. Every one of these must still hold when the LLM answers:

      * the polished text actually differs from what we pasted;
      * it is short enough to retype without a visible storm of keystrokes;
      * no transcription is in flight — taken as the real _transcribe_lock,
        not a flag, so a take that finishes mid-check cannot interleave its own
        keystrokes with ours. A take that is merely RECORDING types nothing until
        it ends, so it no longer blocks the rewrite: 25 of the user's 211 logged
        takes lost their polish to "recording again" — the next sentence started
        before Groq answered for the last one;
      * no modifier is held: a combo hotkey held down for the next take would
        turn our Backspace into Alt+Backspace (undo) or Ctrl+Backspace;
      * state['last_output'] is still character-for-character the text we pasted,
        into the same window — if a later dictation, a voice command or another
        rewrite has landed since, ours is stale;
      * that window is still focused, and little enough time has passed that the
        caret is plausibly where we left it.

    Any failed check means no rewrite. The user keeps the raw transcript, which
    is a correct, complete result — never a partial delete. The same is true of
    an LLM error or timeout, which _llm_request already swallows into None."""
    if not raw or len(raw) > ASYNC_REWRITE_MAX_CHARS:
        return

    def work():
        # The network call happens OUTSIDE _transcribe_lock: holding it for up
        # to 15 s would stall the next dictation behind a slow Groq response.
        # style is resolved once in _transcribe_impl (the target window may lose
        # focus before this thread runs). Only passed when set, so a two-argument
        # llm_polish stand-in (test_async_polish.py) keeps working.
        polished = flow.llm_polish(raw, lang, style) if style else flow.llm_polish(raw, lang)
        if not polished or polished == raw:
            return
        if len(polished) > ASYNC_REWRITE_MAX_CHARS:
            flow.log("async polish skipped — result too long to retype safely")
            return
        # A short wait, not a skip: the lock is also taken for a moment by the
        # live preview and the speculative decode of a take now recording. A
        # take that really is transcribing pastes before releasing the lock,
        # and the last_output check below then sees our text is gone.
        if not flow._transcribe_lock.acquire(timeout=flow.ASYNC_LOCK_WAIT_S):
            flow.log("async polish skipped — another take is in flight")
            return
        try:
            if flow._modifiers_held():
                flow.log("async polish skipped — modifier key held")
                return
            last = flow.state.get("last_output") or {}
            if last.get("text") != raw or last.get("hwnd") != target_hwnd:
                flow.log("async polish skipped — output no longer ours")
                return
            if time.time() - last.get("at", 0) > ASYNC_REWRITE_WINDOW_S:
                flow.log("async polish skipped — too late to rewrite safely")
                return
            if target_hwnd and flow.user32.GetForegroundWindow() != target_hwnd:
                # deliberately NOT refocusing the way paste_text does: stealing
                # focus back for a cosmetic cleanup would yank the user out of
                # whatever they moved on to.
                flow.log("async polish skipped — window no longer focused")
                return
            flow._send_backspaces(len(raw))
            if flow.paste_text(polished, target_hwnd):
                flow.state["last_output"] = {"text": polished, "hwnd": target_hwnd,
                                        "at": time.time()}
                flow.history_update_text(row_id, polished)
                flow.state["pill_text"] = polished
                flow.log(f"async polish applied: {polished!r}")
            else:
                # the backspaces already went through, so the old text is gone
                # and the new one is on the clipboard — say so rather than
                # leaving the user staring at a silently emptied field
                flow.state["last_output"] = {"text": polished, "hwnd": target_hwnd,
                                        "at": time.time()}
                flow.history_update_text(row_id, polished)
                flow.log("async polish: paste failed — polished text left in clipboard")
        except Exception as e:
            flow.log(f"async polish failed ({e.__class__.__name__}: {e})")
        finally:
            flow._transcribe_lock.release()

    threading.Thread(target=work, daemon=True).start()
