"""The user's own writing style, learned LOCALLY from their dictation history.

Tools like Willow Voice / Typeless "learn how you write" by shipping your past
texts to their servers. KuubWave cannot do that: a user's history may hold
patients' data, and it must never leave the machine in bulk. So the learning
here is deliberately crude and entirely on-device:

  history texts  ->  a handful of COUNTS (shares, medians)  ->  a fixed template

The only thing that ever reaches the LLM is the template's output — a few
generic sentences like "short sentences, «ти», keep colloquial verb forms" —
which is appended to the polish prompt. No sentence, word, name or number from
the history is copied into it: every word of the profile text comes from the
template fragments in this file (plus a closed allowlist of generic sentence
openers such as «так» / «дивись»). validate_profile_text() re-checks that
promise at runtime as a belt-and-braces guard, and test_style_profile.py pins it.

A trait is only stated when the evidence is strong (enough samples AND a clear
majority); a weak or mixed signal is simply left out, because a wrong style hint
is worse than none — the polish would start "correcting" the user toward a
habit they do not have.

A caveat that shapes which traits exist at all: the history stores the FINAL
text, i.e. what Whisper and the previous polish already punctuated. Punctuation
habits (dashes, "!", sentence splits) are therefore partly the machine's habits,
not the speaker's; word choice (ти/ви, colloquial verb forms, English terms in
Latin, openers) is genuinely the user's. The punctuation traits are phrased as
"don't add X" guards, never as "add more X", so a machine-made habit can at
worst keep the polish from inventing something.

Stdlib only, pure functions, never raises on odd input (None/empty/garbage
rows are skipped). Runtime on the real 2 400-row history: see BUILD_NOTE.
"""
from __future__ import annotations

import re
import statistics
import time

# Measured on a copy of the real history.db (2 433 rows, 2026-10-10): building
# the profile from all rows takes ~0.1 s, so the background rebuild is free.
BUILD_NOTE = "~0.1 s for 2.4k rows"

# Below this many usable texts no trait is ever stated: a brand-new install
# would otherwise get a "style" learned from its first five test phrases.
MIN_SAMPLES = 40
# history rows read per build; the newest ones, since style drifts
MAX_SAMPLES = 5000
# A "usable" text: at least this many words. One-word takes ("так", "дякую")
# say nothing about sentence length or address and would only dilute shares.
MIN_WORDS = 3
# Profile text limits — it rides along in EVERY polish request, so it must stay
# small (tokens, latency) and readable at a glance.
MAX_CHARS = 600
MAX_LINES = 8

_WORD_RE = re.compile(r"[A-Za-zА-Яа-яІіЇїЄєҐґ'’ʼ]+")
_CYR_RE = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")
_LAT_WORD_RE = re.compile(r"(?<![\w'’ʼ])[A-Za-z][A-Za-z0-9.+#_-]*[A-Za-z0-9+#]|(?<![\w'’ʼ])[A-Za-z](?![\w'’ʼ])")
_SENT_SPLIT_RE = re.compile(r"[.!?…]+(?:\s+|$)")
# Covers the common pictographic blocks; enough to tell "never" from "often".
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]")
_DASH_RE = re.compile(r"\s[—–-]\s")
_ELLIPSIS_RE = re.compile(r"…|\.\.\.")

# Second-person forms. "ви" can also be plural "you all", which is why the
# formal side needs the same strong majority before it is stated.
_INFORMAL = {"ти", "тебе", "тобі", "тобою", "твій", "твоя", "твоє", "твої",
             "твого", "твоєї", "твоєму", "твоїй", "твоїм", "твоїх", "твоїми",
             "твою"}
_FORMAL = {"ви", "вас", "вам", "вами", "ваш", "ваша", "ваше", "ваші",
           "вашого", "вашої", "вашому", "вашій", "вашим", "ваших", "вашими",
           "вашу"}

