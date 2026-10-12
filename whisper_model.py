"""Whisper model: loading (CUDA with CPU fallback), the Hugging Face tokenizer repair, and the per-language model choice. Moved verbatim out of flow.py."""

import json
import os
import shutil
import threading
import time

import numpy as np
from faster_whisper import WhisperModel

import flow


# ---------------- Model ----------------
_model_lock = threading.Lock()


def load_model(name: str = flow.MODEL_NAME) -> WhisperModel:
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
    snaps = os.path.join(flow._repo_cache_dir(repo), "snapshots")
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
    nothing. KuubWave always passes initial_prompt for Ukrainian, so the fine-tune
    looked completely deaf while the stock model worked.

    The default (large-v3 turbo, vocab 51866) is only a valid donor for another
    large-v3 model. medium/small/base/tiny use a 51865 vocab, so the tokenizer
    must NOT be lent across sizes — we copy only when vocabulary.json matches."""
    if repo == flow.MODEL_NAME:
        return
    snap = _snapshot_dir(repo)
    if not snap or os.path.isfile(os.path.join(snap, "tokenizer.json")):
        return
    src_snap = _snapshot_dir(flow.MODEL_NAME)
    src = os.path.join(src_snap, "tokenizer.json") if src_snap else ""
    if not src or not os.path.isfile(src):
        flow.log(f"{repo} ships no tokenizer.json and the default model isn't "
            f"downloaded to lend one — prompts/hotwords will misbehave")
        return
    if _vocab_size(snap) != _vocab_size(src_snap):
        flow.log(f"{repo} has a different vocabulary than the default model — not "
            f"lending an incompatible tokenizer")
        return
    try:
        shutil.copyfile(src, os.path.join(snap, "tokenizer.json"))
        flow.log(f"supplied missing tokenizer.json to {repo}")
    except OSError as e:
        flow.log(f"could not supply tokenizer for {repo} ({e.__class__.__name__}: {e})")


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
    if name in flow.state["models"]:
        return flow.state["models"][name]
    ensure_tokenizer(name)
    want = flow.config.get("compute_type") or ""
    # The CPU fallback must NOT blindly reuse `want`. Someone benchmarking the
    # GPU sets compute_type to "float16", which CTranslate2 cannot run on CPU —
    # so honouring it on the fallback path would turn "CUDA is unavailable, run
    # slowly on the CPU" into "no dictation at all", removing the safety net
    # exactly when it is needed. Only CPU-runnable values carry over.
    cpu_want = want if want in flow.CPU_COMPUTE_TYPES else "int8"
    if flow.config.get("device") == "cpu":
        m = _build_model(name, "cpu", cpu_want)
        flow.log(f"model {name} on CPU (forced, {cpu_want})")
    else:
        try:
            m = _build_model(name, "cuda", want or "int8_float16")
            flow.log(f"model {name} on CUDA ({want or 'int8_float16'})")
        except Exception as e:
            flow.log(f"CUDA failed ({e.__class__.__name__}: {e}), falling back to CPU")
            if want and cpu_want != want:
                flow.log(f"compute_type {want!r} is GPU-only — using {cpu_want!r} on CPU")
            m = _build_model(name, "cpu", cpu_want)
            flow.log(f"model {name} on CPU ({cpu_want})")
    t0 = time.time()
    list(m.transcribe(np.zeros(flow.SAMPLE_RATE, dtype=np.float32), language="en")[0])
    flow.log(f"warm-up done ({time.time() - t0:.1f}s)")
    flow.state["models"][name] = m
    return m


def reload_models() -> None:
    """Drop cached models and re-warm the default on the new compute device."""
    flow.set_status("loading")
    with _model_lock:
        flow.state["models"].clear()
        flow.state["model"] = None
        # a device switch must rebuild Parakeet's sessions too, or it would keep
        # running on the provider it was first loaded with
        flow.state["parakeet"] = None

    def boot():
        try:
            flow.state["model"] = flow.model_for(flow.LANGUAGES[flow.state["lang"]])
            flow.preload_parakeet()
            flow.set_status("idle")
            flow.log("model reloaded on " + flow.config.get("device", "cuda"))
        except Exception as e:
            flow.log(f"model reload failed ({e.__class__.__name__}: {e})")
            flow.set_status("idle")

    threading.Thread(target=boot, daemon=True).start()


def model_name_for(lang: str) -> str:
    """Resolve the picked model's repo id for a language.

    One picker drives both languages, with two guards: an English-only model
    never handles Ukrainian, and the Ukrainian fine-tune never handles English.
    Either mismatch — or a stale key from an older config — falls back to the
    multilingual default."""
    key = flow.config.get("model_uk", "stock")
    spec = flow.MODELS.get(key)
    if spec is None:
        return flow.MODEL_NAME
    if lang == "uk" and spec.get("en"):
        return flow.MODEL_NAME
    if lang != "uk" and key == "uk-ft":
        return flow.MODEL_NAME
    return spec["repo"]


def model_for(lang: str) -> WhisperModel:
    return flow.load_model(model_name_for(lang))
