"""Smart Turn (semantic end-of-turn) tests: flow.SmartTurnGate decisions, the
audio window shown to the model, and the hands-free loop with the model
stubbed — no mic, no network. The one real-model test is skipped unless the
onnx is already in the local HF cache."""
import os, sys, threading, time, unittest
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flow

F = flow.VAD_FRAME_S  # 32 ms
STOP = 2.0            # Roma's silence_stop_s
GAP = 0.6


class Gate(unittest.TestCase):
    def test_never_asks_before_speech(self):
        g = flow.SmartTurnGate(GAP, STOP)
        for s in np.arange(0, 5, 0.1):
            self.assertFalse(g.should_ask(False, float(s)))

    def test_asks_only_after_gap(self):
        g = flow.SmartTurnGate(GAP, STOP)
        self.assertFalse(g.should_ask(True, 0.0))
        self.assertFalse(g.should_ask(True, 0.3))
        self.assertFalse(g.should_ask(True, GAP - 0.05))
        self.assertTrue(g.should_ask(True, GAP))

    def test_one_ask_per_pause_then_new_pause_asks_again(self):
        g = flow.SmartTurnGate(GAP, STOP)
        self.assertTrue(g.should_ask(True, 0.65))
        self.assertFalse(g.verdict(0.1))
        for s in (0.7, 1.0, 1.3, 1.9):
            self.assertFalse(g.should_ask(True, s), s)
        # the user spoke again (silence back to 0), then a new pause
        self.assertFalse(g.should_ask(True, 0.0))
        self.assertTrue(g.should_ask(True, 0.62))

    def test_new_pause_detected_without_seeing_zero(self):
        # speech and a new pause both fell between two polls
        g = flow.SmartTurnGate(GAP, STOP)
        self.assertTrue(g.should_ask(True, 0.9))
        g.verdict(0.2)
        self.assertFalse(g.should_ask(True, 0.3))
        self.assertTrue(g.should_ask(True, 0.6))

    def test_second_ask_spaced_one_gap_from_the_first(self):
        g = flow.SmartTurnGate(0.5, 3.0, max_asks=2)
        self.assertTrue(g.should_ask(True, 0.8))   # late poll
        g.verdict(0.1)
        self.assertFalse(g.should_ask(True, 0.9))  # not on the very next poll
        self.assertTrue(g.should_ask(True, 1.3))
        g.verdict(0.1)
        self.assertFalse(g.should_ask(True, 2.5))

    def test_no_ask_at_or_after_silence_stop(self):
        self.assertFalse(flow.SmartTurnGate(2.0, 2.0).should_ask(True, 2.0))
        self.assertFalse(flow.SmartTurnGate(2.5, 2.0).should_ask(True, 2.6))

    def test_verdict_threshold(self):
        g = flow.SmartTurnGate(GAP, STOP, threshold=0.7)
        self.assertFalse(g.verdict(0.69))
        self.assertTrue(g.verdict(0.7))

    def test_gap_has_a_floor(self):
        self.assertGreaterEqual(flow.SmartTurnGate(0.0, STOP).gap, 0.3)

    def test_failure_disables(self):
        g = flow.SmartTurnGate(GAP, STOP)
        g.fail()
        self.assertFalse(g.should_ask(True, 1.0))


def energy_vad(audio):
    """Stub Silero: a frame is 'speech' (0.9) if it carries signal, else 0.0."""
    fr = audio.reshape(-1, 512)
    return np.where(np.abs(fr).max(1) > 0.05, 0.9, 0.0).reshape(-1, 1)


