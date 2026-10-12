"""Transcription: speculative decode during a hands-free pause, the recognition backends (cloud, Parakeet, Whisper with the Russian-drift retry) and _transcribe_impl, which filters, matches commands and pastes. Moved verbatim out of flow.py."""

import threading
import time

import numpy as np

import app_styles
import latency
import text_fixes

import flow


# ---------------- Speculative decode (hands-free) ----------------
# Hands-free ends a take only after silence_stop_s of silence, and the GPU sits
# idle through that whole wait. So once the pause is SPEC_AFTER_S old, the take
# so far is recognised in the background; if the auto-stop then fires on that
# same pause (no speech since — the VAD's silent_since is unchanged), the final
# decode reuses the result instead of starting from scratch. Same _recognize,
# same model and settings, so the text is the one the final decode would give;
# the only audio it lacks is the trailing silence. Any new speech starts a new
# pause with a new silent_since, and a stale result simply never matches.
SPEC_AFTER_S = 0.35
_spec_lock = threading.Lock()
_spec_result: dict = {}   # (take_id, silent_since) -> _recognize() tuple


def speculative_enabled() -> bool:
    # cloud: each speculation would be one more billed request
    return bool(flow.config.get("speculative_decode", True)
                and flow.config.get("stt_backend", "local") != "cloud")


def _speculate(key: tuple, pre: list, cur: list) -> None:
    """Background: recognise a snapshot of the take for `key`. Never raises."""
    try:
        audio = np.concatenate(pre + cur).flatten().astype(np.float32)
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms < flow.config["rms_threshold"]:
            return
        # the same boost _transcribe_impl applies to the whole take
        target_rms = flow.config.get("target_rms", 0.06)
        if rms < target_rms:
            gain = min(target_rms / rms, flow.config.get("max_gain", 12.0))
            audio = np.clip(audio * gain, -1.0, 1.0)
        with flow._transcribe_lock:
            # the final decode got the model first and already went its own way
            if flow._spec_taken == key or flow.state.get("take_id") != key[0]:
                return
            t0 = time.time()
            res = flow._recognize(audio, len(audio) / flow.SAMPLE_RATE)
            # stored INSIDE the lock: a final decode waiting on it must find it
            with _spec_lock:
                _spec_result.clear()
                _spec_result[key] = res
        flow.log(f"speculative decode ready in {time.time() - t0:.2f}s")
    except Exception as e:
        flow.log(f"speculative decode failed ({e.__class__.__name__}: {e})")


def _speculative_result(key):
    """The speculative _recognize() tuple for this stop, or None. Called by the
    final decode under _transcribe_lock; settles `key` either way."""
    if key is None:
        return None
    with _spec_lock:
        flow._spec_taken = key
        res = _spec_result.pop(key, None)
        _spec_result.clear()
    if res is not None:
        flow.log("speculative decode reused")
    return res


class CloudSTTError(Exception):
    """The cloud recognizer failed; the message is shown in the pill."""


