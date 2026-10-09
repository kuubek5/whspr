"""Tests for command mode (voice editing of the selected text): the pure
decision/prompt/sanitising helpers, and run_selection_command end to end with
every side effect stubbed. Like test_async_polish.py, this must never touch the
real keyboard, clipboard or network."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flow


class Pure(unittest.TestCase):
    def test_selection_decision(self):
        self.assertIsNone(flow.selection_from_copy(5, 5, "старе"))   # untouched
        self.assertIsNone(flow.selection_from_copy(5, 6, ""))        # app wrote ""
        self.assertIsNone(flow.selection_from_copy(5, 6, "  \n"))
        self.assertIsNone(flow.selection_from_copy(5, 6, None))
        self.assertEqual(flow.selection_from_copy(5, 6, "текст"), "текст")
        # same text as the old clipboard still counts: the sequence moved
        self.assertEqual(flow.selection_from_copy(5, 7, "старе"), "старе")

    def test_prompt_delimits_parts(self):
        sys_p, user = flow.build_command_request(" скороти ", "Довгий текст.")
        self.assertIn("ONLY", sys_p)
        self.assertIn("<instruction>\nскороти\n</instruction>", user)
        self.assertIn("<text>\nДовгий текст.\n</text>", user)
        self.assertLess(user.index("</instruction>"), user.index("<text>"))

    def test_clean_strips_wrappers(self):
        c = flow.clean_command_output
        self.assertEqual(c('"Привіт!"', "привіт"), "Привіт!")
        self.assertEqual(c("«Привіт!»", "привіт"), "Привіт!")
        self.assertEqual(c("```\nx = 1\n```", "x=1"), "x = 1")
        self.assertEqual(c("<text>\nГотово.\n</text>", "готово"), "Готово.")
        # quotes the source itself had are kept
        self.assertEqual(c('"цитата"', '"цитата"'), '"цитата"')

    def test_clean_keeps_selection_edges(self):
        self.assertEqual(flow.clean_command_output("Рядок.", "  рядок\n"), "  Рядок.\n")

    def test_clean_rejects_bad_replies(self):
        c = flow.clean_command_output
        self.assertIsNone(c(None, "x"))
        self.assertIsNone(c("   ", "x"))
        self.assertIsNone(c('""', "x"))
        self.assertIsNone(c("Будь ласка, надайте текст.", "щось", "скороти"))
        self.assertIsNone(c("<instruction>скороти</instruction> текст", "текст"))
        self.assertIsNone(c("Скороти.", "довгий текст", "скороти"))  # echoed instruction
        self.assertIsNone(c("б" * (flow.COMMAND_OUT_FLOOR + 1), "коротко"))

    def test_clean_allows_legit_translation_and_growth(self):
        c = flow.clean_command_output
        # "I can't" is a refusal for the polisher but a real translation here
        self.assertEqual(c("I can't come tomorrow.", "я не можу прийти завтра",
                           "переклади англійською"), "I can't come tomorrow.")
        sel = "один два три " * 30
        self.assertIsNotNone(c("- " + "\n- ".join(sel.split()), sel, "зроби списком"))

    def test_trigger_binding(self):
        dic = flow.parse_hotkey("mouse_middle")
        self.assertEqual(flow.command_trigger("ctrl+alt+space", True, dic),
                         frozenset({"ctrl", "alt", "space"}))
        self.assertEqual(flow.command_trigger("ctrl+alt+space", False, dic), frozenset())
        # "" must NOT fall through parse_hotkey's f9 default
        self.assertEqual(flow.command_trigger("", True, flow.parse_hotkey("f9")), frozenset())
        self.assertEqual(flow.command_trigger("f9", True, flow.parse_hotkey("f9")), frozenset())

    def test_terminal_classes(self):
        self.assertTrue(flow.is_terminal_class("ConsoleWindowClass"))
        self.assertTrue(flow.is_terminal_class("CASCADIA_HOSTING_WINDOW_CLASS"))
        self.assertFalse(flow.is_terminal_class("Chrome_WidgetWin_1"))
        self.assertFalse(flow.is_terminal_class(""))

    def test_defaults(self):
        self.assertTrue(flow.DEFAULTS["command_mode_enabled"])
        self.assertEqual(flow.DEFAULTS["command_hotkey"], "ctrl+alt+space")


class FakeClip:
    """pyperclip + clipboard sequence number stand-in."""
    def __init__(self, text):
        self.text, self.seq, self.copies = text, 100, []

    def paste(self): return self.text

    def copy(self, t):
        self.text = t; self.seq += 1; self.copies.append(t)


class FakeUser32:
    def __init__(self, clip, hwnd, cls="Notepad"):
        self.clip, self.hwnd, self.cls = clip, hwnd, cls

    def GetForegroundWindow(self): return self.hwnd
    def SetForegroundWindow(self, h): pass
    def GetClipboardSequenceNumber(self): return self.clip.seq
    def GetAsyncKeyState(self, vk): return 0

    def GetClassNameW(self, hwnd, buf, n):
        buf.value = self.cls
        return len(self.cls)


class FakeKb:
    """Records keystrokes; a Ctrl+C 'copies' the app's selection, if any."""
    def __init__(self, clip, selection):
        self.clip, self.selection, self.keys = clip, selection, []

    def pressed(self, *mods):
        kb = self

        class Ctx:
            def __enter__(self): return kb
            def __exit__(self, *a): return False
        return Ctx()

    def press(self, key):
        vk = getattr(key, "vk", None)
        self.keys.append(vk)
        if vk == 0x43 and self.selection is not None:
            self.clip.copy(self.selection)

    def release(self, key): pass


