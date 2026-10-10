"""Suggest dictionary terms from the dictation history — stdlib only, pure.

The dictionary (config "dictionary") only helps with terms the user already
knows are a problem. Finding them was manual: the user's folder name
"скачано-прошито" came back in ~15 spellings across the history
("скачано-прошитано", "скачано-просчитано", "скачане прочитане", ...) before
anyone noticed. `suggest_terms` looks for that signal automatically.

The signal is NOT "a rare word" (most words of a 20k-word history are rare) and
NOT "a word with many forms" (Ukrainian inflects everything: скачати, скачали,
скачано are one ordinary verb). It is several DIFFERENTLY SPELLED versions of
one unusual thing. Without a Ukrainian lexicon "unusual" cannot be judged for
an arbitrary word, so the search is restricted to the shapes where it can:

 1. Two-word compounds. A hyphenated compound ("скачано-прошито") is rare in
    ordinary speech; when the same compound keeps coming back with a different
    second (or first) word — "скачано-прошитано", "скачано-просчитано",
    "скачане прочитане" — the decoder plainly does not know it.
 2. Latin names. When "Obsidian" appears in the history AND its Cyrillic
    transliterations ("обсідіан", "обсидіан") appear too, the decoder knows the
    word but not reliably its spelling — exactly what the dictionary fixes.
 3. Unknown Cyrillic words with several mid-word spellings ("прошитана",
    "прощитана", "просчитана"): only rare words, only when the spellings differ
    in the MIDDLE of the word (endings are inflection, prefixes are other
    verbs), and only with three or more distinct spellings.

Precision matters more than recall: every suggestion costs the user a decision,
so a false positive is an annoyance while a miss is merely the status quo.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher

import text_fixes

# Words: letters with internal apostrophes or hyphens ("п'ять", "скачано-
# прошито"). Digits are excluded — "n8n"-style terms are short and the fuzzy
# layer is useless on them anyway.
_WORD_RE = re.compile(r"[^\W\d_]+(?:['’ʼ`\-][^\W\d_]+)*", re.UNICODE)
_LATIN_RE = re.compile(r"[a-z]")
_VOWELS_RE = re.compile(r"[аеиіїоуюяєё]")

# Inflection endings, longest first. Deliberately crude: the stem only has to
# make "скачано" / "скачане" / "скачана" land on one key, it never reaches the
# user. Over-stripping is harmless here, under-stripping makes an inflected
# form look like a second spelling.
_ENDINGS = sorted({
    "ування", "ювання", "ання", "ення", "ається", "ються", "уться", "иться",
    "ться", "ись", "ася", "ося", "ися", "ся", "сь",
    "аний", "яний", "ений", "ане", "ано", "ана", "ані", "ену", "ене", "ено",
    "ена", "ені", "ого", "ому", "ими", "іми", "ами", "ями", "ові", "еві",
    "ити", "ати", "яти", "іти", "ють", "уть", "ать", "ять", "ить", "ете",
    "ємо", "имо", "ий", "ій", "ої", "ою", "ею", "ах", "ях", "ам", "ям", "ом",
    "ем", "ти", "ть", "ла", "ло", "ли", "ав", "ив", "ує", "ює", "ую",
    "а", "я", "о", "е", "и", "і", "у", "ю", "ь", "й", "є", "ї",
}, key=len, reverse=True)
_MIN_STEM = 3

# Similarity between two stems. One substituted letter in a 6-letter stem
# already scores 0.83 (прошит/прощит), so the cutoff cannot be higher; the
# middle-only guard (_mid_change) carries the rest of the precision.
_STEM_CUTOFF = 0.8
# Inside a compound whose other half is identical: see pair_similar.
_PAIR_CUTOFF = 0.72
# Latin rendering vs Cyrillic word: restore_terms' own cutoff, so a suggestion
# only appears for spellings the dictionary will then actually repair.
_LATIN_CUTOFF = text_fixes._FUZZY_CUTOFF

_STOPWORDS = frozenset("""
the and for with this that from have not you are was but all can one out use
your about just into than then them there what when which will would been
also more some such only other here very much like make made need want
""".split())

# A stem used this often is the user's ordinary vocabulary. Rare-word
# detectors (3) ignore it; the Latin detector (2) refuses to call it a
# transliteration ("тест" is a Ukrainian word, not a mangled "test").
_COMMON_SHARE = 0.0015
_COMMON_MIN = 8

_MAX_RESULTS = 15
_MAX_EXAMPLES = 2
_EXAMPLE_CTX = 30


def _fold(s: str) -> str:
    return text_fixes._fold(s)


def _stem(word: str) -> str:
    """Strip one inflection ending, keeping at least _MIN_STEM letters."""
    for end in _ENDINGS:
        if word.endswith(end) and len(word) - len(end) >= _MIN_STEM:
            return word[:-len(end)]
    return word


def _mid_change(a: str, b: str) -> bool:
    """True when two different stems differ somewhere in the MIDDLE.

    A pure prefix difference (прочит / перечит / зчит) is two ordinary verbs; a
    pure suffix difference is an ending the crude stemmer missed (розум /
    розумі). A mangled term shares its start and its end and differs inside:
    прошит / прощит / просчит."""
    if a == b:
        return False
    pre = 0
    while pre < min(len(a), len(b)) and a[pre] == b[pre]:
        pre += 1
    suf = 0
    while (suf < min(len(a), len(b)) - pre
           and a[-1 - suf] == b[-1 - suf]):
        suf += 1
    return pre >= 2 and suf >= 1


def _close(a: str, b: str, m: SequenceMatcher, cutoff: float = _STEM_CUTOFF) -> bool:
    if abs(len(a) - len(b)) > 2:
        return False
    m.set_seqs(a, b)
    return (m.real_quick_ratio() >= cutoff and m.quick_ratio() >= cutoff
            and m.ratio() >= cutoff)


def _snippet(text: str, s: int, e: int) -> str:
    lo, hi = max(0, s - _EXAMPLE_CTX), min(len(text), e + _EXAMPLE_CTX)
    return ("…" if lo else "") + text[lo:hi].strip() + ("…" if hi < len(text) else "")


class _Spellings:
    """Occurrence counter that remembers the user's original casing and one
    example snippet per spelling."""

    def __init__(self) -> None:
        self.count: Counter[str] = Counter()
        self.shape: dict[str, Counter[str]] = defaultdict(Counter)
        self.example: dict[str, str] = {}

    def add(self, folded: str, raw: str, text: str, s: int, e: int) -> None:
        self.count[folded] += 1
        self.shape[folded][raw] += 1
        self.example.setdefault(folded, _snippet(text, s, e))

    def display(self, folded: str) -> str:
        # Most frequent original casing, except a sentence-initial capital on
        # a lowercase word: "Скачано-прошито" at the start of a take is still
        # "скачано-прошито" mid-sentence.
        raw = self.shape[folded].most_common(1)[0][0] if folded in self.shape else folded
        if raw[:1].isupper() and raw[1:] == raw[1:].lower() and not _LATIN_RE.search(folded):
            return raw[:1].lower() + raw[1:]
        return raw


def _star_clusters(keys: list, weight: Counter, similar, block) -> list[list]:
    """Greedy star clustering: the heaviest unassigned key is a seed and takes
    every unassigned key similar TO IT. Unlike union-find this does not chain
    (a~b, b~c, c~d ... would glue half the vocabulary together). `block(key)`
    partitions the keys so only keys in the same block are ever compared."""
    blocks: dict = defaultdict(list)
    for k in sorted(keys, key=lambda k: (-weight[k], k)):
        blocks[block(k)].append(k)
    out = []
    for order in blocks.values():
        taken: set = set()
        for seed in order:
            if seed in taken:
                continue
            taken.add(seed)
            group = [seed]
            for k in order:
                if k not in taken and similar(seed, k):
                    taken.add(k)
                    group.append(k)
            out.append(group)
    return out


def _complete_clusters(keys: list[str], weight: Counter[str], similar) -> list[list[str]]:
    """Like _star_clusters, but a key joins a group only when it is similar to
    EVERY member — the stricter rule for single words, where a loose group
    would sweep in neighbouring ordinary words."""
    order = sorted(keys, key=lambda k: (-weight[k], k))
    taken: set[str] = set()
    out = []
    for seed in order:
        if seed in taken:
            continue
        taken.add(seed)
        group = [seed]
        for k in order:
            if k not in taken and all(similar(g, k) for g in group):
                taken.add(k)
                group.append(k)
        out.append(group)
    return out


def _covered(folded: str, dict_keys: set[str], dictionary: str) -> bool:
    """Is this spelling already handled by the user's dictionary?"""
    parts = [p for p in re.split(r"[\s\-]+", folded) if p]
    if " ".join(_stem(p) for p in parts) in dict_keys:
        return True
    if any(_stem(p) in dict_keys for p in parts if len(p) >= 4):
        return True
    if dictionary:
        _fixed, changes = text_fixes.restore_terms(" ".join(parts), dictionary)
        if changes:
            return True
    return False


