"""Pure text repairs for whspr transcripts — stdlib only, no I/O, no state.

Three defects measured on the user's own 3822-dictation history live here:

 1. YouTube-subtitle hallucinations glued onto genuine speech. flow.py already
    drops a take that is *only* an artifact (`_hallucination_reason`), but that
    rule compares the whole string, so "Покажи мені Дякую за перегляд!" goes
    into the user's document artifact and all. `trim_artifacts` handles the
    glued-on case; `is_pure_artifact` reproduces flow.py's whole-string rule so
    flow.py can delegate instead of keeping a second copy of the phrase list.

 2. Latin brand/tech names transliterated into Cyrillic by the Ukrainian
    decoder ("Wispr Flow" -> "віспор флоу"). `hotwords` only biases the
    decoder, it never guarantees the spelling, so a post-pass is needed.

 3. Russian leaking into a Ukrainian take (2.0% of takes, 75 of 3822).
    `ru_chars` / `ru_score` / `looks_russian` are detectors only — the retry
    policy belongs to flow.py.

Nothing here imports flow, so every rule is testable without a model, a
microphone or a config file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from itertools import product

# ---------------------------------------------------------------- shared bits

# Whisper emits all four apostrophe shapes for the same Ukrainian sound, and
# an apostrophe is word-INTERNAL here: "п'ять" is one token, not two. Every
# tokenisation and comparison below therefore folds them onto ASCII "'".
# Same list as flow.py's _norm_apos (~line 700) plus the ASCII one it produces.
_APOS = "'’ʼ`"

# Word tokens keep internal apostrophes; runs of punctuation/whitespace are
# tokens too, so re-joining the list reproduces the input byte for byte and the
# user's original spacing survives every rewrite. Mirrors normalize_numbers()
# in flow.py, widened to all apostrophe variants.
_TOKEN_RE = re.compile(r"[^\W_]+(?:[" + _APOS + r"][^\W_]+)*|\W+|_", re.UNICODE)
_IS_WORD = re.compile(r"[^\W_]", re.UNICODE)


def _norm_apos(s: str) -> str:
    """Fold every apostrophe variant onto ASCII "'" — flow.py's helper, copied
    rather than imported so this module stays dependency-free."""
    return s.replace("’", "'").replace("ʼ", "'").replace("`", "'")


def _fold(s: str) -> str:
    """Comparison key: apostrophes normalised, case folded. Never used as
    output — every replacement is built from the original or the dictionary."""
    return _norm_apos(s).lower()


# ------------------------------------------------- 1. subtitle hallucinations

# The seven phrases flow.py ships today (flow.py line 259), lowercased, plus
# well-known Whisper subtitle residue in the three languages this app sees.
#
# Membership rule, applied to every addition: the phrase must be something a
# person NEVER dictates into a text field. That is why "дякую" alone, "дякую за
# увагу", "see you next time" and "please subscribe" are absent — all four are
# ordinary things to say, and flow.py already catches an unconfidently decoded
# short take by its logprob instead. The Russian entries are safe for a
# different reason: this user dictates Ukrainian and English only, so a Russian
# YouTube sign-off is never their speech.
HALLUCINATIONS: frozenset[str] = frozenset({
    # --- exactly what flow.py has today (the single source of truth) ---
    "дякую за перегляд", "дякую за перегляд!", "субтитри створені спільнотою amara.org",
    "продовження в наступній серії", "підпишіться на канал",
    "thanks for watching", "thank you for watching",
    # --- Ukrainian subtitle residue ---
    "субтитри від спільноти amara.org",
    "редактор субтитрів а.семкін коректор а.єгорова",
    "дякую за перегляд і до зустрічі",
    "підписуйтесь на канал",
    # --- Russian subtitle residue (never this user's speech) ---
    "спасибо за просмотр", "спасибо за просмотр!",
    "подписывайтесь на канал", "продолжение следует",
    "субтитры сделал димитрий лозовский",
    "редактор субтитров а.синецкая корректор а.егорова",
    # --- English subtitle residue ---
    "subtitles by the amara.org community",
    "thanks for watching!", "thank you for watching!",
    "thanks for watching everyone",
    "don't forget to subscribe",
})

# Punctuation that may sit around an artifact without being part of it. Trimmed
# off both the stored phrases and the candidate text before comparing, so
# "Дякую за перегляд…" and "дякую за перегляд!!!" match the same entry.
_EDGE_PUNCT = " \t\n\r.,!?…:;\"'«»„“”()[]{}-–—"


def _base(phrase: str) -> str:
    """Bare comparison form of a phrase: folded, edge punctuation removed,
    internal whitespace collapsed."""
    return re.sub(r"\s+", " ", _fold(phrase).strip(_EDGE_PUNCT)).strip()


_BASES: frozenset[str] = frozenset(_base(h) for h in HALLUCINATIONS if _base(h))


def is_pure_artifact(text: str) -> bool:
    """True when the whole utterance is nothing but a known artifact.

    This is flow.py's existing whole-string rule, so flow.py can delegate and
    the phrase list stops existing in two places. It is a deliberate SUPERSET
    of the current comparison (which strips only " .!?"): an ellipsis, quotes
    or doubled punctuation around the same phrase is still the same artifact,
    and the extra tolerance cannot reach real speech because the whole string
    still has to reduce to a listed phrase."""
    return _base(text) in _BASES if text else False


@lru_cache(maxsize=2)
def _edge_patterns() -> tuple[re.Pattern[str], re.Pattern[str]]:
    """Regexes that bite an artifact off the head / tail of a transcript.

    Longest phrase first, so "дякую за перегляд і до зустрічі" wins over the
    prefix "дякую за перегляд" and the leftover " і до зустрічі" is not left
    dangling in the user's text."""
    alts = []
    for base in sorted(_BASES, key=len, reverse=True):
        # words joined by \s+ so a line break inside the artifact still matches;
        # re.escape keeps "amara.org"'s dot literal
        alts.append(r"\s+".join(re.escape(w) for w in base.split(" ")))
    alt = "(?:" + "|".join(alts) + ")"
    # Both patterns demand a word boundary on the phrase's inner side: the
    # lookbehind/lookahead pair rejects a match inside a longer word, and the
    # apostrophe class is there because an apostrophe is word-internal in
    # Ukrainian and Python's \b would happily break on it.
    head = re.compile(
        r"^[\s\"'«„“(\[]*" + alt + r"(?![^\W_])(?![" + _APOS + r"])[\s.,!?…:;\"'»”)\]\-–—]*",
        re.IGNORECASE | re.UNICODE)
    tail = re.compile(
        r"[\s\-–—]*(?<![^\W_])(?<![" + _APOS + r"])" + alt
        + r"[\s.,!?…:;\"'»”)\]]*$",
        re.IGNORECASE | re.UNICODE)
    return head, tail