class RunSelectionCommand(unittest.TestCase):
    HWND = 777

    def setUp(self):
        self._orig = (flow.pyperclip, flow.user32, flow.kb, flow.log, flow._llm_request,
                      flow.paste_text, flow.history_add, dict(flow.state),
                      dict(flow.config), flow.COMMAND_COPY_TIMEOUT_S)
        self.clip = FakeClip("мій буфер")
        flow.pyperclip = self.clip
        flow.user32 = FakeUser32(self.clip, self.HWND)
        flow.log = lambda *a, **k: None
        flow.COMMAND_COPY_TIMEOUT_S = 0.2
        self.pasted, self.hist, self.llm_calls = [], [], []
        flow.paste_text = self.fake_paste
        flow.history_add = lambda t, l, d: self.hist.append(t) or 1
        flow.config["llm"] = "groq"
        flow.config["groq_api_key"] = "x"
        flow.state["llm_down_until"] = 0
        self.reply = "Ввічливий текст."
        flow._llm_request = lambda s, u, label: (self.llm_calls.append(u) or self.reply)

    def tearDown(self):
        (flow.pyperclip, flow.user32, flow.kb, flow.log, flow._llm_request,
         flow.paste_text, flow.history_add, st, cfg, flow.COMMAND_COPY_TIMEOUT_S) = self._orig
        flow.state.clear(); flow.state.update(st)
        flow.config.clear(); flow.config.update(cfg)

    def fake_paste(self, text, hwnd, restore=None):
        self.pasted.append((text, hwnd, restore))
        return True

    def run_cmd(self, selection, instruction="зроби ввічливіше"):
        flow.kb = FakeKb(self.clip, selection)
        return flow.run_selection_command(instruction, "uk", 1.0, self.HWND)

    def test_happy_path_replaces_and_restores_original_clipboard(self):
        msg, ok = self.run_cmd("грубий текст")
        self.assertTrue(ok, msg)
        self.assertEqual(self.pasted, [("Ввічливий текст.", self.HWND, "мій буфер")])
        self.assertEqual(self.hist, ["Ввічливий текст."])
        self.assertIn(0x43, flow.kb.keys)
        self.assertIn("грубий текст", self.llm_calls[0])
        self.assertEqual(flow.state["last_output"]["text"], "Ввічливий текст.")

    def test_nothing_selected_does_nothing(self):
        msg, ok = self.run_cmd(None)
        self.assertFalse(ok)
        self.assertEqual(msg, "нічого не виділено")
        self.assertEqual((self.pasted, self.llm_calls, self.hist), ([], [], []))
        self.assertEqual(self.clip.text, "мій буфер")
        self.assertEqual(self.clip.copies, [])  # clipboard never written

    def test_app_copies_empty_string_restores(self):
        msg, ok = self.run_cmd("")
        self.assertFalse(ok)
        self.assertEqual(self.clip.text, "мій буфер")
        self.assertEqual(self.pasted, [])

    def test_llm_unavailable_never_copies(self):
        flow.config["llm"] = "off"
        msg, ok = self.run_cmd("текст")
        self.assertFalse(ok)
        self.assertEqual(flow.kb.keys, [])
        self.assertEqual(self.clip.text, "мій буфер")

    def test_llm_failure_restores_clipboard(self):
        self.reply = None
        msg, ok = self.run_cmd("текст")
        self.assertFalse(ok)
        self.assertEqual(self.pasted, [])
        self.assertEqual(self.clip.text, "мій буфер")

    def test_meta_reply_rejected(self):
        self.reply = "Будь ласка, надайте текст, який потрібно змінити."
        msg, ok = self.run_cmd("текст")
        self.assertFalse(ok)
        self.assertEqual(self.pasted, [])
        self.assertEqual(self.clip.text, "мій буфер")

    def test_unchanged_result_not_pasted(self):
        self.reply = "текст"
        msg, ok = self.run_cmd("текст")
        self.assertTrue(ok)
        self.assertEqual(msg, "без змін")
        self.assertEqual(self.pasted, [])
        self.assertEqual(self.clip.text, "мій буфер")

    def test_selection_too_long(self):
        msg, ok = self.run_cmd("а" * (flow.COMMAND_MAX_SELECTION + 1))
        self.assertFalse(ok)
        self.assertEqual(self.llm_calls, [])
        self.assertEqual(self.clip.text, "мій буфер")

    def test_terminal_refused_without_ctrl_c(self):
        flow.user32.cls = "CASCADIA_HOSTING_WINDOW_CLASS"
        msg, ok = self.run_cmd("текст")
        self.assertFalse(ok)
        self.assertEqual(flow.kb.keys, [])  # no Ctrl+C = no SIGINT

    def test_focus_lost_before_copy(self):
        flow.user32.hwnd = 1  # SetForegroundWindow does nothing in the fake
        msg, ok = self.run_cmd("текст")
        self.assertFalse(ok)
        self.assertEqual(flow.kb.keys, [])

    def test_paste_failure_restores_clipboard(self):
        def failing(text, hwnd, restore=None):
            self.clip.copy(text)  # what the real paste_text does on failure
            return False
        flow.paste_text = failing
        msg, ok = self.run_cmd("текст")
        self.assertFalse(ok)
        self.assertEqual(self.clip.text, "мій буфер")
        self.assertEqual(self.hist, [])

    def test_modifiers_held_aborts(self):
        flow.user32.GetAsyncKeyState = lambda vk: 0x8000 if vk == 0x12 else 0
        orig = flow.COMMAND_MODS_TIMEOUT_S
        flow.COMMAND_MODS_TIMEOUT_S = 0.1
        try:
            msg, ok = self.run_cmd("текст")
        finally:
            flow.COMMAND_MODS_TIMEOUT_S = orig
        self.assertFalse(ok)
        self.assertEqual(flow.kb.keys, [])


