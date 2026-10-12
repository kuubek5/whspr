"""Audio input: the mic callback, the input stream, hands-free auto-stop (RMS and Silero VAD engines) and Smart Turn end-of-turn. Moved verbatim out of flow.py."""

import threading
import time

import numpy as np
import sounddevice as sd

import flow


# ---------------- Audio ----------------
def audio_callback(indata, frames, t, status):
    # keep the locked section as short as possible: this runs on the audio
    # thread, and blocking here drops samples. Only the buffer append needs to
    # be atomic against take_audio()/start_rec().
    block = indata.copy()
    with flow._buf_lock:
        if flow.state["recording"]:
            flow.chunks.append(block)
        else:
            flow.pre_roll.append(block)
    # cheap live input level for the mic meter / test — deliberately outside the
    # lock: it only feeds the UI meter and need not match the buffer exactly
    try:
        rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
        flow.state["input_level"] = rms
        # Feed the recording pill's wave the real level instead of its synthetic
        # motion. Only while recording (the pill hides otherwise), throttled to
        # ~15 Hz so the audio thread stays cheap. This is the raw stream RMS on
        # the audio thread — NOT the pycaw endpoint probe that crashes the bridge
        # (see webview_app._mic_endpoint_state); different, safe path. The soft
        # curve gives a lively wave on a quiet mic without per-machine tuning.
        if flow.state["recording"] and flow.overlay is not None:
            now = time.monotonic()
            if now - flow._last_lvl_push >= 0.066:
                flow._last_lvl_push = now
                flow.overlay.level(min(1.0, (rms / 0.05) ** 0.5))
    except Exception:
        pass


# ---------------- Hands-free auto-stop ----------------
# Silero v5/v6 at 16 kHz takes exactly 512-sample (32 ms) frames.
VAD_FRAME = 512
VAD_FRAME_S = VAD_FRAME / flow.SAMPLE_RATE
# Audio fed to Silero per poll. faster-whisper's SileroVADModel starts every
# call with a zeroed LSTM state, so the first frames of a window are scored
# "cold"; ~1 s of context warms it up before the frames we actually read (only
# the newest ones, see silence_watch). Measured ~1 ms per 1 s window on CPU, so
# polling every 100 ms costs ~1% of one core.
VAD_WINDOW_FRAMES = 32
# Speech must add up to this much before auto-stop arms. One stray frame (a
# click, a cough, the keyboard) must not arm it, or the opening pause would end
# the take before the user has said a word.
VAD_MIN_SPEECH_S = 0.25


class RmsAutoStop:
    """The original loudness heuristic, unchanged in behaviour, pulled out of
    silence_watch so both engines share one loop. Fed the live block RMS and a
    wall-clock time; returns True when the take should stop."""

    name = "rms"

    def __init__(self, gap_s: float):
        self.gap = gap_s
        self.peak, self.floor, self.lvl = 0.0, 0.0025, 0.0
        self.silent_since = None
        self.now = 0.0

    def feed(self, lvl: float, now: float) -> bool:
        self.lvl, self.now = lvl, now
        self.peak = max(self.peak, lvl)
        # A quiet mic (XONAR analog in ~0.008-0.013 RMS) never crossed the old
        # 0.015 arm gate, so auto-stop never armed and the take ran to the 60 s
        # cap. Arm at 0.006 — above ambient noise (~0.001-0.003), below this
        # mic's speech — and make the silence floor RELATIVE to the take's own
        # peak so it scales to any mic instead of assuming a fixed loudness.
        spoke = self.peak > 0.006
        # silence = well below this take's own peak, but forgiving: a very quiet
        # mic (rms ~0.004) dips under an aggressive floor between words, which
        # used to auto-stop the user mid-sentence.
        self.floor = max(0.0025, self.peak * 0.22)
        if spoke and lvl < self.floor:
            if self.silent_since is None:
                self.silent_since = now
            return now - self.silent_since >= self.gap
        if lvl > self.floor * 1.5:
            # Only a CLEARLY voiced block resets the silence timer. On a quiet
            # mic the level jitters right around `floor` after the user stops
            # talking; treating every marginal blip as speech kept restarting
            # the timer, so the take trailed for seconds.
            self.silent_since = None
        return False

    def silence_ago(self, recorded_s: float, now: float) -> float | None:
        """Seconds of silence already behind the user when the take stopped —
        the latency trace's "wait" stage. Wall clock, like silent_since here."""
        return None if self.silent_since is None else max(0.0, now - self.silent_since)

    def describe(self) -> str:
        sil = 0 if self.silent_since is None else self.now - self.silent_since
        return (f"engine=rms peak={self.peak:.4f} floor={self.floor:.4f} "
                f"lvl={self.lvl:.4f} silence={sil * 1000:.0f}ms")