def trim_artifacts(text: str) -> tuple[str, list[str]]:
    """Strip known artifact phrases from the START and END of a transcript.

    Returns (cleaned_text, removed_phrases).

    Edges only. An artifact-looking phrase in the MIDDLE of a sentence is far
    more likely to be real speech ("я подзвонив і сказав дякую за перегляд
    відео") and eating it would destroy the user's text; a hallucinated
    sign-off, by construction, is decoded at one end of the clip or the other.

    If trimming would leave nothing behind, the ORIGINAL text is returned with
    an empty removed list. The whole-utterance case is is_pure_artifact()'s job
    and the caller handles it separately (flow.py drops the take and says "не
    розчув"); silently pasting an empty string instead is worse than pasting
    the artifact."""
    if not text or not text.strip():
        return text, []
    head, tail = _edge_patterns()
    cur, removed = text, []
    # loop: a clip can end with two stacked artifacts
    # ("Дякую за перегляд! Підпишіться на канал")
    while True:
        m = tail.search(cur)
        if m and m.group().strip():
            removed.append(m.group().strip())
            cur = cur[:m.start()]
            continue
        m = head.match(cur)
        if m and m.group().strip():
            removed.append(m.group().strip())
            cur = cur[m.end():]
            continue
        break
    cleaned = cur.strip()
    if not removed:
        return text, []
    if not cleaned:
        return text, []
    return cleaned, removed