def suggest_terms(texts, existing_dictionary: str = "",
                  limit: int = _MAX_RESULTS) -> list[dict]:
    """Find terms the recogniser spells inconsistently.

    `texts`: iterable of transcripts, any order. `existing_dictionary`: the raw
    config string; anything it already covers is left out. Returns at most
    `limit` dicts, most unstable first:
        {"term": proposed canonical spelling (user may edit),
         "variants": [(spelling, count), ...] most frequent first,
         "total": occurrences, "examples": [short snippets]}
    """
    texts = [t for t in (texts or []) if t and t.strip()]
    if not texts:
        return []

    docs = []
    stem_total: Counter[str] = Counter()
    total_words = 0
    for t in texts:
        words = [(m.group(), _fold(m.group()), m.start(), m.end())
                 for m in _WORD_RE.finditer(t)]
        docs.append((t, words))
        total_words += len(words)
        for _raw, lw, _s, _e in words:
            if "-" not in lw:
                stem_total[_stem(lw)] += 1
    common_min = max(_COMMON_MIN, int(total_words * _COMMON_SHARE))
    common = {s for s, n in stem_total.items() if n >= common_min}

    sp = _Spellings()
    matcher = SequenceMatcher(autojunk=False)
    candidates: list[tuple[list[str], int]] = []   # (spellings, distinct stems)
    compound_idx: list[int] = []

    # ---------------------------------------------------- 1. two-word compounds
    def pair_key(a: str, b: str) -> tuple[str, str]:
        return _stem(a), _stem(b)

    anchors: Counter[tuple[str, str]] = Counter()
    for _t, words in docs:
        for _raw, lw, _s, _e in words:
            if lw.count("-") == 1:
                a, b = lw.split("-")
                if len(a) >= 3 and len(b) >= 3:
                    anchors[pair_key(a, b)] += 1
    firsts = {a for a, _b in anchors}
    seconds = {b for _a, b in anchors}
    pair_spell: dict[tuple[str, str], set[str]] = defaultdict(set)
    for t, words in docs:
        for i, (raw, lw, s, e) in enumerate(words):
            if lw.count("-") == 1:
                a, b = lw.split("-")
                if len(a) >= 3 and len(b) >= 3:
                    k = pair_key(a, b)
                    pair_spell[k].add(lw)
                    sp.add(lw, raw, t, s, e)
                continue
            # the same compound dictated with a space: "скачане прочитане"
            if i + 1 < len(words) and "-" not in lw:
                raw2, lw2, s2, e2 = words[i + 1]
                if "-" in lw2 or not t[e:s2].isspace() or len(lw2) < 3 or len(lw) < 3:
                    continue
                k = pair_key(lw, lw2)
                if k[0] in firsts or k[1] in seconds:
                    unit = lw + " " + lw2
                    pair_spell[k].add(unit)
                    sp.add(unit, raw + " " + raw2, t, s, e2)

    def pair_similar(x: tuple[str, str], y: tuple[str, str]) -> bool:
        # one half identical (as a stem), the other a mid-word misspelling —
        # or both halves misspelt but each still close
        same = [x[i] == y[i] for i in (0, 1)]
        if all(same):
            return True
        # with one half pinned the context is already specific, so the other
        # half may drift further: прошит/просчит scores only 0.77
        cutoff = _PAIR_CUTOFF if any(same) else _STEM_CUTOFF
        for i in (0, 1):
            if not same[i] and not (_mid_change(x[i], y[i])
                                    and _close(x[i], y[i], matcher, cutoff)):
                return False
        return True

    pair_weight = Counter({k: sum(sp.count[u] for u in us) for k, us in pair_spell.items()})
    # a spaced pair never seeds a cluster on its own: without a hyphenated
    # anchor in it, it is just two words that happened to be adjacent
    # Block on the first half's first two letters: pair_similar needs that half
    # identical or a mid-word drift, and both share at least two letters.
    for group in _star_clusters(list(pair_spell), pair_weight, pair_similar,
                                lambda k: k[0][:2]):
        if not any(k in anchors for k in group):
            continue
        if len(group) < 2:
            continue
        if all(k[0] in common and k[1] in common for k in group):
            continue
        spellings = [u for k in group for u in pair_spell[k]]
        compound_idx.append(len(candidates))
        candidates.append((spellings, len(group)))

    # ------------------------------------------------------ 2. Latin names
    latin_words: dict[str, int] = Counter()
    cyr_words: dict[str, int] = Counter()
    for t, words in docs:
        for raw, lw, s, e in words:
            if "-" in lw or len(lw) < 4:
                continue
            if _LATIN_RE.search(lw):
                if lw not in _STOPWORDS:
                    latin_words[lw] += 1
                    sp.add(lw, raw, t, s, e)
            else:
                cyr_words[lw] += 1
    cyr_by_first: dict[str, list[str]] = defaultdict(list)
    for w in cyr_words:
        if _stem(w) not in common:
            cyr_by_first[w[0]].append(w)
    used_cyr: set[str] = set()
    for lw in sorted(latin_words, key=lambda w: -latin_words[w]):
        renders = text_fixes._word_variants(lw)
        rstems = {_stem(r) for r in renders}
        hits = []
        exact = 0
        for f in {r[0] for r in renders if r}:
            for w in cyr_by_first.get(f, []):
                if w in used_cyr:
                    continue
                ws = _stem(w)
                ok = ws in rstems
                exact += ok
                if not ok:
                    for r in renders:
                        if r[:1] != f or abs(len(r) - len(w)) > 2:
                            continue
                        matcher.set_seqs(r, w)
                        if (matcher.quick_ratio() >= _LATIN_CUTOFF
                                and matcher.ratio() >= _LATIN_CUTOFF):
                            ok = True
                            break
                if ok:
                    hits.append(w)
        if not hits:
            continue
        # A lone fuzzy hit is too weak: "макет" sits 0.91 from a rendering of
        # "Market" and is an ordinary word. Fuzzy hits only count alongside an
        # exact transliteration or each other.
        if not exact and len(hits) < 2:
            continue
        # A native Ukrainian word that merely sounds like the English one
        # ("група" for Group, "лівий" for live) shows up in a full paradigm of
        # endings; a transliterated name mostly keeps one or two forms
        # ("коміт", "телеграм/телеграму").
        by_stem: dict[str, set[str]] = defaultdict(set)
        for w in hits:
            by_stem[_stem(w)].add(w)
        if any(len(ws) >= 3 for ws in by_stem.values()):
            continue
        used_cyr.update(hits)
        for t, words in docs:
            for raw, w, s, e in words:
                if w in hits:
                    sp.add(w, raw, t, s, e)
        stems = {_stem(w) for w in hits}
        candidates.append(([lw] + hits, 1 + len(stems)))

    # ------------------------------------------ 3. rare Cyrillic, mid-word drift
    rare: Counter[str] = Counter()
    for w, n in cyr_words.items():
        st = _stem(w)
        if w in used_cyr or len(st) < 5:
            continue
        rare[st] += n
    # Not the user's everyday vocabulary: a common stem next to a compound
    # ("прочитати" is an ordinary verb) must not be pulled into it.
    rare = Counter({st: n for st, n in rare.items() if st not in common})
    stem_words: dict[str, set[str]] = defaultdict(set)
    for w in cyr_words:
        stem_words[_stem(w)].add(w)
    # stems that make up compound suggestions: a drifting single word that
    # belongs to one ("прошитана" next to "скачано-прошитано") is folded into
    # that suggestion instead of becoming a second one
    compound_of: dict[str, int] = {}
    for idx in compound_idx:
        for u in candidates[idx][0]:
            for p in re.split(r"[\s\-]+", u):
                compound_of.setdefault(_stem(p), idx)
    # only stems that could join a compound are clustered at all (drift needs a
    # shared two-letter start), which also keeps this pass fast
    heads = {st[:2] for st in compound_of}
    rare = Counter({st: n for st, n in rare.items() if st[:2] in heads})

    def drift(a: str, b: str) -> bool:
        # the vowel alternation of Ukrainian morphology (вибір/вибору,
        # тривог/тревог) is not a spelling drift; consonants must differ
        va, vb = _VOWELS_RE.sub("V", a), _VOWELS_RE.sub("V", b)
        return _mid_change(va, vb) and _close(a, b, matcher)

    # Words already counted inside a spaced compound ("скачане прочитане") are
    # not merged again as singles: their other occurrences are as likely the
    # ordinary word ("прочитане" = "read").
    pair_words = {p for idx in compound_idx for u in candidates[idx][0] if " " in u
                  for p in u.split(" ")}
    for group in _complete_clusters(list(rare), rare, drift):
        words_ = [w for st in group for w in stem_words[st] if w not in pair_words]
        home = next((compound_of[st] for st in group if st in compound_of), None)
        if home is None or not words_:
            # A standalone single-word cluster is NOT suggested. Measured on the
            # real history it was the noisiest detector by far — ordinary words
            # plus one decoder slip (нагадую/назад/нарадить, вибач/видачі) look
            # exactly like a drifting term without a lexicon to tell them apart.
            continue
        spellings, distinct = candidates[home]
        new = [w for w in words_ if w not in spellings]
        candidates[home] = (spellings + new, distinct + len({_stem(w) for w in new}))
        for t, words in docs:
            for raw, w, s, e in words:
                if w in words_:
                    sp.add(w, raw, t, s, e)

    # ------------------------------------------------ score, filter, rank
    dict_keys = set()
    for chunk in re.split(r"[,\n]", existing_dictionary or ""):
        f = _fold(chunk.strip())
        if f:
            parts = [p for p in re.split(r"[\s\-]+", f) if p]
            dict_keys.add(" ".join(_stem(p) for p in parts))
            # each word of a multi-word term on its own too: "Claude Code"
            # already teaches the decoder "Code"
            dict_keys.update(_stem(p) for p in parts if len(p) >= 4)
    results = []
    seen_terms: set[str] = set()
    for spellings, distinct in candidates:
        spellings = list(dict.fromkeys(spellings))
        total = sum(sp.count[u] for u in spellings)
        if distinct < 2 or total < 3:
            continue
        if any(_covered(u, dict_keys, existing_dictionary) for u in spellings):
            continue
        variants = sorted(((u, sp.count[u]) for u in spellings), key=lambda x: (-x[1], x[0]))
        latin = [u for u, _n in variants if _LATIN_RE.search(u)]
        # the Latin spelling is the intended one even when the decoder mostly
        # transliterates it; otherwise the most frequent spelling wins
        # (a compound is proposed in its hyphenated form, the shape the user
        # evidently means when the decoder gets it closest)
        hyphened = [u for u, _n in variants if "-" in u]
        best = latin[0] if latin else (hyphened or [variants[0][0]])[0]
        term = sp.display(best)
        if _fold(term) in seen_terms:
            continue
        seen_terms.add(_fold(term))
        results.append({
            "term": term,
            "variants": [(sp.display(u), n) for u, n in variants],
            "total": total,
            "score": distinct * total,
            "examples": [sp.example[u] for u, _n in variants[:_MAX_EXAMPLES] if u in sp.example],
        })
    results.sort(key=lambda r: (-r["score"], -r["total"], r["term"]))
    return results[:limit]