class VadAutoStop:
    """Speech-probability end-of-utterance decision. Pure: fed one Silero
    probability per 32 ms frame plus that frame's END time on the audio clock
    (seconds of recorded audio, not wall time — deterministic, and immune to the
    poll thread being late), returns True when the take should stop.

    Rules: arm only after VAD_MIN_SPEECH_S of speech frames (the opening pause
    never stops a take); after that, stop once `gap_s` of CONTINUOUS non-speech
    has passed. Any speech frame cancels a pending stop."""

    name = "vad"

    def __init__(self, gap_s: float, threshold: float = 0.5,
                 min_speech_s: float = VAD_MIN_SPEECH_S):
        self.gap = gap_s
        self.threshold = threshold
        # Silero's own neg_threshold: hysteresis so a frame hovering at the
        # threshold doesn't flip speech/silence on every poll
        self.neg_threshold = max(0.01, threshold - 0.15)
        self.min_speech_s = min_speech_s
        self.speech_s = 0.0
        self.silent_since = None
        self.last_prob = 0.0
        self.last_speech_prob = 0.0
        self.t = 0.0

    @property
    def armed(self) -> bool:
        return self.speech_s >= self.min_speech_s - 1e-9

    def silence_s(self) -> float:
        return 0.0 if self.silent_since is None else self.t - self.silent_since

    def silence_ago(self, recorded_s: float, now: float) -> float | None:
        """Seconds between the real end of speech and the end of the recording,
        for the latency trace. Measured on the AUDIO clock (silent_since is
        seconds into the take, recorded_s is the detached take's length), not as
        silence_s(): the poll returns at the frame that crossed the gap, and the
        audio already recorded past it — plus the up-to-100 ms poll delay — is
        wait the user sat through too."""
        if self.silent_since is None:
            return None
        return max(0.0, recorded_s - self.silent_since)

    def feed(self, prob: float, t: float) -> bool:
        self.last_prob, self.t = prob, t
        if prob >= self.threshold:
            self.speech_s += VAD_FRAME_S
            self.last_speech_prob = prob
            self.silent_since = None
            return False
        if prob < self.neg_threshold and self.armed:
            if self.silent_since is None:
                # silence began at the START of this frame
                self.silent_since = t - VAD_FRAME_S
            return self.silence_s() >= self.gap - 1e-9
        # in the hysteresis band, or not armed yet: keep the current state. A
        # pending timer keeps running through a band frame — a word trailing
        # off is not new speech — but a band frame never STARTS the timer.
        return self.silent_since is not None and self.silence_s() >= self.gap - 1e-9

    def describe(self) -> str:
        return (f"engine=vad silence={self.silence_s() * 1000:.0f}ms "
                f"last_p={self.last_prob:.2f} last_speech_p="
                f"{self.last_speech_prob:.2f} speech={self.speech_s:.1f}s "
                f"thr={self.threshold:.2f}")


_vad_lock = threading.Lock()


def _load_vad_model():
    """Separate from get_autostop_vad so tests can make it fail."""
    from faster_whisper.vad import get_vad_model as _fw_get_vad_model
    m = _fw_get_vad_model()
    m(np.zeros(VAD_FRAME * 2, dtype=np.float32))  # first run allocates; do it now
    return m


