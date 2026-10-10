"""Learned writing style (style_profile.py + flow wiring): traits from synthetic
corpora, thresholds that omit weak evidence, the privacy validator, and the
polish prompt composition. Pure — no network, no real history."""
import inspect, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import style_profile as sp
import flow
import app_styles


def corpus(lines, times=1):
    return [l for _ in range(times) for l in lines]


# 50 short, informal, Latin-term, no-"!" texts opening with «так»
TY_SHORT = corpus([
    "Так, глянь цей файл. Він ламається на старті.",
    "Так, ти можеш перевірити Docker? Там помилка.",
    "Зроби коміт у Git. Потім запусти тести.",
    "Так, твій варіант кращий. Беремо його.",
    "Перевір логи. Ти бачив помилку в API?",
], times=10)


class Traits(unittest.TestCase):
    def ids(self, texts):
        return [t["id"] for t in sp.build_profile(texts)["traits"]]

    def test_informal_short_latin(self):
        ids = self.ids(TY_SHORT)
        for want in ("address_ty", "short_sent", "latin_terms", "no_exclaim",
                     "no_emoji", "openers"):
            self.assertIn(want, ids)
        self.assertNotIn("address_vy", ids)
        self.assertNotIn("long_sent", ids)

    def test_formal_and_exclaim(self):
        texts = corpus([
            "Дякую, ви дуже допомогли нам сьогодні з цим питанням!",
            "Чи могли б ви надіслати ваш звіт до кінця тижня, будь ласка!",
            "Ваша пропозиція нам підходить, чекаємо на договір!",
            "Прошу вас переглянути документ і дати відповідь.",
        ], times=12)
        ids = self.ids(texts)
        self.assertIn("address_vy", ids)
        self.assertIn("exclaim_ok", ids)
        self.assertNotIn("address_ty", ids)
        self.assertNotIn("no_exclaim", ids)

    def test_long_sentences(self):
        long = ("Сьогодні ми обговорили план робіт на наступний місяць і вирішили "
                "що спершу треба закінчити перевірку всіх модулів а потім уже "
                "братися за нову функцію яку давно просили користувачі.")
        self.assertIn("long_sent", self.ids([long] * 45))

    def test_colloquial_verbs(self):
        texts = corpus([
            "Давай зробим це завтра зранку.",
            "Потім берем наступну задачу зі списку.",
            "Ми займемся цим після обіду, добре.",
            "Беремо його в роботу сьогодні.",
            "Зробимо швидко і підем далі.",
        ], times=10)
        self.assertIn("colloquial", self.ids(texts))

    def test_adjective_im_is_not_colloquial(self):
        # "-им/-ем" adjectives and nouns have no "-имо" twin: never counted
        texts = corpus(["Новим проєктом займається великим колективом.",
                        "Кількість проблем і систем зростає з кожним днем."],
                       times=25)
        self.assertNotIn("colloquial", self.ids(texts))


class WeakEvidence(unittest.TestCase):
    def test_too_few_samples_is_empty(self):
        p = sp.build_profile(TY_SHORT[:sp.MIN_SAMPLES - 1])
        self.assertEqual(p["text"], "")
        self.assertEqual(p["traits"], [])

    def test_short_texts_dont_count(self):
        p = sp.build_profile(["Так.", "Добре", "ок ок"] * 100)
        self.assertEqual(p["samples"], 0)
        self.assertEqual(p["text"], "")

    def test_mixed_address_omitted(self):
        texts = corpus(["Ти зроби це, будь ласка, сьогодні.",
                        "Ви зробите це, будь ласка, сьогодні."], times=25)
        ids = [t["id"] for t in sp.build_profile(texts)["traits"]]
        self.assertNotIn("address_ty", ids)
        self.assertNotIn("address_vy", ids)

    def test_few_address_texts_omitted(self):
        texts = ["Ти зроби це сьогодні."] * 5 + ["Треба зробити це сьогодні."] * 60
        ids = [t["id"] for t in sp.build_profile(texts)["traits"]]
        self.assertNotIn("address_ty", ids)

    def test_rare_openers_omitted(self):
        texts = ["Дивись, тут нова задача."] * 3 + ["Треба зробити це сьогодні."] * 60
        self.assertNotIn("openers", [t["id"] for t in sp.build_profile(texts)["traits"]])

    def test_garbage_rows_ignored(self):
        p = sp.build_profile([None, 5, b"x", "", "   "] + TY_SHORT)
        self.assertTrue(p["text"])

    def test_limits(self):
        p = sp.build_profile(TY_SHORT)
        self.assertLessEqual(len(p["text"]), sp.MAX_CHARS)
        self.assertLessEqual(p["text"].count("\n") + 1, sp.MAX_LINES)