# ----------------------------------------------- 2. Latin term restoration

# Latin -> Cyrillic renderings the Ukrainian decoder actually produces. Longer
# keys are consumed first, so "sh" never decomposes into "s" + "h".
#
# Several letters carry more than one rendering because Whisper is inconsistent
# about them: "i" comes back as і or и, "w" as в or у ("flow" -> "флов" AND
# "флоу"), "g" as г, ґ or дж. Every alternative multiplies the candidate set,
# which is cheap (tens of strings per term, built once and cached) and is what
# lets the exact-match layer carry most of the work before fuzzy matching is
# even considered.
_TRANSLIT: dict[str, tuple[str, ...]] = {
    "sch": ("щ",), "tch": ("ч",),
    "ch": ("ч", "х", "к"), "sh": ("ш",), "zh": ("ж",), "kh": ("х",),
    "ph": ("ф",), "th": ("т",), "ck": ("к",), "qu": ("кв",), "ts": ("ц",),
    "oo": ("у",), "ee": ("і", "и"), "ea": ("і", "е"),
    "ow": ("оу", "ов", "о"), "ou": ("у", "ау", "оу"),
    "ai": ("ай", "ей"), "ay": ("ей", "ай"), "ey": ("ей", "і"),
    "ya": ("я",), "yu": ("ю",), "ju": ("джу", "ю"),
    "ge": ("дж", "ге", "ґе"), "gi": ("джі", "гі"),
    "ia": ("ія", "іа"), "io": ("іо", "йо"),
    "a": ("а",), "b": ("б",), "c": ("к", "ц", "с"), "d": ("д",),
    "e": ("е", "і"), "f": ("ф",), "g": ("г", "ґ", "дж"), "h": ("х", "г", ""),
    "i": ("і", "и"), "j": ("дж", "й"), "k": ("к",), "l": ("л",), "m": ("м",),
    "n": ("н",), "o": ("о",), "p": ("п",), "q": ("к",), "r": ("р",),
    "s": ("с", "з"), "t": ("т",), "u": ("у", "ю", "а"), "v": ("в",),
    "w": ("в", "у"), "x": ("кс",), "y": ("и", "й", "і"), "z": ("з",),
}
_MAX_KEY = max(len(k) for k in _TRANSLIT)
# Hard ceiling on generated spellings per word / per term. Nothing in a sane
# dictionary comes close (the worst real entry, "antigravity", makes ~80), but
# a pathological term must not turn a keystroke into a combinatorial explosion.
_MAX_WORD_VARIANTS = 400
_MAX_TERM_VARIANTS = 2000

# Fuzzy cutoff for "this Cyrillic blob is a mangled dictionary term".
#
# 0.88, not the 0.82 that was the starting suggestion. A single substituted
# letter in an n-letter word scores (n-1)/n: 0.83 at 6 letters, 0.86 at 7.
# At 0.82 an ordinary Ukrainian word one letter away from a candidate — "герпес"
# against Hermes' "гермес" — gets silently rewritten into a brand name, which is
# exactly the corruption this function must never commit. 0.88 rejects every
# one-letter substitution up to 7 letters while still accepting the real
# failures, which are insertions/extra vowels: "віспор" vs "віспр" scores 0.91,
# "віспор флоу" vs "віспр флоу" 0.95. Measured on the 3822-take history, this
# cutoff changes only lines that are genuinely the term.
_FUZZY_CUTOFF = 0.88
# Terms of 3 characters or fewer never reach the fuzzy layer: "n8n" is three
# characters and would match noise at any ratio worth using. Exact and
# transliterated matching still apply to them.
_MIN_FUZZY_LEN = 4