def get_autostop_vad():
    """The shared Silero model, loaded once (~0.2 s). Returns None — and logs
    ONCE — if it cannot be loaded (onnxruntime or the onnx asset missing from a
    build); callers then fall back to the rms engine. Never raises: a broken VAD
    must cost the user auto-stop quality, never dictation."""
    with _vad_lock:
        if flow._vad_model is None and not flow._vad_failed:
            t0 = time.time()
            try:
                flow._vad_model = flow._load_vad_model()
                flow.log(f"auto-stop VAD loaded ({time.time() - t0:.2f}s)")
            except Exception as e:
                flow._vad_failed = True
                flow.log(f"auto-stop VAD unavailable ({e.__class__.__name__}: {e}) "
                    f"— falling back to rms auto-stop")
        return flow._vad_model


def make_autostop(gap_s: float):
    """Pick the engine for one hands-free take: the configured one, or rms if
    VAD was asked for but cannot be loaded."""
    if str(flow.config.get("autostop_engine", "vad")).lower() == "vad":
        if get_autostop_vad() is not None:
            thr = float(flow.config.get("vad_speech_threshold", 0.5))
            return VadAutoStop(gap_s, threshold=thr)
    return RmsAutoStop(gap_s)


# ---------------- Smart Turn v3 (semantic end-of-turn) ----------------
# Pinned to a commit so a re-upload upstream can never silently swap the model
# (or its input contract) under an installed app.
SMART_TURN_REPO = "pipecat-ai/smart-turn-v3"
SMART_TURN_FILE = "smart-turn-v3.2-cpu.onnx"
SMART_TURN_REV = "f766f81d3cfdf7737ac64aad813d91bbfd56bf93"
# The model's input window: the LAST 8 s of the turn, zero-padded at the FRONT
# when shorter (the authors' contract: audio sits at the end of the vector).
SMART_TURN_S = 8
# Trailing silence the model is shown. Pipecat runs it the moment its VAD has
# heard ~0.2 s of silence, so that is what it was tuned on; fed 0.6-1.2 s of
# silence it drifts towards "finished" whatever was said (measured on 90
# mid-sentence cuts of Ukrainian TTS: 66% scored >= 0.5 with a 0.25 s tail, 81%
# with 0.6 s; finished sentences 90% vs 93%). So however late we ask, the
# audio ends 0.25 s into the pause.
SMART_TURN_TAIL_S = 0.25
# Asks per pause. With the tail trimmed (above) a second ask later in the same
# pause would show the model the very same audio, so one is all that is useful.
# The gate supports more (each costs one ~50 ms inference) should the input
# ever change between asks.
SMART_TURN_MAX_ASKS = 1


