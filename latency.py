"""Per-take latency trace: where the time between "the user stopped talking"
and "the text is in their window" actually goes.

Why a module of its own: the numbers are only worth anything if the arithmetic
is right, and flow.py cannot be unit-tested without booting the audio stack.
Everything here is stdlib, pure and side-effect free (test_latency.py).

One trace per take. Stages are CONTIGUOUS — each runs from the previous mark to
its own — so they always add up to the headline total and nothing hides in a
gap between two measured blocks:

  speech_end -> stop        wait    hands-free silence the auto-stop sat through
                                    (0 for push-to-talk / a manual tap: release
                                    IS the end of speech as far as we can know)
  stop       -> stt_start   queue   thread start, model lock, level/boost pass
  stt_start  -> stt_end     stt     recognition, incl. any ru-retry re-decode
  stt_end    -> polish_start text   filters, numbers, punctuation, dictionary
  polish_*                  polish  the LLM call, or ~0 when skipped/off
  polish_end -> paste       paste   replacements, history row, clipboard paste

Never raises: a broken trace must not cost the user their dictation, so every
public method swallows its own errors and summary() returns None instead.
Carries no text — only timestamps and a short label like "groq:<model>"."""
import time

# order matters: it is both the stage order and the fallback chain for a mark
# that was never set (a take that skipped polish has no polish marks of its own)
MARKS = ("speech_end", "stop", "stt_start", "stt_end",
         "polish_start", "polish_end", "paste")
# (stage name, mark it ends at); each stage starts at the previous stage's end
STAGES = (("wait", "stop"), ("queue", "stt_start"), ("stt", "stt_end"),
          ("text", "polish_start"), ("polish", "polish_end"), ("paste", "paste"))


class Trace:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self.t: dict[str, float] = {}
        self.polish_label = ""

    def mark(self, name: str, at: float | None = None) -> None:
        try:
            self.t[name] = self._clock() if at is None else float(at)
        except Exception:
            pass

    def stopped(self, silence_ago: float | None) -> None:
        """Record the stop decision. `silence_ago` = how long the user had
        already been silent when the auto-stop fired (None/0 = not known, the
        stop moment is taken as the end of speech)."""
        try:
            now = self._clock()
            ago = max(0.0, float(silence_ago or 0.0))
            self.t["speech_end"] = now - ago
            self.t["stop"] = now
        except Exception:
            pass

    def stages(self) -> list[tuple[str, float]] | None:
        """[(stage, seconds)] in order, or None if the trace is unusable.

        A missing mark inherits the previous one (its stage is then 0.00), so a
        take with the LLM off still reports polish 0.00 rather than vanishing.
        Needs at least a start and the final paste mark."""
        try:
            t = self.t
            if "paste" not in t:
                return None
            first = next((m for m in MARKS if m in t), None)
            if first is None:
                return None
            prev = t[first]
            out = []
            for name, end in STAGES:
                cur = t.get(end, prev)
                # clamp: a mark recorded out of order (clock oddity, a retried
                # stage) must not produce a negative stage and a wrong total
                out.append((name, max(0.0, cur - prev)))
                prev = max(prev, cur)
            return out
        except Exception:
            return None

    def summary(self) -> str | None:
        """The one log line per take, e.g.
        latency: speech_end->paste 1.42s = wait 0.80 + queue 0.02 + stt 0.41
        + text 0.00 + polish 0.12 (groq:model) + paste 0.07"""
        st = self.stages()
        if st is None:
            return None
        try:
            total = sum(s for _, s in st)
            parts = []
            for name, secs in st:
                p = f"{name} {secs:.2f}"
                if name == "polish":
                    p += f" ({self.polish_label or 'off'})"
                parts.append(p)
            return f"latency: speech_end->paste {total:.2f}s = " + " + ".join(parts)
        except Exception:
            return None
