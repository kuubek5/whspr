"""Text passes on the transcript: replacements, number normalisation and spoken punctuation. Moved verbatim out of flow.py."""

import re

import flow


# ---------------- Voice commands ----------------
def apply_replacements(text: str) -> str:
    for phrase, repl in flow.config.get("replacements", {}).items():
        # eat surrounding punctuation/spaces so "Привіт. Новий рядок. Бувай"
        # becomes "Привіт.\nБувай"
        pattern = r"[,.!?]?\s*" + re.escape(phrase) + r"[,.!?]?\s*"
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return text.strip()


def _norm_apos(s: str) -> str:
    return s.replace("’", "'").replace("ʼ", "'").replace("`", "'")


# Ukrainian + English cardinals, common declensions folded in (Whisper emits
# whatever case was spoken). Values 1-900; scales handled separately.
_NUM_WORDS = {
    "нуль": 0, "zero": 0,
    "один": 1, "одна": 1, "одне": 1, "одно": 1, "один": 1, "one": 1,
    "два": 2, "дві": 2, "two": 2,
    "три": 3, "three": 3, "чотири": 4, "four": 4,
    "п'ять": 5, "five": 5, "шість": 6, "six": 6, "сім": 7, "seven": 7,
    "вісім": 8, "eight": 8, "дев'ять": 9, "nine": 9,
    "десять": 10, "ten": 10, "одинадцять": 11, "eleven": 11,
    "дванадцять": 12, "twelve": 12, "тринадцять": 13, "thirteen": 13,
    "чотирнадцять": 14, "fourteen": 14, "п'ятнадцять": 15, "fifteen": 15,
    "шістнадцять": 16, "sixteen": 16, "сімнадцять": 17, "seventeen": 17,
    "вісімнадцять": 18, "eighteen": 18, "дев'ятнадцять": 19, "nineteen": 19,
    "двадцять": 20, "twenty": 20, "тридцять": 30, "thirty": 30,
    "сорок": 40, "forty": 40, "п'ятдесят": 50, "fifty": 50,
    "шістдесят": 60, "sixty": 60, "сімдесят": 70, "seventy": 70,
    "вісімдесят": 80, "eighty": 80, "дев'яносто": 90, "ninety": 90,
    "сто": 100, "hundred": 100, "двісті": 200, "триста": 300, "чотириста": 400,
    "п'ятсот": 500, "шістсот": 600, "сімсот": 700, "вісімсот": 800,
    "дев'ятсот": 900,
}
_NUM_SCALE = {
    "тисяча": 1000, "тисячі": 1000, "тисяч": 1000, "thousand": 1000,
    "мільйон": 1_000_000, "мільйони": 1_000_000, "мільйонів": 1_000_000,
    "million": 1_000_000,
}
# lone "один/одна/one" is far more often the article "a/one" than a digit, so
# a single isolated such word is left as a word; inside a bigger number it counts
_LONE_KEEP = {"один", "одна", "одне", "одно", "one"}


def _num_key(tok: str) -> str:
    return _norm_apos(tok).lower()


def _is_num(tok: str) -> bool:
    k = _num_key(tok)
    return k in _NUM_WORDS or k in _NUM_SCALE


def _run_to_digits(keys: list[str]) -> str:
    total, current = 0, 0
    for k in keys:
        if k in _NUM_SCALE:
            total += (current or 1) * _NUM_SCALE[k]
            current = 0
        else:
            current += _NUM_WORDS[k]
    return str(total + current)


def normalize_numbers(text: str) -> str:
    """Fold spoken number words into digits: "триста п'ятдесят два" -> "352",
    "дві тисячі двадцять чотири" -> "2024". A run of number words joined only by
    single spaces becomes one number; anything else (punctuation, other words)
    breaks the run and passes through untouched."""
    if not flow.config.get("normalize_numbers", True) or not text:
        return text
    # apostrophe kept inside words so "п'ять" stays one token; \W-runs (spaces,
    # punctuation) are tokens too, so original spacing survives verbatim
    tokens = re.findall(r"[^\W_]+(?:['][^\W_]+)*|\W+|_", _norm_apos(text))
    out, i, n = [], 0, len(tokens)
    while i < n:
        if _is_num(tokens[i]):
            keys, j = [_num_key(tokens[i])], i + 1
            while j + 1 < n and tokens[j].isspace() and " " in tokens[j] \
                    and _is_num(tokens[j + 1]):
                keys.append(_num_key(tokens[j + 1]))
                j += 2
            # a single lone article-like "один" stays a word
            if len(keys) == 1 and keys[0] in _LONE_KEEP:
                out.append(tokens[i])
            elif len(keys) >= 2 and all(_NUM_WORDS.get(k, 99) < 10 for k in keys):
                # a run of single digits is a sequence (code/phone/pin/year read
                # digit by digit), not a sum: "три чотири п'ять" -> "345", not 12
                out.append("".join(str(_NUM_WORDS[k]) for k in keys))
            else:
                # has a ten/hundred/thousand word -> compose arithmetically:
                # "триста п'ятдесят два" -> 352, "дві тисячі" -> 2000
                out.append(_run_to_digits(keys))
            i = j
        else:
            out.append(tokens[i])
            i += 1
    return "".join(out)


# Spoken words -> punctuation, longest phrase first so "крапка з комою" wins
# over "крапка". Whisper often already writes . and , ; this turns the words a
# user says out loud ("привіт кома як справи") into the mark instead.
# Only phrases unlikely to appear as ordinary dictated words. Deliberately
# omitted because they collide with common speech: "кому" (dative of "хто"),
# "крапку" (idiom "поставити крапку"), English "period"/"colon"/"dash". The
# feature is a toggle, so a user who needs even these literally can switch it off.
SPOKEN_PUNCT = [
    ("крапка з комою", ";"),
    ("знак питання", "?"), ("знак оклику", "!"),
    ("двокрапка", ":"), ("тире", " — "),
    ("три крапки", "…"), ("багатокрапка", "…"),
    ("кома", ","),
    ("крапка", "."),
    # English, for en dictation — multi-word forms only, to avoid common nouns
    ("semicolon", ";"), ("question mark", "?"), ("exclamation mark", "!"),
    ("ellipsis", "…"),
    ("comma", ","), ("full stop", "."),
]
_SENTENCE_END = ".!?…"


def apply_spoken_punctuation(text: str) -> str:
    """Turn dictated punctuation words into marks with correct spacing.

    "привіт кома як справи знак питання" -> "привіт, як справи?". Spacing is
    fixed up afterwards so marks hug the previous word and are followed by one
    space, which is why this can't reuse the freeform replacements pass."""
    if not flow.config.get("spoken_punctuation", True) or not text:
        return text
    for phrase, mark in SPOKEN_PUNCT:
        # \b around a Cyrillic phrase works: in Python 3 \w is Unicode by default
        text = re.sub(r"\s*\b" + re.escape(phrase) + r"\b\s*", mark,
                      text, flags=re.IGNORECASE)
    # tighten: no space before a mark, exactly one space after it
    text = re.sub(r"\s+([,;:!?.…])", r"\1", text)
    # collapse duplicates: Whisper may punctuate AND transcribe the spoken word,
    # so "готово. крапка" -> "готово. ." -> "готово."
    text = re.sub(r"([,;:!?.…])(?:\s*\1)+", r"\1", text)
    text = re.sub(r"([,;:!?.…])(?=[^\s\d])", r"\1 ", text)  # keep 3.14 intact
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