class SmartTurnGate:
    """When to ask Smart Turn, and what its answer means. Pure: fed the VAD
    decision's state (armed, seconds of continuous silence on the audio clock)
    once per poll; the caller runs the model only when should_ask() says so and
    hands the probability to verdict().

    Rules: never ask before speech (VadAutoStop not armed) or before `gap_s` of
    silence — so Smart Turn can never stop a take sooner than that. Ask at most
    `max_asks` times per pause, spaced one gap apart (asking every poll would
    burn CPU on the same answer). An ask that would land at or after `stop_s`
    is skipped — the plain silence rule ends the take then anyway. "Not
    finished" only means "keep listening": silence_stop_s still applies. Speech
    resets the per-pause count, so every new pause gets its own ask.
    After a model failure the gate goes quiet for the rest of the take, which
    leaves exactly the VAD-only behaviour."""

    def __init__(self, gap_s: float, stop_s: float, threshold: float = 0.5,
                 max_asks: int = SMART_TURN_MAX_ASKS):
        # a sub-0.3 s gap would ask inside ordinary between-word gaps
        self.gap = max(0.3, float(gap_s))
        self.stop_s = float(stop_s)
        self.threshold = float(threshold)
        self.max_asks = max_asks
        self.asks = 0            # asks in the current pause
        self.next_due = self.gap
        self.last_sil = 0.0
        self.last_p = None
        self.disabled = False

    def should_ask(self, armed: bool, silence_s: float) -> bool:
        # silence shrank (or is zero) => the user spoke since the last poll:
        # this is a new pause, with a fresh budget of asks
        if silence_s <= 0 or silence_s < self.last_sil - 1e-9:
            self.asks, self.next_due = 0, self.gap
        self.last_sil = silence_s
        if self.disabled or not armed or silence_s <= 0:
            return False
        if self.asks >= self.max_asks:
            return False
        if self.next_due >= self.stop_s - 1e-9:
            return False
        return silence_s >= self.next_due - 1e-9

    def verdict(self, p: float) -> bool:
        """Record one answer; True = the turn is complete, stop now."""
        self.asks += 1
        self.last_p = float(p)
        # measured from the silence we actually asked at, so a late poll does
        # not cause a second ask on the very next poll
        self.next_due = self.last_sil + self.gap
        return self.last_p >= self.threshold

    def fail(self):
        self.disabled = True


def smart_turn_features(audio: np.ndarray, fe) -> np.ndarray:
    """Whisper log-mel input for Smart Turn, shape (1, 80, 800), float32.

    The reference (pipecat _whisper_features / transformers WhisperFeatureExtractor
    with chunk_length=8, do_normalize=True) normalises the WAVEFORM to zero mean,
    unit variance first, then takes the standard Whisper log-mel. faster_whisper's
    numpy FeatureExtractor is that same log-mel, so we normalise here and call it
    with padding=0 (its default 160-sample tail pad shifts every frame: max error
    0.009 vs 2e-7 with padding=0, measured against the reference). The front
    zero-padding is part of the normalised signal, exactly as in the reference —
    it is what tells the model how short the turn was."""
    n = SMART_TURN_S * flow.SAMPLE_RATE
    x = np.asarray(audio, dtype=np.float32).reshape(-1)[-n:]
    if x.size < n:
        x = np.pad(x, (n - x.size, 0))
    x = (x - x.mean()) / np.sqrt(x.var() + 1e-7)
    feats = fe(x, padding=0)
    if feats.shape != (80, 800):
        # a faster_whisper upgrade changing the extractor must fail loudly
        # (=> pure VAD), not feed the model garbage
        raise ValueError(f"unexpected Smart Turn feature shape {feats.shape}")
    return feats[None].astype(np.float32)


def _load_smart_turn_model():
    """Fetch (once) and load Smart Turn; returns predict(audio) -> P(finished).
    Separate from get_smart_turn so tests can make it fail."""
    from huggingface_hub import hf_hub_download
    try:
        # offline first: after the first run this never touches the network
        path = hf_hub_download(SMART_TURN_REPO, SMART_TURN_FILE,
                               revision=SMART_TURN_REV, local_files_only=True)
    except Exception:
        path = hf_hub_download(SMART_TURN_REPO, SMART_TURN_FILE,
                               revision=SMART_TURN_REV)
    import onnxruntime as ort
    from faster_whisper.feature_extractor import FeatureExtractor
    so = ort.SessionOptions()
    # one short inference per pause; keep it off the cores Whisper is about to
    # need for the transcribe that follows the stop
    so.inter_op_num_threads = 1
    so.intra_op_num_threads = 2
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess = ort.InferenceSession(path, sess_options=so,
                                providers=["CPUExecutionProvider"])
    fe = FeatureExtractor(feature_size=80, sampling_rate=flow.SAMPLE_RATE,
                          chunk_length=SMART_TURN_S)

    def predict(audio: np.ndarray) -> float:
        out = sess.run(None, {"input_features": smart_turn_features(audio, fe)})
        # the exported graph ends in a sigmoid: this is already a probability
        return float(np.asarray(out[0]).reshape(-1)[0])

    predict(np.zeros(flow.SAMPLE_RATE, dtype=np.float32))  # first run allocates
    return predict


