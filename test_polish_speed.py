"""Polish latency work: the short-take skip rule, the reasoning_effort gate,
and the kept-alive HTTP helper (against a local HTTP/1.1 server — no network,
no real key)."""
import http.server, json, os, sys, threading, unittest, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import text_fixes
import flow

skip = text_fixes.polish_skip_reason


class SkipRule(unittest.TestCase):
    def test_short_punctuated_skips(self):
        for t in ("Так.", "Добре, давай.", "Що там далі?", "Привіт, як справи?",
                  "так.", "Беремо в роботу."):
            self.assertIsNotNone(skip(t, 4), t)

    def test_word_threshold(self):
        self.assertIsNotNone(skip("Один два три чотири.", 4))
        self.assertIsNone(skip("Один два три чотири п'ять.", 4))
        # apostrophe word counts once, numbers count as words
        self.assertIsNotNone(skip("П'ять хвилин.", 2))
        self.assertIsNotNone(skip("О 15:30.", 4))

    def test_needs_final_punctuation(self):
        for t in ("Так", "Добре, давай", "Що там далі,"):
            self.assertIsNone(skip(t, 4), t)
        self.assertIsNotNone(skip("Чекай…", 4))
        self.assertIsNotNone(skip("Стоп!", 4))

    def test_fillers_go_to_llm(self):
        for t in ("Ем, добре.", "Ну добре.", "Так, еее, давай.", "Um, okay.", "Е, так."):
            self.assertIsNone(skip(t, 4), t)

    def test_question_word_without_question_mark_goes_to_llm(self):
        self.assertIsNone(skip("Що скажеш.", 4))
        self.assertIsNone(skip("Чи працює.", 4))
        self.assertIsNotNone(skip("Що скажеш?", 4))

    def test_comma_opener_goes_to_llm_unless_punctuated(self):
        self.assertIsNone(skip("Так застосовую.", 4))
        self.assertIsNone(skip("А тут таке.", 4))
        self.assertIsNotNone(skip("Так, застосовую.", 4))
        self.assertIsNotNone(skip("Добре — роби.", 4))
        self.assertIsNotNone(skip("Так.", 4))   # alone: nothing to separate

    def test_russian_goes_to_llm(self):
        self.assertIsNone(skip("Это хорошо.", 4))

    def test_disabled_and_empty(self):
        self.assertIsNone(skip("Так.", 0))
        self.assertIsNone(skip("", 4))
        self.assertIsNone(skip("   ", 4))
        self.assertIsNone(skip("...", 4))   # no words at all
        self.assertIsNone(skip(None, 4))

    def test_reason_has_no_text(self):
        r = skip("Секретний пароль.", 4)
        self.assertNotIn("пароль", r.lower())