class Privacy(unittest.TestCase):
    SECRET = ["Пацієнт Петренко Іван, 45 років, діагноз гіпертонія, тиск 160 на 95.",
              "Так, ти глянь аналізи Коваленко. Номер картки 12345.",
              "Призначити Kardiomagnyl Олені Шевчук завтра о 9:30."]

    def test_profile_text_has_no_history_content(self):
        texts = corpus(self.SECRET, times=20) + TY_SHORT
        p = sp.build_profile(texts)
        self.assertTrue(p["text"])
        ok, why = sp.validate_profile_text(p["text"])
        self.assertTrue(ok, why)
        low = p["text"].lower()
        for w in ("петренко", "коваленко", "шевчук", "олені", "гіпертонія",
                  "kardiomagnyl", "пацієнт", "картки", "файл", "docker"):
            self.assertNotIn(w, low)
        self.assertFalse(any(ch.isdigit() for ch in p["text"]))
        # stats are numbers / allowlisted openers only
        for k, v in p["stats"].items():
            if k == "openers":
                self.assertTrue(set(v) <= set(sp.GENERIC_OPENERS))
            else:
                self.assertIsInstance(v, (int, float), k)

    def test_validator_accepts_every_template_line(self):
        for k, line in sp.T.items():
            line = line.format(openers="«так», «дивись»") if k == "openers" else line
            ok, why = sp.validate_profile_text(sp.HEADER + "\n- " + line)
            self.assertTrue(ok, (k, why))
        self.assertEqual(sp.validate_profile_text(""), (True, ""))

    def test_validator_rejects_digits(self):
        self.assertFalse(sp.validate_profile_text("- Короткі речення 12.")[0])

    def test_validator_rejects_unknown_words(self):
        self.assertFalse(sp.validate_profile_text("- Автор пише про діагноз.")[0])
        self.assertFalse(sp.validate_profile_text("- Автор пише Docker.")[0])

    def test_validator_rejects_names(self):
        # even a word that IS allowlisted, capitalised mid-sentence, looks like a name
        self.assertFalse(sp.validate_profile_text("- Автор звертається Так.")[0])
        self.assertFalse(sp.validate_profile_text("- Автор Петренко.")[0])

    def test_validator_rejects_symbols_and_size(self):
        self.assertFalse(sp.validate_profile_text("- Автор @ пише.")[0])
        self.assertFalse(sp.validate_profile_text("- Автор http пише.")[0])
        self.assertFalse(sp.validate_profile_text("- Автор.\n" * 20)[0])
        self.assertFalse(sp.validate_profile_text(None)[0])

    def test_tampered_config_text_is_dropped(self):
        cfg = {"style_profile_enabled": True,
               "style_profile": {"text": "- Пацієнт Петренко, тиск 160."}}
        self.assertEqual(sp.profile_prompt(cfg), "")
        self.assertEqual(flow.style_profile_prompt(cfg), "")

    def test_openers_only_from_allowlist(self):
        texts = ["Петро, глянь це сьогодні ввечері."] * 60
        p = sp.build_profile(texts)
        self.assertNotIn("петро", p["text"].lower())
        self.assertNotIn("openers", [t["id"] for t in p["traits"]])