def _recognize(audio: np.ndarray, dur: float) -> tuple:
    """Speech -> (text, avg_logprob, no_speech_prob, lang) for one prepared
    (boosted) clip: cloud or local engine, Parakeet with its Whisper second
    opinion, and the Russian-drift retry. text is None/"" when nothing was
    recognised. Raises CloudSTTError when the cloud backend fails.

    Must run under _transcribe_lock (the model is not thread-safe). Split out
    of _transcribe_impl so a hands-free take can be recognised speculatively
    during the trailing pause (see _speculate) with the very same code."""
    text = None
    avg_logprob = no_speech_prob = 0.0
    lang = flow.LANGUAGES[flow.state["lang"]]
    if flow.config.get("stt_backend", "local") == "cloud":
        t0 = time.time()
        hint = None if flow.config.get("auto_lang", False) else lang
        try:
            text = flow._cloud_transcribe(audio, hint)
        except Exception as e:
            flow.log(f"cloud STT failed ({e.__class__.__name__}: {e})")
            raise CloudSTTError(str(e)) from e
        flow.log(f"{dur:.1f}s audio -> {time.time()-t0:.2f}s cloud "
            f"[{flow.config.get('stt_provider')}/{flow.config.get('stt_model')}]: {text!r}")
    auto = flow.config.get("auto_lang", False)
    # Parakeet's transcript when it decoded this take but Whisper is asked
    # for a second opinion (Russian drift, below); None otherwise
    pk_text = None
    if text is None and flow.local_engine_for(lang, auto) == "parakeet":
        t0 = time.time()
        try:
            text = flow.parakeet_transcribe(audio)
        except Exception as e:
            # missing package/model or a runtime error: this take goes to
            # Whisper, which is always there
            flow.log(f"parakeet failed ({e.__class__.__name__}: {e}) — using Whisper")
            text = None
        if text is not None:
            # Parakeet exposes no avg_logprob / no_speech_prob, so the
            # confidence numbers stay at the neutral 0.0 set above. In
            # _hallucination_reason that means rule 2 (short AND unsure)
            # cannot fire for a Parakeet take, while rule 1 (known subtitle
            # artifacts) still applies. That is the right trade: a transducer
            # emits nothing over silence rather than Whisper-style filler, so
            # the short-unsure rule has little to catch here, and guessing a
            # confidence would only risk dropping real "так"/"дякую" takes.
            # Dictionary hotwords and initial_prompt are Whisper-only;
            # text_fixes.restore_terms below still runs on this output.
            flow.log(f"{dur:.1f}s audio -> {time.time() - t0:.2f}s parakeet "
                f"[{lang}]: {text!r}")
            # Russian drift: Parakeet has no language token or prompt to
            # steer, so the Whisper ru_retry trick (re-decode with a heavier
            # Ukrainian prompt) has no Parakeet equivalent. Instead hand the
            # take to Whisper — which runs its own ru-retry — and keep
            # whichever transcript is less Russian (ties keep Parakeet's).
            if (text and lang == "uk" and not auto
                    and flow.config.get("ru_retry", True)
                    and text_fixes.looks_russian(text)):
                flow.log("parakeet output looks Russian — asking Whisper")
                pk_text, text = text, None
    if text is None:
        hotwords = flow._build_hotwords(flow.config.get("dictionary", ""))
        t0 = time.time()
        # auto language: let Whisper detect instead of the manual F10 choice.
        # Detection needs the multilingual stock model and no Ukrainian prompt
        # bias, so auto mode trades the uk fine-tune for hands-off language.
        if auto:
            model = flow.load_model(flow.MODEL_NAME)
            tr_lang, initial_prompt = None, None
        else:
            lang = flow.LANGUAGES[flow.state["lang"]]
            model = flow.model_for(lang)
            tr_lang = lang
            initial_prompt = flow.UK_INITIAL_PROMPT if lang == "uk" else None
        # hallucination_silence_threshold drops text invented over silent gaps,
        # but it can only find those gaps with word_timestamps, and that forced
        # alignment pass costs ~5-10% extra latency per segment. Push-to-talk
        # clips rarely contain long silences, so the guard is opt-in.
        guard = {}
        if flow.config.get("hallucination_guard", False):
            guard = {"word_timestamps": True, "hallucination_silence_threshold": 2.0}
        # vad_filter is a config key, not a constant. The old comment here
        # claimed Silero was off because onnxruntime "hangs for minutes on this
        # machine"; that is no longer true — measured on this machine,
        # onnxruntime imports in 0.3 s, faster_whisper.vad loads in 0.24 s and
        # get_speech_timestamps runs in 138 ms on an 8 s clip, i.e. it is cheap.
        # The real reason it stays off by default is accuracy, not speed: see
        # the "vad" entry in DEFAULTS. No vad_parameters are passed — the
        # faster-whisper defaults are sensible and there is no measurement here
        # justifying anything else.
        def _decode(prompt, temperature=None):
            """One decode pass. Returns (info, text, avg_logprob, no_speech).

            Factored out only so the Russian-drift retry below can run the exact
            same configuration with one knob changed — every parameter here is
            the single source of truth for both passes."""
            kw = dict(
                language=tr_lang, vad_filter=flow.config.get("vad", False),
                beam_size=flow.config["beam_size"], hotwords=hotwords,
                initial_prompt=prompt,
                condition_on_previous_text=False,
                # anti-hallucination guards that are OFF by default in
                # faster-whisper and cost nothing, so they stay on
                # unconditionally. The temperature fallback and
                # compression/no-speech thresholds are already on:
                #   no_repeat_ngram_size — blocks "4 4 4 4 4" / "піп піп" loops
                #   repetition_penalty   — discourages the model repeating itself
                no_repeat_ngram_size=3,
                repetition_penalty=1.1,
                **guard,
            )
            if temperature is not None:
                kw["temperature"] = temperature
            segments, inf = model.transcribe(audio, **kw)
            # materialise the generator once: the text and the two confidence
            # numbers the filter needs all come from the same single pass
            segs = list(segments)
            return (inf,) + flow._segment_stats(segs)

        info, text, avg_logprob, no_speech_prob = _decode(initial_prompt)
        if auto:
            # keep the detected language if it's one we support, else stay put
            lang = info.language if info.language in flow.LANGUAGES else flow.LANGUAGES[flow.state["lang"]]
            flow.state["lang"] = flow.LANGUAGES.index(lang)
        ru = "".join(sorted(set(text) & flow.RU_ONLY_CHARS))
        flow.log(f"{dur:.1f}s audio -> {time.time() - t0:.2f}s transcribe [{lang}]"
            f"{' RU-chars:' + ru if ru else ''}: {text!r} "
            f"(avg_logprob={avg_logprob:.2f}, no_speech={no_speech_prob:.2f})")
        # Russian drift. 2.0% of this user's 3822 takes came back with Russian in
        # them ("Тесты", "Релиз", "пошты") — the model phonetically slipping
        # language, not the user switching. RU_ONLY_CHARS is an exact test with
        # no false positives: those four letters do not exist in Ukrainian, so
        # seeing one in a take the user asked to be Ukrainian is proof of drift.
        # Re-decode with a heavier Ukrainian prompt and the temperature fallback
        # pinned off (the fallback is often what produced the drift), then keep
        # whichever pass looks less Russian. Costs one extra ~0.4 s pass on the
        # 2% of takes that trip it, and never runs in auto-language mode, where
        # Russian may be exactly what the user is speaking.
        # text_fixes.looks_russian subsumes the RU_ONLY_CHARS test (a
        # Russian-only letter alone already scores above the threshold) and adds
        # Russian function words that contain no such letter — "что", "нужно",
        # "потому" would otherwise sail through. Measured: 31 of the user's 3834
        # takes trip it, all genuinely Russian, none false.
        if (text and lang == "uk" and not auto
                and flow.config.get("ru_retry", True)
                and text_fixes.looks_russian(text)):
            try:
                t1 = time.time()
                _, r_text, r_lp, r_ns = _decode(flow.UK_RETRY_PROMPT, temperature=0.0)
                r_ru = "".join(sorted(set(r_text) & flow.RU_ONLY_CHARS))
                flow.log(f"ru-retry {time.time() - t1:.2f}s: {r_text!r} "
                    f"(RU-chars:{r_ru or '-'}, avg_logprob={r_lp:.2f})")
                # Accept only a strict improvement, scored the same way the
                # trigger is. Deliberately NOT the distinct-letter sets `ru` /
                # `r_ru` that the log line carries: "Тесты и релизы" and "Тесты
                # і релізи" both reduce to the single letter "ы", so comparing
                # those sets would reject a retry that fixed half the Russian in
                # the take. An empty or equally-Russian retry must never replace
                # a transcript the user can still fix by hand; ties go to the
                # first pass.
                if r_text and text_fixes.ru_score(r_text) < text_fixes.ru_score(text):
                    text, avg_logprob, no_speech_prob, ru = r_text, r_lp, r_ns, r_ru
                    flow.log("ru-retry accepted")
            except Exception as e:
                flow.log(f"ru-retry failed ({e.__class__.__name__}: {e}) — keeping first pass")
        if pk_text is not None:
            if text and text_fixes.ru_score(text) < text_fixes.ru_score(pk_text):
                flow.log("whisper second opinion accepted over parakeet")
            else:
                text, avg_logprob, no_speech_prob = pk_text, 0.0, 0.0
                flow.log("keeping parakeet output")
    return text, avg_logprob, no_speech_prob, lang


