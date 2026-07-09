# test_pipeline.py — headless smoke test: model loads on CUDA, transcribes, measures speed
import os, sys, time

venv_site = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Lib", "site-packages")
for sub in ("nvidia/cublas/bin", "nvidia/cudnn/bin"):
    p = os.path.join(venv_site, *sub.split("/"))
    if os.path.isdir(p):
        os.add_dll_directory(p)
        os.environ["PATH"] = p + os.pathsep + os.environ["PATH"]

import numpy as np
from faster_whisper import WhisperModel

t0 = time.time()
model = WhisperModel("deepdml/faster-whisper-large-v3-turbo-ct2", device="cuda", compute_type="int8_float16")
print(f"load: {time.time() - t0:.1f}s")

# 5s of quiet noise — checks pipeline runs, not accuracy
audio = (np.random.randn(16000 * 5) * 0.005).astype(np.float32)
t0 = time.time()
segments, info = model.transcribe(audio, language="uk", vad_filter=True)
text = " ".join(s.text for s in segments)
print(f"transcribe 5s: {time.time() - t0:.2f}s, text={text!r}")
print("CUDA PIPELINE OK")
