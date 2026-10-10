"""latency.Trace arithmetic and formatting, on a fake clock. Pure: no flow
import, no audio, no network."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import latency


class Clock:
    def __init__(self, t=100.0): self.t = t
    def __call__(self): return self.t
    def tick(self, dt): self.t += dt


def full_trace(silence_ago=0.80, label="groq:m"):
    c = Clock()
    tr = latency.Trace(clock=c)
    tr.stopped(silence_ago)
    c.tick(0.02); tr.mark("stt_start")
    c.tick(0.41); tr.mark("stt_end")
    c.tick(0.01); tr.mark("polish_start")
    c.tick(0.12); tr.mark("polish_end")
    c.tick(0.07); tr.mark("paste")
    tr.polish_label = label
    return tr


class TraceTests(unittest.TestCase):
    def test_full_line(self):
        line = full_trace().summary()
        self.assertEqual(
            line, "latency: speech_end->paste 1.43s = wait 0.80 + queue 0.02 + "
                  "stt 0.41 + text 0.01 + polish 0.12 (groq:m) + paste 0.07")

    def test_stages_add_up_to_total(self):
        st = full_trace().stages()
        self.assertEqual([n for n, _ in st],
                         ["wait", "queue", "stt", "text", "polish", "paste"])
        self.assertAlmostEqual(sum(s for _, s in st), 1.43, places=6)

    def test_manual_stop_has_zero_wait(self):
        for ago in (None, 0, -1):
            st = dict(full_trace(silence_ago=ago).stages())
            self.assertEqual(st["wait"], 0.0)

    def test_missing_polish_marks_inherit(self):
        # LLM off and the polish marks never set: polish 0.00, nothing lost —
        # the time lands in the next stage that has a mark
        c = Clock(); tr = latency.Trace(clock=c)
        tr.stopped(0.5)
        c.tick(0.1); tr.mark("stt_start")
        c.tick(0.3); tr.mark("stt_end")
        c.tick(0.2); tr.mark("paste")
        st = dict(tr.stages())
        self.assertEqual(st["polish"], 0.0)
        self.assertEqual(st["text"], 0.0)
        self.assertAlmostEqual(st["paste"], 0.2)
        self.assertIn("polish 0.00 (off)", tr.summary())
        self.assertIn("speech_end->paste 1.10s", tr.summary())

    def test_no_stop_mark_starts_at_first_mark(self):
        # a test or any caller that passed no trace: no wait/queue to report
        c = Clock(); tr = latency.Trace(clock=c)
        tr.mark("stt_start"); c.tick(0.4); tr.mark("stt_end"); c.tick(0.1)
        tr.mark("paste")
        st = dict(tr.stages())
        self.assertEqual((st["wait"], st["queue"]), (0.0, 0.0))
        self.assertAlmostEqual(sum(st.values()), 0.5)

    def test_not_pasted_gives_none(self):
        c = Clock(); tr = latency.Trace(clock=c)
        tr.stopped(1.0); tr.mark("stt_start"); tr.mark("stt_end")
        self.assertIsNone(tr.summary())
        self.assertIsNone(latency.Trace().summary())

    def test_out_of_order_mark_never_negative(self):
        c = Clock(); tr = latency.Trace(clock=c)
        tr.stopped(0)
        c.tick(0.5); tr.mark("stt_end")
        tr.mark("stt_start", at=c.t + 0.2)  # later than stt_end: clock oddity
        c.tick(0.3); tr.mark("paste")
        st = tr.stages()
        self.assertTrue(all(s >= 0 for _, s in st))
        self.assertAlmostEqual(sum(s for _, s in st), 0.8)

    def test_never_raises(self):
        def boom(): raise RuntimeError("clock")
        tr = latency.Trace(clock=boom)
        tr.stopped(1.0); tr.mark("stt_start"); tr.mark("paste", at="junk")
        self.assertIsNone(tr.summary())
        tr2 = latency.Trace(); tr2.t = None  # corrupted state
        self.assertIsNone(tr2.summary())

    def test_line_carries_no_text(self):
        # only fixed words, numbers and the label — a dictated phrase has no
        # way into the line
        line = full_trace(label="skipped").summary()
        self.assertRegex(line, r"^latency: speech_end->paste [\d.]+s = "
                               r"(\w+ [\d.]+( \([\w:./-]+\))?( \+ )?)+$")


class SilenceAgoTests(unittest.TestCase):
    """The deciders' silence_ago feeds the wait stage; flow is imported only
    here, the same way test_autostop does."""
    @classmethod
    def setUpClass(cls):
        import flow
        cls.flow = flow

    def test_vad_audio_clock(self):
        f = self.flow
        dec = f.VadAutoStop(1.0)
        t = 0.0
        for _ in range(20):          # 0.64 s of speech arms it
            t += f.VAD_FRAME_S; dec.feed(0.9, t)
        speech_end = t
        self.assertIsNone(dec.silence_ago(t, 0))
        stopped = False
        while not stopped:
            t += f.VAD_FRAME_S; stopped = dec.feed(0.0, t)
        # 0.3 s more audio recorded after the stopping frame (poll lag)
        self.assertAlmostEqual(dec.silence_ago(t + 0.3, 0), t + 0.3 - speech_end,
                               places=6)

    def test_rms_wall_clock(self):
        dec = self.flow.RmsAutoStop(1.0)
        self.assertIsNone(dec.silence_ago(5.0, 10.0))
        dec.feed(0.05, 10.0)          # speech
        dec.feed(0.0001, 10.5)        # silence starts
        self.assertAlmostEqual(dec.silence_ago(0, 12.0), 1.5)


if __name__ == "__main__":
    unittest.main()
