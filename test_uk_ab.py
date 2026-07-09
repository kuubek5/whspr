# test_uk_ab.py — A/B: stock deepdml turbo vs skypro1111 Ukrainian fine-tune.
# Edge-TTS (uk-UA-OstapNeural) speaks test phrases, both models transcribe.
import asyncio, os, subprocess, sys, time, wave

BASE = os.path.dirname(os.path.abspath(__file__))
venv_site = os.path.join(BASE, ".venv", "Lib", "site-packages")
for sub in ("nvidia/cublas/bin", "nvidia/cudnn/bin"):
    p = os.path.join(venv_site, *sub.split("/"))
    if os.path.isdir(p):
        os.add_dll_directory(p)
        os.environ["PATH"] = p + os.pathsep + os.environ["PATH"]

import numpy as np
from faster_whisper import WhisperModel

PHRASES = [
    "Раз, два, три, чотири, п'ять — перевірка мікрофона.",
    "Надішли мені, будь ласка, звіт щодо проєкту до вечора.",
    "Зустрінемось біля кав'ярні о пів на восьму.",
    "Ключова ідея — локальне розпізнавання мовлення без хмари.",
    "Потрібно оновити прошивку квадрокоптера і перевірити пропелери.",
]
VOICE = "uk-UA-OstapNeural"


async def synth(text: str, path_mp3: str):
    import edge_tts
    await edge_tts.Communicate(text, VOICE).save(path_mp3)


def to_pcm(path_mp3: str) -> np.ndarray:
    # decode via PyAV (ships with faster-whisper)
    import av
    container = av.open(path_mp3)
    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    samples = []
    for frame in container.decode(audio=0):
        for f in resampler.resample(frame):
            samples.append(f.to_ndarray().flatten())
    audio = np.concatenate(samples).astype(np.float32) / 32768.0
    return audio


def wer(ref: str, hyp: str) -> float:
    norm = lambda s: [w.strip(".,!?—:;'\"’").lower() for w in s.split() if w.strip(".,!?—:;")]
    r, h = norm(ref), norm(hyp)
    d = [[0] * (len(h) + 1) for _ in range(len(r) + 1)]
    for i in range(len(r) + 1): d[i][0] = i
    for j in range(len(h) + 1): d[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i][j] = min(d[i-1][j] + 1, d[i][j-1] + 1,
                          d[i-1][j-1] + (r[i-1] != h[j-1]))
    return d[len(r)][len(h)] / max(len(r), 1)


def main():
    clips = []
    for i, ph in enumerate(PHRASES):
        mp3 = os.path.join(BASE, f"uk_test_{i}.mp3")
        if not os.path.isfile(mp3):
            asyncio.run(synth(ph, mp3))
        clips.append((ph, to_pcm(mp3)))
    print(f"synthesized {len(clips)} clips", flush=True)

    models = {
        "stock ": "deepdml/faster-whisper-large-v3-turbo-ct2",
        "uk-ft ": "skypro1111/whisper-large-v3-turbo-ukrainian-ukraine-3percent-ct2",
    }
    dev = ("cpu", "int8") if "--cpu" in sys.argv else ("cuda", "int8_float16")
    for tag, name in models.items():
        m = WhisperModel(name, device=dev[0], compute_type=dev[1])
        total, t_sum = 0.0, 0.0
        for ph, audio in clips:
            t0 = time.time()
            segs, _ = m.transcribe(audio, language="uk", vad_filter=False,
                                   beam_size=5, condition_on_previous_text=False)
            hyp = " ".join(s.text.strip() for s in segs).strip()
            t_sum += time.time() - t0
            w = wer(ph, hyp)
            total += w
            print(f"[{tag}] WER {w:.2f} | {hyp}", flush=True)
        print(f"[{tag}] AVG WER {total/len(clips):.3f}, avg time {t_sum/len(clips):.2f}s", flush=True)
        del m


if __name__ == "__main__":
    main()
