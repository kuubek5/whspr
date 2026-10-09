"""Tests for snippets: a whole-utterance trigger pastes a stored block verbatim.

The pure matcher is tested directly; the pipeline tests drive the real
_transcribe_impl with the cloud backend stubbed, so like test_async_polish.py
nothing here touches the real clipboard, keyboard, network or models."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import flow
import text_fixes

SIG = "З повагою,\nРоман Кубек\n+380 00 000 00 00"
SNIPS = {"мій підпис": SIG, "посилання на календар": "https://cal.example.com/r",
         "моя адреса": "вул. Прикладна, 1\nКиїв"}


class Matcher(unittest.TestCase):
    def m(self, text, snips=SNIPS, fuzzy=True):
        hit = text_fixes.match_snippet(text, snips, fuzzy)
        return hit[0] if hit else None

    def test_exact(self):
        self.assertEqual(self.m("мій підпис"), "мій підпис")

    def test_case_punctuation_spaces(self):
        for t in ("Мій підпис.", "МІЙ  ПІДПИС!", "  мій підпис…  ", "Мій, підпис?"):
            self.assertEqual(self.m(t), "мій підпис", t)

    def test_prefix(self):
        self.assertEqual(self.m("Вставити мій підпис."), "мій підпис")
        self.assertEqual(self.m("вставити сніпет посилання на календар"),
                         "посилання на календар")

    def test_contains_does_not_trigger(self):
        for t in ("Я пришлю мій підпис завтра.", "мій підпис і печатка",
                  "Ось посилання на календар на завтра"):
            self.assertIsNone(self.m(t), t)

    def test_fuzzy_small_variance(self):
        # one letter misheard in a long trigger
        self.assertEqual(self.m("Посилання на календарь."), "посилання на календар")
        self.assertEqual(self.m("мій підпіс"), "мій підпис")

    def test_fuzzy_conservative(self):
        self.assertIsNone(self.m("твій підпис"))
        self.assertIsNone(self.m("моя адресa", {"адреса": "x"}))  # different words
        # short trigger never fuzzes
        self.assertIsNone(self.m("адресу", {"адреса": "x"}))
        self.assertIsNone(self.m("Посилання на календарь.", fuzzy=False))

    def test_ambiguous_fuzzy_is_none(self):
        snips = {"мій підпис один": "a", "мій підпис одна": "b"}
        self.assertIsNone(self.m("мій підпис одне", snips))

    def test_empty_bodies_ignored(self):
        self.assertIsNone(self.m("мій підпис", {"мій підпис": "  "}))
        self.assertIsNone(self.m("мій підпис", {}))


class Pipeline(unittest.TestCase):
    NAMES = ("_cloud_transcribe", "paste_text", "history_add", "set_status",
             "log", "llm_available", "llm_polish", "_llm_request",
             "_schedule_llm_polish")

    def setUp(self):
        self._orig = {n: getattr(flow, n) for n in self.NAMES}
        self._cfg = dict(flow.config)
        self._state = dict(flow.state)
        self.pasted, self.hist, self.llm, self.selection = [], [], [], []
        self.transcript = ""
        flow._cloud_transcribe = lambda audio, hint: self.transcript
        flow.paste_text = lambda t, h, restore=None: (self.pasted.append(t) or True)
        flow.history_add = lambda t, l, d: (self.hist.append(t) or 1)
        flow.set_status = lambda s: None
        flow.log = lambda *a, **k: None
        # the LLM is "available" so any call to it would be a real bug
        flow.llm_available = lambda: True
        flow.llm_polish = lambda *a, **k: (self.llm.append(a) or a[0])
        flow._llm_request = lambda *a, **k: (self.llm.append(a) or "x")
        flow._schedule_llm_polish = lambda *a, **k: self.llm.append(a)
        flow.config.update({"stt_backend": "cloud", "overlay": False,
                            "snippets": dict(SNIPS), "snippets_enabled": True,
                            "voice_commands": True, "app_styles_enabled": False,
                            "dictionary": "", "llm_async": True})
        flow.state["last_output"] = None

    def tearDown(self):
        for n, f in self._orig.items():
            setattr(flow, n, f)
        flow.config.clear(); flow.config.update(self._cfg)
        flow.state.clear(); flow.state.update(self._state)

    def take(self, transcript, command=False):
        self.transcript = transcript
        audio = [np.full((flow.SAMPLE_RATE, 1), 0.1, dtype=np.float32)]
        orig = flow.run_selection_command
        flow.run_selection_command = lambda t, *a: (self.selection.append(t) or ("ok", True))
        try:
            flow._transcribe_impl([], audio, 42, command=command)
        finally:
            flow.run_selection_command = orig
        return self.pasted[-1] if self.pasted else None

    def test_exact_pastes_verbatim_multiline(self):
        self.assertEqual(self.take("Мій підпис."), SIG)
        self.assertIn("\n", self.pasted[0])
        self.assertEqual(self.hist, [SIG])
        self.assertEqual(flow.state["last_output"]["text"], SIG)
        self.assertEqual(flow.state["last_output"]["hwnd"], 42)
        self.assertEqual(self.llm, [])

    def test_body_not_normalised(self):
        # numbers, "крапка", replacements and capitalisation must not touch it
        body = "два три крапка новий рядок lowercase"
        flow.config["snippets"] = {"тестовий блок": body}
        self.assertEqual(self.take("тестовий блок"), body)

    def test_sentence_with_phrase_is_dictated(self):
        out = self.take("я пришлю мій підпис завтра")
        self.assertNotEqual(out, SIG)
        self.assertIn("підпис", out)
        self.assertNotIn("\n", out)

    def test_command_take_never_triggers(self):
        self.take("мій підпис", command=True)
        self.assertEqual(self.pasted, [])
        self.assertEqual(self.selection, ["мій підпис"])

    def test_disabled(self):
        flow.config["snippets_enabled"] = False
        self.assertNotEqual(self.take("мій підпис"), SIG)

    def test_voice_command_still_works_and_deletes_snippet(self):
        self.take("мій підпис")
        sent = []
        orig = flow._send_backspaces
        orig_u32 = flow.user32

        class U32:
            def GetForegroundWindow(self): return 42
            def SetForegroundWindow(self, h): pass
        flow._send_backspaces = lambda n: sent.append(n)
        flow.user32 = U32()
        try:
            self.take("видали це")
        finally:
            flow._send_backspaces = orig
            flow.user32 = orig_u32
        self.assertEqual(sent, [len(SIG)])
        self.assertIsNone(flow.state["last_output"])

    def test_exact_user_trigger_beats_command_but_fuzzy_does_not(self):
        flow.config["snippets"] = {"видали це": "СНІПЕТ"}
        self.assertEqual(flow.match_snippet("Видали це.")[1], "СНІПЕТ")
        # a near-miss trigger must not steal a built-in command
        flow.config["snippets"] = {"видали цей": "СНІПЕТ"}
        self.assertIsNone(flow.match_snippet("видали це"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
