"""Tests for term_suggest.suggest_terms — "Знайти проблемні слова".

Synthetic corpora only: the real history is the user's private dictation.
Each corpus is padded with ordinary Ukrainian filler so the frequency rules
("common vocabulary") see a realistically sized history.
"""
import unittest

from term_suggest import suggest_terms

# Ordinary speech, repeated: gives the corpus a body of common words, and is
# itself full of inflected forms of one word (робити/роблю/зробив...) that must
# never be suggested.
FILLER = [
    "сьогодні треба зробити звіт і відправити його клієнту",
    "я зробив звіт але клієнт ще не відповів на листа",
    "робимо нову версію і перевіряємо чи все працює",
    "перевір будь ласка чи працює кнопка на головній сторінці",
    "завтра робитимемо дизайн нової сторінки для клієнта",
    "зроби коротко і без зайвих слів бо часу мало",
    "відкрий файл і подивись що там написано",
    "файли лежать у папці на робочому столі",
] * 6


def terms(result):
    return [r["term"].lower() for r in result]


class SuggestTermsTest(unittest.TestCase):

    def test_empty_history(self):
        self.assertEqual(suggest_terms([], ""), [])
        self.assertEqual(suggest_terms(["", "   "], ""), [])
        self.assertEqual(suggest_terms(None, ""), [])

    def test_unstable_compound_surfaces(self):
        # the real-world case: a folder name the decoder never spells the same
        texts = FILLER + [
            "поклади файл у папку скачано-прошитано",
            "відкрий скачано-прошитано і знайди там звіт",
            "я зберіг усе в скачано-прощитано",
            "переміси це в скачано-просчитано",
            "файл лежить у скачане прочитане на диску",
            "скинь у скачана-прошитана",
        ]
        res = suggest_terms(texts, "")
        self.assertTrue(res, "the unstable compound must be suggested")
        top = res[0]
        self.assertIn("-", top["term"])
        self.assertTrue(top["term"].lower().startswith("скачан"))
        spellings = {v for v, _n in top["variants"]}
        self.assertIn("скачано-просчитано", spellings)
        self.assertIn("скачане прочитане", spellings)
        self.assertGreaterEqual(top["total"], 6)
        # canonical = the most frequent hyphenated spelling
        self.assertEqual(top["term"], "скачано-прошитано")
        self.assertTrue(top["examples"])

    def test_ordinary_inflections_are_not_suggested(self):
        texts = FILLER + [
            "ми робили це вчора і зробимо ще раз",
            "він робить усе сам а вона робила інше",
            "перевіряли перевіряємо перевірили перевіримо",
            "клієнти клієнтів клієнтам клієнтами клієнтові",
            "будь-який файл або будь-яка папка підійде",
            "по-моєму це будь-яке рішення",
        ]
        self.assertEqual(suggest_terms(texts, ""), [])

    def test_latin_term_and_its_transliterations_cluster(self):
        texts = FILLER + [
            "відкрий Obsidian і створи нотатку",
            "нотатки лежать в обсідіан",
            "синхронізуй обсидіан з телефоном",
            "у обсідіан є плагін для цього",
        ]
        res = suggest_terms(texts, "")
        self.assertEqual(terms(res), ["obsidian"])
        self.assertEqual(res[0]["term"], "Obsidian")   # the user's casing
        spellings = {v for v, _n in res[0]["variants"]}
        self.assertEqual(spellings, {"Obsidian", "обсідіан", "обсидіан"})

    def test_terms_already_in_dictionary_are_excluded(self):
        texts = FILLER + [
            "відкрий Obsidian і створи нотатку",
            "нотатки лежать в обсідіан",
            "синхронізуй обсидіан з телефоном",
            "поклади файл у папку скачано-прошито",
            "відкрий скачано-прошитано",
            "я зберіг усе в скачано-прощитано",
            "переміси це в скачано-просчитано",
        ]
        self.assertEqual(len(suggest_terms(texts, "")), 2)
        self.assertEqual(suggest_terms(texts, "Obsidian, скачано-прошито"), [])
        # newline-separated dictionaries work too, and case does not matter
        only = terms(suggest_terms(texts, "obsidian"))
        self.assertEqual(len(only), 1)
        self.assertTrue(only[0].startswith("скачано-"))
        self.assertEqual(terms(suggest_terms(texts, "Codex\nСкачано-прошито")), ["obsidian"])

    def test_native_word_that_sounds_english_is_not_a_transliteration(self):
        # "група" in all its cases is Ukrainian, not a mangled "group"
        texts = FILLER + [
            "створи group для проекту",
            "додай його в групу",
            "ця група вже є",
            "у групі п'ять людей",
            "з групи вийшов один",
        ]
        self.assertEqual(suggest_terms(texts, ""), [])

    def test_limit_and_shape(self):
        texts = FILLER + [
            "відкрий Obsidian", "обсідіан", "обсидіан",
            "запусти Telegram", "телеграм", "телеграм",
        ]
        res = suggest_terms(texts, "", limit=1)
        self.assertEqual(len(res), 1)
        r = res[0]
        self.assertEqual(set(r), {"term", "variants", "total", "score", "examples"})
        self.assertEqual(r["total"], sum(n for _v, n in r["variants"]))


if __name__ == "__main__":
    unittest.main()
