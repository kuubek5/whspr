# bench.py — measurement harness for whspr's three open latency/quality trade-offs.
#
# It answers, with numbers from THIS machine and THIS voice, three questions that
# cannot be answered from documentation:
#   1) beam_size 5 vs 1  — how much latency does greedy decoding actually save,
#      and does the Ukrainian transcript change at all?
#   2) compute_type int8_float16 vs float16 — INT8 is a large win on CPU, but on
#      an Ampere GPU (RTX 3070) the FP16 tensor cores are already saturated, so
#      INT8 often buys little while costing some accuracy. Measure, don't guess.
#   3) word_timestamps=True — the forced-alignment pass that
#      hallucination_silence_threshold requires. flow.py's comment estimates
#      "~5-10%"; this measures the real number.
#
# Run:  python bench.py clip.wav
#       python bench.py --record 8            (record your own clip first)
#       python bench.py samples --runs 5 --beam 1 5 --compute float16
#
# --------------------------------------------------------------------------
# Why `import flow` is safe here (verified against flow.py as it stands — re-check
# if flow.py's module scope grows):
#
#   Module-level code in flow.py runs exactly this much work at import time:
#     * BASE / DATA_DIR / FROZEN path math                    — pure computation
#     * register_cuda_dlls()   line 70  — os.add_dll_directory + PATH edits so
#       ctranslate2 can find cuBLAS/cuDNN. This is the ONE thing we actually
#       need from the import, and it must happen before faster_whisper loads.
#     * prime_platform_cache() line 100 — fills platform._uname_cache from the
#       PEB so the sounddevice import cannot hang on a wedged WMI service.
#     * imports of numpy / sounddevice / pyperclip / pynput / faster_whisper
#     * load_config()          line 270 — READ-ONLY: opens config.json and falls
#       back to DEFAULTS. It never writes (save_config is a separate function
#       and is not called at module scope).
#     * keyboard.Controller() line 301 and ctypes.windll.user32 line 302 —
#       these construct handles only; no listener thread is started, no hook is
#       installed, no key is ever sent.
#
#   What does NOT happen at import: no sounddevice InputStream is opened, no
#   hotkey listener is started, no tray icon or overlay is created, no sqlite
#   connection, no network call, no thread. All of that lives inside main() and
#   its helpers, behind `if __name__ == "__main__":` at the end of flow.py.
#
#   Conclusion: importing flow is side-effect-safe for a benchmark, and we take
#   the constants (MODELS, MODEL_NAME, SAMPLE_RATE, UK_INITIAL_PROMPT) and the
#   CUDA DLL registration from it. flow.main() is NEVER called from this script.
# --------------------------------------------------------------------------

from __future__ import annotations

import argparse
import gc
import glob
import os
import re
import statistics
import sys
import time
import wave

# The Windows console defaults to a legacy code page (cp866/cp1251) which cannot
# encode the Ukrainian output below; without this every print() would raise.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import numpy as np

# flow.py may be under active edit; a transient SyntaxError there should produce
# a readable message rather than a traceback from deep inside the import machinery.
try:
    import flow
except Exception as exc:  # pragma: no cover - depends on the state of flow.py
    print(f"Не вдалося імпортувати flow.py ({exc.__class__.__name__}: {exc}).")
    print("Бенчмарк бере з нього константи та реєстрацію CUDA-бібліотек, "
          "тому без нього не працює.")
    sys.exit(2)

from faster_whisper import WhisperModel

# Importing flow attaches ITS RotatingFileHandler to whspr.log — the same file a
# running whspr instance already holds open. RotatingFileHandler is not safe
# across processes: if the log crosses its 2 MB limit while a benchmark runs,
# both processes try to rename it at once and one of them loses its output (on
# Windows the rename simply fails). Benchmarking while the app is in the tray is
# the normal case, so detach the file handler here and let flow.log() fall back
# to print() — everything it says is worth seeing on the console anyway.
for _h in list(flow._logger.handlers):
    flow._logger.removeHandler(_h)
    try:
        _h.close()
    except Exception:
        pass

SR = flow.SAMPLE_RATE  # 16000 — Whisper's fixed input rate, not a preference

# Compute types worth comparing, per device. On CUDA these are the two the
# question is about; on CPU, int8 is what flow.py falls back to and float32 is
# the accuracy reference (float16 has no CPU kernel in CTranslate2).
CUDA_COMPUTE = ["int8_float16", "float16"]
CPU_COMPUTE = ["int8", "float32"]


