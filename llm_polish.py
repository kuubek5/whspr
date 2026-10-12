"""LLM post-processing: style profile prompt, the Groq/local LLM request with its connection pool, and llm_polish. Moved verbatim out of flow.py."""

import os
import json
import time
import threading
import io
import urllib.error
import urllib.parse
import urllib.request
import http.client
import ssl
import text_fixes
import app_styles
import style_profile

import flow


# ---------------- LLM post-processing ----------------
# Still the pre-rename name: it is a user-set environment variable, and renaming
# it would silently stop honouring a key someone already exported.
GROQ_KEY_ENV = "WHSPR_GROQ_API_KEY"


def groq_key() -> str:
    """The Groq API key: environment first, config.json second.

    config.json is gitignored, but it is still a plaintext secret sitting in the
    project folder, and it travels with any backup, support log or screen share
    of the settings screen. The environment variable gives anyone who cares a
    way to keep the key out of the file entirely; leaving it unset keeps the
    existing behaviour exactly, so nothing breaks for a user who never sets it.

    Never log the return value."""
    return (os.environ.get(GROQ_KEY_ENV) or flow.config.get("groq_api_key") or "").strip()


def llm_available() -> bool:
    mode = flow.config.get("llm", "off")
    if mode == "groq":
        return bool(groq_key())
    return mode == "ollama"


# Kept-alive HTTP(S) connections for the LLM call, one parked per host.
# urlopen() builds a new TCP + TLS session for every request; to api.groq.com
# that measured ~60 ms of a ~0.26 s round trip on this machine (GET /models,
# fresh vs reused, 15 alternating pairs), paid on EVERY polish. Groq kept an
# idle connection open for at least 90 s, so back-to-back dictations reuse it,
# and _llm_prewarm opens one while the user is still talking so even the first
# take after a long idle skips the handshake.
#
# A connection is checked OUT of the pool for the duration of a request, so two
# threads (sync polish + an async rewrite, command mode) never share a socket:
# the second simply opens its own, and only one is parked afterwards.
_http_pool: dict[tuple[str, str], tuple["http.client.HTTPConnection", float]] = {}
_http_pool_lock = threading.Lock()
# Past this idle time a parked connection is presumed dead (servers and NATs
# drop idle TCP silently) and replaced up front rather than discovered stale.
_HTTP_IDLE_MAX_S = 60.0
# Errors that mean "the kept-alive socket was already closed by the other end"
# — raised before any response, so the request never ran and one retry on a
# fresh connection is safe.
_HTTP_STALE = (http.client.RemoteDisconnected, http.client.CannotSendRequest,
               ConnectionError, ssl.SSLEOFError)


def _http_new(scheme: str, netloc: str, timeout: float):
    cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    return cls(netloc, timeout=timeout)


def _http_take(scheme: str, netloc: str, timeout: float):
    """(connection, reused?) — a parked one if still fresh, else a new one."""
    with _http_pool_lock:
        conn, last = _http_pool.pop((scheme, netloc), (None, 0.0))
    if conn is not None:
        if time.monotonic() - last <= _HTTP_IDLE_MAX_S:
            conn.timeout = timeout
            if conn.sock is not None:
                conn.sock.settimeout(timeout)
            return conn, True
        conn.close()
    return _http_new(scheme, netloc, timeout), False


def _http_park(scheme: str, netloc: str, conn) -> None:
    with _http_pool_lock:
        old = _http_pool.get((scheme, netloc))
        _http_pool[(scheme, netloc)] = (conn, time.monotonic())
    if old is not None and old[0] is not conn:
        old[0].close()


