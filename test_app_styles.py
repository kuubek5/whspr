"""Tests for app_styles: exe -> category, prompt composition, and that every
failure degrades to the plain (pre-feature) prompt. No real windows are touched:
window_app is stubbed wherever a lookup would happen."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app_styles

BASE = "BASE PROMPT"


class Classify(unittest.TestCase):
    def test_builtin_categories(self):
        self.assertEqual(app_styles.classify("telegram.exe"), "chat")
        self.assertEqual(app_styles.classify("outlook.exe"), "email")
        self.assertEqual(app_styles.classify("code.exe"), "code")
        self.assertEqual(app_styles.classify("claude.exe"), "code")

    def test_case_insensitive(self):
        self.assertEqual(app_styles.classify("Telegram.EXE"), "chat")
        self.assertEqual(app_styles.classify("  WindowsTerminal.exe "), "code")

    def test_unknown_and_empty_are_default(self):
        self.assertEqual(app_styles.classify("notepad.exe"), "default")
        self.assertEqual(app_styles.classify(""), "default")
        self.assertEqual(app_styles.classify(None), "default")

    def test_config_override_adds_and_replaces(self):
        cfg = {"app_styles": {"Notepad.exe": "email", "telegram.exe": "default"}}
        self.assertEqual(app_styles.classify("notepad.exe", cfg=cfg), "email")
        self.assertEqual(app_styles.classify("telegram.exe", cfg=cfg), "default")
        # untouched built-ins survive an override of other entries
        self.assertEqual(app_styles.classify("discord.exe", cfg=cfg), "chat")

    def test_bad_override_shapes_ignored(self):
        for bad in (None, [], "x", {"a.exe": 5}):
            self.assertEqual(app_styles.classify("telegram.exe", cfg={"app_styles": bad}), "chat")

    def test_browser_title(self):
        self.assertEqual(app_styles.classify("chrome.exe", "Inbox (3) - Gmail - Google Chrome"), "email")
        self.assertEqual(app_styles.classify("msedge.exe", "WhatsApp"), "chat")
        self.assertEqual(app_styles.classify("chrome.exe", "YouTube"), "default")
        # a title rule never applies to a non-browser
        self.assertEqual(app_styles.classify("notepad.exe", "gmail notes.txt"), "default")


class Compose(unittest.TestCase):
    def test_style_is_appended_after_base(self):
        out = app_styles.compose_prompt(BASE, "chat")
        self.assertTrue(out.startswith(BASE + "\n\n"))
        self.assertIn(app_styles.BUILTIN_STYLE_PROMPTS["chat"], out)

    def test_default_none_unknown_unchanged(self):
        for cat in (None, "", "default", "no-such-category"):
            self.assertEqual(app_styles.compose_prompt(BASE, cat), BASE)

    def test_style_prompt_override(self):
        cfg = {"style_prompts": {"chat": "BE BRIEF", "email": ""}}
        self.assertEqual(app_styles.compose_prompt(BASE, "chat", cfg), BASE + "\n\nBE BRIEF")
        # blank override switches that category's addition off
        self.assertEqual(app_styles.compose_prompt(BASE, "email", cfg), BASE)


class Resolve(unittest.TestCase):
    def setUp(self):
        self._orig = app_styles.window_app

    def tearDown(self):
        app_styles.window_app = self._orig

    def test_resolves_through_window_app(self):
        app_styles.window_app = lambda h: ("telegram.exe", "Chat")
        self.assertEqual(app_styles.resolve_style(123, {}), ("chat", "telegram.exe"))

    def test_lookup_failure_is_default(self):
        app_styles.window_app = lambda h: ("", "")
        self.assertEqual(app_styles.resolve_style(123, {})[0], "default")

        def boom(h):
            raise OSError("access denied")
        app_styles.window_app = boom
        self.assertEqual(app_styles.resolve_style(123, {}), ("default", ""))

    def test_disabled_skips_lookup(self):
        called = []
        app_styles.window_app = lambda h: called.append(h) or ("telegram.exe", "")
        self.assertEqual(app_styles.resolve_style(123, {"app_styles_enabled": False})[0], "default")
        self.assertEqual(called, [])

    def test_real_resolver_never_raises(self):
        # bogus / null handles must come back empty, not blow up
        self.assertEqual(self._orig(0), ("", ""))
        exe, title = self._orig(0xDEAD)
        self.assertIsInstance(exe, str)
        self.assertIsInstance(title, str)


class FlowIntegration(unittest.TestCase):
    """llm_polish appends the style; no style = exactly the old prompt."""
    def setUp(self):
        import flow
        self.flow = flow
        self.seen = []
        self._orig = (flow._llm_request, flow.config.get("llm_prompt"))
        flow._llm_request = lambda p, t, l: (self.seen.append(p) or t)
        flow.config["llm_prompt"] = ""

    def tearDown(self):
        self.flow._llm_request, self.flow.config["llm_prompt"] = self._orig

    def test_no_style_is_unchanged_prompt(self):
        self.flow.llm_polish("текст", "uk")
        self.flow.llm_polish("текст", "uk", "default")
        self.assertEqual(self.seen, [self.flow.LLM_PROMPT, self.flow.LLM_PROMPT])

    def test_style_appends_to_custom_prompt(self):
        self.flow.config["llm_prompt"] = "MY RULES"
        self.flow.llm_polish("текст", "uk", "code")
        self.assertTrue(self.seen[0].startswith("MY RULES\n\n"))
        self.assertIn(app_styles.BUILTIN_STYLE_PROMPTS["code"], self.seen[0])


class Describe(unittest.TestCase):
    def test_lists_categories_with_overrides(self):
        d = {c["id"]: c for c in app_styles.describe({"app_styles": {"foo.exe": "chat",
                                                                     "bar.exe": "mine"}})}
        self.assertIn("foo.exe", d["chat"]["apps"])
        self.assertIn("code.exe", d["code"]["apps"])
        self.assertIn("mine", d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
