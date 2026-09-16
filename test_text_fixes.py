"""Unit tests for text_fixes.py — plain unittest (pytest is not a dependency
of this project; see requirements.txt).

    .venv/Scripts/python -m unittest test_text_fixes -v

The examples are real lines from the user's 3822-dictation history, not
invented ones: the point of this suite is that the fixes work on the text the
app actually produces, and — far more important — that they leave everything
else exactly as it was.
"""
from __future__ import annotations

import unittest

import text_fixes as tf

# The dictionary as it stands in the user's config.json, plus the term whose
# failure motivated restore_terms.
DICT = ("Claude Code,Codex,Gemini,Antigravity,Obsidian,GitHub,openrouter,n8n,"
        "Cloudflare,SQLite,Hermes,бекенд,фронтенд,промпт,субагент,скілл,Wispr Flow")

# Real Ukrainian dictations containing none of the dictionary terms. Any change
# to one of these is text corruption, full stop.
CLEAN_UK = [
    "Дивись, я вважаю, що потрібно трішки змінити логіку обрання рівнів тривог.",
    "Перестала пропонувати вибирати найбільш схожий варіант, що у клієнтів, що в матеріалів.",
    "Також у зворотному напрямку потрібно, щоб працювали. Тобто англійською вводиш.",
    "Тобто не тільки обрання самого рівня тривог, але й пуші, і сама логіка.",
    "Можливо, варто щось додати, виправити в роботі програми.",
    "Інформаційний рівень жовтий та червоний.",
    "На матеріалах схоже не працює.",
    "Бувають помилки, трапляються у розпізнаванні.",
]

# flow.py's HALLUCINATIONS set, verbatim as of the commit this module was
# written against (flow.py line 259). Copied here on purpose: if flow.py's set
# and text_fixes' set ever drift apart, this test says so.
FLOW_HALLUCINATIONS = {
    "дякую за перегляд", "дякую за перегляд!", "субтитри створені спільнотою amara.org",
    "продовження в наступній серії", "підпишіться на канал",
    "thanks for watching", "thank you for watching",
}


def flow_rule(text: str) -> bool:
    """flow.py's current whole-string test, reproduced exactly."""
    stripped = text.lower().strip(" .!?")
    if not stripped:
        return False
    return stripped in {h.strip(" .!?") for h in FLOW_HALLUCINATIONS}


class TestIsPureArtifact(unittest.TestCase):
    def test_matches_flow_on_the_exact_set(self):
        for phrase in FLOW_HALLUCINATIONS:
            with self.subTest(phrase=phrase):
                self.assertTrue(flow_rule(phrase))
                self.assertTrue(tf.is_pure_artifact(phrase))

    def test_flow_set_is_a_subset_of_ours(self):
        # text_fixes owns the list now; it may only ever grow.
        missing = {p for p in FLOW_HALLUCINATIONS if not tf.is_pure_artifact(p)}
        self.assertEqual(missing, set())

    def test_case_and_punctuation_insensitive(self):
        for variant in ("Дякую за перегляд!", "ДЯКУЮ ЗА ПЕРЕГЛЯД",
                        "  дякую за перегляд...  ", "Thanks for watching!"):
            with self.subTest(variant=variant):
                self.assertTrue(tf.is_pure_artifact(variant))

    def test_real_speech_is_not_an_artifact(self):
        for text in CLEAN_UK + ["дякую", "Дякую!", "Дякую за допомогу.",
                                "Дякую за перегляд документа", "you", ""]:
            with self.subTest(text=text):
                self.assertFalse(tf.is_pure_artifact(text))

    def test_agrees_with_flow_on_clean_history_lines(self):
        for text in CLEAN_UK:
            with self.subTest(text=text):
                self.assertEqual(tf.is_pure_artifact(text), flow_rule(text))