# Colloquial 1st-person-plural verb forms: "зробим" for "зробимо", "берем" for
# "беремо", "займемся" for "займемося". The polish model likes to "fix" these
# (gpt-oss and qwen both did in the 2026-10-09 benchmark), but they are the
# user's real voice. Detected three ways, all conservative:
#   * "-емся/-имся" endings — standard Ukrainian has no such word, so every hit
#     is the colloquial reflexive form;
#   * a "-ем/-им" token whose "-емо/-имо" twin also occurs in the corpus — this
#     filters out "великим", "проблем" etc., which have no "-о" twin;
#   * a "-ем/-им" token right after "давай"/"давайте" ("давай зробим").
_COLLOQ_REFLEXIVE_RE = re.compile(r"^\w{2,}(?:ем|им)ся$")
_SHORT_1PL_RE = re.compile(r"^\w{2,}(?:ем|им)$")
_LONG_1PL_RE = re.compile(r"^\w{2,}(?:емо|имо|емося|имося)$")
_LETS = {"давай", "давайте"}

# Sentence openers that may be named in the profile. CLOSED list of generic
# discourse words — the profile can only ever echo one of these, never a
# user's word. "ну" is deliberately absent: the base prompt lists it as a
# filler to remove, and the profile must not contradict the core rules.
GENERIC_OPENERS = ("так", "добре", "дивись", "слухай", "окей", "давай",
                   "тепер", "зараз", "отже", "короче", "загалом", "ось",
                   "також", "тоді", "ага", "смотри")
# "смотри" is listed only so it can be COUNTED as an opener; it is excluded
# from what gets stated (a Russian word in the profile would invite drift).
_STATEABLE_OPENERS = tuple(o for o in GENERIC_OPENERS if o != "смотри")

# ---- thresholds (each one: how strong evidence must be to state a trait) ----
# address: share of texts with any 2nd-person form that use the majority form
ADDRESS_MIN_TEXTS = 20
ADDRESS_MAJORITY = 0.8
# sentences: median words per sentence
SHORT_SENT_MAX = 9
LONG_SENT_MIN = 18
# "never X": share of texts containing X must be at most this. 0.8% rather
# than a round 1%: on the real history dashes sat at 1.0% — a borderline
# signal, and a borderline trait is exactly the kind not worth stating.
RARE_SHARE = 0.008
# "often X": share of texts containing X must be at least this
OFTEN_SHARE = 0.15
# English terms: share of texts with a Latin-script word, plus a floor count
LATIN_MIN_SHARE = 0.05
LATIN_MIN_TEXTS = 20
# colloquial verb forms: hits, share of texts, and share vs the standard form
COLLOQ_MIN_HITS = 8
COLLOQ_MIN_SHARE = 0.25
# openers: share of usable texts that start with this word, plus a floor count
OPENER_MIN_SHARE = 0.04
OPENER_MIN_COUNT = 15
OPENER_MAX = 3
# lower-case first letter: share of texts that start lower-case
LOWER_START_SHARE = 0.6

# ---- the template. EVERY word of the profile text comes from here. ----
HEADER = ("Звички автора (лише не порушуй їх, текст під них не переписуй; "
          "правила вище та інструкція для програми нижче важливіші):")
T = {
    "address_ty": "Автор звертається на «ти» — не міняй на «ви».",
    "address_vy": "Автор звертається на «ви» — не міняй на «ти».",
    "short_sent": "Короткі речення — не зливай їх у довгі.",
    "long_sent": "Довгі речення — не розбивай їх без потреби.",
    "no_exclaim": "Знаків оклику майже немає — не додавай їх.",
    "exclaim_ok": "Знаки оклику — звична частина стилю, не прибирай їх.",
    "no_emoji": "Без емодзі — не додавай їх.",
    "no_ellipsis": "Без трикрапок — не став їх.",
    "no_dash": "Тире рідкісні — не вставляй їх замість ком.",
    "latin_terms": "Англійські терміни автор пише латиницею — не перекладай і не транслітеруй їх.",
    "colloquial": "Розмовні форми дієслів (як «зробим», «берем», «займемся») — це стиль автора, залиш їх як є.",
    "lower_start": "Автор починає текст з малої літери.",
    # {openers} is filled ONLY from _STATEABLE_OPENERS, quoted «...»
    "openers": "Слова на початку на кшталт {openers} — частина стилю, не прибирай їх.",
}
# order the lines appear in (most useful for the polish first)
_ORDER = ("address_ty", "address_vy", "colloquial", "latin_terms", "openers",
          "short_sent", "long_sent", "no_exclaim", "exclaim_ok", "no_emoji",
          "no_ellipsis", "no_dash", "lower_start")

