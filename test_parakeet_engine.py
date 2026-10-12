"""Engine selection / fallback tests for the optional Parakeet engine.

Both engines are stubbed: no model is loaded, nothing is downloaded, and the
paste / history / status side effects are captured instead of performed, so
this never touches the real keyboard, clipboard, history.db or config.json."""
import os, sys, types, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import flow


class FakeWhisper:
    """Stands in for faster_whisper.WhisperModel.transcribe()."""
    def __init__(self, text, logprob=-0.1, no_speech=0.01):
        self.text, self.logprob, self.no_speech, self.calls = text, logprob, no_speech, 0

    def transcribe(self, audio, **kw):
        self.calls += 1
        seg = types.SimpleNamespace(text=self.text, start=0.0, end=1.0,
                                    avg_logprob=self.logprob,
                                    no_speech_prob=self.no_speech)
        return iter([seg]), types.SimpleNamespace(language=kw.get("language") or "uk")


class EngineSelection(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(flow.config)

    def tearDown(self):
        flow.config.clear(); flow.config.update(self._cfg)

    def test_default_is_whisper(self):
        flow.config.pop("local_engine", None)
        self.assertEqual(flow.local_engine_for("uk"), "whisper")
        self.assertEqual(flow.DEFAULTS["local_engine"], "whisper")

    def test_parakeet_for_supported_languages(self):
        flow.config["local_engine"] = "parakeet"
        self.assertEqual(flow.local_engine_for("uk"), "parakeet")
        self.assertEqual(flow.local_engine_for("en"), "parakeet")

    def test_unsupported_language_falls_back(self):
        flow.config["local_engine"] = "parakeet"
        self.assertEqual(flow.local_engine_for("ja"), "whisper")

    def test_auto_language_uses_parakeet(self):
        flow.config["local_engine"] = "parakeet"
        self.assertEqual(flow.local_engine_for(None, auto=True), "parakeet")

    def test_junk_value_is_whisper(self):
        flow.config["local_engine"] = "nonsense"
        self.assertEqual(flow.local_engine_for("uk"), "whisper")


class TranscribeFallback(unittest.TestCase):
    """Drive the real _transcribe_impl with both engines stubbed."""
    NAMES = ("parakeet_transcribe", "model_for", "load_model", "paste_text",
             "history_add", "set_status", "log", "llm_available")

    def setUp(self):
        self._orig = {n: getattr(flow, n) for n in self.NAMES}
        self._cfg = dict(flow.config)
        self._lang = flow.state["lang"]
        self.pasted, self.pk_calls = [], 0
        self.whisper = FakeWhisper("Привіт, як справи?")
        flow.model_for = lambda lang: self.whisper
        flow.load_model = lambda name=None: self.whisper
        flow.paste_text = lambda t, h: (self.pasted.append(t) or True)
        flow.history_add = lambda *a: 1
        flow.set_status = lambda s: None
        flow.log = lambda *a, **k: None
        flow.llm_available = lambda: False
        flow.config.update({"stt_backend": "local", "auto_lang": False,
                            "dictionary": "", "ru_retry": True,
                            "voice_commands": False, "llm": "off"})
        flow.state["lang"] = flow.LANGUAGES.index("uk")

    def tearDown(self):
        for n, f in self._orig.items():
            setattr(flow, n, f)
        flow.config.clear(); flow.config.update(self._cfg)
        flow.state["lang"] = self._lang

    def parakeet_returns(self, text=None, exc=None):
        def fake(audio):
            self.pk_calls += 1
            if exc:
                raise exc
            return text
        flow.parakeet_transcribe = fake

    def run_take(self):
        audio = [np.full((flow.SAMPLE_RATE, 1), 0.1, dtype=np.float32)]
        flow._transcribe_impl([], audio, 0)
        return self.pasted[-1] if self.pasted else None

    def test_whisper_engine_never_calls_parakeet(self):
        flow.config["local_engine"] = "whisper"
        self.parakeet_returns("не має бути")
        self.assertEqual(self.run_take(), "Привіт, як справи?")
        self.assertEqual(self.pk_calls, 0)

    def test_parakeet_engine_skips_whisper(self):
        flow.config["local_engine"] = "parakeet"
        self.parakeet_returns("Зустрінемось о восьмій.")
        self.assertEqual(self.run_take(), "Зустрінемось о восьмій.")
        self.assertEqual(self.whisper.calls, 0)

    def test_parakeet_failure_falls_back_to_whisper(self):
        flow.config["local_engine"] = "parakeet"
        self.parakeet_returns(exc=FileNotFoundError("not downloaded"))
        self.assertEqual(self.run_take(), "Привіт, як справи?")
        self.assertEqual(self.whisper.calls, 1)

    def test_short_parakeet_take_is_not_dropped(self):
        # no confidence numbers from Parakeet -> the short-AND-unsure rule must
        # not fire on a genuine one-word take
        flow.config["local_engine"] = "parakeet"
        self.parakeet_returns("Так.")
        self.assertEqual(self.run_take(), "Так.")

    def test_known_artifact_still_dropped(self):
        flow.config["local_engine"] = "parakeet"
        self.parakeet_returns("Дякую за перегляд!")
        self.assertIsNone(self.run_take())

    def test_russian_parakeet_take_gets_whisper_second_opinion(self):
        flow.config["local_engine"] = "parakeet"
        self.parakeet_returns("Это тесты для релиза.")
        self.whisper = FakeWhisper("Це тести для релізу.")
        self.assertEqual(self.run_take(), "Це тести для релізу.")
        self.assertEqual(self.whisper.calls, 1)

    def test_equally_russian_whisper_keeps_parakeet(self):
        flow.config["local_engine"] = "parakeet"
        self.parakeet_returns("Это тесты.")
        self.whisper = FakeWhisper("Это тесты!")
        # tie (whisper and its own ru-retry are just as Russian) -> Parakeet's
        self.assertEqual(self.run_take(), "Это тесты.")
        self.assertGreaterEqual(self.whisper.calls, 1)

    def test_ru_retry_off_never_escalates(self):
        flow.config["local_engine"] = "parakeet"
        flow.config["ru_retry"] = False
        self.parakeet_returns("Это тесты.")
        self.assertEqual(self.run_take(), "Это тесты.")
        self.assertEqual(self.whisper.calls, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