class Loop(unittest.TestCase):
    """Drive vad_poll + smart_turn_poll the way silence_watch does: blocks
    arrive, a poll runs every ~3 blocks (~100 ms)."""

    def setUp(self):
        self._saved = (flow.chunks[:], flow.log)
        self.logs = []
        flow.log = lambda msg, *a, **k: self.logs.append(msg)
        flow.chunks[:] = []

    def tearDown(self):
        flow.chunks[:], flow.log = self._saved

    def blocks(self, seconds, v):
        return [v] * int(round(seconds / F))

    def stream(self, blocks, model=None, poll_every=3):
        """Returns (stop time on the audio clock or None, why, model inputs)."""
        dec, fed = flow.VadAutoStop(STOP), 0
        gate = flow.SmartTurnGate(GAP, STOP) if model else None
        seen = []

        def spy(audio):
            seen.append(audio.copy())
            return model(audio)
        for i, b in enumerate(blocks, 1):
            flow.chunks.append(np.full((512, 1), b, dtype=np.float32))
            if i % poll_every:
                continue
            stop, fed = flow.vad_poll(energy_vad, dec, fed)
            if stop:
                return i * F, "silence", seen
            if gate is not None and flow.smart_turn_poll(spy, gate, dec):
                return i * F, "smart", seen
        return None, None, seen

    def take(self, pause=4.0):
        lead, speech = self.blocks(0.5, 0.0), self.blocks(2.0, 0.2)
        return lead + speech + self.blocks(pause, 0.0), len(lead + speech) * F

    def test_complete_stops_at_gap(self):
        blocks, speech_end = self.take()
        t, why, seen = self.stream(blocks, model=lambda a: 0.9)
        self.assertEqual(why, "smart")
        self.assertGreaterEqual(t - speech_end, GAP - 1e-6)  # never sooner
        self.assertLess(t - speech_end, GAP + 4 * F)          # within one poll
        self.assertEqual(len(seen), 1)
        self.assertTrue(any("smart-turn: complete p=0.90" in m for m in self.logs))

    def test_incomplete_keeps_going_and_stops_like_vad_only(self):
        blocks, _ = self.take()
        t_vad, why_vad, _ = self.stream(blocks)
        flow.chunks[:] = []
        t, why, seen = self.stream(blocks, model=lambda a: 0.1)
        self.assertEqual((why_vad, why), ("silence", "silence"))
        self.assertAlmostEqual(t, t_vad)
        self.assertEqual(len(seen), 1, "one ask per pause")
        self.assertTrue(any("smart-turn: incomplete p=0.10" in m
                            and "keep listening" in m for m in self.logs))

    def test_model_failure_is_identical_to_vad_only(self):
        blocks, _ = self.take()
        t_vad, _, _ = self.stream(blocks)
        flow.chunks[:] = []

        def boom(audio):
            raise RuntimeError("onnx exploded")
        t, why, _ = self.stream(blocks, model=boom)
        self.assertEqual((t, why), (t_vad, "silence"))
        self.assertEqual(sum("smart-turn: failed" in m for m in self.logs), 1)

    def test_never_asks_during_opening_silence(self):
        calls = []
        t, _, _ = self.stream(self.blocks(10, 0.0),
                              model=lambda a: calls.append(1) or 0.99)
        self.assertIsNone(t)
        self.assertEqual(calls, [])

    def test_mid_sentence_pause_then_finished_sentence(self):
        # pause 1 is judged unfinished (keep going), pause 2 finished
        answers = iter([0.2, 0.95])
        blocks = (self.blocks(1.5, 0.2) + self.blocks(1.0, 0.0)
                  + self.blocks(1.5, 0.2) + self.blocks(3.0, 0.0))
        t, why, seen = self.stream(blocks, model=lambda a: next(answers))
        self.assertEqual(why, "smart")
        self.assertEqual(len(seen), 2)
        self.assertLess(t, 4.0 + GAP + 4 * F)

    def test_model_sees_speech_plus_short_tail_only(self):
        blocks, speech_end = self.take()
        _, _, seen = self.stream(blocks, model=lambda a: 0.9)
        audio = seen[0]
        # ends SMART_TURN_TAIL_S into the pause, however late the ask ran
        self.assertAlmostEqual(len(audio) / flow.SAMPLE_RATE,
                               speech_end + flow.SMART_TURN_TAIL_S, delta=F)
        tail = audio[-int(flow.SMART_TURN_TAIL_S * flow.SAMPLE_RATE) + 16:]
        self.assertEqual(np.abs(tail).max(), 0.0)
        self.assertGreater(np.abs(audio[:-int(0.3 * flow.SAMPLE_RATE)]).max(), 0)

    def test_model_input_capped_at_8s(self):
        blocks = self.blocks(12, 0.2) + self.blocks(1.0, 0.0)
        _, _, seen = self.stream(blocks, model=lambda a: 0.9)
        self.assertEqual(len(seen[0]), flow.SMART_TURN_S * flow.SAMPLE_RATE)