def _http_post_json(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    """POST JSON, return the parsed JSON reply, over a kept-alive connection.

    Behaves like the urlopen() it replaces for every caller-visible outcome:
    a 4xx/5xx raises urllib.error.HTTPError (same .code), a network failure
    raises OSError/HTTPException, so _llm_request's except-all and back-off
    are unchanged. If a system/env HTTPS proxy is configured, falls back to
    urlopen outright: http.client does not honour proxies and a dictation that
    silently stops polishing behind a corporate proxy is worse than 60 ms."""
    body = json.dumps(payload).encode("utf-8")
    u = urllib.parse.urlsplit(url)
    if urllib.request.getproxies().get(u.scheme):
        req = urllib.request.Request(url, body, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    path = u.path + (f"?{u.query}" if u.query else "")
    for attempt in (0, 1):
        conn, reused = _http_take(u.scheme, u.netloc, timeout)
        try:
            conn.request("POST", path, body, headers)
            resp = conn.getresponse()
            data = resp.read()
        except _HTTP_STALE:
            conn.close()
            if reused and attempt == 0:
                continue  # parked socket was dead; the request never ran
            raise
        except BaseException:
            conn.close()
            raise
        if resp.will_close or resp.status >= 400:
            # an error reply may come with the server about to hang up; never
            # park a connection we are not sure about
            conn.close()
        else:
            _http_park(u.scheme, u.netloc, conn)
        if resp.status >= 400:
            raise urllib.error.HTTPError(url, resp.status, resp.reason,
                                         resp.headers, io.BytesIO(data))
        return json.loads(data)
    raise ConnectionError("unreachable")  # loop always returns or raises


def _llm_prewarm() -> None:
    """Open the Groq connection in the background while the user is still
    talking (called from start_rec), so the polish request after the take goes
    straight out on an established TLS session. No-op unless Groq polish is on
    and no fresh connection is already parked. Never raises, never logs the
    key — it sends no request at all, only the TCP/TLS handshake. Everything,
    the checks included, runs on its own thread: the caller is the hotkey
    listener, which must never wait on a registry read or a DNS lookup."""
    def work():
        try:
            if flow.config.get("llm") != "groq" or not groq_key():
                return
            if urllib.request.getproxies().get("https"):
                return  # _http_post_json uses urlopen then; nothing to warm
            key = ("https", "api.groq.com")
            with _http_pool_lock:
                parked = _http_pool.get(key)
            if parked is not None and time.monotonic() - parked[1] <= _HTTP_IDLE_MAX_S:
                return
            conn = _http_new(*key, 15)
            conn.connect()
            _http_park(*key, conn)
        except Exception:
            pass  # the real request just opens its own, as before
    threading.Thread(target=work, daemon=True).start()


def _llm_label() -> str:
    """'groq:<model>[/<effort>]' or 'ollama:<model>' for the latency line —
    provider and model only, never the key or any text."""
    mode = flow.config.get("llm", "off")
    if mode == "groq":
        model = flow.config.get("groq_model", flow.DEFAULTS["groq_model"])
        effort = _groq_reasoning_effort(model)
        return f"groq:{model}" + (f"/{effort}" if effort else "")
    if mode == "ollama":
        return f"ollama:{flow.config.get('ollama_model', flow.DEFAULTS['ollama_model'])}"
    return mode


def _groq_reasoning_effort(model: str, key: str = "groq_reasoning_effort") -> str | None:
    """reasoning_effort to send with a Groq request, or None to send none.
    `key` is the config entry to read (polish: groq_reasoning_effort, Scribe:
    scribe_reasoning_effort). Only the gpt-oss family is known to accept the
    field; sending it to a model that does not is a 400, i.e. a polish that
    silently never happens plus a 60 s back-off — so any other model gets the
    plain request."""
    # str(): a hand-edited config.json can hold anything, and _llm_label calls
    # this outside any try on the dictation path
    effort = str(flow.config.get(key) or "").strip().lower()
    if effort in ("low", "medium", "high") and str(model).startswith("openai/gpt-oss"):
        return effort
    return None


def _llm_request(system_prompt: str, user_text: str, label: str,
                 groq_model: str | None = None) -> str | None:
    """One chat call to the configured provider. Returns the reply, or None on
    any failure (with a shared back-off so an unreachable provider doesn't add a
    connection timeout to every request). `groq_model` overrides the configured
    Groq model for this one call (ignored for Ollama)."""
    mode = flow.config.get("llm", "off")
    if mode == "off" or not user_text:
        return None
    if time.time() < flow.state.get("llm_down_until", 0):
        return None
    try:
        # a browser-like User-Agent is required: Groq sits behind Cloudflare,
        # which blocks urllib's default "Python-urllib/x.y" agent with a 403
        # (Cloudflare error 1010) before the request ever reaches the API
        headers = {"Content-Type": "application/json", "User-Agent": flow.HTTP_UA}
        if mode == "groq":
            key = groq_key()
            if not key:
                return None
            url = "https://api.groq.com/openai/v1/chat/completions"
            model = groq_model or flow.config.get("groq_model", flow.DEFAULTS["groq_model"])
            headers["Authorization"] = f"Bearer {key}"
        elif mode == "ollama":
            # 127.0.0.1, not localhost: the latter resolves to ::1 first and
            # doubles the wait when nothing is listening
            url = "http://127.0.0.1:11434/v1/chat/completions"
            model = flow.config.get("ollama_model", flow.DEFAULTS["ollama_model"])
        else:
            return None
        payload = {"model": model, "temperature": 0.2, "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}]}
        # polish and Scribe only, each with its own setting: command mode and
        # the voice rewrite follow free-form instructions and keep Groq's
        # default, where the extra thinking is worth its time
        effort = None
        if mode == "groq" and label == "polish":
            effort = _groq_reasoning_effort(model)
        elif mode == "groq" and label == "scribe":
            effort = _groq_reasoning_effort(model, "scribe_reasoning_effort")
        if effort:
            payload["reasoning_effort"] = effort
        t0 = time.time()
        reply = flow._http_post_json(url, payload, headers, timeout=15)
        out = (reply["choices"][0]["message"].get("content") or "").strip()
        flow.log(f"llm {label} ({mode}): {time.time() - t0:.2f}s")
        flow.state["llm_down_until"] = 0
        return out or None
    except Exception as e:
        flow.state["llm_down_until"] = time.time() + flow.LLM_BACKOFF_S
        flow.log(f"llm {label} failed ({e.__class__.__name__}: {e}); "
            f"skipping llm for {flow.LLM_BACKOFF_S}s")
        return None


def style_profile_prompt(cfg: dict | None = None) -> str:
    """The user's learned style block for an LLM prompt, or "" when the
    feature is off, no profile has been built, or the stored text fails the
    privacy validator. Public on purpose: other prompt builders (e.g. Scribe)
    look it up with getattr(flow, "style_profile_prompt") — keep the name and
    signature. Never raises: a broken profile must cost the style hint, not the
    dictation."""
    try:
        return style_profile.profile_prompt(flow.config if cfg is None else cfg)
    except Exception:
        return ""


def compose_polish_prompt(style: str | None = None,
                          correction: bool = False) -> str:
    """System prompt for one polish: base -> style profile -> per-app style.

    Order matters. The base rules (custom llm_prompt or LLM_PROMPT) come first
    and stay in charge. The user's habits come next and say outright that the
    rules above and the per-app instruction below win. The per-app style goes
    LAST, so on a conflict ("розмовно" for a chat vs. a habit learned mostly
    from neat text) the more specific, closer-to-the-end instruction is the
    one the model follows — and the profile text itself tells it so."""
    # a non-empty llm_prompt in config overrides the built-in instruction, so
    # the admin can tune the corrector from Settings without touching code; blank
    # falls back to the shipped default (and picks up its future improvements).
    prompt = (flow.config.get("llm_prompt") or "").strip() or flow.LLM_PROMPT
    # right after the base rules it is an exception to; only for takes that
    # carry a correction marker (see SELF_CORRECTION_RULE)
    if correction:
        prompt = f"{prompt}\n\n{flow.SELF_CORRECTION_RULE}"
    habits = flow.style_profile_prompt(flow.config)
    if habits:
        prompt = f"{prompt}\n\n{habits}"
    # the per-app style is APPENDED, so the core rules above — custom or
    # shipped — still govern; None/"default" leaves the prompt untouched
    return app_styles.compose_prompt(prompt, style, flow.config)


_style_build_lock = threading.Lock()


def rebuild_style_profile(reason: str = "manual") -> dict:
    """Recount the user's writing habits from the local history and store the
    result in config. Everything happens on this machine: the history is read
    from history.db, reduced to counts, and only the template text derived
    from those counts is kept (style_profile.build_profile validates it).

    The log line names trait ids and counts only — never a text. Returns the
    stored profile ({} on failure, leaving the previous profile in place)."""
    with _style_build_lock:
        try:
            texts = [row[4] for row in flow.history_last(style_profile.MAX_SAMPLES)]
            prof = style_profile.build_profile(texts)
        except Exception as e:
            flow.log(f"style profile build failed ({e.__class__.__name__})")
            return {}
        flow.config["style_profile"] = prof
        try:
            flow.save_config(flow.config)
        except Exception as e:
            flow.log(f"style profile save failed ({e.__class__.__name__})")
        ids = ",".join(t["id"] for t in prof.get("traits", [])) or "none"
        flow.log(f"style profile rebuilt ({reason}): {prof.get('samples', 0)} takes, "
            f"traits={ids}, {prof.get('build_s', 0):.2f}s")
        return prof


def maybe_rebuild_style_profile() -> None:
    """Background refresh at startup, at most once per style_profile_auto_days.
    Cheap (~0.06 s on 2.4k takes) but still off the boot path."""
    try:
        days = float(flow.config.get("style_profile_auto_days",
                                flow.DEFAULTS["style_profile_auto_days"]) or 0)
    except (TypeError, ValueError):
        days = flow.DEFAULTS["style_profile_auto_days"]
    if days <= 0 or not style_profile.is_stale(flow.config, days):
        return
    threading.Thread(target=rebuild_style_profile, args=("auto",),
                     daemon=True).start()


def llm_polish(text: str, lang: str, style: str | None = None) -> str:
    """Optional cleanup pass. Any failure returns the raw text.

    A short dictated imperative ("Так роби всі три") reads to the model as an
    instruction, and it answers with a meta-reply ("надайте текст, який потрібно
    виправити") instead of correcting anything. Pasting that would overwrite the
    user's words with a chatbot line, so polish_is_safe vets the result and we
    fall back to the raw text when it looks like the model answered rather than
    corrected. The prompt hardening reduces how often this happens; the guard is
    what makes it safe when it happens anyway."""
    # Self-correction path: only a take with a correction marker gets the rule
    # that lets the model delete words, on the stronger model, and its answer
    # must pass self_correction_ok. A rejected answer falls through to the
    # ordinary polish below, exactly as if the feature were off.
    if (flow.config.get("self_correction", True)
            and text_fixes.has_correction_marker(text)):
        out = flow._llm_request(compose_polish_prompt(style, correction=True), text,
                           "polish", flow.config.get("self_correction_model")
                           or flow.DEFAULTS["self_correction_model"])
        if (out and text_fixes.polish_is_safe(text, out)
                and text_fixes.self_correction_ok(text, out)):
            return out
        if out:
            flow.log(f"self-correction rejected, plain polish instead: {out!r}")
    # base prompt + the user's learned habits + per-app style; see
    # compose_polish_prompt for the order and why the per-app style wins
    prompt = compose_polish_prompt(style)
    out = flow._llm_request(prompt, text, "polish")
    if not out:
        return text
    if not text_fixes.polish_is_safe(text, out):
        flow.log(f"llm polish rejected (looks like a reply, not a correction): {out!r}")
        return text
    return out