class ReasoningEffort(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(flow.config)

    def tearDown(self):
        flow.config.clear(); flow.config.update(self._cfg)

    def test_only_gpt_oss(self):
        flow.config["groq_reasoning_effort"] = "low"
        self.assertEqual(flow._groq_reasoning_effort("openai/gpt-oss-20b"), "low")
        self.assertEqual(flow._groq_reasoning_effort("openai/gpt-oss-120b"), "low")
        self.assertIsNone(flow._groq_reasoning_effort("qwen/qwen3.8-27b"))
        self.assertIsNone(flow._groq_reasoning_effort("llama-3.1-8b-instant"))

    def test_off_and_junk(self):
        for v in ("", None, "none", "turbo", 3):
            flow.config["groq_reasoning_effort"] = v
            self.assertIsNone(flow._groq_reasoning_effort("openai/gpt-oss-20b"), v)

    def test_payload_polish_only(self):
        sent = []
        orig = flow._http_post_json, flow.log, dict(flow.state)
        flow._http_post_json = lambda url, p, h, timeout: (
            sent.append(p) or {"choices": [{"message": {"content": "Так."}}]})
        flow.log = lambda *a, **k: None
        try:
            flow.config.update(llm="groq", groq_api_key="x",
                               groq_model="openai/gpt-oss-20b",
                               groq_reasoning_effort="low")
            flow.state["llm_down_until"] = 0
            self.assertEqual(flow._llm_request("sys", "так", "polish"), "Так.")
            self.assertEqual(sent[-1].get("reasoning_effort"), "low")
            flow._llm_request("sys", "так", "command-mode")
            self.assertNotIn("reasoning_effort", sent[-1])
            flow.config["groq_model"] = "qwen/qwen3.8-27b"
            flow._llm_request("sys", "так", "polish")
            self.assertNotIn("reasoning_effort", sent[-1])
            self.assertEqual(flow._llm_label(), "groq:qwen/qwen3.8-27b")
        finally:
            flow._http_post_json, flow.log, st = orig
            flow.state.clear(); flow.state.update(st)


class PipelineSkip(unittest.TestCase):
    """_transcribe_impl end to end with the recogniser, LLM, paste and history
    stubbed: the skip decision and the one latency line per take."""
    NAMES = ("_cloud_transcribe", "paste_text", "history_add", "set_status",
             "log", "llm_available", "llm_polish", "_schedule_llm_polish")

    def setUp(self):
        import numpy as np
        self.np = np
        self._orig = {n: getattr(flow, n) for n in self.NAMES}
        self._cfg = dict(flow.config)
        self._state = dict(flow.state)
        self.pasted, self.llm, self.logs = [], [], []
        self.transcript = ""
        flow._cloud_transcribe = lambda audio, hint: self.transcript
        flow.paste_text = lambda t, h, restore=None: (self.pasted.append(t) or True)
        flow.history_add = lambda t, l, d: 1
        flow.set_status = lambda s: None
        flow.log = lambda m, *a, **k: self.logs.append(str(m))
        flow.llm_available = lambda: True
        flow.llm_polish = lambda t, *a: (self.llm.append(t) or t.rstrip(".") + "!")
        flow._schedule_llm_polish = lambda *a, **k: self.llm.append(a[0])
        flow.config.update({"stt_backend": "cloud", "overlay": False,
                            "snippets_enabled": False, "voice_commands": False,
                            "app_styles_enabled": False, "dictionary": "",
                            "llm_async": False, "llm": "groq",
                            "groq_model": "openai/gpt-oss-20b",
                            "groq_reasoning_effort": "low",
                            "polish_skip_short": True, "polish_skip_max_words": 4})

    def tearDown(self):
        for n, f in self._orig.items():
            setattr(flow, n, f)
        flow.config.clear(); flow.config.update(self._cfg)
        flow.state.clear(); flow.state.update(self._state)

    def take(self, transcript):
        self.transcript = transcript
        audio = [self.np.full((flow.SAMPLE_RATE, 1), 0.1, dtype=self.np.float32)]
        flow._transcribe_impl([], audio, 42)
        return self.pasted[-1]

    def latency_lines(self):
        return [l for l in self.logs if l.startswith("latency:")]

    def test_short_take_skips_llm_but_still_capitalised(self):
        self.assertEqual(self.take("добре, давай."), "Добре, давай.")
        self.assertEqual(self.llm, [])
        (line,) = self.latency_lines()
        self.assertIn("polish 0.00 (skipped)", line)
        self.assertNotIn("давай", line)

    def test_long_take_goes_to_llm(self):
        self.assertEqual(self.take("Добре, давай зробимо це завтра зранку."),
                         "Добре, давай зробимо це завтра зранку!")
        self.assertEqual(len(self.llm), 1)
        (line,) = self.latency_lines()
        self.assertIn("(groq:openai/gpt-oss-20b/low)", line)
        self.assertNotIn("зранку", line)

    def test_skip_off_always_polishes(self):
        flow.config["polish_skip_short"] = False
        self.take("Так.")
        self.assertEqual(self.llm, ["Так."])

    def test_junk_max_words_falls_back(self):
        flow.config["polish_skip_max_words"] = "lots"
        self.take("Так.")
        self.assertEqual(self.llm, [])  # default 4 applied, not a crash

    def test_skip_applies_to_async_too(self):
        flow.config["llm_async"] = True
        self.take("Так.")
        self.assertEqual(self.llm, [])
        self.take("Добре, давай зробимо це завтра зранку.")
        self.assertEqual(len(self.llm), 1)  # scheduled, not inline
        self.assertIn("(async)", self.latency_lines()[-1])

    def test_trace_from_stop_rec_carries_wait(self):
        tr = flow.latency.Trace()
        tr.stopped(1.5)
        self.transcript = "Так."
        audio = [self.np.full((flow.SAMPLE_RATE, 1), 0.1, dtype=self.np.float32)]
        flow._transcribe_impl([], audio, 42, False, tr)
        (line,) = self.latency_lines()
        self.assertRegex(line, r"= wait 1\.50 \+ queue")


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive
    peers: list = []

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        _Handler.peers.append(self.client_address[1])  # client port = connection
        status = 400 if body.get("fail") else 200
        out = json.dumps({"echo": body}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


class KeepAlive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.srv.daemon_threads = True
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/v1/chat"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def setUp(self):
        _Handler.peers.clear()
        with flow._http_pool_lock:
            for c, _ in flow._http_pool.values():
                c.close()
            flow._http_pool.clear()
        self._gp = flow.urllib.request.getproxies
        flow.urllib.request.getproxies = lambda: {}  # no proxy on the test box

    def tearDown(self):
        flow.urllib.request.getproxies = self._gp

    def post(self, payload):
        return flow._http_post_json(self.url, payload,
                                    {"Content-Type": "application/json"}, 5)

    def test_reuses_one_connection(self):
        for i in range(3):
            self.assertEqual(self.post({"i": i})["echo"], {"i": i})
        self.assertEqual(len(set(_Handler.peers)), 1, _Handler.peers)

    def test_http_error_raises_like_urlopen_and_is_not_parked(self):
        self.post({"i": 0})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.post({"fail": True})
        self.assertEqual(cm.exception.code, 400)
        self.post({"i": 1})
        self.assertEqual(len(set(_Handler.peers)), 2)  # fresh after the error

    def test_stale_parked_connection_retries_once(self):
        self.post({"i": 0})
        # the server side hangs up on the idle socket (what a proxy/NAT does)
        with flow._http_pool_lock:
            conn, _ = next(iter(flow._http_pool.values()))
        conn.sock.shutdown(2)
        self.assertEqual(self.post({"i": 1})["echo"], {"i": 1})

    def test_idle_too_long_is_replaced(self):
        self.post({"i": 0})
        key = next(iter(flow._http_pool))
        with flow._http_pool_lock:
            c, _ = flow._http_pool[key]
            flow._http_pool[key] = (c, flow.time.monotonic() - flow._HTTP_IDLE_MAX_S - 1)
        self.post({"i": 1})
        self.assertEqual(len(set(_Handler.peers)), 2)

    def test_proxy_falls_back_to_urlopen(self):
        flow.urllib.request.getproxies = lambda: {"http": "http://proxy.invalid:1"}
        calls = []
        orig = flow.urllib.request.urlopen
        flow.urllib.request.urlopen = lambda req, timeout: calls.append(req) or (_ for _ in ()).throw(OSError("via proxy"))
        try:
            with self.assertRaises(OSError):
                self.post({"i": 0})
        finally:
            flow.urllib.request.urlopen = orig
        self.assertEqual(len(calls), 1)
        self.assertEqual(_Handler.peers, [])

    def test_connection_refused_raises(self):
        with self.assertRaises(OSError):
            flow._http_post_json("http://127.0.0.1:9/x", {}, {}, 2)


if __name__ == "__main__":
    unittest.main()