# A fuzzy match is only ever attempted against an all-Cyrillic window. That is
# the single most important guard in this module: the fuzzy layer physically
# cannot touch Latin text, so it can never mangle "Codex" into "Claude Code".
_CYRILLIC_ONLY = re.compile(r"^[Ѐ-ӿ" + _APOS + r"\-\s]+$")
_HAS_LATIN = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class _Term:
    """One dictionary entry plus every Cyrillic spelling it might come back as."""
    canonical: str            # exactly as the user wrote it in config.json
    words: tuple[str, ...]    # canonical split on whitespace
    folded: str               # lowercase, single-spaced comparison key
    latin: bool               # False for terms already Cyrillic (бекенд, промпт)
    variants: tuple[str, ...]  # folded Cyrillic renderings, "" for Cyrillic terms


def _word_variants(word: str) -> list[str]:
    """Every Cyrillic rendering of one Latin word, per the letter map."""
    slots: list[tuple[str, ...]] = []
    i, n = 0, len(word)
    while i < n:
        for size in range(min(_MAX_KEY, n - i), 0, -1):
            key = word[i:i + size]
            if key in _TRANSLIT:
                slots.append(_TRANSLIT[key])
                i += size
                break
        else:
            # digits and anything unmapped pass through unchanged: "n8n" keeps
            # its 8, so the exact layer can still match it
            slots.append((word[i],))
            i += 1
    out: list[str] = []
    for combo in product(*slots):
        out.append("".join(combo))
        if len(out) >= _MAX_WORD_VARIANTS:
            break
    return out


def _term_variants(words: tuple[str, ...]) -> tuple[str, ...]:
    """Cyrillic renderings of a whole (possibly multi-word) term, words joined
    by a single space — the same shape the matcher builds from the transcript."""
    per_word = [_word_variants(w) for w in words]
    out: list[str] = []
    for combo in product(*per_word):
        out.append(" ".join(combo))
        if len(out) >= _MAX_TERM_VARIANTS:
            break
    return tuple(dict.fromkeys(out))


@lru_cache(maxsize=8)
def _compile_dictionary(raw: str) -> tuple[_Term, ...]:
    """Parse and pre-expand the config dictionary once per distinct string.

    Cleaning matches flow.py's _build_hotwords (strip surrounding punctuation,
    drop empties, de-duplicate case-insensitively, keep the user's order) so the
    decoder and this pass always work from the same term list.

    Sorted longest-first, in words then in characters: "Claude Code" must win
    over "Codex" when both could start at the same position."""
    seen: set[str] = set()
    terms: list[_Term] = []
    for chunk in re.split(r"[,\n]", raw or ""):
        term = chunk.strip().strip(".,;:!?()[]{}\"'«»„“”-–—…")
        if not term:
            continue
        key = _fold(term)
        if key in seen:
            continue
        seen.add(key)
        words = tuple(term.split())
        latin = bool(_HAS_LATIN.search(term))
        # A term that is already Cyrillic (бекенд, промпт, субагент) has nothing
        # to transliterate — it can only be normalised exactly. Generating
        # "variants" for it would mean fuzzy-matching Ukrainian against
        # Ukrainian, which is how inflected forms ("промпті", "субагента") get
        # silently flattened to the nominative.
        variants = _term_variants(tuple(_fold(w) for w in words)) if latin else ()
        terms.append(_Term(canonical=term, words=words,
                           folded=re.sub(r"\s+", " ", _fold(term)),
                           latin=latin, variants=variants))
    terms.sort(key=lambda t: (len(t.words), len(t.canonical)), reverse=True)
    return tuple(terms)