class PromptComposition(unittest.TestCase):
    def setUp(self):
        self._saved = {k: flow.config.get(k) for k in
                       ("llm_prompt", "style_profile", "style_profile_enabled",
                        "app_styles_enabled")}
        flow.config["llm_prompt"] = ""
        self.prof = sp.build_profile(TY_SHORT)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                flow.config.pop(k, None)
            else:
                flow.config[k] = v

    def test_empty_profile_leaves_prompt_unchanged(self):
        flow.config["style_profile_enabled"] = True
        flow.config["style_profile"] = {}
        self.assertEqual(flow.compose_polish_prompt(None), flow.LLM_PROMPT)
        self.assertEqual(flow.compose_polish_prompt("chat"),
                         app_styles.compose_prompt(flow.LLM_PROMPT, "chat", flow.config))

    def test_disabled_leaves_prompt_unchanged(self):
        flow.config["style_profile_enabled"] = False
        flow.config["style_profile"] = self.prof
        self.assertEqual(flow.compose_polish_prompt(None), flow.LLM_PROMPT)
        self.assertEqual(flow.style_profile_prompt(), "")

    def test_enabled_appends_after_base_before_app_style(self):
        flow.config["style_profile_enabled"] = True
        flow.config["style_profile"] = self.prof
        p = flow.compose_polish_prompt("chat")
        base_at = p.index(flow.LLM_PROMPT)
        prof_at = p.index(self.prof["text"])
        chat_at = p.index(app_styles.BUILTIN_STYLE_PROMPTS["chat"])
        self.assertTrue(base_at < prof_at < chat_at)
        # and the profile says the per-app instruction wins
        self.assertIn("інструкція для програми нижче важливіші", self.prof["text"])
        self.assertTrue(flow.compose_polish_prompt(None).endswith(self.prof["text"]))

    def test_custom_base_prompt_kept(self):
        flow.config["llm_prompt"] = "Моя інструкція."
        flow.config["style_profile_enabled"] = True
        flow.config["style_profile"] = self.prof
        self.assertTrue(flow.compose_polish_prompt(None).startswith("Моя інструкція."))

    def test_llm_polish_uses_composed_prompt(self):
        flow.config["style_profile_enabled"] = True
        flow.config["style_profile"] = self.prof
        seen = {}
        real = flow._llm_request

        def fake(system, user, label):
            seen["system"], seen["label"] = system, label
            return user
        flow._llm_request = fake
        try:
            flow.llm_polish("тест тексту для перевірки", "uk", "code")
        finally:
            flow._llm_request = real
        self.assertEqual(seen["label"], "polish")
        self.assertIn(self.prof["text"], seen["system"])
        self.assertIn(app_styles.BUILTIN_STYLE_PROMPTS["code"], seen["system"])

    def test_signature(self):
        sig = inspect.signature(flow.style_profile_prompt)
        self.assertEqual(list(sig.parameters), ["cfg"])
        self.assertIn(sig.return_annotation, (str, "str"))
        self.assertIsNone(sig.parameters["cfg"].default)  # flow.config when omitted
        # getattr lookup the Scribe feature uses, with an explicit config
        fn = getattr(flow, "style_profile_prompt")
        self.assertEqual(fn({}), "")
        self.assertEqual(fn({"style_profile_enabled": True,
                             "style_profile": self.prof}), self.prof["text"])
        # never raises on junk
        self.assertEqual(fn({"style_profile_enabled": True, "style_profile": 7}), "")


class Staleness(unittest.TestCase):
    def test_is_stale(self):
        p = sp.build_profile(TY_SHORT, now=1_000_000_000)
        cfg = {"style_profile": p}
        self.assertFalse(sp.is_stale(cfg, 7, now=1_000_000_000 + 86400))
        self.assertTrue(sp.is_stale(cfg, 7, now=1_000_000_000 + 8 * 86400))
        self.assertTrue(sp.is_stale({}, 7))
        self.assertTrue(sp.is_stale({"style_profile": {"built_at": "junk"}}, 7))


class Rebuild(unittest.TestCase):
    def test_rebuild_stores_profile_without_touching_disk(self):
        saved = {k: flow.config.get(k) for k in ("style_profile",)}
        real_hist, real_save, real_log = flow.history_last, flow.save_config, flow.log
        writes, lines = [], []
        flow.history_last = lambda n=100: [(i, "2026-10-10 10:00:00", "uk", 1.0, t)
                                           for i, t in enumerate(TY_SHORT)]
        flow.save_config = lambda cfg: writes.append(dict(cfg))
        flow.log = lines.append
        try:
            prof = flow.rebuild_style_profile("test")
        finally:
            flow.history_last, flow.save_config, flow.log = real_hist, real_save, real_log
            flow.config["style_profile"] = saved["style_profile"] or {}
        self.assertTrue(prof["text"])
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["style_profile"]["text"], prof["text"])
        # the log line carries ids and counts, never a history text
        self.assertEqual(len(lines), 1)
        self.assertNotIn("Docker", lines[0])
        self.assertIn("address_ty", lines[0])


if __name__ == "__main__":
    unittest.main()
