"""Hands-free auto-stop decision tests (flow.VadAutoStop / RmsAutoStop /
make_autostop). Synthetic probabilities and levels only — no mic, no model
unless the optional real-Silero test finds one installed."""
import os, sys, unittest
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flow

F = flow.VAD_FRAME_S  # 32 ms


def feed_vad(dec, probs, t0=0.0):
    """Feed one probability per frame; return the audio time of the first
    frame that asked to stop, or None."""
    for i, p in enumerate(probs):
        t = t0 + (i + 1) * F
        if dec.feed(p, t):
            return t
    return None


def frames(seconds, p):
    return [p] * int(round(seconds / F))


class VadDecision(unittest.TestCase):
    GAP = 2.2

    def test_opening_silence_never_stops(self):
        dec = flow.VadAutoStop(self.GAP)
        self.assertIsNone(feed_vad(dec, frames(30, 0.02)))
        self.assertFalse(dec.armed)

    def test_single_blip_does_not_arm(self):
        # a click / cough scored as speech for one frame must not arm auto-stop,
        # or the rest of the opening pause would end the take
        dec = flow.VadAutoStop(self.GAP)
        probs = frames(1, 0.0) + [0.95] + frames(10, 0.0)
        self.assertIsNone(feed_vad(dec, probs))

    def test_short_pause_does_not_stop(self):
        dec = flow.VadAutoStop(self.GAP)
        probs = frames(1.5, 0.9) + frames(1.2, 0.05) + frames(1.0, 0.9)
        self.assertIsNone(feed_vad(dec, probs))
        self.assertEqual(dec.silence_s(), 0.0)

    def test_pause_just_under_gap_does_not_stop(self):
        dec = flow.VadAutoStop(self.GAP)
        probs = frames(1.0, 0.9) + frames(self.GAP - 0.1, 0.0) + frames(0.5, 0.9)
        self.assertIsNone(feed_vad(dec, probs))

    def test_long_silence_stops_after_gap(self):
        dec = flow.VadAutoStop(self.GAP)
        speech = frames(2.0, 0.9)
        t = feed_vad(dec, speech + frames(5, 0.02))
        self.assertIsNotNone(t)
        speech_end = len(speech) * F
        self.assertAlmostEqual(t - speech_end, self.GAP, delta=F + 1e-6)
        self.assertIn("engine=vad", dec.describe())

    def test_trailing_off_band_frames_keep_timer_running(self):
        # after the user stops, p hovering in the hysteresis band (0.35..0.5)
        # must neither cancel the pending stop nor keep the take open forever
        dec = flow.VadAutoStop(self.GAP, threshold=0.5)
        probs = (frames(1.0, 0.9) + frames(0.5, 0.0)
                 + [0.42, 0.0] * int(self.GAP / F))
        self.assertIsNotNone(feed_vad(dec, probs))

    def test_band_frames_do_not_start_timer(self):
        dec = flow.VadAutoStop(self.GAP, threshold=0.5)
        probs = frames(1.0, 0.9) + frames(5, 0.4)  # quiet speech, never "silence"
        self.assertIsNone(feed_vad(dec, probs))

    def test_threshold_is_configurable(self):
        dec = flow.VadAutoStop(self.GAP, threshold=0.8)
        # 0.7 is below 0.8 -> never counts as speech, never arms
        self.assertIsNone(feed_vad(dec, frames(2, 0.7) + frames(5, 0.0)))


class RmsDecision(unittest.TestCase):
    GAP = 1.5

    def run_levels(self, levels, dt=0.1):
        dec = flow.RmsAutoStop(self.GAP)
        for i, lvl in enumerate(levels):
            if dec.feed(lvl, i * dt):
                return i * dt
        return None

    def test_opening_quiet_never_stops(self):
        self.assertIsNone(self.run_levels([0.002] * 300))

    def test_speech_then_silence_stops(self):
        t = self.run_levels([0.02] * 20 + [0.001] * 40)
        self.assertIsNotNone(t)
        self.assertAlmostEqual(t, 2.0 + self.GAP, delta=0.11)

    def test_short_pause_does_not_stop(self):
        self.assertIsNone(self.run_levels([0.02] * 20 + [0.001] * 10 + [0.02] * 20))