class PasteRestoreArg(unittest.TestCase):
    """paste_text's new `restore` argument: the explicit value wins over
    whatever is on the clipboard at paste time."""
    def setUp(self):
        self._orig = (flow.pyperclip, flow.user32, flow.kb, flow.threading.Thread)
        self.clip = FakeClip("виділення")
        flow.pyperclip = self.clip
        flow.user32 = FakeUser32(self.clip, 5)
        flow.kb = FakeKb(self.clip, None)
        self.threads = []

        class SyncThread:
            def __init__(s, target=None, daemon=None, **kw): s.target = target
            def start(s): self.threads.append(s.target)
        flow.threading.Thread = SyncThread

    def tearDown(self):
        (flow.pyperclip, flow.user32, flow.kb, flow.threading.Thread) = self._orig

    def test_explicit_restore(self):
        orig_sleep = flow.time.sleep
        flow.time.sleep = lambda s: None
        try:
            self.assertTrue(flow.paste_text("нове", 5, restore="оригінал"))
            self.assertEqual(self.clip.text, "нове")
            for t in self.threads:
                t()
        finally:
            flow.time.sleep = orig_sleep
        self.assertEqual(self.clip.text, "оригінал")
        self.assertIn(0x56, flow.kb.keys)


if __name__ == "__main__":
    unittest.main(verbosity=2)