# Human-readable labels for Settings (Ukrainian, addressed to the user).
LABELS = {
    "address_ty": "Пишете на «ти»",
    "address_vy": "Пишете на «ви»",
    "short_sent": "Короткі речення",
    "long_sent": "Довгі, розгорнуті речення",
    "no_exclaim": "Майже без знаків оклику",
    "exclaim_ok": "Часто ставите знаки оклику",
    "no_emoji": "Без емодзі",
    "no_ellipsis": "Без трикрапок",
    "no_dash": "Рідко ставите тире",
    "latin_terms": "Англійські терміни — латиницею",
    "colloquial": "Розмовні форми дієслів («зробим», «берем»)",
    "lower_start": "Починаєте з малої літери",
    "openers": "Часто починаєте з {openers}",
}


def _words(text: str) -> list[str]:
    return [w.lower().replace("’", "'").replace("ʼ", "'")
            for w in _WORD_RE.findall(text)]


def _sentences(text: str) -> list[str]:
    return [s for s in _SENT_SPLIT_RE.split(text) if _WORD_RE.search(s)]


def _clean(texts) -> list[str]:
    out = []
    for t in texts or []:
        if not isinstance(t, str):
            continue
        t = t.strip()
        if len(t.split()) >= MIN_WORDS and _CYR_RE.search(t):
            out.append(t)
    return out


def compute_stats(texts) -> dict:
    """Aggregate COUNTS over the texts. Every value is a number or one of the
    allowlisted opener words — nothing here can carry content."""
    texts = _clean(texts)
    n = len(texts)
    st = {"samples": n}
    if not n:
        return st
    sent_lens = []
    informal = formal = 0
    excl = emoji = ellipsis = dash = latin = lower = 0
    colloq_hits = colloq_texts = long_forms = 0
    openers = {o: 0 for o in GENERIC_OPENERS}
    vocab = set()
    tokenized = []
    for t in texts:
        ws = _words(t)
        tokenized.append(ws)
        vocab.update(ws)
    for t, ws in zip(texts, tokenized):
        for s in _sentences(t):
            sent_lens.append(len(_WORD_RE.findall(s)))
        wset = set(ws)
        has_i, has_f = bool(wset & _INFORMAL), bool(wset & _FORMAL)
        # a text using both (quoting someone, plural "ви") counts for neither
        if has_i and not has_f:
            informal += 1
        elif has_f and not has_i:
            formal += 1
        excl += "!" in t
        emoji += bool(_EMOJI_RE.search(t))
        ellipsis += bool(_ELLIPSIS_RE.search(t))
        dash += bool(_DASH_RE.search(t))
        latin += bool(_LAT_WORD_RE.search(t))
        first = t.lstrip("«\"'([-—– ")[:1]
        lower += bool(first) and first.islower()
        if ws and ws[0] in openers:
            openers[ws[0]] += 1
        hits = 0
        for i, w in enumerate(ws):
            if _COLLOQ_REFLEXIVE_RE.match(w):
                hits += 1
            elif _SHORT_1PL_RE.match(w) and (
                    (w + "о") in vocab or (i and ws[i - 1] in _LETS)):
                hits += 1
            elif _LONG_1PL_RE.match(w):
                long_forms += 1
        colloq_hits += hits
        colloq_texts += bool(hits)
    st.update({
        "sentence_median": statistics.median(sent_lens) if sent_lens else 0,
        "informal_texts": informal, "formal_texts": formal,
        "exclaim_share": excl / n, "emoji_share": emoji / n,
        "ellipsis_share": ellipsis / n, "dash_share": dash / n,
        "latin_share": latin / n, "latin_texts": latin,
        "lower_start_share": lower / n,
        "colloquial_hits": colloq_hits, "colloquial_texts": colloq_texts,
        "standard_1pl": long_forms,
        "openers": {o: c for o, c in openers.items() if c},
    })
    return st


