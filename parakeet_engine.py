"""Parakeet (optional local engine via onnx-asr): loading, transcription, sentence casing. Moved verbatim out of flow.py."""

import os
import re
import time
import numpy as np

import flow


# ---------------- Parakeet (optional local engine) ----------------
# NVIDIA Parakeet TDT 0.6B v3: a 600M-parameter FastConformer transducer that
# covers 25 European languages including Ukrainian. Published FLEURS uk WER is
# ~6.8% — between whisper-large-v3 (~6.5%) and large-v3-turbo (~7.3%) — at
# several times turbo's speed, and as a transducer it does not invent "дякую за
# перегляд" over silence the way Whisper's subtitle-trained decoder does.
#
# Runtime: onnx-asr, NOT NeMo. NeMo drags in torch (~2.5 GB of wheels, plus its
# own CUDA copy) for a model that is just two ONNX graphs and a greedy loop.
# onnx-asr is a pure-Python wheel whose only hard dependency is numpy; it runs
# on the onnxruntime that faster-whisper already pulls in for Silero VAD, and
# loads ONNX exports of the official checkpoint from Hugging Face. sherpa-onnx
# would also work but ships its own native runtime (a second onnxruntime in the
# process) and a different model packaging, for no gain here.
#
# Everything about Parakeet is optional and imported lazily: the default
# Whisper path never touches onnx_asr, and any failure here (package missing,
# model not downloaded, bad provider) falls back to Whisper for that take.
PARAKEET = {
    # onnx-asr's registry name and the HF repo it resolves to
    "name": "nemo-parakeet-tdt-0.6b-v3",
    "repo": "istupakov/parakeet-tdt-0.6b-v3-onnx",
    "label": "Parakeet TDT 0.6B v3",
    "size": {"int8": "640 MB", "fp32": "2.4 GB"},
}
# ISO codes Parakeet v3 was trained on. Anything else goes to Whisper.
PARAKEET_LANGS = frozenset(
    "bg hr cs da nl en et fi fr de el hu it lv lt mt pl pt ro sk sl es sv ru uk".split())


def local_engine_for(lang: str | None, auto: bool = False) -> str:
    """Which local engine should decode this take: "parakeet" or "whisper".

    Parakeet only when the user picked it AND it can handle the language.
    In auto-language mode there is no language to check up front — Parakeet
    identifies the language itself (it has no language token at all), so it is
    used as is. Unknown values in config fall back to Whisper, never to an error."""
    if flow.config.get("local_engine", "whisper") != "parakeet":
        return "whisper"
    if not auto and lang not in PARAKEET_LANGS:
        return "whisper"
    return "parakeet"


def _parakeet_providers() -> tuple[list[str], str]:
    """onnxruntime providers for Parakeet plus a label for the log.

    CUDA only when the user wants the GPU AND the installed onnxruntime actually
    has the CUDA provider. The stock `onnxruntime` wheel (what requirements.txt
    and the frozen build ship) is CPU-only; the GPU needs `onnxruntime-gpu`
    instead, which conflicts with the CPU wheel in the same environment."""
    try:
        import onnxruntime as ort
        avail = ort.get_available_providers()
    except Exception:
        avail = []
    if flow.config.get("device") != "cpu" and "CUDAExecutionProvider" in avail:
        return ["CUDAExecutionProvider", "CPUExecutionProvider"], "CUDA"
    return ["CPUExecutionProvider"], "CPU"


def _parakeet_quant(device_label: str) -> str:
    """"int8" or "fp32" — see parakeet_quantization in DEFAULTS."""
    q = flow.config.get("parakeet_quantization") or ""
    if q in ("int8", "fp32"):
        return q
    return "fp32" if device_label == "CUDA" else "int8"


def _parakeet_files(quant: str) -> list[str]:
    """Repo files onnx-asr needs for one quantization (the mel preprocessor is
    bundled inside the onnx_asr wheel, so it is not fetched)."""
    sfx = ".int8" if quant == "int8" else ""
    files = ["config.json", "vocab.txt",
             f"encoder-model{sfx}.onnx", f"decoder_joint-model{sfx}.onnx"]
    if quant == "fp32":
        files.append("encoder-model.onnx.data")  # >2 GB external weights
    return files


def parakeet_available() -> bool:
    """True if the onnx-asr package can be imported (cheap spec lookup only)."""
    import importlib.util
    return importlib.util.find_spec("onnx_asr") is not None


def parakeet_installed(quant: str | None = None) -> bool:
    """Are the weights for this (or the currently applicable) quantization on disk?"""
    quant = quant or _parakeet_quant(_parakeet_providers()[1])
    snap = flow._snapshot_dir(PARAKEET["repo"])
    return bool(snap) and all(os.path.isfile(os.path.join(snap, f))
                              for f in _parakeet_files(quant))


def parakeet_status() -> dict:
    """What the settings page needs to draw the engine switch."""
    quant = _parakeet_quant(_parakeet_providers()[1])
    return {"available": parakeet_available(),
            "installed": parakeet_installed(quant),
            "size": PARAKEET["size"][quant], "quant": quant}


def load_parakeet():
    """Build (once) and return the onnx-asr Parakeet recognizer.

    Loads strictly from the local HF snapshot (path=..., which onnx-asr treats
    as offline): a missing model must fail fast and fall back to Whisper, never
    start a 640 MB download in the middle of a dictation. Shares _model_lock with
    Whisper so a settings-triggered reload cannot race a load."""
    with flow._model_lock:
        if flow.state.get("parakeet") is not None:
            return flow.state["parakeet"]
        import onnx_asr  # lazy: optional dependency, only for this engine
        providers, dev = _parakeet_providers()
        quant = _parakeet_quant(dev)
        snap = flow._snapshot_dir(PARAKEET["repo"])
        if not snap or not parakeet_installed(quant):
            raise FileNotFoundError(f"{PARAKEET['label']} ({quant}) is not downloaded")
        t0 = time.time()
        m = onnx_asr.load_model(PARAKEET["name"], snap,
                                quantization="int8" if quant == "int8" else None,
                                providers=providers)
        t1 = time.time()
        # first run allocates arenas / picks kernels; pay it here, not on a take
        m.recognize(np.zeros(flow.SAMPLE_RATE, dtype=np.float32), sample_rate=flow.SAMPLE_RATE)
        flow.log(f"parakeet loaded on {dev} ({quant}) in {t1 - t0:.1f}s, "
            f"warm-up {time.time() - t1:.1f}s")
        flow.state["parakeet"] = m
        return m


def preload_parakeet() -> None:
    """Warm Parakeet in the background-boot thread when it is the chosen engine,
    so the first dictation does not pay the ~4 s load. Never raises."""
    if flow.config.get("local_engine", "whisper") != "parakeet":
        return
    try:
        load_parakeet()
    except Exception as e:
        flow.log(f"parakeet preload failed ({e.__class__.__name__}: {e}) — "
            f"dictation will use Whisper")


def parakeet_transcribe(audio: np.ndarray) -> str:
    """Decode one 16 kHz mono float32 clip with Parakeet. Raises on any failure;
    the caller falls back to Whisper."""
    m = load_parakeet()
    return (m.recognize(audio, sample_rate=flow.SAMPLE_RATE) or "").strip()


def capitalize_sentences(text: str) -> str:
    # uk fine-tune tends to lowercase sentence starts
    return re.sub(
        r"(^|[.!?]\s+)([а-яґєіїa-z])",
        lambda m: m.group(1) + m.group(2).upper(),
        text,
    )
