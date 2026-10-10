"""Tests for Scribe (command key with nothing selected -> compose a message):
the routing decision, prompt building (per-app style + optional style-profile
hook), output cleaning, and run_selection_command end to end with every side
effect stubbed. Like test_command_mode.py, this never touches the real
keyboard, clipboard, network or window lookups."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flow
from test_command_mode import FakeClip, FakeUser32, FakeKb


class Route(unittest.TestCase):
    def test_selection_rewrites(self):
        self.assertEqual(flow.command_route(None, True), "rewrite")
        self.assertEqual(flow.command_route(None, False), "rewrite")

    def test_nothing_selected_composes_only_when_enabled(self):
        self.assertEqual(flow.command_route(flow.COMMAND_NOTHING_SELECTED, True), "compose")
        self.assertEqual(flow.command_route(flow.COMMAND_NOTHING_SELECTED, False), "abort")

    def test_other_refusals_never_compose(self):
        for err in ("у терміналі не працює", "відпустіть Ctrl/Alt і спробуйте ще",
                    "вікно втрачено — нічого не змінено", "буфер обміну зайнятий"):
            self.assertEqual(flow.command_route(err, True), "abort", err)

    def test_defaults(self):
        self.assertTrue(flow.DEFAULTS["scribe_enabled"])
        self.assertIn(flow.DEFAULTS["scribe_reasoning_effort"], ("low", "medium", "high"))


class Prompt(unittest.TestCase):
    REQ = " напиши Олегу, що зустріч переноситься на завтра "

    def test_base_rules_and_request_tag(self):
        sys_p, user = flow.build_scribe_request(self.REQ)
        self.assertIn("ONLY", sys_p)
        self.assertIn("Never invent facts", sys_p)
        self.assertIn("проєкт", sys_p)
        self.assertEqual(user, "<request>\nнапиши Олегу, що зустріч переноситься на завтра\n</request>")

    def test_chat_vs_email_style(self):
        chat, _ = flow.build_scribe_request(self.REQ, "chat")
        mail, _ = flow.build_scribe_request(self.REQ, "email")
        plain, _ = flow.build_scribe_request(self.REQ, "default")
        self.assertIn("No greeting formula, no sign-off", chat)
        self.assertIn("З повагою", mail)
        self.assertNotIn("З повагою", chat)
        self.assertEqual(plain, flow.SCRIBE_SYSTEM_PROMPT)
        self.assertEqual(flow.build_scribe_request(self.REQ, "мій-власний")[0],
                         flow.SCRIBE_SYSTEM_PROMPT)

    def test_user_style_override(self):
        cfg = {"scribe_style_prompts": {"chat": "Пиши з емодзі.", "email": ""}}
        chat, _ = flow.build_scribe_request(self.REQ, "chat", cfg=cfg)
        mail, _ = flow.build_scribe_request(self.REQ, "email", cfg=cfg)
        self.assertTrue(chat.endswith("Пиши з емодзі."))
        self.assertEqual(mail, flow.SCRIBE_SYSTEM_PROMPT)

    def test_profile_appended_last(self):
        sys_p, _ = flow.build_scribe_request(self.REQ, "chat", "  Пише коротко, без смайлів. ")
        self.assertTrue(sys_p.endswith("Пише коротко, без смайлів."))
        self.assertLess(sys_p.index("messenger"), sys_p.index("Пише коротко"))
        self.assertEqual(flow.build_scribe_request(self.REQ, None, "   ")[0],
                         flow.SCRIBE_SYSTEM_PROMPT)


class ProfileHook(unittest.TestCase):
    def setUp(self):
        self._log = flow.log
        flow.log = lambda *a, **k: None
        # flow ships a real style_profile_prompt now; these tests swap it in
        # and out, so keep the original and put it back — deleting it would
        # break every later test that polishes text
        self._orig_hook = vars(flow).get("style_profile_prompt")

    def tearDown(self):
        flow.log = self._log
        if self._orig_hook is not None:
            flow.style_profile_prompt = self._orig_hook
        elif "style_profile_prompt" in vars(flow):
            del flow.style_profile_prompt

    def test_absent_hook(self):
        if "style_profile_prompt" in vars(flow):
            del flow.style_profile_prompt
        self.assertEqual(flow._style_profile_text(), "")

    def test_present_hook(self):
        flow.style_profile_prompt = lambda cfg: " Профіль. "
        self.assertEqual(flow._style_profile_text(), "Профіль.")

    def test_broken_hook_is_ignored(self):
        def boom(cfg):
            raise RuntimeError("x")
        flow.style_profile_prompt = boom
        self.assertEqual(flow._style_profile_text(), "")
        flow.style_profile_prompt = lambda cfg: None
        self.assertEqual(flow._style_profile_text(), "")


class Clean(unittest.TestCase):
    Q = "напиши Олегу, що зустріч переноситься на завтра"

    def c(self, out, q=None):
        return flow.clean_scribe_output(out, self.Q if q is None else q)

    def test_plain_message_kept(self):
        self.assertEqual(self.c("Олеже, зустріч переноситься на завтра."),
                         "Олеже, зустріч переноситься на завтра.")

    def test_strips_wrappers(self):
        msg = "Олеже, зустріч переноситься на завтра."
        self.assertEqual(self.c(f"«{msg}»"), msg)
        self.assertEqual(self.c(f'"{msg}"'), msg)
        self.assertEqual(self.c(f"```\n{msg}\n```"), msg)
        self.assertEqual(self.c(f"<message>\n{msg}\n</message>"), msg)

    def test_inner_quotes_not_mistaken_for_wrapper(self):
        s = '"Кава" — о 10, а "Чай" — о 12'
        self.assertEqual(self.c(s), s)

    def test_strips_preface(self):
        msg = "Олеже, зустріч переноситься на завтра."
        self.assertEqual(self.c("Ось повідомлення:\n" + msg), msg)
        self.assertEqual(self.c("Звісно! Ось варіант повідомлення для Олега:\n\n" + msg), msg)
        self.assertEqual(self.c("Here is the message: " + msg), msg)
        # a real first line that merely starts with "Ось" stays
        keep = "Ось документи, які ти просив:\n- договір\n- акт"
        self.assertEqual(self.c(keep, "скинь Олі документи"), keep)
        # a preface with nothing after it is not a message
        self.assertIsNone(self.c("Ось повідомлення:"))

    def test_trailing_spaces_and_capital(self):
        self.assertEqual(self.c("колеги,  \nу понеділок я у відпустці.  "),
                         "Колеги,\nу понеділок я у відпустці.")

    def test_rejects_refusals_and_meta(self):
        for bad in ("Як AI, я не можу надсилати повідомлення.",
                    "Будь ласка, надайте текст.",
                    "Уточніть, будь ласка, кому адресоване повідомлення?",
                    "I'm sorry, but I can't help with that.",
                    "<request>напиши Олегу</request>"):
            self.assertIsNone(self.c(bad), bad)

    def test_refusal_phrase_from_request_allowed(self):
        q = "напиши Марині, що я не можу виконати це завдання до п'ятниці"
        out = "Марино, я не можу виконати це завдання до п'ятниці."
        self.assertEqual(self.c(out, q), out)

    def test_rejects_empty_echo_and_long(self):
        self.assertIsNone(self.c(None))
        self.assertIsNone(self.c("   "))
        self.assertIsNone(self.c('""'))
        self.assertIsNone(self.c("Напиши Олегу, що зустріч переноситься на завтра."))
        self.assertIsNone(self.c("а" * (flow.SCRIBE_MAX_OUT + 1)))
        self.assertIsNotNone(self.c("а" * flow.SCRIBE_MAX_OUT))


class RunScribe(unittest.TestCase):
    """run_selection_command with nothing selected, Scribe on."""
    HWND = 777

    def setUp(self):
        self._orig = (flow.pyperclip, flow.user32, flow.kb, flow.log, flow._llm_request,
                      flow.paste_text, flow.history_add, flow._overlay_flash,
                      flow.app_styles.resolve_style, dict(flow.state),
                      dict(flow.config), flow.COMMAND_COPY_TIMEOUT_S)
        self.clip = FakeClip("мій буфер")
        flow.pyperclip = self.clip
        flow.user32 = FakeUser32(self.clip, self.HWND)
        self.logs = []
        flow.log = lambda m, *a, **k: self.logs.append(str(m))
        flow.COMMAND_COPY_TIMEOUT_S = 0.2
        self.pasted, self.hist, self.calls, self.flashes = [], [], [], []
        flow.paste_text = self.fake_paste
        flow.history_add = lambda t, l, d: self.hist.append(t) or 1
        flow._overlay_flash = lambda m, ok: self.flashes.append(m)
        self.category = "chat"
        flow.app_styles.resolve_style = lambda h, cfg: (self.category, "telegram.exe")
        flow.config["llm"] = "groq"
        flow.config["groq_api_key"] = "x"
        flow.config["scribe_enabled"] = True
        flow.state["llm_down_until"] = 0
        flow.state["last_output"] = None
        self.reply = "Олеже, зустріч переноситься на завтра на 15:00."
        flow._llm_request = lambda s, u, label: (self.calls.append((s, u, label)) or self.reply)

    def tearDown(self):
        (flow.pyperclip, flow.user32, flow.kb, flow.log, flow._llm_request,
         flow.paste_text, flow.history_add, flow._overlay_flash,
         flow.app_styles.resolve_style, st, cfg, flow.COMMAND_COPY_TIMEOUT_S) = self._orig
        flow.state.clear(); flow.state.update(st)
        flow.config.clear(); flow.config.update(cfg)

    def fake_paste(self, text, hwnd, restore=flow._READ_CLIPBOARD):
        self.pasted.append((text, hwnd, restore))
        return True

    REQ = "напиши Олегу, що зустріч переноситься на завтра на 15:00, ввічливо"

    def run_cmd(self, selection=None, instruction=REQ):
        flow.kb = FakeKb(self.clip, selection)
        return flow.run_selection_command(instruction, "uk", 1.0, self.HWND)

    def test_compose_pastes_message(self):
        msg, ok = self.run_cmd()
        self.assertTrue(ok, msg)
        self.assertEqual(msg, "готово")
        self.assertEqual(len(self.calls), 1)
        system, user, label = self.calls[0]
        self.assertEqual(label, "scribe")
        self.assertIn(self.REQ, user)
        self.assertIn("messenger", system)  # chat style applied
        # pasted with the default restore: the clipboard as the user had it
        self.assertEqual(self.pasted, [(self.reply, self.HWND, flow._READ_CLIPBOARD)])
        self.assertEqual(self.clip.text, "мій буфер")
        self.assertEqual(self.hist, [self.reply])
        self.assertEqual(flow.state["last_output"]["text"], self.reply)
        self.assertEqual(self.flashes, ["пишу…"])
        # the probe still ran (Ctrl+C), and nothing about the text was logged
        self.assertIn(0x43, flow.kb.keys)
        self.assertFalse(any("Олеж" in m for m in self.logs))

    def test_email_style_reaches_prompt(self):
        self.category = "email"
        self.run_cmd()
        self.assertIn("З повагою", self.calls[0][0])

    def test_profile_hook_reaches_prompt(self):
        orig = vars(flow).get("style_profile_prompt")
        flow.style_profile_prompt = lambda cfg: "Пише без знаків оклику."
        try:
            self.run_cmd()
        finally:
            if orig is not None:
                flow.style_profile_prompt = orig
            else:
                del flow.style_profile_prompt
        self.assertIn("Пише без знаків оклику.", self.calls[0][0])

    def test_selection_still_rewrites(self):
        self.reply = "Ввічливий текст."
        msg, ok = self.run_cmd("грубий текст", "зроби ввічливіше")
        self.assertTrue(ok)
        self.assertEqual(self.calls[0][2], "command-mode")
        self.assertEqual(self.pasted, [("Ввічливий текст.", self.HWND, "мій буфер")])

    def test_disabled_keeps_old_behaviour(self):
        flow.config["scribe_enabled"] = False
        msg, ok = self.run_cmd()
        self.assertEqual((msg, ok), ("нічого не виділено", False))
        self.assertEqual((self.calls, self.pasted, self.hist), ([], [], []))

    def test_terminal_refused_no_probe_no_compose(self):
        flow.user32.cls = "ConsoleWindowClass"
        msg, ok = self.run_cmd()
        self.assertFalse(ok)
        self.assertEqual(msg, "у терміналі не працює")
        self.assertEqual(flow.kb.keys, [])  # no Ctrl+C
        self.assertEqual((self.calls, self.pasted), ([], []))

    def test_llm_off_types_nothing(self):
        flow.config["llm"] = "off"
        msg, ok = self.run_cmd()
        self.assertFalse(ok)
        self.assertEqual(flow.kb.keys, [])
        self.assertEqual((self.calls, self.pasted), ([], []))

    def test_llm_failure_types_nothing(self):
        self.reply = None
        msg, ok = self.run_cmd()
        self.assertFalse(ok)
        self.assertIn("нічого не написано", msg)
        self.assertEqual((self.pasted, self.hist), ([], []))
        self.assertIsNone(flow.state["last_output"])
        self.assertEqual(self.clip.text, "мій буфер")

    def test_bad_reply_types_nothing(self):
        self.reply = "Як AI, я не можу надсилати повідомлення від вашого імені."
        msg, ok = self.run_cmd()
        self.assertFalse(ok)
        self.assertEqual((self.pasted, self.hist), ([], []))

    def test_paste_failure(self):
        flow.paste_text = lambda t, h, restore=None: False
        msg, ok = self.run_cmd()
        self.assertFalse(ok)
        self.assertEqual(self.hist, [])

    def test_app_wrote_empty_copy_then_compose_restores_clipboard(self):
        msg, ok = self.run_cmd("")  # app answers Ctrl+C with "" on the clipboard
        self.assertTrue(ok, msg)
        self.assertEqual(self.clip.text, "мій буфер")  # probe undid the ""
        self.assertEqual(len(self.pasted), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