def derive_traits(st: dict) -> list[str]:
    """Trait ids that the evidence in `st` clearly supports, in _ORDER."""
    n = st.get("samples", 0)
    if n < MIN_SAMPLES:
        return []
    on = set()
    inf, frm = st["informal_texts"], st["formal_texts"]
    if inf + frm >= ADDRESS_MIN_TEXTS:
        if inf / (inf + frm) >= ADDRESS_MAJORITY:
            on.add("address_ty")
        elif frm / (inf + frm) >= ADDRESS_MAJORITY:
            on.add("address_vy")
    med = st["sentence_median"]
    if med and med <= SHORT_SENT_MAX:
        on.add("short_sent")
    elif med >= LONG_SENT_MIN:
        on.add("long_sent")
    if st["exclaim_share"] <= RARE_SHARE:
        on.add("no_exclaim")
    elif st["exclaim_share"] >= OFTEN_SHARE:
        on.add("exclaim_ok")
    if st["emoji_share"] <= RARE_SHARE:
        on.add("no_emoji")
    if st["ellipsis_share"] <= RARE_SHARE:
        on.add("no_ellipsis")
    if st["dash_share"] <= RARE_SHARE:
        on.add("no_dash")
    if (st["latin_share"] >= LATIN_MIN_SHARE
            and st["latin_texts"] >= LATIN_MIN_TEXTS):
        on.add("latin_terms")
    hits, std = st["colloquial_hits"], st["standard_1pl"]
    if hits >= COLLOQ_MIN_HITS and hits / max(1, hits + std) >= COLLOQ_MIN_SHARE:
        on.add("colloquial")
    if st["lower_start_share"] >= LOWER_START_SHARE:
        on.add("lower_start")
    if top_openers(st):
        on.add("openers")
    return [k for k in _ORDER if k in on]


def top_openers(st: dict) -> list[str]:
    n = max(1, st.get("samples", 0))
    ops = st.get("openers") or {}
    good = [(c, o) for o, c in ops.items()
            if o in _STATEABLE_OPENERS and c >= OPENER_MIN_COUNT
            and c / n >= OPENER_MIN_SHARE]
    return [o for _c, o in sorted(good, reverse=True)[:OPENER_MAX]]


def _openers_phrase(ops: list[str]) -> str:
    return ", ".join(f"«{o}»" for o in ops)


def render_text(trait_ids: list[str], st: dict) -> str:
    """The prompt block: HEADER + one line per trait, capped to MAX_LINES /
    MAX_CHARS by dropping the least useful (last in _ORDER) lines. "" when
    there is nothing to say — which makes the whole feature a no-op."""
    lines = []
    for k in trait_ids:
        line = T[k]
        if k == "openers":
            ops = top_openers(st)
            if not ops:
                continue
            line = line.format(openers=_openers_phrase(ops))
        lines.append("- " + line)
    while lines:
        text = "\n".join([HEADER] + lines)
        if len(lines) + 1 <= MAX_LINES and len(text) <= MAX_CHARS:
            return text
        lines.pop()
    return ""


def trait_labels(trait_ids: list[str], st: dict) -> list[dict]:
    out = []
    for k in trait_ids:
        label = LABELS[k]
        if k == "openers":
            label = label.format(openers=_openers_phrase(top_openers(st)))
        out.append({"id": k, "label": label})
    return out