# ------------------------- audio loading -------------------------

def _load_with_soundfile(path: str):
    import soundfile as sf
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    return data.mean(axis=1).astype(np.float32), sr


def _load_with_wave(path: str):
    """stdlib fallback so the script runs with nothing beyond numpy installed.

    soundfile is the better reader (it handles float WAVs, WAVE_FORMAT_EXTENSIBLE
    and every bit depth), but it is an optional dependency. The wave module
    covers plain PCM, which is what --record writes and what Windows recorders
    produce, so the common case works either way."""
    with wave.open(path, "rb") as w:
        ch, width, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width == 1:
        # 8-bit WAV is unsigned and centred on 128 — every wider format is signed.
        a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        # 24-bit has no numpy dtype: widen each 3-byte little-endian sample into
        # the top three bytes of an int32, then scale by 2**31.
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        pad = np.zeros((len(b), 4), dtype=np.uint8)
        pad[:, 1:] = b
        a = pad.view("<i4").ravel().astype(np.float32) / 2147483648.0
    elif width == 4:
        a = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"непідтримувана розрядність WAV: {width * 8} біт")
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return a.astype(np.float32), sr


def _resample(a: np.ndarray, sr: int) -> tuple[np.ndarray, str]:
    """Bring audio to 16 kHz, returning the signal and a note about how.

    Preference order matters. soxr and scipy's resample_poly both low-pass before
    decimating, so nothing aliases. The numpy linear-interpolation path does NOT
    filter, so downsampling 44.1k -> 16k with it folds everything above 8 kHz back
    into the speech band. That degrades the transcript, which would silently
    corrupt the very comparison this script exists to make — so it is a last
    resort and is reported loudly to the user rather than used quietly."""
    try:
        import soxr
        return soxr.resample(a, sr, SR).astype(np.float32), "soxr"
    except Exception:
        pass
    try:
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(SR, sr)
        return resample_poly(a, SR // g, sr // g).astype(np.float32), "scipy"
    except Exception:
        pass
    n = int(round(len(a) * (SR / sr)))
    idx = np.linspace(0, len(a) - 1, n)
    return np.interp(idx, np.arange(len(a)), a).astype(np.float32), "linear"


def load_audio(path: str) -> np.ndarray:
    try:
        a, sr = _load_with_soundfile(path)
    except ImportError:
        a, sr = _load_with_wave(path)
    if sr != SR:
        a, how = _resample(a, sr)
        if how == "linear":
            print(f"  УВАГА: {os.path.basename(path)} має {sr} Гц, а потрібно {SR} Гц.")
            print("  Ні soxr, ні scipy не встановлені, тому використано грубу лінійну "
                  "інтерполяцію без фільтра — вона дає аліасинг і псує розпізнавання.")
            print("  Якість у результатах нижче буде заниженою. Встановіть soxr "
                  "(pip install soxr) або запишіть кліп через --record (одразу 16 кГц).")
        else:
            print(f"  {os.path.basename(path)}: {sr} Гц -> {SR} Гц ({how})")
    return a


def collect_inputs(paths: list[str]) -> list[str]:
    """Expand positional args: each may be a WAV file or a directory of WAVs."""
    out: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            found = sorted(glob.glob(os.path.join(p, "*.wav")) +
                           glob.glob(os.path.join(p, "*.WAV")))
            if not found:
                print(f"У теці {p} немає WAV-файлів.")
            out.extend(found)
        elif os.path.isfile(p):
            out.append(p)
        else:
            print(f"Не знайдено: {p}")
    # Dedupe while preserving order: a directory and a file inside it can overlap,
    # and Windows paths differing only in case are the same file.
    seen, uniq = set(), []
    for p in out:
        key = os.path.abspath(p).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


# ------------------------- recording -------------------------

def record_clip(seconds: float, out_path: str) -> str:
    """Record a test clip from the default mic at 16 kHz mono float32.

    Recording at the target rate sidesteps resampling entirely, and lets the user
    benchmark on their own voice through their own mic — the only input that makes
    the beam/compute/word-timestamp verdict meaningful for them."""
    import sounddevice as sd
    # Record from the SAME device the app dictates through, not the system
    # default. With a headset selected in whspr's settings while Windows still
    # defaults to a built-in array mic, a default-device clip would measure
    # hardware the user never dictates with — and the RMS, the boost factor and
    # the whole quality verdict would describe the wrong microphone.
    dev = flow.config.get("input_device") or None
    try:
        name = sd.query_devices(dev)["name"] if dev is not None else "за замовчуванням"
    except Exception:
        # a stale device name in config: fall back the way flow.open_input_stream does
        print(f"Пристрій {dev!r} з config.json недоступний — беру системний за замовчуванням.")
        dev, name = None, "за замовчуванням"
    print(f"Запис {seconds:.0f} с з мікрофона: {name}. Говоріть звичайним темпом…")
    buf = sd.rec(int(seconds * SR), samplerate=SR, channels=1, dtype="float32",
                 device=dev)
    sd.wait()
    a = np.asarray(buf).flatten().astype(np.float32)
    rms = float(np.sqrt(np.mean(a ** 2))) if len(a) else 0.0
    print(f"Записано {len(a) / SR:.1f} с, RMS = {rms:.4f}")
    # The app's silence gate sits at rms_threshold (0.003 by default) and it boosts
    # anything below target_rms. 0.01 is the practical floor below which Whisper
    # starts returning empty text even after that boost — and an empty transcript
    # makes every configuration look identical, which is a false result, not a win.
    if rms < 0.01:
        print("  УВАГА: сигнал дуже тихий (RMS < 0.01). Whisper на такому кліпі "
              "може повертати порожній текст, і тоді порівняння конфігурацій нічого "
              "не покаже. Підсуньте мікрофон ближче, підніміть підсилення входу в "
              "налаштуваннях Windows і перезапишіть.")
    # int16 PCM: readable both by the soundfile path and by the stdlib wave path.
    pcm = (np.clip(a, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(out_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"Збережено: {os.path.abspath(out_path)}")
    return out_path


# ------------------------- transcription -------------------------

def preprocess(a: np.ndarray, boost: bool) -> np.ndarray:
    """Apply the same quiet-mic gain the real hot path applies.

    _transcribe_impl scales anything below target_rms up toward it (capped by
    max_gain) before calling transcribe. Skipping that here would feed the model a
    much quieter signal than production ever sees, and a quiet signal changes both
    the transcript and — through the temperature-fallback retries that a bad decode
    triggers — the timing. So the benchmark mirrors it."""
    if not boost or not len(a):
        return a
    rms = float(np.sqrt(np.mean(a ** 2)))
    target = flow.config.get("target_rms", 0.06)
    if 0 < rms < target:
        gain = min(target / rms, flow.config.get("max_gain", 12.0))
        return np.clip(a * gain, -1.0, 1.0).astype(np.float32)
    return a


def transcribe_once(model: WhisperModel, audio: np.ndarray, beam: int, wt: bool,
                    lang: str, hotwords, initial_prompt) -> tuple[str, float]:
    """One timed transcription with EXACTLY flow.py's hot-path arguments.

    Every kwarg below is copied from `segments, info = model.transcribe(...)` in
    _transcribe_impl. Dropping any of them would change the decode path and make
    the measurement describe a program the user does not run: condition_on_
    previous_text, no_repeat_ngram_size and repetition_penalty all alter how many
    decoder steps happen, and hotwords/initial_prompt prepend real tokens."""
    guard = {}
    if wt:
        # flow.py never sets word_timestamps alone: it is the prerequisite for
        # hallucination_silence_threshold, and that pair is what the user would
        # actually switch on. Benchmarking word_timestamps by itself would measure
        # a configuration that does not exist in the app.
        guard = {"word_timestamps": True, "hallucination_silence_threshold": 2.0}
    t0 = time.perf_counter()
    segments, _info = model.transcribe(
        audio, language=lang, vad_filter=False,
        beam_size=beam, hotwords=hotwords,
        initial_prompt=initial_prompt,
        condition_on_previous_text=False,
        no_repeat_ngram_size=3,
        repetition_penalty=1.1,
        **guard,
    )
    # transcribe() returns a lazy generator: the decoding happens while the list is
    # consumed. Timing must include this line, or every configuration would appear
    # to take a few microseconds and the whole benchmark would be meaningless.
    text = " ".join(s.text.strip() for s in segments).strip()
    return text, time.perf_counter() - t0


def build_model(repo: str, device: str, compute_type: str) -> WhisperModel:
    """Build and warm up a model the way flow.py's _load_model_locked does.

    Three details are borrowed deliberately:
      * ensure_tokenizer — several community CT2 conversions (the Ukrainian
        fine-tune among them) ship no tokenizer.json, and faster-whisper then
        silently falls back to whisper-tiny's off-by-one vocabulary. Plain
        decoding survives that; initial_prompt does not, and we always pass one
        for Ukrainian. Without this call the uk-ft numbers would be garbage.
      * local_files_only first — a cached model otherwise triggers an HF revision
        check that can hang for a long time on a slow or blocked network.
      * the throwaway transcription — CTranslate2's first call allocates workspace
        and selects/compiles kernels. That one-off cost is hundreds of milliseconds
        and would land entirely on the first timed run, inflating whichever
        configuration happened to be measured first."""
    flow.ensure_tokenizer(repo)
    try:
        m = WhisperModel(repo, device=device, compute_type=compute_type,
                         local_files_only=True)
    except Exception:
        # not cached locally yet — allow the download / revision check
        m = WhisperModel(repo, device=device, compute_type=compute_type)
    t0 = time.perf_counter()
    list(m.transcribe(np.zeros(SR, dtype=np.float32), language="en")[0])
    print(f"    прогрів: {time.perf_counter() - t0:.2f} с")
    return m


# ------------------------- reporting -------------------------

def norm(text: str) -> str:
    """Whitespace-insensitive form used ONLY for the identical/different verdict.

    Segment boundaries move between configurations, so joining segments can yield
    a different number of spaces for word-for-word identical output. Comparing on
    collapsed whitespace keeps the verdict about words, not formatting. The text
    printed to the user is always the raw one."""
    return " ".join(text.split())


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="bench.py",
        description="Заміряє beam_size, compute_type і word_timestamps для whspr "
                    "на реальних аргументах гарячого шляху flow.py.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Приклади:\n"
               "  python bench.py clip.wav\n"
               "  python bench.py --record 8\n"
               "  python bench.py samples --runs 5 --beam 1 5 --compute float16\n",
    )
    ap.add_argument("audio", nargs="*",
                    help="WAV-файли або тека з WAV-файлами")
    ap.add_argument("--record", type=float, metavar="N",
                    help="записати N секунд із мікрофона і використати цей кліп")
    ap.add_argument("--record-out", default="bench_sample.wav", metavar="WAV",
                    help="куди зберегти запис (типово bench_sample.wav)")
    ap.add_argument("--record-only", action="store_true",
                    help="лише записати кліп і вийти, без бенчмарку")
    ap.add_argument("--beam", type=int, nargs="+", default=[1, 5], metavar="N",
                    help="значення beam_size (типово 1 5)")
    ap.add_argument("--compute", nargs="+", default=None, metavar="TYPE",
                    help="типи обчислень (типово int8_float16 float16 на CUDA, "
                         "int8 float32 на CPU)")
    ap.add_argument("--wt", choices=["on", "off", "both"], default="both",
                    help="word_timestamps: on / off / both (типово both)")
    ap.add_argument("--model", default=None, metavar="KEY",
                    help="ключ моделі з flow.MODELS: " + ", ".join(flow.MODELS) +
                         " (типово значення model_uk з config.json)")
    ap.add_argument("--runs", type=int, default=3, metavar="N",
                    help="скільки разів повторити кожну конфігурацію (типово 3)")
    ap.add_argument("--lang", default="uk", metavar="LANG",
                    help="мова розпізнавання (типово uk)")
    ap.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto",
                    help="пристрій (типово auto)")
    ap.add_argument("--no-hotwords", action="store_true",
                    help="не передавати словник із config.json як hotwords")
    ap.add_argument("--no-boost", action="store_true",
                    help="не піднімати гучність тихого кліпу так, як це робить застосунок")
    args = ap.parse_args()

    paths = collect_inputs(args.audio)
    if args.record:
        paths = [record_clip(args.record, args.record_out)] + paths
        if args.record_only:
            return 0
    if not paths:
        print("Немає аудіо. Передайте WAV-файл або теку, або скористайтеся --record N.")
        return 1

    # ---- device and compute types ----
    device = args.device
    if device == "auto":
        # ctranslate2 ships with faster-whisper and answers this without loading a
        # model, so the probe costs nothing. flow's register_cuda_dlls() has already
        # run at import, which is what makes the CUDA libraries findable at all.
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    computes = args.compute or (CUDA_COMPUTE if device == "cuda" else CPU_COMPUTE)
    if device == "cpu":
        print("=" * 78)
        print("CUDA НЕДОСТУПНА — усі числа нижче отримані на ЦЕНТРАЛЬНОМУ ПРОЦЕСОРІ (CPU).")
        print("Вони НЕ описують поведінку на RTX 3070 і не можуть бути підставою для")
        print("вибору compute_type: на CPU int8 виграє майже завжди, на Ampere — ні.")
        print("=" * 78)
        # float16 has no CPU kernel in CTranslate2; swap it for the closest
        # meaningful CPU reference instead of crashing halfway through the sweep.
        computes = [("float32" if c in ("float16", "int8_float16") else c) for c in computes]
        computes = list(dict.fromkeys(computes))

    wts = {"on": [True], "off": [False], "both": [False, True]}[args.wt]

    model_key = args.model or flow.config.get("model_uk", "stock")
    spec = flow.MODELS.get(model_key)
    if spec is None:
        print(f"Невідомий ключ моделі {model_key!r}. Доступні: {', '.join(flow.MODELS)}")
        return 1
    repo = spec["repo"]

    hotwords = None
    if not args.no_hotwords:
        # same split as _transcribe_impl: comma- or newline-separated terms
        hotwords = " ".join(
            t.strip() for t in re.split(r"[,\n]", flow.config.get("dictionary", "")) if t.strip()
        ) or None
    initial_prompt = flow.UK_INITIAL_PROMPT if args.lang == "uk" else None

    # ---- load audio once; every configuration reuses the same arrays ----
    print("\nАудіо:")
    clips = []
    for p in paths:
        a = preprocess(load_audio(p), boost=not args.no_boost)
        clips.append((os.path.basename(p), a))
        rms = float(np.sqrt(np.mean(a ** 2))) if len(a) else 0.0
        print(f"  {os.path.basename(p)}: {len(a) / SR:.2f} с, RMS = {rms:.4f}")
    total_dur = sum(len(a) for _, a in clips) / SR
    if total_dur <= 0:
        print("Аудіо порожнє.")
        return 1

    n_cfg = len(args.beam) * len(computes) * len(wts)
    print(f"\nМодель: {model_key} ({spec['label']}, {repo})")
    print(f"Пристрій: {device} | мова: {args.lang} | повторів на конфігурацію: {args.runs}")
    print(f"hotwords: {'так' if hotwords else 'ні'} | "
          f"initial_prompt: {'так' if initial_prompt else 'ні'} | "
          f"підсилення тихого кліпу: {'ні' if args.no_boost else 'так'}")
    print(f"Матриця: beam {args.beam} x compute {computes} x word_timestamps "
          f"{['так' if w else 'ні' for w in wts]} = {n_cfg} конфігурацій\n")

    # ---- sweep ----
    # compute_type is the OUTER loop on purpose: it is the only axis that requires
    # rebuilding and re-warming the model, which costs seconds to tens of seconds.
    # beam_size and word_timestamps are per-call arguments and cost nothing to vary.
    results = []
    for ct in computes:
        print(f"[{ct}] будую модель…")
        try:
            model = build_model(repo, device, ct)
        except Exception as exc:
            print(f"  не вдалося: {exc.__class__.__name__}: {exc} — "
                  f"пропускаю цей compute_type\n")
            continue
        for beam in args.beam:
            for wt in wts:
                label = f"beam={beam} {ct} wt={'так' if wt else 'ні'}"
                times, text = [], ""
                try:
                    for _ in range(args.runs):
                        # One "run" is all clips together, so multi-file input is
                        # compared as a single workload instead of producing one
                        # table per file.
                        parts, total = [], 0.0
                        for name, a in clips:
                            t, dt = transcribe_once(model, a, beam, wt, args.lang,
                                                    hotwords, initial_prompt)
                            parts.append(t if len(clips) == 1 else f"[{name}] {t}")
                            total += dt
                        times.append(total)
                        text = "\n".join(parts)
                except Exception as exc:
                    print(f"  {label}: помилка {exc.__class__.__name__}: {exc}")
                    continue
                # min is the cleanest "how fast can this go" signal — it is the run
                # least polluted by Windows scheduling, antivirus and GPU clock
                # ramping. median is the robust central value; mean is not reported
                # because a single stalled run drags it arbitrarily far.
                med, mn = statistics.median(times), min(times)
                results.append({"beam": beam, "compute": ct, "wt": wt, "label": label,
                                "median": med, "min": mn, "text": text})
                print(f"  {label}: медіана {med:.3f} с, мін {mn:.3f} с, "
                      f"RTF {total_dur / med:.1f}x")
        # Release VRAM before building the next compute_type. Two large-v3 models
        # would otherwise sit in memory at once, and on an 8 GB card that can push
        # the second build into a slower allocation path — or fail outright.
        del model
        gc.collect()
        print()

    if not results:
        print("Жодна конфігурація не відпрацювала.")
        return 1

    # ---- baseline: the slowest, highest-quality corner of the requested matrix ----
    # beam 5 + full precision + word timestamps is the reference the user trusts;
    # everything faster has to prove it does not change the text. If flags narrowed
    # the matrix so that corner was not measured, the best available corner is used.
    def baseline_rank(r):
        precise = 0 if r["compute"].startswith("int8") else 1
        return (r["beam"], precise, r["wt"])

    base = max(results, key=baseline_rank)
    base_norm = norm(base["text"])
    for r in results:
        r["same"] = norm(r["text"]) == base_norm

    # ---- summary table ----
    print("=" * 78)
    print("ПІДСУМОК (відсортовано за медіаною часу, швидші вгорі)")
    print("=" * 78)
    print(f"{'beam':<5}{'compute':<15}{'word_ts':<9}{'медіана':>10}{'мін':>10}"
          f"{'RTF':>8}  текст")
    print("-" * 78)
    for r in sorted(results, key=lambda x: x["median"]):
        if r is base:
            mark = "БАЗОВИЙ"
        else:
            mark = "такий самий" if r["same"] else "ВІДРІЗНЯЄТЬСЯ"
        print(f"{r['beam']:<5}{r['compute']:<15}{('так' if r['wt'] else 'ні'):<9}"
              f"{r['median']:>9.3f}с{r['min']:>9.3f}с"
              f"{total_dur / r['median']:>7.1f}x  {mark}")
    print("-" * 78)
    print(f"Тривалість аудіо: {total_dur:.2f} с. "
          f"RTF = тривалість аудіо / час розпізнавання (більше — краще).")

    # ---- transcripts ----
    print("\n" + "=" * 78)
    print("ТЕКСТИ")
    print("=" * 78)
    print(f"БАЗОВИЙ ({base['label']}):")
    print(f"  {base['text']}")
    differing = [r for r in results if not r["same"]]
    if not differing:
        print("\nУсі інші конфігурації дали ТОЙ САМИЙ текст, "
              "тому вибирати можна суто за швидкістю.")
    else:
        # Printed in full rather than as a word diff: the user has to judge
        # Ukrainian quality by eye — a shorter or differently punctuated transcript
        # is not automatically worse, and a 2x speedup that mangles the language is
        # not a win no matter what the table says.
        print(f"\nВідрізняються від базового: {len(differing)} із {len(results) - 1}.")
        for r in sorted(differing, key=lambda x: x["median"]):
            print(f"\n{r['label']} (медіана {r['median']:.3f} с):")
            print(f"  {r['text']}")

    # ---- recommendation ----
    print("\n" + "=" * 78)
    identical = sorted([r for r in results if r["same"]], key=lambda x: x["median"])
    best = identical[0]
    where = "на CPU" if device == "cpu" else "на GPU"
    if best is base:
        print(f"РЕКОМЕНДАЦІЯ: жодна швидша конфігурація не зберегла текст базової — "
              f"залишайте beam_size={base['beam']}, compute_type={base['compute']}, "
              f"word_timestamps={'увімкнено' if base['wt'] else 'вимкнено'} ({where}).")
    else:
        speedup = base["median"] / best["median"] if best["median"] else 1.0
        print(f"РЕКОМЕНДАЦІЯ: beam_size={best['beam']}, compute_type={best['compute']}, "
              f"word_timestamps={'увімкнено' if best['wt'] else 'вимкнено'} — текст "
              f"ідентичний базовому, а швидкість у {speedup:.2f} разу вища "
              f"({best['median']:.3f} с проти {base['median']:.3f} с {where}).")
        print("У config.json це поля \"beam_size\" і \"hallucination_guard\"; "
              "compute_type задано в flow.py у _load_model_locked.")
    if device == "cpu":
        print("Нагадування: це числа CPU. Для рішення про compute_type "
              "потрібен запуск із доступною CUDA.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