class TestTrimArtifacts(unittest.TestCase):
    def test_real_example_no_trailing_punctuation(self):
        raw = ("І як це буде виглядати після твоїх правок. "
               "Покажи мені Дякую за перегляд!")
        cleaned, removed = tf.trim_artifacts(raw)
        self.assertEqual(cleaned,
                         "І як це буде виглядати після твоїх правок. Покажи мені")
        self.assertEqual(removed, ["Дякую за перегляд!"])

    def test_real_example_keeps_the_sentence_full_stop(self):
        raw = ("Ще одне прохання: знайдіть користувача з іменем Валентин "
               "і надішліть йому пошту. Дякую за перегляд!")
        cleaned, removed = tf.trim_artifacts(raw)
        self.assertEqual(cleaned,
                         "Ще одне прохання: знайдіть користувача з іменем Валентин "
                         "і надішліть йому пошту.")
        self.assertEqual(removed, ["Дякую за перегляд!"])

    def test_pure_artifact_is_returned_unchanged(self):
        # emptying a take is worse than leaving the artifact — is_pure_artifact
        # plus flow.py's drop path own this case
        for phrase in ("Дякую за перегляд!", "Thanks for watching",
                       "  Підпишіться на канал  "):
            with self.subTest(phrase=phrase):
                cleaned, removed = tf.trim_artifacts(phrase)
                self.assertEqual(cleaned, phrase)
                self.assertEqual(removed, [])

    def test_leading_artifact(self):
        cleaned, removed = tf.trim_artifacts(
            "Дякую за перегляд! Тепер перевір, будь ласка, логи сервера.")
        self.assertEqual(cleaned, "Тепер перевір, будь ласка, логи сервера.")
        self.assertEqual(removed, ["Дякую за перегляд!"])

    def test_two_stacked_artifacts_at_the_end(self):
        cleaned, removed = tf.trim_artifacts(
            "Перевір логи сервера. Дякую за перегляд! Підпишіться на канал.")
        self.assertEqual(cleaned, "Перевір логи сервера.")
        self.assertEqual(len(removed), 2)

    def test_middle_of_sentence_is_never_touched(self):
        # this is real speech about the artifact, and eating it would destroy
        # the user's text
        raw = "Я написав дякую за перегляд у коментарі під відео."
        self.assertEqual(tf.trim_artifacts(raw), (raw, []))

    def test_not_matched_inside_a_longer_word(self):
        raw = "Недякую за переглядом користувача"
        self.assertEqual(tf.trim_artifacts(raw), (raw, []))

    def test_clean_text_is_byte_identical(self):
        for text in CLEAN_UK:
            with self.subTest(text=text):
                self.assertEqual(tf.trim_artifacts(text), (text, []))

    def test_empty_and_whitespace(self):
        self.assertEqual(tf.trim_artifacts(""), ("", []))
        self.assertEqual(tf.trim_artifacts("   "), ("   ", []))


class TestRestoreTerms(unittest.TestCase):
    def test_wispr_flow_from_history(self):
        fixed, changes = tf.restore_terms(
            "Проаналізую на віспор флоу оригінальний", "Wispr Flow,Claude Code")
        self.assertEqual(fixed, "Проаналізую на Wispr Flow оригінальний")
        self.assertEqual(changes, [("віспор флоу", "Wispr Flow")])

    def test_real_history_transliterations(self):
        cases = [
            ("Клауд код.", "Claude Code."),
            ("Або кодекс.", "Або Codex."),
            ("Та антигравити.", "Та Antigravity."),
            ("Дивись, мені потрібна інформація для Хермес.",
             "Дивись, мені потрібна інформація для Hermes."),
            ("Щоб ти ще додав в обсидіан.", "Щоб ти ще додав в Obsidian."),
        ]
        for raw, want in cases:
            with self.subTest(raw=raw):
                self.assertEqual(tf.restore_terms(raw, DICT)[0], want)

    def test_case_normalisation_of_a_latin_term(self):
        self.assertEqual(tf.restore_terms("Але щоб оригінал на Github лишився.", DICT)[0],
                         "Але щоб оригінал на GitHub лишився.")
        self.assertEqual(tf.restore_terms("Пишемо в sqlite базу.", DICT)[0],
                         "Пишемо в SQLite базу.")

    def test_lowercase_dictionary_term_keeps_sentence_capital(self):
        # "бекенд" is lowercase in the dictionary: there is no capitalisation to
        # restore, and lowercasing the first word of a sentence is corruption
        for raw in ("Бекенд працює нормально.", "Промпт треба переписати.",
                    "Openrouter віддає помилку."):
            with self.subTest(raw=raw):
                self.assertEqual(tf.restore_terms(raw, DICT)[0], raw)

    def test_cyrillic_dictionary_terms_keep_their_inflection(self):
        # fuzzy matching is disabled for Cyrillic entries precisely so that
        # Ukrainian case endings survive
        raw = "У промпті для субагента бракує контексту про бекенди."
        self.assertEqual(tf.restore_terms(raw, DICT), (raw, []))

    def test_short_terms_are_not_fuzzy_matched(self):
        # n8n is 3 characters: exact only, never fuzzy, or it matches noise
        raw = "Він написав нан і пішов."
        self.assertEqual(tf.restore_terms(raw, DICT), (raw, []))
        self.assertEqual(tf.restore_terms("Сценарій у n8n готовий.", DICT),
                         ("Сценарій у n8n готовий.", []))

    def test_not_matched_inside_a_longer_word(self):
        raw = "Кодексуальний підхід і антигравитаційний ефект."
        self.assertEqual(tf.restore_terms(raw, DICT), (raw, []))

    def test_multiword_term_needs_whitespace_between_its_words(self):
        # "клауд, код" is not the phrase "Claude Code"
        fixed, _ = tf.restore_terms("Спочатку клауд, код потім.", DICT)
        self.assertEqual(fixed, "Спочатку клауд, код потім.")

    def test_spacing_and_punctuation_are_preserved(self):
        fixed, _ = tf.restore_terms("  Так,   кодекс —  добре!  ", DICT)
        self.assertEqual(fixed, "  Так,   Codex —  добре!  ")

    def test_apostrophe_words_stay_one_token(self):
        raw = "Він зробив п'ять правок і сказав дев'ять слів."
        self.assertEqual(tf.restore_terms(raw, DICT), (raw, []))

    def test_empty_inputs(self):
        self.assertEqual(tf.restore_terms("", DICT), ("", []))
        self.assertEqual(tf.restore_terms("Будь-який текст.", ""),
                         ("Будь-який текст.", []))
        self.assertEqual(tf.restore_terms("Будь-який текст.", " , , "),
                         ("Будь-який текст.", []))