def _transcribe_impl(pre: list, cur: list, target_hwnd: int,
                     command: bool = False, trace=None, stop_info=None) -> None:
    """`command` marks a command-mode take: the transcript is an instruction for
    run_selection_command and is never pasted. It goes through the same
    silence/hallucination filters first, so a misheard or empty instruction
    aborts before the user's selection or clipboard is ever touched.

    `trace` is the take's latency.Trace from stop_rec (None from tests and any
    other caller: a fresh one is made, it just has no wait/queue stages).

    `stop_info` is the (take_id, silent_since) key of a hands-free auto-stop,
    used to pick up a speculative decode of this take (see _speculate)."""
    if trace is None:
        trace = latency.Trace()
    flow.set_status("processing")
    done_msg, ok = None, True
    try:
        # measure what the user actually said, separately from the pre-roll:
        # the pre-roll is up to PRE_ROLL_S of audio captured *before* the key
        # press, so a combined threshold would silently swallow every phrase
        # shorter than MIN_DURATION_S + PRE_ROLL_S
        spoken = sum(len(c) for c in cur) / flow.SAMPLE_RATE
        audio = np.concatenate(pre + cur).flatten().astype(np.float32)
        dur = len(audio) / flow.SAMPLE_RATE
        if spoken < flow.MIN_DURATION_S:
            return
        # Cheap whole-clip silence gate. It runs regardless of the "vad" setting
        # because it answers a different question: Silero decides WHICH PARTS of
        # a clip are speech, this decides whether the clip is worth decoding at
        # all, and it costs one numpy pass instead of a neural net.
        rms = float(np.sqrt(np.mean(audio**2)))
        # published for the UI alongside mic_too_quiet: the warning is only
        # actionable if the user can see the number it is complaining about
        flow.state["mic_rms"] = rms
        flow.log(f"level rms={rms:.4f} (threshold {flow.config['rms_threshold']})")
        if rms < flow.config["rms_threshold"]:
            flow.log(f"skipped: too quiet (rms={rms:.4f})")
            done_msg, ok = "тиша", False
            return
        # weak mics record at ~0.01 RMS. That clears the silence gate but is
        # still too faint for Whisper, which then returns an empty transcript.
        # Scale up to a healthy target so quiet speech transcribes. Cap the gain
        # so a near-silent clip of pure hiss isn't blown up into hallucinations.
        target_rms = flow.config.get("target_rms", 0.06)
        max_gain = flow.config.get("max_gain", 12.0)
        if 0 < rms < target_rms:
            gain = min(target_rms / rms, max_gain)
            audio = np.clip(audio * gain, -1.0, 1.0)
            flow.log(f"boosted x{gain:.1f} -> rms {float(np.sqrt(np.mean(audio**2))):.4f}")
            # A take that lands at (or near) the gain cap means the mic itself is
            # recording far too quietly — measured ~0.006-0.008 RMS on this
            # machine, i.e. pinned at x8-x10.6 on every single take. At that
            # point we are amplifying room noise as much as speech, and Whisper
            # answers with hallucinated filler. No amount of code fixes this;
            # the input level has to be raised in Windows sound settings, so say
            # so, and flag it in state so the UI can surface it later.
            flow.state["mic_too_quiet"] = gain >= max_gain * 0.8
            if flow.state["mic_too_quiet"]:
                flow.log("WARNING: microphone input level is far too low "
                    f"(rms={rms:.4f}, boost pinned at x{gain:.1f} of max "
                    f"x{max_gain:.1f}). Raise the mic level in Windows sound "
                    "settings — heavy boost amplifies noise and causes "
                    "hallucinated text.")
        else:
            # loud enough to need no boost at all — clear any earlier warning
            flow.state["mic_too_quiet"] = False
        # --- recognition backend: cloud (BYOK) or local (default) ---
        trace.mark("stt_start")
        spec = _speculative_result(stop_info)
        if spec is not None:
            text, avg_logprob, no_speech_prob, lang = spec
        else:
            try:
                text, avg_logprob, no_speech_prob, lang = flow._recognize(audio, dur)
            except CloudSTTError as e:
                done_msg, ok = ("хмара: " + str(e))[:80], False
                return
        trace.mark("stt_end")
        if not text:
            # also the normal outcome when vad_filter is on and Silero judged the
            # whole clip non-speech: `segments` is then empty and there is
            # nothing to paste, which is exactly what this path already handled
            done_msg, ok = "порожньо", False
            return
        reason = flow._hallucination_reason(text, avg_logprob, no_speech_prob)
        if reason:
            flow.log(f"dropped as hallucination — {reason}")
            done_msg, ok = "не розчув", False
            return
        # The take survived the whole-utterance filter, so it is real speech —
        # but Whisper may still have tacked a subtitle artifact onto the end of
        # it ("...Покажи мені Дякую за перегляд!"). Trim the edges only; a
        # matching phrase in the MIDDLE of a sentence is far likelier to be
        # something the user actually said. Runs before the command match so a
        # command with an artifact stuck to it still matches its trigger.
        text, removed = text_fixes.trim_artifacts(text)
        if removed:
            flow.log(f"trimmed artifact(s) {removed} -> {text!r}")
        if command:
            if not text.strip():
                done_msg, ok = "порожньо", False
                return
            done_msg, ok = flow.run_selection_command(text, lang, dur, target_hwnd)
            return
        # NOTE on ordering: the filter runs BEFORE match_voice_command, and every
        # voice-command trigger is 1-3 words ("стерти", "капсом", "видали це"),
        # so an unconfidently decoded command is dropped rather than executed.
        # That is deliberate, not an oversight: "видали останнє" sends real
        # backspaces over the user's text, and acting on a command the model was
        # unsure it heard is worse than making the user repeat it. Moving this
        # check after the command match would trade that safety for convenience.
        # Snippets come first among the whole-utterance matches (the command
        # branch above has already returned, so a command-mode instruction can
        # never paste a snippet). Precedence is documented in match_snippet: an
        # exact user trigger beats a built-in voice command, a fuzzy one never
        # does. Like voice commands, a short trigger decoded with low confidence
        # was already dropped by the hallucination filter above.
        snip = flow.match_snippet(text)
        if snip:
            done_msg, ok = flow.run_snippet(snip[0], snip[1], lang, dur, target_hwnd)
            return
        # a whole-utterance command edits the previous dictation instead of
        # typing new text; checked before normalization so triggers match cleanly
        cmd = flow.match_voice_command(text)
        if cmd:
            flow.log(f"voice command: {text!r}")
            done_msg, ok = flow.run_voice_command(cmd[0], cmd[1], target_hwnd)
            return
        # deterministic passes first, so the LLM (if any) sees clean digits and
        # marks instead of spelled-out numbers and dictated "кома"/"крапка"
        text = flow.normalize_numbers(text)
        text = flow.apply_spoken_punctuation(text)
        # Restore dictionary terms the decoder transliterated. hotwords only
        # bias the decoder — in Ukrainian mode a Latin brand still comes back as
        # "віспор флоу", and no decoding parameter fixes that. Measured over the
        # user's 3834 recorded takes with their real dictionary: 50 takes (1.3%)
        # changed, every one of them a genuine term. See test_text_fixes.py for
        # the anti-corruption suite that keeps it that conservative.
        text, restored = text_fixes.restore_terms(text, flow.config.get("dictionary", ""))
        if restored:
            flow.log(f"dictionary restored: {restored}")
        # Sync vs async LLM (see the llm_async note in DEFAULTS). Sync keeps the
        # original ordering, where the LLM sees normalised digits and marks and
        # the replacement/capitalisation passes run over its answer. Async skips
        # it here, pastes the deterministic result immediately, and lets
        # _schedule_llm_polish rewrite it in place once the network answers — so
        # the LLM sees the fully normalised text instead, which is if anything
        # the friendlier input.
        use_llm = flow.llm_available()
        # A few-word take Whisper already punctuated comes back from the LLM
        # unchanged (see polish_skip_short in DEFAULTS), so skip the round trip;
        # the deterministic passes above and capitalize_sentences below still
        # run. Applies to the async path too: no pointless rewrite either.
        skip = None
        if use_llm and flow.config.get("polish_skip_short", True):
            try:
                max_w = int(flow.config.get("polish_skip_max_words",
                                       flow.DEFAULTS["polish_skip_max_words"]))
            except (TypeError, ValueError):
                max_w = flow.DEFAULTS["polish_skip_max_words"]
            skip = text_fixes.polish_skip_reason(text, max_w)
            if skip:
                flow.log(f"polish skipped: {skip}")
                use_llm = False
        polish_async = flow.config.get("llm_async", True) and use_llm
        # Per-app style, resolved from the paste target once, here, for both the
        # sync and async paths. Only looked up when a polish will actually run,
        # and None for "default" so the call is exactly the pre-feature one.
        style = None
        if use_llm and flow.config.get("app_styles_enabled", True):
            category, exe = app_styles.resolve_style(target_hwnd, flow.config)
            flow.log(f"style: {category} ({exe or '?'})")
            if category != app_styles.DEFAULT:
                style = category
        trace.mark("polish_start")
        if skip:
            trace.polish_label = "skipped"
        elif not use_llm:
            trace.polish_label = "off"
        elif polish_async:
            trace.polish_label = "async"
        else:
            trace.polish_label = flow._llm_label()
            text = flow.llm_polish(text, lang, style) if style else flow.llm_polish(text, lang)
        trace.mark("polish_end")
        text = flow.apply_replacements(text)
        text = flow.capitalize_sentences(text)
        row_id = flow.history_add(text, lang, dur)
        pasted = flow.paste_text(text, target_hwnd)
        trace.mark("paste")
        line = trace.summary()  # None on any trace trouble; never raises
        if line:
            flow.log(line)
        done_msg, ok = (text, True) if pasted else ("фокус втрачено — текст у буфері", False)
        flow.state["pill_text"] = text
        flow.state["pill_done_at"] = time.time()
        # remember what we typed and where, so a follow-up voice command can edit it
        if pasted:
            flow.state["last_output"] = {"text": text, "hwnd": target_hwnd, "at": time.time()}
            if polish_async:
                flow._schedule_llm_polish(text, lang, target_hwnd, row_id, style)
    finally:
        flow.set_status("idle")
        if flow.overlay is not None and flow.config.get("overlay", True):
            try:
                if done_msg is not None:
                    flow.overlay.flash(done_msg, ok)
                else:
                    flow.overlay.hide()
            except Exception as e:
                flow.log(f"overlay flash failed ({e.__class__.__name__}: {e})")