class Selection(unittest.TestCase):
    def setUp(self):
        self._orig = (flow._load_smart_turn_model, flow._st_model,
                      flow._st_failed, flow._st_loading, flow.log,
                      dict(flow.config))
        self.logs = []
        flow.log = lambda msg, *a, **k: self.logs.append(msg)
        flow._st_model, flow._st_failed, flow._st_loading = None, False, False

    def tearDown(self):
        (flow._load_smart_turn_model, flow._st_model, flow._st_failed,
         flow._st_loading, flow.log, cfg) = self._orig
        flow.config.clear(); flow.config.update(cfg)

    def wait_load(self):
        for _ in range(200):
            if not flow._st_loading:
                return
            time.sleep(0.01)
        self.fail("load thread never finished")

    def test_defaults(self):
        d = flow.DEFAULTS
        # opt-in until proven on a real mic (TTS cut-offs: 66% false "finished")
        self.assertIs(d["smart_turn"], False)
        self.assertEqual(d["smart_turn_gap_s"], 0.6)
        self.assertEqual(d["smart_turn_threshold"], 0.5)

    def test_off_when_disabled_or_rms(self):
        flow._st_model = lambda a: 0.9
        flow.config["smart_turn"] = False
        self.assertEqual(flow.make_smart_turn_gate(flow.VadAutoStop(STOP), STOP),
                         (None, None))
        flow.config["smart_turn"] = True
        self.assertEqual(flow.make_smart_turn_gate(flow.RmsAutoStop(STOP), STOP),
                         (None, None))
        flow.config["autostop_engine"] = "rms"
        self.assertFalse(flow.smart_turn_enabled())

    def test_not_ready_never_blocks_then_loads(self):
        gate_open = threading.Event()

        def slow():
            gate_open.wait(2)
            return lambda a: 0.9
        flow._load_smart_turn_model = slow
        flow.config.update(smart_turn=True, autostop_engine="vad",
                           smart_turn_gap_s=0.7, smart_turn_threshold=0.6)
        t0 = time.time()
        self.assertEqual(flow.make_smart_turn_gate(flow.VadAutoStop(STOP), STOP),
                         (None, None))
        self.assertLess(time.time() - t0, 0.5, "must not wait for the load")
        gate_open.set()
        self.wait_load()
        model, gate = flow.make_smart_turn_gate(flow.VadAutoStop(STOP), STOP)
        self.assertIsNotNone(model)
        self.assertEqual((gate.gap, gate.threshold), (0.7, 0.6))

    def test_load_failure_logs_once_and_is_not_retried(self):
        calls = []

        def boom():
            calls.append(1)
            raise OSError("no network")
        flow._load_smart_turn_model = boom
        flow.config.update(smart_turn=True, autostop_engine="vad")
        for _ in range(3):
            self.assertIsNone(flow.get_smart_turn())
            self.wait_load()
        self.assertEqual(len(calls), 1)
        self.assertEqual(sum("smart-turn: unavailable" in m for m in self.logs), 1)


class RealModel(unittest.TestCase):
    """Smoke test against the real onnx, only if it is already cached (the
    test never downloads)."""

    def test_shape_and_probability(self):
        try:
            from huggingface_hub import hf_hub_download
            hf_hub_download(flow.SMART_TURN_REPO, flow.SMART_TURN_FILE,
                            revision=flow.SMART_TURN_REV, local_files_only=True)
            predict = flow._load_smart_turn_model()
        except Exception as e:
            self.skipTest(f"Smart Turn not cached: {e}")
        from faster_whisper.feature_extractor import FeatureExtractor
        fe = FeatureExtractor(feature_size=80, chunk_length=8)
        feats = flow.smart_turn_features(np.zeros(16000, np.float32), fe)
        self.assertEqual(feats.shape, (1, 80, 800))
        rng = np.random.default_rng(0)
        p = predict(rng.normal(0, 0.01, 3 * 16000).astype(np.float32))
        self.assertTrue(0.0 <= p <= 1.0)


if __name__ == "__main__":
    unittest.main()