def _match_window(window: str, term: _Term) -> str | None:
    """Should this run of the transcript become `term.canonical`?

    Three layers, cheapest and safest first. Returns None — leave the user's
    text alone — far more often than not; that asymmetry is the whole design."""
    folded = re.sub(r"\s+", " ", _fold(window))
    if not folded:
        return None

    # Layer 1: the term is already there, only spelled with the wrong case.
    # "github" -> "GitHub", "sqlite" -> "SQLite". Risk-free: same letters.
    if folded == term.folded:
        if window == term.canonical:
            return None
        if term.canonical.islower():
            # the dictionary entry carries no capitalisation of its own, so
            # there is nothing to restore and "Бекенд" at the start of a
            # sentence must keep its capital
            return None
        return term.canonical

    if not term.latin:
        # Cyrillic dictionary entries get exact normalisation only — see
        # _compile_dictionary. Ukrainian inflection makes anything fuzzier a
        # corruption machine.
        return None

    # Everything below rewrites Cyrillic into Latin, so the window must be
    # entirely Cyrillic. A window with any Latin in it is either already the
    # term (layer 1) or someone else's word.
    if not _CYRILLIC_ONLY.match(window):
        return None

    # Layer 2: an exact transliteration. "флоу" is in the generated set, so no
    # fuzziness is needed or wanted here.
    if folded in term.variants:
        return term.canonical

    # Layer 3: fuzzy, and only ever against the generated candidates — never
    # against arbitrary text.
    if len(term.canonical.replace(" ", "")) < _MIN_FUZZY_LEN:
        return None
    matcher = SequenceMatcher(autojunk=False)
    matcher.set_seq2(folded)
    for cand in term.variants:
        # A wrong first letter means the decoder heard a different word, not a
        # mangled spelling of this one; requiring it cuts the false-positive
        # surface sharply at almost no cost in recall (the real failures are
        # vowel noise in the middle: віспр/віспор, флов/флоу).
        if cand[:1] != folded[:1]:
            continue
        matcher.set_seq1(cand)
        # two cheap upper bounds before the O(n*m) pass
        if matcher.real_quick_ratio() < _FUZZY_CUTOFF:
            continue
        if matcher.quick_ratio() < _FUZZY_CUTOFF:
            continue
        if matcher.ratio() >= _FUZZY_CUTOFF:
            return term.canonical
    return None


def restore_terms(text: str, dictionary: str) -> tuple[str, list[tuple[str, str]]]:
    """Restore dictionary terms the decoder transliterated or mis-spelled.

    `dictionary` is the raw comma/newline-separated config string (the same one
    that feeds Whisper's hotwords). Returns (fixed_text, [(was, became), ...]).

    Deliberately conservative. A false positive silently corrupts text the user
    already believes is correct — they see it only later, in a document — while
    a miss merely leaves a transliteration they can read and fix. So every
    layer here is allowed to say "no": fuzzy matching runs on all-Cyrillic
    windows only, against generated transliterations only, at a high cutoff,
    with a first-letter check, and never for terms of 3 characters or fewer.

    Spacing and punctuation around a match are preserved exactly: the text is
    tokenised into words and separators, and only word tokens are ever
    replaced."""
    if not text or not dictionary:
        return text, []
    terms = _compile_dictionary(dictionary)
    if not terms:
        return text, []
    tokens = _TOKEN_RE.findall(text)
    word_pos = [i for i, t in enumerate(tokens) if _IS_WORD.match(t)]
    if not word_pos:
        return text, []

    out = list(tokens)
    changes: list[tuple[str, str]] = []
    k = 0
    while k < len(word_pos):
        hit: tuple[int, int, str, str, int] | None = None
        for term in terms:
            span = len(term.words)
            if k + span > len(word_pos):
                continue
            if span > 1 and not _seps_are_space(tokens, word_pos, k, span):
                continue
            start, end = word_pos[k], word_pos[k + span - 1]
            window = "".join(tokens[start:end + 1])
            repl = _match_window(window, term)
            if repl is not None:
                hit = (start, end, window, repl, span)
                break
        if hit is None:
            k += 1
            continue
        start, end, window, repl, span = hit
        out[start] = repl
        for j in range(start + 1, end + 1):
            out[j] = ""     # the whole matched window collapses into one token
        changes.append((window, repl))
        k += span
    return "".join(out), changes


def _seps_are_space(tokens: list[str], word_pos: list[int], k: int, span: int) -> bool:
    """A multi-word term may only match words separated by whitespace. Anything
    else ("флоу, оригінальний") means these words are not one phrase."""
    for i in range(k, k + span - 1):
        for j in range(word_pos[i] + 1, word_pos[i + 1]):
            if not tokens[j].isspace():
                return False
    return True