class EngineSelection(unittest.TestCase):
    def setUp(self):
        self._orig = (flow._load_vad_model, flow._vad_model, flow._vad_failed,
                      flow.log, dict(flow.config))
        self.logs = []
        flow.log = lambda msg, *a, **k: self.logs.append(msg)
        flow._vad_model, flow._vad_failed = None, False

    def tearDown(self):
        (flow._load_vad_model, flow._vad_model, flow._vad_failed,
         flow.log, cfg) = self._orig
        flow.config.clear(); flow.config.update(cfg)

    def test_vad_load_failure_falls_back_to_rms_and_logs_once(self):
        calls = []

        def boom():
            calls.append(1)
            raise RuntimeError("onnxruntime missing")
        flow._load_vad_model = boom
        flow.config["autostop_engine"] = "vad"
        a = flow.make_autostop(2.2)
        b = flow.make_autostop(2.2)
        self.assertIsInstance(a, flow.RmsAutoStop)
        self.assertIsInstance(b, flow.RmsAutoStop)
        self.assertEqual(len(calls), 1, "a failed load must not be retried per take")
        self.assertEqual(sum("VAD unavailable" in m for m in self.logs), 1)

    def test_vad_engine_when_model_loads(self):
        flow._load_vad_model = lambda: (lambda audio: np.zeros((len(audio) // 512, 1)))
        flow.config["autostop_engine"] = "vad"
        flow.config["vad_speech_threshold"] = 0.6
        dec = flow.make_autostop(2.2)
        self.assertIsInstance(dec, flow.VadAutoStop)
        self.assertEqual(dec.threshold, 0.6)

    def test_rms_engine_never_loads_vad(self):
        def must_not_load():
            raise AssertionError("VAD loaded although engine is rms")
        flow._load_vad_model = must_not_load
        flow.config["autostop_engine"] = "rms"
        self.assertIsInstance(flow.make_autostop(2.2), flow.RmsAutoStop)

    def test_default_engine_is_vad(self):
        self.assertEqual(flow.DEFAULTS["autostop_engine"], "vad")


class RecordedTail(unittest.TestCase):
    def setUp(self):
        self._chunks = flow.chunks[:]

    def tearDown(self):
        flow.chunks[:] = self._chunks

    def test_tail_returns_latest_samples_and_total(self):
        flow.chunks[:] = [np.full((512, 1), i, dtype=np.float32) for i in range(50)]
        audio, total = flow._recorded_tail(32 * 512)
        self.assertEqual(total, 50 * 512)
        self.assertEqual(audio.shape, (32 * 512,))
        self.assertEqual(audio[0], 18.0)
        self.assertEqual(audio[-1], 49.0)

    def test_tail_short_take(self):
        flow.chunks[:] = [np.zeros((512, 1), dtype=np.float32)] * 3
        audio, total = flow._recorded_tail(32 * 512)
        self.assertEqual((len(audio), total), (3 * 512, 3 * 512))

    def test_tail_empty(self):
        flow.chunks[:] = []
        audio, total = flow._recorded_tail(32 * 512)
        self.assertEqual((len(audio), total), (0, 0))


def energy_vad(audio):
    """Stub Silero: a frame is 'speech' (0.9) if it carries signal, else 0.0."""
    fr = audio.reshape(-1, 512)
    return np.where(np.abs(fr).max(1) > 0.05, 0.9, 0.0).reshape(-1, 1)


class VadPollStream(unittest.TestCase):
    """Drive vad_poll the way silence_watch does: blocks arrive, a poll runs
    every ~3 blocks (~100 ms)."""

    def setUp(self):
        self._chunks = flow.chunks[:]
        flow.chunks[:] = []

    def tearDown(self):
        flow.chunks[:] = self._chunks

    def stream(self, blocks, poll_every=3, gap=2.2):
        dec, fed = flow.VadAutoStop(gap), 0
        for i, b in enumerate(blocks, 1):
            flow.chunks.append(np.full((512, 1), b, dtype=np.float32))
            if i % poll_every == 0:
                stop, fed = flow.vad_poll(energy_vad, dec, fed)
                if stop:
                    return i * F, dec
        return None, dec

    def blocks(self, seconds, v):
        return [v] * int(round(seconds / F))

    def test_stream_stops_after_gap(self):
        speech = self.blocks(2, 0.2)
        t, dec = self.stream(self.blocks(1, 0.0) + speech + self.blocks(4, 0.0))
        self.assertIsNotNone(t)
        stop_after = t - (len(self.blocks(1, 0.0)) + len(speech)) * F
        self.assertGreaterEqual(stop_after, 2.2 - 1e-6)
        self.assertLess(stop_after, 2.2 + 4 * F)  # within one poll

    def test_stream_opening_silence_never_stops(self):
        t, _ = self.stream(self.blocks(20, 0.0))
        self.assertIsNone(t)

    def test_stream_pause_does_not_stop(self):
        t, _ = self.stream(self.blocks(1, 0.2) + self.blocks(1.5, 0.0)
                           + self.blocks(1, 0.2) + self.blocks(1.0, 0.0))
        self.assertIsNone(t)

    def test_starved_poll_skips_old_frames_but_keeps_clock(self):
        # one poll after 3 s of audio: only the last ~1 s window is scored, and
        # the frame times still come from the take's audio clock
        for b in self.blocks(3, 0.2):
            flow.chunks.append(np.full((512, 1), b, dtype=np.float32))
        dec = flow.VadAutoStop(2.2)
        stop, fed = flow.vad_poll(energy_vad, dec, 0)
        self.assertFalse(stop)
        self.assertEqual(fed, len(flow.chunks))
        self.assertAlmostEqual(dec.t, len(flow.chunks) * F)
        self.assertAlmostEqual(dec.speech_s, flow.VAD_WINDOW_FRAMES * F)


class RealSilero(unittest.TestCase):
    """Smoke test against the shipped model, skipped if it can't load. Proves
    the API shape we rely on (one probability per 512-sample frame) and that
    near-silence at this mic's noise floor never arms auto-stop."""

    def test_noise_floor_scores_as_non_speech(self):
        try:
            m = flow._load_vad_model()
        except Exception as e:
            self.skipTest(f"Silero unavailable: {e}")
        rng = np.random.default_rng(0)
        noise = rng.normal(0, 0.002, 32 * 512).astype(np.float32)
        probs = np.asarray(m(noise)).reshape(-1)
        self.assertEqual(len(probs), 32)
        dec = flow.VadAutoStop(2.2)
        self.assertIsNone(feed_vad(dec, [float(p) for p in probs] * 5))
        self.assertFalse(dec.armed)


if __name__ == "__main__":
    unittest.main()
