"""Bring-your-own-key cloud speech-to-text (Groq, OpenAI, ElevenLabs). Moved verbatim out of flow.py."""

import io
import json
import os
import urllib.error
import urllib.request
import uuid
import wave
import numpy as np

import flow

# ---------------- Cloud recognition (BYOK) ----------------
def _wav_bytes(audio) -> bytes:
    """Float32 mono @ SAMPLE_RATE -> 16-bit PCM WAV bytes for a multipart upload."""
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(flow.SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _multipart(fields: dict, file_field: str, filename: str, filedata: bytes,
               filetype: str = "audio/wav"):
    """Build a multipart/form-data body (urllib has no multipart helper)."""
    boundary = "----kuubwave" + uuid.uuid4().hex
    crlf = "\r\n"
    out = io.BytesIO()
    for k, v in fields.items():
        if v is None:
            continue
        out.write(("--" + boundary + crlf).encode())
        out.write((f'Content-Disposition: form-data; name="{k}"' + crlf + crlf).encode())
        out.write((str(v) + crlf).encode())
    out.write(("--" + boundary + crlf).encode())
    out.write((f'Content-Disposition: form-data; name="{file_field}"; '
               f'filename="{filename}"' + crlf).encode())
    out.write((f"Content-Type: {filetype}" + crlf + crlf).encode())
    out.write(filedata)
    out.write(crlf.encode())
    out.write(("--" + boundary + "--" + crlf).encode())
    return out.getvalue(), "multipart/form-data; boundary=" + boundary


def _cloud_transcribe(audio, lang_hint: str | None = None) -> str:
    """Send the clip to the configured cloud STT provider and return the text.

    BYOK: each provider uses the user's own key. Groq reuses groq_key() (shared
    with LLM polish); OpenAI/ElevenLabs use their own keys. Raises on any failure
    so the caller can fall back to a status message rather than pasting nothing."""
    provider = flow.config.get("stt_provider", "groq")
    model = flow.config.get("stt_model", "whisper-large-v3")
    wav = _wav_bytes(audio)
    if provider == "groq":
        key = flow.groq_key()
        if not key:
            raise RuntimeError("no Groq API key")
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        fields = {"model": model, "response_format": "json"}
        if lang_hint:
            fields["language"] = lang_hint
        headers = {"Authorization": "Bearer " + key}
    elif provider == "openai":
        key = (os.environ.get("OPENAI_API_KEY") or flow.config.get("openai_api_key") or "").strip()
        if not key:
            raise RuntimeError("no OpenAI API key")
        url = "https://api.openai.com/v1/audio/transcriptions"
        fields = {"model": model, "response_format": "json"}
        if lang_hint:
            fields["language"] = lang_hint
        headers = {"Authorization": "Bearer " + key}
    elif provider == "elevenlabs":
        key = (os.environ.get("ELEVENLABS_API_KEY") or flow.config.get("elevenlabs_api_key") or "").strip()
        if not key:
            raise RuntimeError("no ElevenLabs API key")
        url = "https://api.elevenlabs.io/v1/speech-to-text"
        fields = {"model_id": model}
        if lang_hint:
            fields["language_code"] = lang_hint
        headers = {"xi-api-key": key}
    else:
        raise RuntimeError(f"unknown STT provider {provider!r}")
    body, ctype = _multipart(fields, "file", "audio.wav", wav)
    headers["Content-Type"] = ctype
    headers["User-Agent"] = flow.HTTP_UA  # Cloudflare 403s the default urllib agent
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        # surface the provider's own message (bad key, no credits, wrong model)
        detail = ""
        try:
            payload = json.loads(e.read().decode("utf-8", "replace"))
            detail = (payload.get("error", {}) or {}).get("message") \
                or payload.get("detail") or payload.get("message") or ""
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("status") or str(detail)
        except Exception:
            pass
        raise RuntimeError(f"{provider} HTTP {e.code}: {detail or e.reason}")
    return (data.get("text") or "").strip()


def verify_stt() -> dict:
    """Test the currently configured cloud provider/model/key with one tiny real
    request. Returns {ok, message}. Catches the common failures the user hits —
    a bad key, no credits, or a wrong model — with the provider's own wording."""
    provider = flow.config.get("stt_provider", "groq")
    # 0.4 s of a quiet tone: a structurally valid clip the API will accept, so a
    # 200 proves key + credits + model, while auth/quota faults return non-200.
    n = int(flow.SAMPLE_RATE * 0.4)
    t = np.arange(n, dtype=np.float32) / flow.SAMPLE_RATE
    tone = (0.05 * np.sin(2 * np.pi * 220.0 * t)).astype(np.float32)
    try:
        _cloud_transcribe(tone, None)
        return {"ok": True, "message": f"{provider}: ключ працює"}
    except Exception as e:
        flow.log(f"stt verify failed ({e.__class__.__name__}: {e})")
        return {"ok": False, "message": str(e)}