# --------------------------------------------------- 3. Russian leak detector

# Same set flow.py logs on (flow.py line 267). These letters do not exist in the
# Ukrainian alphabet at all, so their presence is proof, not evidence.
RU_ONLY_CHARS: frozenset[str] = frozenset("ыэъёЫЭЪЁ")

# Frequent Russian words with no Ukrainian spelling of the same form. Every
# entry was checked against its Ukrainian counterpart — the counterpart is what
# makes the word safe to flag: что/що, это/це, если/якщо, нужно/потрібно,
# хорошо/добре, время/час, релиз/реліз.
#
# Words that exist in BOTH languages are deliberately absent even when they feel
# Russian: "все", "просто", "мало", "завтра", "там", "них", "тебе", "уже" and
# "хочу" are all ordinary Ukrainian and would fire on clean takes. The cost of
# an entry here is a pointless decode retry; the cost of a wrong entry is a
# retry on every third sentence, so the list stays short and certain.
#
# The bare conjunction "и" was tried and removed. It is the most frequent word
# in Russian, but as a STANDALONE token it is also what the decoder produces
# from a stutter or a hyphen ("Які+и, які-и з цього кроку" — the one and only
# false positive this detector produced over the whole 3829-take history).
# Nothing is lost: a genuinely Russian sentence long enough to contain "и"
# always carries other markers from this list or a Russian-only letter.
RU_WORDS: frozenset[str] = frozenset({
    "но", "что", "чтобы", "чем", "или", "это", "этот", "эта", "эти", "этого", "этом",
    "если", "когда", "тогда", "сейчас", "теперь", "зачем", "почему", "потому",
    "поэтому", "здесь", "туда", "сюда", "очень", "тоже", "также", "только",
    "всегда", "никогда", "ничего", "кто", "где", "какой", "какая", "какие",
    "который", "которые", "была", "было", "были", "будет", "может", "можно",
    "нужно", "надо", "меня", "тебя", "него", "нее", "мне", "их", "ими",
    "вместе", "сказал", "сделать", "делать", "работать", "хорошо", "плохо",
    "спасибо", "пожалуйста", "привет", "конечно", "наверное", "даже", "чуть",
    "больше", "меньше", "лучше", "хуже", "потом", "сразу", "опять", "снова",
    "много", "время", "сегодня", "вчера", "нет", "почта", "почту", "ошибка",
    "настройки", "сообщение", "пользователь", "файлы", "релиз", "релизы",
    "побольше", "поменьше", "срок", "сроки",
})

# Density gain: a take is not "Russian" because of one borrowed word, but three
# Russian words in a ten-word sentence is a leak. 2.5 puts the 0.15 threshold at
# roughly one flagged word in sixteen.
_RU_DENSITY_GAIN = 2.5
# Floor when a Russian-only LETTER is present. Those letters cannot occur in
# Ukrainian, so the take demonstrably leaked — even if only one word did, which
# is the common case ("Рідок лабораторія пошты"). 0.5 keeps such a take above
# any sane threshold without pretending the whole utterance is Russian.
_RU_CHAR_FLOOR = 0.5


def ru_chars(text: str) -> str:
    """The Russian-only characters present, sorted and de-duplicated, or "".

    Exactly what flow.py already computes for its log line. Cheap, exact, and
    incapable of a false positive: these letters are not in the Ukrainian
    alphabet."""
    if not text:
        return ""
    return "".join(sorted(set(text) & RU_ONLY_CHARS))


def ru_score(text: str) -> float:
    """0.0-1.0 estimate that this Ukrainian-language take leaked into Russian.

    Two independent signals: Russian-only letters (proof) and frequent Russian
    function words that have no Ukrainian form (strong evidence). Ordinary
    Ukrainian scores a flat 0.0 — verified on the user's history, where the
    Ukrainian lines produce no hits at all.

    This is a decision aid for a decode retry, not a language classifier: it
    assumes the take was MEANT to be Ukrainian, which is the only situation
    flow.py calls it in."""
    if not text:
        return 0.0
    words = [_fold(t) for t in _TOKEN_RE.findall(text) if _IS_WORD.match(t)]
    words = [w for w in words if any(c.isalpha() for c in w)]
    if not words:
        return 0.0
    hits = sum(1 for w in words if (set(w) & RU_ONLY_CHARS) or w in RU_WORDS)
    score = min(1.0, hits / len(words) * _RU_DENSITY_GAIN)
    if ru_chars(text):
        score = max(score, _RU_CHAR_FLOOR)
    return round(score, 3)


