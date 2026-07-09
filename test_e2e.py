# test_e2e.py — end-to-end accuracy test: Windows SAPI TTS speaks a phrase,
# whisper transcribes it, we check the words came through.
import os, subprocess, time, wave

venv_site = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Lib", "site-packages")
for sub in ("nvidia/cublas/bin", "nvidia/cudnn/bin"):
    p = os.path.join(venv_site, *sub.split("/"))
    if os.path.isdir(p):
        os.add_dll_directory(p)
        os.environ["PATH"] = p + os.pathsep + os.environ["PATH"]

import numpy as np
from faster_whisper import WhisperModel

PHRASE = "The quick brown fox jumps over the lazy dog"
WAV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_test.wav")

ps = f'''
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile("{WAV}", $fmt)
$s.Speak("{PHRASE}")
$s.Dispose()
'''
subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=60)

with wave.open(WAV) as w:
    assert w.getframerate() == 16000, w.getframerate()
    audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
print(f"TTS wav: {len(audio)/16000:.1f}s")

model = WhisperModel("deepdml/faster-whisper-large-v3-turbo-ct2", device="cuda", compute_type="int8_float16")
t0 = time.time()
segments, _ = model.transcribe(audio, language="en", vad_filter=False, beam_size=5)
text = " ".join(s.text.strip() for s in segments).strip()
dt = time.time() - t0
print(f"transcribe: {dt:.2f}s -> {text!r}")

want = {"quick", "brown", "fox", "lazy", "dog"}
got = set(text.lower().replace(".", "").replace(",", "").split())
missing = want - got
print("E2E OK" if not missing else f"E2E FAIL, missing: {missing}")