# ---- privacy guard ----
def _template_vocab() -> set[str]:
    words = set()
    for s in [HEADER, *T.values()]:
        words.update(_words(s.replace("{openers}", "")))
    words.update(_STATEABLE_OPENERS)
    return words


ALLOWED_WORDS = frozenset(_template_vocab())
# characters a template line can contain besides letters and spaces
_ALLOWED_PUNCT = set(" \n-—–«»,.:;()'’ʼ")


def validate_profile_text(text: str) -> tuple[bool, str]:
    """(ok, reason). Belt-and-braces check that a profile text is made only of
    template words — run on every build AND every time the text is read from
    config (a hand-edited config.json is just as untrusted as a bug).

    Rejects: digits; any character outside letters/allowed punctuation (so no
    "@", "/", URLs, emoji); any word not in ALLOWED_WORDS (a name, a diagnosis,
    a phrase from the history); a capitalised word that does not start a line
    or sentence (looks like a name even if allowlisted); over-long text."""
    if not isinstance(text, str):
        return False, "not a string"
    if not text:
        return True, ""
    if len(text) > MAX_CHARS or text.count("\n") + 1 > MAX_LINES:
        return False, "too long"
    if any(ch.isdigit() for ch in text):
        return False, "digit"
    for ch in text:
        if not (ch.isalpha() or ch in _ALLOWED_PUNCT):
            return False, f"character {ch!r}"
    for m in _WORD_RE.finditer(text):
        w = m.group(0)
        if w.lower().replace("’", "'").replace("ʼ", "'") not in ALLOWED_WORDS:
            return False, "unknown word"
        if w[:1].isupper():
            before = text[:m.start()].rstrip(" «")
            if before and before[-1] not in ".:\n-—!?":
                return False, "capitalised word mid-sentence"
    return True, ""


def build_profile(texts, now: float | None = None) -> dict:
    """Full build: {"text", "traits", "stats", "samples", "built_at"}.
    Returns text "" (and no traits) when the evidence is too thin, or when the
    validator refuses the rendered text — failing closed, never open."""
    t0 = time.perf_counter()
    if isinstance(texts, list):
        texts = texts[:MAX_SAMPLES]
    st = compute_stats(texts)
    ids = derive_traits(st)
    text = render_text(ids, st)
    ok, _why = validate_profile_text(text)
    if not ok:
        text, ids = "", []
    # stats are rounded aggregates only — safe to keep in config for the UI
    stats = {k: (round(v, 3) if isinstance(v, float) else v)
             for k, v in st.items()}
    return {
        "text": text,
        "traits": trait_labels(ids, st),
        "stats": stats,
        "samples": st.get("samples", 0),
        "built_at": time.strftime("%Y-%m-%d %H:%M",
                                  time.localtime(now if now is not None else time.time())),
        "build_s": round(time.perf_counter() - t0, 3),
    }


def profile_prompt(cfg: dict | None) -> str:
    """The text to append to the polish prompt, or "" when the feature is off,
    the profile is empty, or the stored text fails validation."""
    cfg = cfg or {}
    if not cfg.get("style_profile_enabled", False):
        return ""
    prof = cfg.get("style_profile") or {}
    text = prof.get("text", "") if isinstance(prof, dict) else ""
    if not isinstance(text, str) or not text.strip():
        return ""
    ok, _ = validate_profile_text(text.strip())
    return text.strip() if ok else ""


def is_stale(cfg: dict | None, days: float, now: float | None = None) -> bool:
    """True when the profile was never built or is older than `days`."""
    prof = (cfg or {}).get("style_profile") or {}
    stamp = prof.get("built_at") if isinstance(prof, dict) else None
    if not stamp:
        return True
    try:
        built = time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M"))
    except (TypeError, ValueError):
        return True
    return ((now if now is not None else time.time()) - built) >= days * 86400