_st_lock = threading.Lock()


def _smart_turn_load_worker():
    t0 = time.time()
    try:
        m = flow._load_smart_turn_model()
        with _st_lock:
            flow._st_model = m
        flow.log(f"smart-turn: model loaded ({time.time() - t0:.2f}s)")
    except Exception as e:
        with _st_lock:
            flow._st_failed = True
        flow.log(f"smart-turn: unavailable ({e.__class__.__name__}: {e}) "
            f"— hands-free uses plain VAD silence")
    finally:
        with _st_lock:
            flow._st_loading = False


def get_smart_turn(start_load: bool = True):
    """The loaded Smart Turn predictor, or None. NEVER blocks: if it is not
    loaded yet the load (and on first use the 8 MB download) is started on a
    background thread and this take runs on plain VAD. A failed load is logged
    once and not retried until restart — no network must not mean a download
    attempt on every take."""
    with _st_lock:
        if flow._st_model is not None or flow._st_failed:
            return flow._st_model
        if start_load and not flow._st_loading:
            flow._st_loading = True
            threading.Thread(target=_smart_turn_load_worker, daemon=True).start()
    return None


def smart_turn_enabled() -> bool:
    return bool(flow.config.get("smart_turn", False)) and \
        str(flow.config.get("autostop_engine", "vad")).lower() == "vad"


def make_smart_turn_gate(dec, stop_s: float):
    """(predictor, gate) for one hands-free take, or (None, None) when Smart
    Turn is off, the take is not on the VAD engine, or the model isn't ready."""
    if getattr(dec, "name", "") != "vad" or not smart_turn_enabled():
        return None, None
    model = get_smart_turn()
    if model is None:
        return None, None
    return model, SmartTurnGate(float(flow.config.get("smart_turn_gap_s", 0.6)), stop_s,
                                float(flow.config.get("smart_turn_threshold", 0.5)))


def smart_turn_audio(dec: "VadAutoStop") -> np.ndarray:
    """The model's input: up to SMART_TURN_S of the take ending
    SMART_TURN_TAIL_S into the current pause (see SMART_TURN_TAIL_S for why
    not at "now"). Positions come from the VAD's audio clock, so they index the
    take's samples exactly however late this poll runs."""
    n = SMART_TURN_S * flow.SAMPLE_RATE
    since = dec.silent_since if dec.silent_since is not None else dec.t
    # + 1 s slack: blocks recorded after the VAD's last scored frame
    audio, total = _recorded_tail(n + int((dec.t - since) * flow.SAMPLE_RATE)
                                  + flow.SAMPLE_RATE)
    end = min(total, int(round((since + SMART_TURN_TAIL_S) * flow.SAMPLE_RATE)))
    offset = total - len(audio)  # take-sample index of audio[0]
    stop = max(0, end - offset)
    return audio[max(0, stop - n):stop]


def smart_turn_poll(model, gate: "SmartTurnGate", dec: "VadAutoStop") -> bool:
    """One Smart Turn check after a VAD poll. Runs the model only when the gate
    asks for it; True = stop the take now. Never raises: a model error disables
    Smart Turn for this take (logged) and the VAD silence rule carries on."""
    sil = dec.silence_s()
    if not gate.should_ask(dec.armed, sil):
        return False
    t0 = time.perf_counter()
    try:
        p = model(smart_turn_audio(dec))
    except Exception as e:
        gate.fail()
        flow.log(f"smart-turn: failed ({e.__class__.__name__}: {e}) — plain VAD "
            f"for this take")
        return False
    ms = (time.perf_counter() - t0) * 1000
    done = gate.verdict(p)
    flow.log(f"smart-turn: {'complete' if done else 'incomplete'} p={p:.2f} "
        f"gap={sil * 1000:.0f}ms infer={ms:.0f}ms -> "
        f"{'stop' if done else 'keep listening'} (thr={gate.threshold:.2f} "
        f"ask={gate.asks})")
    return done