def looks_russian(text: str, threshold: float = 0.15) -> bool:
    """Convenience wrapper over ru_score for the retry decision.

    0.15 is intentionally low: the action on the other side is re-decoding the
    same audio with a stronger Ukrainian bias, which costs a second of GPU time
    and nothing else. A missed leak, by contrast, is Russian text pasted into a
    Ukrainian document."""
    return ru_score(text) >= threshold


# ------------------------------------------------- 5. LLM polish safety net

# Assistant meta-replies the polish model emits when it mistakes a dictated
# imperative for an instruction to itself ("Так роби всі три" -> the model asks
# for "the text to fix"). These are never a correction of the user's speech, so
# pasting one destroys the take. Matched as a substring on the folded text, so
# surrounding punctuation or a leading "Звичайно," does not hide them. Kept
# short and unambiguous — every phrase here is something a corrector says ABOUT
# the task, never something a person dictates INTO a document.
_POLISH_REFUSALS = (
    # uk — "provide the text", "which text", "there is no text", "as an
    # assistant/model", "i cannot", "please clarify"
    "надайте текст", "надай текст", "надайте, будь ласка, текст", "який текст",
    "немає тексту", "відсутній текст", "як асистент", "як мовна модель",
    "не можу виконати", "уточніть", "будь ласка, уточніть", "надішліть текст",
    # ru — same replies from a model that answered in Russian
    "предоставьте текст", "нет текста", "как ассистент", "как языковая модель",
    "не могу выполнить", "уточните",
    # en
    "provide the text", "no text", "as an assistant", "as a language model",
    "i cannot", "i can't", "please clarify", "please provide",
)


def polish_is_safe(raw: str, polished: str) -> bool:
    """True if `polished` is a plausible cleanup of `raw`, False if it looks like
    the model answered the dictation instead of correcting it.

    A corrector changes punctuation, casing and a few words; it does not replace
    the utterance with something unrelated. Two independent rejects, both aimed
    at the observed failure (a short imperative decoded as a command, answered
    with a meta-reply) while staying clear of legitimate heavy fixes of garbled
    speech:

      1. A known assistant meta-reply phrase appears in `polished` but not in
         `raw`. Precise and low-risk: these phrases are things said ABOUT the
         task, and if the user genuinely dictated one it is already in `raw`, so
         the "not in raw" guard leaves that case untouched.

      2. `polished` shares almost no content words with `raw` AND expands it.
         A meta-reply is both unrelated and longer; a real correction of even a
         badly garbled take keeps most of its word stems and does not balloon.
         Only applied when raw is short (<= 6 words), which is where the command
         confusion happens and where a single wrong word is not enough signal to
         trip on a legitimate fix.

    On True the caller keeps `polished`; on False it keeps `raw` — never empty,
    never the meta-reply."""
    if not polished:
        return False
    rawf, polf = _fold(raw), _fold(polished)
    for phrase in _POLISH_REFUSALS:
        if phrase in polf and phrase not in rawf:
            return False
    raw_words = {w for w in (_fold(t) for t in _TOKEN_RE.findall(raw))
                 if _IS_WORD.match(w) and any(c.isalpha() for c in w)}
    pol_words = {w for w in (_fold(t) for t in _TOKEN_RE.findall(polished))
                 if _IS_WORD.match(w) and any(c.isalpha() for c in w)}
    if raw_words and len(raw_words) <= 6:
        shared = raw_words & pol_words
        overlap = len(shared) / len(raw_words)
        expanded = len(pol_words) > 2 * len(raw_words)
        if overlap < 0.34 and expanded:
            return False
    return True
