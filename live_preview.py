"""Live preview: while a dictation records, the words so far are re-decoded on a timer and shown in the pill. Display only: nothing here pastes or touches the history. Moved verbatim out of flow.py."""

import time

import numpy as np

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
    text, lp, ns = flow._segment_stats(list(segments))
    # "дякую за перегляд" over a pause must not flicker into the pill either
    return "" if flow._hallucination_reason(text, lp, ns) else text


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