def _recorded_tail(n_samples: int) -> tuple[np.ndarray, int]:
    """(last n_samples of this take as flat float32, total samples recorded so
    far). Copies only the tail blocks, so it stays cheap on a 60 s take."""
    with flow._buf_lock:
        total = sum(len(c) for c in flow.chunks)
        tail, got = [], 0
        for c in reversed(flow.chunks):
            if got >= n_samples:
                break
            tail.append(c)
            got += len(c)
    if not tail:
        return np.zeros(0, dtype=np.float32), total
    audio = np.concatenate(tail[::-1]).reshape(-1).astype(np.float32)
    return audio[-n_samples:], total


def vad_poll(vad, dec: "VadAutoStop", fed: int) -> tuple[bool, int]:
    """One hands-free poll: score the frames recorded since the last poll and
    feed them to `dec`. `fed` = frames of this take already scored. Returns
    (should_stop, new fed). May raise if the model does; the caller falls back."""
    audio, total = _recorded_tail(VAD_WINDOW_FRAMES * VAD_FRAME)
    # align the window to the frame grid of the WHOLE take, so frame k always
    # covers the same samples from poll to poll
    rem = total % VAD_FRAME
    if rem:
        audio = audio[:-rem]
    n_total = total // VAD_FRAME
    n_win = len(audio) // VAD_FRAME
    # if the poll thread was starved for > 1 s, the frames that fell out of the
    # window are skipped — the audio clock below still stays correct
    new = min(n_total - fed, n_win)
    if new <= 0:
        return False, max(fed, n_total)
    probs = np.asarray(vad(audio[len(audio) - n_win * VAD_FRAME:])).reshape(-1)
    # score only the newest frames: they sit at the end of the window, after up
    # to ~1 s of warm-up context
    first = n_total - new
    for i, p in enumerate(probs[-new:]):
        if dec.feed(float(p), (first + i + 1) * VAD_FRAME_S):
            return True, n_total
    return False, n_total


def mic_test(enable: bool) -> bool:
    """Open the mic (if needed) so the settings meter can show a live level.
    Returns True if a stream is available."""
    if enable:
        if flow.state.get("stream") is None:
            flow.state["stream"] = open_input_stream()
        flow.state["mic_test"] = True
        return flow.state.get("stream") is not None
    flow.state["mic_test"] = False
    if flow.config.get("mic_on_demand") and not flow.state["recording"]:
        close_stream()
    return True


def _make_stream(device):
    return sd.InputStream(
        samplerate=flow.SAMPLE_RATE, channels=1, dtype="float32",
        blocksize=flow.BLOCK, callback=audio_callback, device=device,
    )


def open_input_stream():
    """Open the mic stream on the configured device, falling back to the system
    default. Never raises: returns None if no input device is usable, so a
    missing/unplugged mic degrades to 'dictation disabled' instead of a crash."""
    dev = flow.config.get("input_device") or None
    for target in (dev, None) if dev is not None else (None,):
        try:
            s = _make_stream(target)
            s.start()
            name = sd.query_devices(target)["name"] if target is not None else "system default"
            flow.log(f"input device: {name}")
            return s
        except Exception as e:
            flow.log(f"input device {target!r} failed ({e.__class__.__name__}: {e})")
    flow.log("no usable input device — dictation disabled until one is connected")
    return None


def close_stream() -> None:
    old = flow.state.get("stream")
    if old is not None:
        try:
            old.stop()
            old.close()
        except Exception:
            pass
    flow.state["stream"] = None


def restart_stream() -> None:
    """Reopen the mic stream after a device / mic-mode change. In on-demand mode
    the stream stays closed until the next recording."""
    close_stream()
    if not flow.config.get("mic_on_demand"):
        flow.state["stream"] = open_input_stream()


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
        flow.log(f"device enumeration failed: {e}")
    return out