class TestRestoreTermsDoesNotCorrupt(unittest.TestCase):
    """The anti-corruption suite. restore_terms is the only function in this
    module that can actively damage good output, so every one of these real
    history lines must come back byte-identical."""

    def test_clean_ukrainian_is_untouched(self):
        for text in CLEAN_UK:
            with self.subTest(text=text):
                fixed, changes = tf.restore_terms(text, DICT)
                self.assertEqual(fixed, text)
                self.assertEqual(changes, [])

    def test_near_misses_are_left_alone(self):
        # ordinary words one or two letters away from a transliteration
        # candidate: at the chosen cutoff none of them may be rewritten
        near = [
            "У пацієнта підозра на герпес.",          # ~ Hermes -> гермес
            "Це просто гарний код для тесту.",        # ~ Codex  -> код
            "Клас обсидіанового кольору.",            # ~ Obsidian, inside a word
            "Ми кодуємо це українською.",
            "Гарний крем і гарна кава.",
        ]
        for text in near:
            with self.subTest(text=text):
                self.assertEqual(tf.restore_terms(text, DICT), (text, []))

    def test_latin_text_is_never_fuzzy_matched(self):
        # the fuzzy layer only ever looks at all-Cyrillic windows, so English
        # words that resemble a term cannot be rewritten
        for text in ("The code is fine, the coder is not.",
                     "Please check the codes and the cloud fare price."):
            with self.subTest(text=text):
                self.assertEqual(tf.restore_terms(text, DICT), (text, []))

    def test_idempotent(self):
        raw = "Клауд код і кодекс на віспор флоу."
        once, _ = tf.restore_terms(raw, DICT)
        twice, changes = tf.restore_terms(once, DICT)
        self.assertEqual(twice, once)
        self.assertEqual(changes, [])


class TestRussianDetector(unittest.TestCase):
    def test_ru_chars_exact(self):
        self.assertEqual(tf.ru_chars("пошты"), "ы")
        self.assertEqual(tf.ru_chars("Рідок лабораторія пошты"), "ы")
        self.assertEqual(tf.ru_chars("Всё-таки"), "ё")
        self.assertEqual(tf.ru_chars(""), "")

    def test_ru_chars_empty_on_clean_ukrainian(self):
        for text in CLEAN_UK:
            with self.subTest(text=text):
                self.assertEqual(tf.ru_chars(text), "")

    def test_ru_score_zero_on_clean_ukrainian(self):
        for text in CLEAN_UK:
            with self.subTest(text=text):
                self.assertEqual(tf.ru_score(text), 0.0)
                self.assertFalse(tf.looks_russian(text))

    def test_ru_score_high_on_russian(self):
        for text in ("Тесты", "Релиз", "Всё-таки чуть побольше",
                     "Всё-таки чуть побольше, тож срок — они утром",
                     "Рідок лабораторія пошты", "Раз, два, три, четыре, пять."):
            with self.subTest(text=text):
                self.assertGreaterEqual(tf.ru_score(text), 0.5)
                self.assertTrue(tf.looks_russian(text))

    def test_score_is_bounded(self):
        for text in CLEAN_UK + ["Тесты", "", "   ", "123 456", "Всё"]:
            with self.subTest(text=text):
                self.assertGreaterEqual(tf.ru_score(text), 0.0)
                self.assertLessEqual(tf.ru_score(text), 1.0)

    def test_empty_and_punctuation_only(self):
        for text in ("", "   ", "...", "123"):
            with self.subTest(text=text):
                self.assertEqual(tf.ru_score(text), 0.0)
                self.assertFalse(tf.looks_russian(text))

    def test_single_stray_letter_is_not_russian(self):
        # the one false positive an earlier version produced over the whole
        # history: a stutter/hyphen artifact, not the Russian conjunction
        self.assertFalse(tf.looks_russian("Які+и, які-и з цього кроку, якщо ми зробимо"))

    def test_threshold_is_honoured(self):
        self.assertTrue(tf.looks_russian("Тесты", threshold=0.9))
        self.assertFalse(tf.looks_russian("Тесты", threshold=1.5))


if __name__ == "__main__":
    unittest.main()
