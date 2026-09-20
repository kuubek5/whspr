# ui.py — floating status overlay (KuubWave "Soft Studio" dark).
#
# THREE shapes, one public API. The overlay renders as one of "pill" (the
# original dot + wave + timer capsule), "orb" (a small ring token whose ring
# geometry carries the state) or "dock" (a wider, DISPLAY-ONLY bar: dot + wave +
# timer + state label). The shape is chosen in Settings → Панель and read once
# from config["overlay_style"] at construction; flow.apply_overlay_config()
# rebuilds the overlay when it changes. Both renderers below learn all three.
#
# The overlay window is click-through (WS_EX_TRANSPARENT) and never activates
# (WS_EX_NOACTIVATE), so it can NEVER receive a click or take focus — that is
# what keeps dictation working. The dock is therefore an informative wide bar,
# NOT a control surface: it carries no buttons, because a button in this window
# would be permanently dead. State is always carried by shape/geometry (and the
# one coral→aqua colour event on success), never by a control the user "uses".
#
# Two renderers, one public API. `StatusOverlay` is a thin picker:
#
#   1. PRIMARY — `_LayeredOverlay`: a Win32 layered window driven by
#      UpdateLayeredWindow and fed a Pillow-rendered premultiplied-RGBA bitmap.
#      This gives TRUE per-pixel alpha: perfectly smooth rounded corners, a real
#      soft drop shadow, and anti-aliased interior elements (dot, arc, check,
#      strike, wave). The old header explained the pill lived in Tk because
#      WebView2 can't do rounded transparency — a ctypes layered window CAN, so
#      it supersedes the colour-key hack. The window is WS_EX_NOACTIVATE +
#      WS_EX_TRANSPARENT (click-through) and is only ever shown with
#      SW_SHOWNOACTIVATE — it NEVER takes keyboard focus from the app being
#      dictated into, which is the whole point of the pill.
#
#   2. FALLBACK — `_TkOverlay`: the original Tk-canvas renderer with a magenta
#      color-key (-transparentcolor). Kept fully intact and used verbatim if the
#      layered path can't initialise (non-Windows, ctypes/GDI error, no Pillow).
#      The app must never end up with a broken or invisible pill.
#
# Thread-safe: public methods schedule work onto a Tk main loop via after(); the
# layered renderer keeps a hidden Tk root purely as that timer/after source, so
# callers see exactly the same marshalling contract as before. Positioned with
# winfo_screen* so it lands where the user asked regardless of DPI scaling.
#
# ONE colour identity: coral is the pill's energy in every live state (idle /
# recording / processing). Aqua appears in exactly one place — the moment the
# text is handed over — because that is the only state the user must recognise
# without reading. Every other state is carried by the DOT'S GEOMETRY (hollow
# ring / solid fill / turning arc / check / struck-through), so no state depends
# on hue alone. It floats over arbitrary windows, so the surface stays dark.
#
# Drawing: the layered renderer re-renders a small (~220x64) Pillow image only
# when something actually changes — every recording frame (the wave scrolls) and
# every processing frame (the arc turns), capped at ~13 fps, but NOT for the
# static loading/flash states. The Tk fallback creates each canvas item ONCE in
# _build() and then only moves/resizes/hides it. Neither must compete with the
# mic capture and the GPU transcription for CPU.

import ctypes
import logging
import math
import os
import time
import tkinter as tk
import tkinter.font as tkfont


def _log(msg: str) -> None:
    """Best-effort line to the shared 'kuubwave' logger (configured by flow).

    Imported lazily via logging.getLogger so ui.py never imports flow (which
    imports ui) — no circular import, and if flow hasn't set the handler up
    (e.g. the standalone overlay demo) this simply no-ops."""
    try:
        logging.getLogger("kuubwave").info("%s", msg)
    except Exception:
        pass

TRANSPARENT = "#ff00ff"  # colorkey — never appears in the design

# Soft Studio dark tokens (brand: KuubWave)
COLORS = {
    "surface": "#221C29",   # the pill body
    "plum": "#171319",      # the backdrop the surface sits on
    "ring": "#3A3540",      # hairline edge, so the pill reads on dark windows too
    "text": "#F4EEF2",
    "muted": "#B0A6B4",     # secondary text / the quiet, colourless states
    "coral": "#FF6B5E",     # the energy: idle, recording, processing
    "aqua": "#33CBBB",      # the single second colour — success only
    "check": "#12100F",     # the tick drawn inside the aqua dot
}

# Pill body opacity, 0 (invisible) .. 255 (solid). The default when config has no
# overlay_opacity; the settings slider overrides it per user. Only the layered
# renderer can honour it — true per-pixel alpha over the desktop. The Tk
# colour-key fallback is binary, so it always draws the body solid. Lower = more
# see-through, but the text/dot contrast drops on light windows.
PILL_ALPHA = 210
# Floor for the user-chosen opacity (percent): below this the text stops reading.
OPACITY_MIN = 40

# Per-bar gain envelope: the wave is centre-weighted, so the level reads as one
# shape instead of 13 independent bars (mirrors .p-bars nth-child in the mock).
BAR_GAIN = (.46, .60, .73, .85, .93, .98, 1.0, .98, .93, .85, .73, .60, .46)
N_BARS = len(BAR_GAIN)

# The three overlay shapes the pill can take. "pill" is the original capsule;
# "orb" is a small ring token; "dock" is a wider display-only bar. Kept as a
# tuple so both renderers, and StatusOverlay, validate a style the same way.
STYLES = ("pill", "orb", "dock")


def _valid_style(name) -> str:
    return name if name in STYLES else "pill"


def _wave_gain(n: int) -> tuple:
    """A centre-weighted gain window of length n (edges ~.46, centre 1.0).

    The pill hand-tunes 13 values (BAR_GAIN); the dock's wider lane holds more
    bars, so its envelope is generated with the same shape — one soft hump so
    the level reads as a single wave, not n independent sticks."""
    if n == N_BARS:
        return BAR_GAIN
    if n <= 1:
        return (1.0,)
    return tuple(0.46 + 0.54 * math.sin(math.pi * (i + 0.5) / n)
                 for i in range(n))

FLASH_MAX_CHARS = 30  # result preview length (unchanged from the old pill)
FRAME_MS = 76        # ~13 fps — plenty for a level meter, cheap for the CPU
PROC_MS = 100        # the processing arc turns slower still
SCALE_MIN, SCALE_MAX = 80, 140

# 9 presets expressed in the same percentage model as the free coordinate:
# 0 = flush to the start edge, 50 = centred, 100 = flush to the end edge.
_VY = {"top": 0, "middle": 50, "center": 50, "centre": 50, "bottom": 100}
_HX = {"left": 0, "center": 50, "centre": 50, "middle": 50, "right": 100}


def _mix(fg: str, bg: str, a: float) -> str:
    """Flatten an alpha onto a solid colour — Tk canvas has no opacity."""
    f = [int(fg[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(round(f[i] * a + b[i] * (1 - a)))
                                   for i in range(3))


def parse_position(pos) -> tuple[float, float]:
    """Config placement -> (x%, y%) of the FREE space on each axis.

    Accepts a preset name ("bottom-center", "top left", …) or a free
    coordinate {"x": 0..100, "y": 0..100}; anything unparseable falls back to
    today's bottom-centre."""
    if isinstance(pos, dict):
        try:
            x = min(100.0, max(0.0, float(pos.get("x", 50))))
            y = min(100.0, max(0.0, float(pos.get("y", 100))))
            return x, y
        except (TypeError, ValueError):
            return 50.0, 100.0
    if isinstance(pos, str):
        parts = pos.lower().replace("_", "-").replace(" ", "-").split("-")
        v = h = None
        for p in parts:
            if v is None and p in _VY:
                v = _VY[p]
            elif h is None and p in _HX:
                h = _HX[p]
        if v is not None:
            return (50.0 if h is None else float(h)), float(v)
    return 50.0, 100.0


class _TkOverlay:
    """FALLBACK renderer — the original Tk-canvas pill with a colour-key.

    Small always-on-top pill that floats over whatever is being typed into.
    Hidden while idle; appears for loading / recording / processing and flashes
    the result before hiding again. Never takes focus: overrideredirect +
    -topmost, and nothing here ever calls focus_set or activates the window.

    Kept intact as the safety net for `StatusOverlay` — see the module header."""

    def __init__(self, root: tk.Tk, config: dict | None = None):
        self.root = root
        cfg = config or {}
        try:
            scale = float(cfg.get("overlay_scale", 100))
        except (TypeError, ValueError):
            scale = 100.0
        self.scale = min(SCALE_MAX, max(SCALE_MIN, scale)) / 100.0
        self.pos_x, self.pos_y = parse_position(cfg.get("overlay_position",
                                                        "bottom-center"))
        try:
            self.margin = max(0, int(cfg.get("overlay_margin", 60)))
        except (TypeError, ValueError):
            self.margin = 60

        self.style = _valid_style(cfg.get("overlay_style", "pill"))
        s = self.scale
        r = lambda v: int(round(v * s))  # noqa: E731 — one-liner scale helper
        self.H = r(40)
        self.R = self.H // 2
        self.PAD = r(14)
        self.GAP = r(9)
        self.GLYPH = r(16)          # the dot's own 16x16 box in the mock
        self.DOT_R = 5 * s          # ring radius, kept fractional for the pulse
        self.STROKE = max(1, r(2))
        self.BAR_W = max(1, r(3))
        self.BAR_GAP = max(1, r(3))
        self.LANE_H = r(18)
        self.LANE_W = N_BARS * self.BAR_W + (N_BARS - 1) * self.BAR_GAP
        # per-shape geometry. self.H is the overlay's outer height (the pill and
        # dock are stadiums, the orb is a circle so its height IS its diameter);
        # WAVE_N / WAVE_GAIN size the level meter for whichever shape shows one.
        self.WAVE_N, self.WAVE_GAIN = N_BARS, BAR_GAIN
        if self.style == "orb":
            self.H = r(60)                       # the ring token's diameter
            self.R = self.H // 2
            self.ORB_STROKE = max(2, r(3))
        elif self.style == "dock":
            self.H = r(52)
            self.R = self.H // 2
            self.DOCK_DOT = r(10)                # the state dot on the left
            self.DOCK_LANE_W = r(150)            # the wide wave / label lane
            self.LANE_H = r(26)                  # a taller lane than the pill's
            self.WAVE_N = max(8, self.DOCK_LANE_W // (self.BAR_W + self.BAR_GAP))
            self.WAVE_GAIN = _wave_gain(self.WAVE_N)
        self._levels = [0.0] * self.WAVE_N

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", TRANSPARENT)

        # Font sizes are negative = pixels, so the pill keeps the mock's
        # proportions instead of drifting with the Tk point/DPI conversion.
        fams = {f.lower() for f in tkfont.families(root)}
        if "segoe ui semibold" in fams:
            self.font = tkfont.Font(family="Segoe UI Semibold", size=-r(12))
        else:
            self.font = tkfont.Font(family="Segoe UI", size=-r(12), weight="bold")
        # the timer is tabular so the pill doesn't twitch on every digit; the
        # family is a fallback chain because none of these is guaranteed to
        # exist on the machine (see self.timer_family for what actually won).
        self.timer_family = next(
            (f for f in ("JetBrains Mono", "Cascadia Mono", "Cascadia Code",
                         "Consolas", "Courier New") if f.lower() in fams),
            "TkFixedFont")
        self.mono = tkfont.Font(family=self.timer_family, size=-r(12),
                                weight="bold")

        self.canvas = tk.Canvas(self.win, height=self.H, width=self.H * 4,
                                bg=TRANSPARENT, highlightthickness=0)
        self.canvas.pack()

        self._t0 = 0.0
        self._frozen = "0:00"
        self._timer_job = None      # the 500ms/76ms state loop
        self._anim_job = None       # the wave / arc frame loop
        self._last_geom = None
        # self._levels already sized to WAVE_N above
        self._level = None          # set by level(); None -> synthetic motion
        self._phase = 0.0
        self._arc = 0.0
        self._state = None
        self.frames = 0             # animation frames drawn (used by the demo)
        self._build()
        self.win.withdraw()

    # ---- public, thread-safe ----
    def loading(self):
        self.root.after(0, self._apply, "loading")

    def recording(self):
        self._t0 = time.time()
        self.root.after(0, self._apply, "rec")

    def processing(self):
        self.root.after(0, self._apply, "proc")

    def flash(self, text: str, ok: bool = True):
        self.root.after(0, self._flash, text, ok)

    def hide(self):
        self.root.after(0, self._hide)

    def level(self, value: float):
        """Feed a 0..1 mic level to the wave. flow.audio_callback pushes the live
        stream RMS here (throttled) while recording, so the wave reflects the real
        mic; between pushes / before the first one it falls back to gentle
        synthetic motion."""
        try:
            self._level = min(1.0, max(0.0, float(value)))
        except (TypeError, ValueError):
            pass

    # ---- one-time item construction (tk thread only) ----
    def _build(self):
        if self.style == "orb":
            self._build_orb()
        elif self.style == "dock":
            self._build_dock()
        else:
            self._build_pill()

    def _build_pill(self):
        c = self.canvas
        # two layers: a hairline ring, and the surface one pixel inside it, so
        # the pill keeps an edge over light AND dark windows.
        self._bg = [c.create_oval(0, 0, 0, 0, fill=COLORS["ring"], outline=""),
                    c.create_oval(0, 0, 0, 0, fill=COLORS["ring"], outline=""),
                    c.create_rectangle(0, 0, 0, 0, fill=COLORS["ring"],
                                       outline="")]
        self._fg = [c.create_oval(0, 0, 0, 0, fill=COLORS["surface"], outline=""),
                    c.create_oval(0, 0, 0, 0, fill=COLORS["surface"], outline=""),
                    c.create_rectangle(0, 0, 0, 0, fill=COLORS["surface"],
                                       outline="")]
        self._ring = c.create_oval(0, 0, 0, 0, outline=COLORS["coral"],
                                   width=self.STROKE, fill="")
        self._arc_id = c.create_arc(0, 0, 0, 0, style="arc", start=0, extent=96,
                                    outline=COLORS["coral"], width=self.STROKE,
                                    state="hidden")
        self._check = c.create_line(0, 0, 0, 0, 0, 0, fill=COLORS["check"],
                                    width=self.STROKE, capstyle="round",
                                    joinstyle="round", state="hidden")
        self._strike = c.create_line(0, 0, 0, 0, fill=COLORS["muted"],
                                     width=self.STROKE, capstyle="round",
                                     state="hidden")
        self._bars = [c.create_rectangle(0, 0, 0, 0, fill=COLORS["coral"],
                                         outline="", state="hidden")
                      for _ in range(N_BARS)]
        self._label = c.create_text(0, 0, anchor="w", fill=COLORS["muted"],
                                    font=self.font, text="", state="hidden")
        self._timer = c.create_text(0, 0, anchor="e", fill=COLORS["text"],
                                    font=self.mono, text="0:00",
                                    state="hidden")

    def _build_dock(self):
        # DOCK: a wider stadium bar, reusing the pill's two-layer surface. It is
        # DISPLAY-ONLY — a state dot, a wide wave/label lane and a timer. It has
        # NO buttons: the window is WS_EX_TRANSPARENT (click-through) and
        # WS_EX_NOACTIVATE, so a control here could never be clicked. State is
        # carried by the dot's colour + the label, never by an affordance.
        c = self.canvas
        self._bg = [c.create_oval(0, 0, 0, 0, fill=COLORS["ring"], outline=""),
                    c.create_oval(0, 0, 0, 0, fill=COLORS["ring"], outline=""),
                    c.create_rectangle(0, 0, 0, 0, fill=COLORS["ring"],
                                       outline="")]
        self._fg = [c.create_oval(0, 0, 0, 0, fill=COLORS["surface"], outline=""),
                    c.create_oval(0, 0, 0, 0, fill=COLORS["surface"], outline=""),
                    c.create_rectangle(0, 0, 0, 0, fill=COLORS["surface"],
                                       outline="")]
        self._dot = c.create_oval(0, 0, 0, 0, fill=COLORS["coral"], outline="")
        self._bars = [c.create_rectangle(0, 0, 0, 0, fill=COLORS["coral"],
                                         outline="", state="hidden")
                      for _ in range(self.WAVE_N)]
        self._label = c.create_text(0, 0, anchor="w", fill=COLORS["muted"],
                                    font=self.font, text="", state="hidden")
        self._timer = c.create_text(0, 0, anchor="e", fill=COLORS["text"],
                                    font=self.mono, text="0:00",
                                    state="hidden")

    def _build_orb(self):
        # ORB: a round token where the RING is the whole UI. A faint full track,
        # a coral state ring / arc laid over it, plus a centred check / strike /
        # timer. One coral identity, aqua only on success — same as the pill.
        c = self.canvas
        self._obg = c.create_oval(0, 0, 0, 0, fill=COLORS["ring"], outline="")
        self._ofg = c.create_oval(0, 0, 0, 0, fill=COLORS["surface"], outline="")
        self._track = c.create_oval(
            0, 0, 0, 0, fill="", width=self.ORB_STROKE,
            outline=_mix(COLORS["ring"], COLORS["surface"], 0.9))
        self._oring = c.create_oval(0, 0, 0, 0, outline=COLORS["coral"],
                                    width=self.ORB_STROKE, fill="",
                                    state="hidden")
        self._arc_id = c.create_arc(0, 0, 0, 0, style="arc", start=90, extent=0,
                                    outline=COLORS["coral"], width=self.ORB_STROKE,
                                    state="hidden")
        self._check = c.create_line(0, 0, 0, 0, 0, 0, fill=COLORS["aqua"],
                                    width=max(2, self.STROKE), capstyle="round",
                                    joinstyle="round", state="hidden")
        self._strike = c.create_line(0, 0, 0, 0, fill=COLORS["muted"],
                                     width=max(2, self.STROKE), capstyle="round",
                                     state="hidden")
        self._timer = c.create_text(0, 0, anchor="center", fill=COLORS["text"],
                                    font=self.mono, text="0:00", state="hidden")

    # ---- geometry ----
    def _timer_w(self, text: str) -> int:
        # reserve at least "0:00" so a growing timer doesn't resize the window
        return max(self.mono.measure(text), self.mono.measure("0:00"))

    def _fit(self, text: str, maxw: float, font) -> str:
        """Trim text to fit maxw px, adding an ellipsis (dock lane is fixed)."""
        if not text or font.measure(text) <= maxw:
            return text
        while text and font.measure(text + "…") > maxw:
            text = text[:-1]
        return (text + "…") if text else "…"

    def _place(self, w: int):
        """Size the overlay to its content and put it where config asked.

        x/y are percentages of the FREE space left on each axis once the overlay
        and its margin are taken out — the same model as the settings mock, so
        0/50/100 on both axes are exactly the nine presets."""
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        free_w, free_h = sw - w - 2 * self.margin, sh - self.H - 2 * self.margin
        px = self.margin + int(round(max(0, free_w) * self.pos_x / 100.0))
        py = self.margin + int(round(max(0, free_h) * self.pos_y / 100.0))
        px = max(0, min(px, sw - w))
        py = max(0, min(py, sh - self.H))
        geom = f"{w}x{self.H}+{px}+{py}"
        # only touch the native window when its size/position actually changes
        # (recording ticks ~13x/s but the width almost never moves)
        if geom != self._last_geom:
            self.win.geometry(geom)
            self.canvas.config(width=w)
            self._last_geom = geom
            self._draw_surface(w)

    def _draw_surface(self, w: int):
        if self.style == "orb":
            c = self.canvas
            c.coords(self._obg, 0, 0, w, self.H)
            c.coords(self._ofg, 1, 1, w - 1, self.H - 1)
        else:
            self._draw_pill(w)          # pill and dock share the stadium body

    def _draw_pill(self, w: int):
        c, H, R = self.canvas, self.H, self.R
        c.coords(self._bg[0], 0, 0, 2 * R, H)
        c.coords(self._bg[1], w - 2 * R, 0, w, H)
        c.coords(self._bg[2], R, 0, w - R, H)
        i = 1  # hairline
        c.coords(self._fg[0], i, i, 2 * R - i, H - i)
        c.coords(self._fg[1], w - 2 * R + i, i, w - i, H - i)
        c.coords(self._fg[2], R, i, w - R, H - i)

    # ---- state machine (tk thread only) ----
    def _apply(self, name: str, text: str = "", ok: bool = True):
        if name == "rec":
            self._frozen = "0:00"
        elif name == "proc" and self._state == "rec":
            # the timer freezes at the take's length instead of resetting, so
            # "Розпізнаю…" still says how much audio is being worked on
            self._frozen = self._elapsed()
        self._state = name
        self._cancel_timer()
        self._cancel_anim()
        self._paint(text, ok)
        self.win.deiconify()
        if name == "rec":
            self._timer_job = self.root.after(FRAME_MS, self._tick)
        elif name == "proc" and self.style in ("pill", "orb"):
            # the dock's processing state is static (frozen timer + label), so
            # only the pill/orb turning arc needs the spin loop
            self._anim_job = self.root.after(PROC_MS, self._spin)

    def _paint(self, text: str = "", ok: bool = True):
        if self.style == "orb":
            self._paint_orb(text, ok)
        elif self.style == "dock":
            self._paint_dock(text, ok)
        else:
            self._paint_pill(text, ok)

    def _paint_dock(self, text: str = "", ok: bool = True):
        """DISPLAY-ONLY wide bar: dot + wave/label lane + timer. No buttons."""
        c, st = self.canvas, self._state
        timer_txt = self._elapsed() if st == "rec" else self._frozen
        # constant width — the dock stays a stable wide bar rather than growing
        # like the pill, so it always reads as a dock
        w = (2 * self.PAD + self.DOCK_DOT + self.GAP + self.DOCK_LANE_W
             + self.GAP + self._timer_w("0:00"))
        self._place(w)
        cy = self.H / 2
        x = self.PAD
        # ---- the state dot (carries the colour identity) ----
        dot_fill = COLORS["coral"]
        if st == "loading":
            dot_fill = _mix(COLORS["coral"], COLORS["surface"], 0.55)
        elif st == "proc":
            dot_fill = _mix(COLORS["coral"], COLORS["surface"], 0.40)
        elif st == "flash":
            dot_fill = COLORS["aqua"] if ok else COLORS["muted"]
        dr = self.DOCK_DOT / 2
        c.coords(self._dot, x, cy - dr, x + self.DOCK_DOT, cy + dr)
        c.itemconfigure(self._dot, fill=dot_fill)
        x += self.DOCK_DOT + self.GAP
        # ---- the lane: wave while recording, a status/result label otherwise --
        lane_x = x
        if st == "rec":
            self._place_bars(lane_x, cy)
            c.itemconfigure(self._label, state="hidden")
        else:
            for b in self._bars:
                c.itemconfigure(b, state="hidden")
            label = {"loading": "Завантаження моделі…", "proc": "Розпізнаю…",
                     "flash": text}.get(st, "")
            label = self._fit(label, self.DOCK_LANE_W, self.font)
            colour = COLORS["muted"]
            if st == "flash":
                colour = COLORS["text"] if ok else COLORS["muted"]
            c.itemconfigure(self._label, text=label, fill=colour,
                            state="normal" if label else "hidden")
            c.coords(self._label, lane_x, cy)
        x = lane_x + self.DOCK_LANE_W + self.GAP
        # ---- the timer (recording / processing) ----
        if st in ("rec", "proc"):
            c.itemconfigure(self._timer, text=timer_txt, state="normal",
                            fill=COLORS["text"] if st == "rec" else COLORS["muted"])
            c.coords(self._timer, x + self._timer_w("0:00"), cy)
        else:
            c.itemconfigure(self._timer, state="hidden")

    def _paint_orb(self, text: str = "", ok: bool = True):
        """The ring token: geometry carries the state, timer sits inside."""
        c, st = self.canvas, self._state
        self._place(self.H)                     # square window
        cx = cy = self.H / 2.0
        inset = self.ORB_STROKE + max(2, self.STROKE)
        rr = self.H / 2.0 - inset
        box = (cx - rr, cy - rr, cx + rr, cy + rr)
        c.coords(self._track, *box)
        # hide every state element, then light the ones this state uses
        for item in (self._oring, self._check, self._strike, self._timer):
            c.itemconfigure(item, state="hidden")
        c.itemconfigure(self._arc_id, state="hidden")
        if st == "loading":
            c.coords(self._oring, *box)
            c.itemconfigure(self._oring, outline=COLORS["coral"], state="normal")
        elif st == "rec":
            lv = self._levels[-1] if self._levels else 0.0
            # the coral arc fills clockwise from the top with the level (negative
            # extent = clockwise in Tk); a floor keeps a visible sliver at 0
            extent = -max(8.0, 360.0 * (0.06 + 0.94 * lv))
            c.coords(self._arc_id, *box)
            c.itemconfigure(self._arc_id, start=90, extent=extent,
                            outline=COLORS["coral"], state="normal")
            c.coords(self._timer, cx, cy)
            c.itemconfigure(self._timer, text=self._elapsed(),
                            fill=COLORS["text"], state="normal")
        elif st == "proc":
            c.coords(self._arc_id, *box)
            c.itemconfigure(self._arc_id, start=self._arc, extent=96,
                            outline=COLORS["coral"], state="normal")
            c.coords(self._timer, cx, cy)
            c.itemconfigure(self._timer, text=self._frozen,
                            fill=COLORS["muted"], state="normal")
        elif st == "flash":
            c.coords(self._oring, *box)
            c.itemconfigure(self._oring,
                            outline=COLORS["aqua"] if ok else COLORS["muted"],
                            state="normal")
            if ok:
                g = self.H * 0.5
                gx, gy = cx - g / 2, cy - g / 2
                c.coords(self._check, gx + .20 * g, gy + .55 * g,
                         gx + .42 * g, gy + .74 * g, gx + .80 * g, gy + .30 * g)
                c.itemconfigure(self._check, state="normal")
            else:
                g = self.H * 0.40
                gx, gy = cx - g / 2, cy - g / 2
                c.coords(self._strike, gx, gy + g, gx + g, gy)
                c.itemconfigure(self._strike, state="normal")

    def _paint_pill(self, text: str = "", ok: bool = True):
        """Lay the row out for the current state and move the items onto it."""
        c, st = self.canvas, self._state
        show_bars = st == "rec"
        show_timer = st in ("rec", "proc")
        timer_txt = self._elapsed() if st == "rec" else self._frozen
        # Recording is the widest of the indicator states (wave + timer). Two
        # states may overrun it and both do so on purpose: model loading, whose
        # copy is long because the wait is long, and the result flash, which
        # carries content rather than status (see _flash).
        label = {"loading": "Завантаження моделі…", "proc": "Розпізнаю…",
                 "rec": "", "flash": text}.get(st, "")

        # ---- widths (the window's width IS part of the state) ----
        parts = [self.GLYPH]
        if show_bars:
            parts.append(self.LANE_W)
        if label:
            parts.append(self.font.measure(label))
        if show_timer:
            parts.append(self._timer_w(timer_txt))
        w = 2 * self.PAD + sum(parts) + self.GAP * (len(parts) - 1)
        self._place(w)

        cy = self.H / 2
        x = self.PAD
        # ---- the dot ----
        gx = x + self.GLYPH / 2
        rr = self.DOT_R
        if st == "rec":
            rr *= 1 + 0.16 * self._levels[N_BARS // 2]  # rides the level
        c.coords(self._ring, gx - rr, cy - rr, gx + rr, cy + rr)
        fill, outline = "", COLORS["coral"]
        if st == "rec":
            fill = COLORS["coral"]
        elif st == "proc":
            # hollow again and dimmed: the motion of the arc carries this state
            outline = _mix(COLORS["coral"], COLORS["surface"], 0.30)
        elif st == "flash":
            fill = COLORS["aqua"] if ok else ""
            outline = COLORS["aqua"] if ok else COLORS["muted"]
        c.itemconfigure(self._ring, fill=fill, outline=outline)

        a = self.DOT_R * 1.55  # the arc turns on a slightly wider circle
        c.coords(self._arc_id, gx - a, cy - a, gx + a, cy + a)
        c.itemconfigure(self._arc_id, state="normal" if st == "proc" else "hidden")

        g = self.GLYPH
        ox, oy = gx - g / 2, cy - g / 2
        c.coords(self._check, ox + .28 * g, oy + .53 * g, ox + .44 * g,
                 oy + .69 * g, ox + .72 * g, oy + .34 * g)
        c.itemconfigure(self._check,
                        state="normal" if (st == "flash" and ok) else "hidden")
        c.coords(self._strike, ox + .28 * g, oy + .72 * g, ox + .72 * g,
                 oy + .28 * g)
        c.itemconfigure(self._strike,
                        state="normal" if (st == "flash" and not ok) else "hidden")
        x += self.GLYPH + self.GAP

        # ---- the level wave ----
        if show_bars:
            self._place_bars(x, cy)
            x += self.LANE_W + self.GAP
        else:
            for b in self._bars:
                c.itemconfigure(b, state="hidden")

        # ---- copy ----
        if label:
            colour = COLORS["muted"]
            if st == "flash":
                # the recognised text is content, not a status word, so it gets
                # the pill's own ink; the aqua/neutral signal lives in the dot
                colour = COLORS["text"] if ok else COLORS["muted"]
            c.itemconfigure(self._label, text=label, fill=colour, state="normal")
            c.coords(self._label, x, cy)
            x += self.font.measure(label) + self.GAP
        else:
            c.itemconfigure(self._label, state="hidden")

        if show_timer:
            c.itemconfigure(self._timer, text=timer_txt, state="normal",
                            fill=COLORS["text"] if st == "rec" else COLORS["muted"])
            c.coords(self._timer, x + self._timer_w(timer_txt), cy)
        else:
            c.itemconfigure(self._timer, state="hidden")

    def _place_bars(self, x: float, cy: float):
        c, lane, g = self.canvas, self.LANE_H, self.WAVE_GAIN
        for i, b in enumerate(self._bars):
            h = lane * (0.17 + self._levels[i] * g[i] * 0.83)
            bx = x + i * (self.BAR_W + self.BAR_GAP)
            c.coords(b, bx, cy - h / 2, bx + self.BAR_W, cy + h / 2)
            c.itemconfigure(b, state="normal")

    # ---- animation (only while recording, plus the processing arc) ----
    def _tick(self):
        self._frame()
        self._timer_job = self.root.after(FRAME_MS, self._tick)

    def _frame(self):
        """One wave frame: existing items are moved, never recreated."""
        self._advance_wave()
        self._paint()
        self.frames += 1

    def _advance_wave(self):
        """Scroll one new amplitude in from the right, like the mock's hist()."""
        if self._level is not None:
            v = self._level
        else:
            # No mic level is available in this build, so the lane shows a
            # calm "listening" motion rather than pretending to be a meter.
            self._phase += 0.42
            v = 0.34 + 0.18 * math.sin(self._phase) + 0.10 * math.sin(self._phase * 2.7)
        self._levels = self._levels[1:] + [min(1.0, max(0.0, v))]

    def _spin(self):
        self._arc_frame()
        self._anim_job = self.root.after(PROC_MS, self._spin)

    def _arc_frame(self):
        self._arc = (self._arc - 34) % 360
        self.canvas.itemconfigure(self._arc_id, start=self._arc)
        self.frames += 1

    def _elapsed(self) -> str:
        e = int(time.time() - self._t0)
        return f"{e // 60}:{e % 60:02d}"

    def _flash(self, text: str, ok: bool):
        text = (text or "").replace("\n", " ⏎ ")
        # Width is part of the state language, and recording is the widest of
        # the indicator states (wave + timer). The result flash is the one place
        # that may overrun it: it carries CONTENT the user is checking, and
        # trimming it to the recording width leaves ~13 characters — too few to
        # confirm what was inserted. So the old 30-char limit is the only cap;
        # lower FLASH_MAX_CHARS if the pill should never exceed recording.
        shown = text if len(text) <= FLASH_MAX_CHARS else text[:FLASH_MAX_CHARS - 1] + "…"
        self._apply("flash", shown, ok)
        self._timer_job = self.root.after(1800, self._hide)

    def _hide(self):
        self._cancel_timer()
        self._cancel_anim()
        self._state = None
        self.win.withdraw()

    def _cancel_timer(self):
        if self._timer_job is not None:
            self.root.after_cancel(self._timer_job)
            self._timer_job = None

    def _cancel_anim(self):
        if self._anim_job is not None:
            self.root.after_cancel(self._anim_job)
            self._anim_job = None

    def destroy(self):
        """Stop the loops and drop the window — must run on the Tk thread.

        Size and placement are baked into every metric and canvas item when the
        pill is built, so a settings change is applied by replacing the pill
        rather than patching a live canvas (see flow.apply_overlay_config)."""
        self._cancel_timer()
        self._cancel_anim()
        try:
            self.win.destroy()
        except tk.TclError:
            pass  # already gone (interpreter shutting down) — nothing to free


# ======================================================================
# PRIMARY renderer: a Win32 layered window fed a Pillow RGBA bitmap.
# ======================================================================
# Set KUUBWAVE_OVERLAY_FORCE_FALLBACK=1 to force _LayeredOverlay to raise at
# construction — used by the test suite to prove the Tk fallback actually kicks
# in. Nothing in production sets it.
_FORCE_FALLBACK_ENV = "KUUBWAVE_OVERLAY_FORCE_FALLBACK"

# --- Win32 constants (plain ints — safe to define on any platform) ---
_WS_POPUP = 0x80000000
_WS_EX_LAYERED = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOPMOST = 0x00000008
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000
_OVERLAY_EXSTYLE = (_WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_TOPMOST
                    | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE)
_GWL_EXSTYLE = -20
_SW_HIDE = 0
_SW_SHOWNOACTIVATE = 4          # show WITHOUT stealing focus — non-negotiable
_HWND_TOPMOST = -1
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010        # never activate on a z-order change either
_ULW_ALPHA = 0x02
_AC_SRC_OVER = 0x00
_AC_SRC_ALPHA = 0x01
_BI_RGB = 0
_DIB_RGB_COLORS = 0
_PM_REMOVE = 0x0001

_LRESULT = ctypes.c_ssize_t
_WNDPROC = ctypes.WINFUNCTYPE(_LRESULT, ctypes.c_void_p, ctypes.c_uint,
                              ctypes.c_size_t, ctypes.c_ssize_t)


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16),
                ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32),
                ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32),
                ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER),
                ("bmiColors", ctypes.c_uint32 * 3)]


class _WNDCLASS(ctypes.Structure):
    _fields_ = [("style", ctypes.c_uint), ("lpfnWndProc", _WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", ctypes.c_void_p), ("hIcon", ctypes.c_void_p),
                ("hCursor", ctypes.c_void_p),
                ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", ctypes.c_wchar_p),
                ("lpszClassName", ctypes.c_wchar_p)]


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t),
                ("time", ctypes.c_uint32), ("pt", _POINT),
                ("lPrivate", ctypes.c_uint32)]


_G: dict = {}  # process-wide win32 cache: libs, window class, wndproc keepalive


def _win32():
    """Configure and cache the Win32 entry points. Raises on non-Windows."""
    if _G.get("ready"):
        return _G
    # PRIVATE WinDLL instances, NOT ctypes.windll.user32. windll caches one
    # shared object per DLL, and setting .argtypes on its functions is global to
    # the process — pynput's hotkey listener calls the same windll.user32.
    # PeekMessageW, so our argtypes made its call raise
    # "expected LP__MSG instead of pointer to MSG" and killed the listener
    # threads (no more dictation). A fresh WinDLL has its own function cache, so
    # our type setup stays isolated to this renderer. (AttributeError/OSError on
    # non-Windows -> caller falls back to the Tk pill.)
    user32 = ctypes.WinDLL("user32")
    gdi32 = ctypes.WinDLL("gdi32")
    kernel32 = ctypes.WinDLL("kernel32")
    cvp = ctypes.c_void_p

    user32.CreateWindowExW.restype = cvp
    user32.CreateWindowExW.argtypes = [
        ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        cvp, cvp, cvp, cvp]
    user32.DefWindowProcW.restype = _LRESULT
    user32.DefWindowProcW.argtypes = [cvp, ctypes.c_uint, ctypes.c_size_t,
                                      ctypes.c_ssize_t]
    user32.RegisterClassW.restype = ctypes.c_ushort
    user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASS)]
    user32.ShowWindow.restype = ctypes.c_int
    user32.ShowWindow.argtypes = [cvp, ctypes.c_int]
    user32.DestroyWindow.restype = ctypes.c_int
    user32.DestroyWindow.argtypes = [cvp]
    user32.SetWindowPos.restype = ctypes.c_int
    user32.SetWindowPos.argtypes = [cvp, cvp, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    user32.UpdateLayeredWindow.restype = ctypes.c_int
    user32.UpdateLayeredWindow.argtypes = [
        cvp, cvp, ctypes.POINTER(_POINT), ctypes.POINTER(_SIZE), cvp,
        ctypes.POINTER(_POINT), ctypes.c_uint32,
        ctypes.POINTER(_BLENDFUNCTION), ctypes.c_uint32]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongW.argtypes = [cvp, ctypes.c_int]
    user32.PeekMessageW.restype = ctypes.c_int
    user32.PeekMessageW.argtypes = [ctypes.POINTER(_MSG), cvp, ctypes.c_uint,
                                    ctypes.c_uint, ctypes.c_uint]
    user32.TranslateMessage.argtypes = [ctypes.POINTER(_MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(_MSG)]

    gdi32.CreateCompatibleDC.restype = cvp
    gdi32.CreateCompatibleDC.argtypes = [cvp]
    gdi32.CreateDIBSection.restype = cvp
    gdi32.CreateDIBSection.argtypes = [cvp, ctypes.POINTER(_BITMAPINFO),
                                       ctypes.c_uint, ctypes.POINTER(cvp),
                                       cvp, ctypes.c_uint32]
    gdi32.SelectObject.restype = cvp
    gdi32.SelectObject.argtypes = [cvp, cvp]
    gdi32.DeleteObject.argtypes = [cvp]
    gdi32.DeleteDC.argtypes = [cvp]

    kernel32.GetModuleHandleW.restype = cvp
    kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]

    _G.update(user32=user32, gdi32=gdi32, kernel32=kernel32, ready=True)
    return _G


def _ensure_window_class():
    """Register the overlay window class exactly once per process."""
    if _G.get("class"):
        return _G["class"]
    g = _win32()
    hinst = g["kernel32"].GetModuleHandleW(None)

    def _proc(hwnd, msg, wp, lp):
        return g["user32"].DefWindowProcW(hwnd, msg, wp, lp)

    proc = _WNDPROC(_proc)          # MUST stay referenced for the window's life
    wc = _WNDCLASS()
    wc.style = 0
    wc.lpfnWndProc = proc
    wc.cbClsExtra = 0
    wc.cbWndExtra = 0
    wc.hInstance = hinst
    wc.hIcon = None
    wc.hCursor = None
    wc.hbrBackground = None
    wc.lpszMenuName = None
    wc.lpszClassName = "KuubWaveOverlayPill"
    if not g["user32"].RegisterClassW(ctypes.byref(wc)):
        raise ctypes.WinError()
    _G["wndproc"] = proc
    _G["hinst"] = hinst
    _G["class"] = "KuubWaveOverlayPill"
    return _G["class"]


_FONT_LABELS = {
    "seguisb.ttf": "Segoe UI Semibold", "segoeuib.ttf": "Segoe UI Bold",
    "segoeui.ttf": "Segoe UI", "JetBrainsMono-Regular.ttf": "JetBrains Mono",
    "CascadiaMono.ttf": "Cascadia Mono", "CascadiaCode.ttf": "Cascadia Code",
    "consola.ttf": "Consolas", "cour.ttf": "Courier New",
}


def _load_font(candidates, size):
    """Return (PIL font, friendly name) for the first candidate that loads."""
    from PIL import ImageFont
    for name in candidates:
        try:
            return ImageFont.truetype(name, size), _FONT_LABELS.get(name, name)
        except OSError:
            continue
    return ImageFont.load_default(), "default"


def _rgba(hex_str: str, a: int = 255):
    return (int(hex_str[1:3], 16), int(hex_str[3:5], 16),
            int(hex_str[5:7], 16), a)


class _LayeredOverlay:
    """Win32 layered-window pill with true per-pixel alpha (Pillow-rendered).

    NEVER activates: the window is WS_EX_NOACTIVATE + WS_EX_TRANSPARENT and is
    only ever shown with SW_SHOWNOACTIVATE / positioned with SWP_NOACTIVATE.
    Nothing here calls SetForegroundWindow, SetActiveWindow or ShowWindow with
    an activating flag, so it can never pull keyboard focus away from the app
    the user is dictating into. A hidden Tk root is the timer/after source, so
    the public API keeps exactly the old thread-safety contract."""

    def __init__(self, root: tk.Tk, config: dict | None = None):
        if os.environ.get(_FORCE_FALLBACK_ENV):
            raise RuntimeError("layered renderer forced off via "
                               + _FORCE_FALLBACK_ENV)
        # importing here means a missing Pillow degrades to the Tk fallback
        from PIL import Image, ImageDraw, ImageFilter, ImageChops  # noqa: F401
        self._Image = Image
        self._Draw = ImageDraw.Draw
        self._ImageFilter = ImageFilter
        self._ImageChops = ImageChops

        self.root = root
        cfg = config or {}
        try:
            scale = float(cfg.get("overlay_scale", 100))
        except (TypeError, ValueError):
            scale = 100.0
        self.scale = min(SCALE_MAX, max(SCALE_MIN, scale)) / 100.0
        self.pos_x, self.pos_y = parse_position(cfg.get("overlay_position",
                                                        "bottom-center"))
        try:
            self.margin = max(0, int(cfg.get("overlay_margin", 60)))
        except (TypeError, ValueError):
            self.margin = 60

        # pill-body alpha (0..255), from overlay_opacity percent; clamped so the
        # label/dot never fade past readable. The default mirrors PILL_ALPHA.
        try:
            op = float(cfg.get("overlay_opacity", round(PILL_ALPHA / 255 * 100)))
        except (TypeError, ValueError):
            op = round(PILL_ALPHA / 255 * 100)
        op = min(100.0, max(OPACITY_MIN, op))
        self._alpha = int(round(op * 255 / 100))

        self.style = _valid_style(cfg.get("overlay_style", "pill"))
        s = self.scale
        r = lambda v: int(round(v * s))  # noqa: E731
        self.SS = 3                       # supersample: draw big, downscale sharp
        self.H = r(40)
        self.R = self.H / 2.0
        self.PAD = r(14)
        self.GAP = r(9)
        self.GLYPH = r(16)
        self.DOT_R = 5.0 * s
        self.STROKE = max(1.0, 2.0 * s)
        self.HAIR = max(1.0, 1.0 * s)
        self.BAR_W = max(1.0, 3.0 * s)
        self.BAR_GAP = max(1.0, 3.0 * s)
        self.LANE_H = r(18)
        self.LANE_W = N_BARS * self.BAR_W + (N_BARS - 1) * self.BAR_GAP
        # per-shape geometry (see the header + _TkOverlay for the same model).
        # self.H is the overlay's outer height; the orb is a circle so its
        # height IS its diameter, the dock is a taller stadium.
        self.WAVE_N, self.WAVE_GAIN = N_BARS, BAR_GAIN
        if self.style == "orb":
            self.H = r(60)
            self.R = self.H / 2.0
            self.ORB_STROKE = max(2.0, 3.0 * s)
        elif self.style == "dock":
            self.H = r(52)
            self.R = self.H / 2.0
            self.DOCK_DOT = r(10)
            self.DOCK_LANE_W = r(150)
            self.LANE_H = r(26)
            self.WAVE_N = max(8, int(self.DOCK_LANE_W // (self.BAR_W + self.BAR_GAP)))
            self.WAVE_GAIN = _wave_gain(self.WAVE_N)
        # the shadow spread is baked into the window size so it is never clipped
        self.SHADOW = r(15)

        ss = self.SS
        self._label_font, self.label_family = _load_font(
            ["seguisb.ttf", "segoeuib.ttf", "segoeui.ttf"], round(12 * s * ss))
        self._timer_font, self.timer_family = _load_font(
            ["JetBrainsMono-Regular.ttf", "CascadiaMono.ttf", "consola.ttf",
             "cour.ttf"], round(12 * s * ss))

        # --- state ---
        self._t0 = 0.0
        self._frozen = "0:00"
        self._timer_job = None
        self._anim_job = None
        self._levels = [0.0] * self.WAVE_N
        self._level = None
        self._phase = 0.0
        self._arc = 0.0
        self._state = None
        self._text = ""
        self._ok = True
        self.frames = 0
        self._shown = False
        self._pill_w = 0
        self._win_pos = (0, 0)

        # --- Win32 surface ---
        self._g = _win32()
        cls = _ensure_window_class()
        self._hwnd = self._g["user32"].CreateWindowExW(
            _OVERLAY_EXSTYLE, cls, "KuubWave", _WS_POPUP,
            -10000, -10000, 16, 16, None, None, _G["hinst"], None)
        if not self._hwnd:
            raise ctypes.WinError()
        self._memdc = None
        self._dib = None
        self._old_bmp = None
        self._bits = None
        self._dib_w = self._dib_h = 0
        # Smoke-test the whole GDI pipeline while the window is hidden and
        # off-screen: if CreateDIBSection / UpdateLayeredWindow fail for any
        # reason, this raises now and StatusOverlay falls back to Tk. Tear the
        # half-built window down first so nothing leaks before the fallback.
        try:
            self._push(Image.new("RGBA", (8, 8), (0, 0, 0, 0)), -10000, -10000)
        except BaseException:
            self.destroy()
            raise

    # ---- public, thread-safe (identical contract to _TkOverlay) ----
    def loading(self):
        self.root.after(0, self._apply, "loading")

    def recording(self):
        self._t0 = time.time()
        self.root.after(0, self._apply, "rec")

    def processing(self):
        self.root.after(0, self._apply, "proc")

    def flash(self, text: str, ok: bool = True):
        self.root.after(0, self._flash, text, ok)

    def hide(self):
        self.root.after(0, self._hide)

    def level(self, value: float):
        try:
            self._level = min(1.0, max(0.0, float(value)))
        except (TypeError, ValueError):
            pass

    # ---- DIB / layered-window plumbing ----
    def _ensure_dib(self, w: int, h: int):
        g = self._g
        if self._memdc is None:
            self._memdc = g["gdi32"].CreateCompatibleDC(None)
            if not self._memdc:
                raise ctypes.WinError()
        if self._dib and (w, h) == (self._dib_w, self._dib_h):
            return
        if self._dib:
            g["gdi32"].SelectObject(self._memdc, self._old_bmp)
            g["gdi32"].DeleteObject(self._dib)
            self._dib = None
        bmi = _BITMAPINFO()
        hdr = bmi.bmiHeader
        hdr.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        hdr.biWidth = w
        hdr.biHeight = -h            # top-down, so PIL row order matches
        hdr.biPlanes = 1
        hdr.biBitCount = 32
        hdr.biCompression = _BI_RGB
        bits = ctypes.c_void_p()
        dib = g["gdi32"].CreateDIBSection(self._memdc, ctypes.byref(bmi),
                                          _DIB_RGB_COLORS, ctypes.byref(bits),
                                          None, 0)
        if not dib:
            raise ctypes.WinError()
        self._old_bmp = g["gdi32"].SelectObject(self._memdc, dib)
        self._dib, self._bits = dib, bits
        self._dib_w, self._dib_h = w, h

    def _bgra_premult(self, im):
        """RGBA PIL image -> premultiplied BGRA bytes for the DIB.

        Premultiplication is mandatory for AC_SRC_ALPHA: without it the smooth
        edges fringe against whatever is behind the pill."""
        if im.mode != "RGBA":
            im = im.convert("RGBA")
        r, gc, b, a = im.split()
        mul = self._ImageChops.multiply
        out = self._Image.merge("RGBA", (mul(b, a), mul(gc, a), mul(r, a), a))
        return out.tobytes("raw", "RGBA")   # channel order B,G,R,A == DIB bytes

    def _push(self, image, px: int, py: int):
        w, h = image.size
        self._ensure_dib(w, h)
        data = self._bgra_premult(image)
        ctypes.memmove(self._bits, data, len(data))
        pt_src = _POINT(0, 0)
        pt_dst = _POINT(px, py)
        size = _SIZE(w, h)
        blend = _BLENDFUNCTION(_AC_SRC_OVER, 0, 255, _AC_SRC_ALPHA)
        ok = self._g["user32"].UpdateLayeredWindow(
            self._hwnd, None, ctypes.byref(pt_dst), ctypes.byref(size),
            self._memdc, ctypes.byref(pt_src), 0, ctypes.byref(blend),
            _ULW_ALPHA)
        if not ok:
            raise ctypes.WinError()

    def _pump(self):
        """Drain only THIS window's messages (never Tk's) so it stays live."""
        msg = _MSG()
        u = self._g["user32"]
        while u.PeekMessageW(ctypes.byref(msg), self._hwnd, 0, 0, _PM_REMOVE):
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))

    # ---- measurement / layout ----
    def _measure(self, font, text: str) -> float:
        return font.getlength(text) / self.SS   # device px -> logical px

    def _timer_w(self, text: str) -> float:
        return max(self._measure(self._timer_font, text),
                   self._measure(self._timer_font, "0:00"))

    def _fit(self, text: str, maxw: float, font) -> str:
        """Trim text to fit maxw logical px, adding an ellipsis (dock lane)."""
        if not text or self._measure(font, text) <= maxw:
            return text
        while text and self._measure(font, text + "…") > maxw:
            text = text[:-1]
        return (text + "…") if text else "…"

    def _win_w(self) -> int:
        """Outer width of the current shape (the orb is square, dock is fixed)."""
        if self.style == "orb":
            return int(self.H)
        if self.style == "dock":
            return int(math.ceil(
                2 * self.PAD + self.DOCK_DOT + self.GAP + self.DOCK_LANE_W
                + self.GAP + self._timer_w("0:00")))
        return self._content()[4]

    def _content(self):
        """State -> (label, timer_txt, show_bars, show_timer, pill width)."""
        st = self._state
        show_bars = st == "rec"
        show_timer = st in ("rec", "proc")
        timer_txt = self._elapsed() if st == "rec" else self._frozen
        label = {"loading": "Завантаження моделі…", "proc": "Розпізнаю…",
                 "rec": "", "flash": self._text}.get(st, "")
        parts = [float(self.GLYPH)]
        if show_bars:
            parts.append(self.LANE_W)
        if label:
            parts.append(self._measure(self._label_font, label))
        if show_timer:
            parts.append(self._timer_w(timer_txt))
        w = 2 * self.PAD + sum(parts) + self.GAP * (len(parts) - 1)
        return label, timer_txt, show_bars, show_timer, int(math.ceil(w))

    def _position(self, w: int):
        """Same free-space model as _TkOverlay._place -> pill top-left (px,py)."""
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        free_w = sw - w - 2 * self.margin
        free_h = sh - self.H - 2 * self.margin
        px = self.margin + int(round(max(0, free_w) * self.pos_x / 100.0))
        py = self.margin + int(round(max(0, free_h) * self.pos_y / 100.0))
        px = max(0, min(px, sw - w))
        py = max(0, min(py, sh - self.H))
        return px, py

    # ---- Pillow rendering ----
    def _render(self, w: int):
        if self.style == "orb":
            return self._render_orb(w)
        if self.style == "dock":
            return self._render_dock(w)
        return self._render_pill(w)

    def _render_dock(self, w: int):
        """DISPLAY-ONLY wide bar: dot + wave/label lane + timer. No buttons —
        the window is click-through and could never receive one."""
        Image, Draw = self._Image, self._Draw
        st = self._state
        ss = self.SS
        pad = self.SHADOW
        Wd = (w + 2 * pad) * ss
        Hd = (self.H + 2 * pad) * ss
        ox, oy = pad * ss, pad * ss
        X = lambda lx: ox + lx * ss   # noqa: E731
        Y = lambda ly: oy + ly * ss   # noqa: E731
        img = Image.new("RGBA", (Wd, Hd), (0, 0, 0, 0))
        rec = st == "rec"
        sh = Image.new("RGBA", (Wd, Hd), (0, 0, 0, 0))
        sd = Draw(sh)
        off = int(round((2.5 if rec else 1.8) * self.scale)) * ss
        Rd = self.R * ss
        sd.rounded_rectangle((ox, oy + off, ox + w * ss, oy + self.H * ss + off),
                             radius=Rd, fill=(9, 6, 11, 190 if rec else 150))
        blur = pad * ss * (0.50 if rec else 0.42)
        sh = sh.filter(self._ImageFilter.GaussianBlur(blur))
        img = Image.alpha_composite(img, sh)
        d = Draw(img)
        d.rounded_rectangle((ox, oy, ox + w * ss, oy + self.H * ss),
                            radius=Rd, fill=_rgba(COLORS["ring"], self._alpha))
        ins = self.HAIR * ss
        d.rounded_rectangle((ox + ins, oy + ins, ox + w * ss - ins,
                             oy + self.H * ss - ins),
                            radius=max(1.0, Rd - ins),
                            fill=_rgba(COLORS["surface"], self._alpha))
        cyL = self.H / 2.0
        stroke = max(1, int(round(self.STROKE * ss)))
        lx = float(self.PAD)
        # --- the state dot (carries the colour identity) ---
        dot_fill = COLORS["coral"]
        if st == "loading":
            dot_fill = _mix(COLORS["coral"], COLORS["surface"], 0.55)
        elif st == "proc":
            dot_fill = _mix(COLORS["coral"], COLORS["surface"], 0.40)
        elif st == "flash":
            dot_fill = COLORS["aqua"] if self._ok else COLORS["muted"]
        dr = self.DOCK_DOT / 2.0
        d.ellipse((X(lx), Y(cyL - dr), X(lx + self.DOCK_DOT), Y(cyL + dr)),
                  fill=_rgba(dot_fill))
        lx += self.DOCK_DOT + self.GAP
        lane_x = lx
        # --- the lane: wave while recording, else a status / result label ---
        if st == "rec":
            for i in range(self.WAVE_N):
                hL = self.LANE_H * (0.17 + self._levels[i] * self.WAVE_GAIN[i] * 0.83)
                bxL = lane_x + i * (self.BAR_W + self.BAR_GAP)
                d.rounded_rectangle((X(bxL), Y(cyL - hL / 2), X(bxL + self.BAR_W),
                                     Y(cyL + hL / 2)),
                                    radius=self.BAR_W * ss / 2.0,
                                    fill=_rgba(COLORS["coral"]))
        else:
            label = {"loading": "Завантаження моделі…", "proc": "Розпізнаю…",
                     "flash": self._text}.get(st, "")
            label = self._fit(label, self.DOCK_LANE_W, self._label_font)
            if label:
                colour = COLORS["muted"]
                if st == "flash":
                    colour = COLORS["text"] if self._ok else COLORS["muted"]
                d.text((X(lane_x), Y(cyL)), label, font=self._label_font,
                       fill=_rgba(colour), anchor="lm")
        lx = lane_x + self.DOCK_LANE_W + self.GAP
        # --- the timer (recording / processing) ---
        if st in ("rec", "proc"):
            timer_txt = self._elapsed() if st == "rec" else self._frozen
            tcol = COLORS["text"] if st == "rec" else COLORS["muted"]
            tw = self._timer_w("0:00")
            d.text((X(lx + tw), Y(cyL)), timer_txt, font=self._timer_font,
                   fill=_rgba(tcol), anchor="rm")
        return img.resize((w + 2 * pad, self.H + 2 * pad), self._Image.LANCZOS)

    def _render_orb(self, w: int):
        """The ring token: a faint full track with a coral state ring / arc laid
        over it, plus a centred check / strike / timer. Same colour identity as
        the pill (coral energy, aqua only on success)."""
        Image, Draw = self._Image, self._Draw
        st = self._state
        ss = self.SS
        pad = self.SHADOW
        D = self.H                             # the orb is square: w == H == D
        Wd = (D + 2 * pad) * ss
        Hd = (D + 2 * pad) * ss
        ox, oy = pad * ss, pad * ss
        X = lambda lx: ox + lx * ss   # noqa: E731
        Y = lambda ly: oy + ly * ss   # noqa: E731
        img = Image.new("RGBA", (Wd, Hd), (0, 0, 0, 0))
        rec = st == "rec"
        sh = Image.new("RGBA", (Wd, Hd), (0, 0, 0, 0))
        sd = Draw(sh)
        off = int(round((2.5 if rec else 1.8) * self.scale)) * ss
        sd.ellipse((ox, oy + off, ox + D * ss, oy + D * ss + off),
                   fill=(9, 6, 11, 190 if rec else 150))
        blur = pad * ss * (0.50 if rec else 0.42)
        sh = sh.filter(self._ImageFilter.GaussianBlur(blur))
        img = Image.alpha_composite(img, sh)
        d = Draw(img)
        d.ellipse((ox, oy, ox + D * ss, oy + D * ss),
                  fill=_rgba(COLORS["ring"], self._alpha))
        ins = self.HAIR * ss
        d.ellipse((ox + ins, oy + ins, ox + D * ss - ins, oy + D * ss - ins),
                  fill=_rgba(COLORS["surface"], self._alpha))
        cx = cy = D / 2.0
        stroke = max(2, int(round(self.ORB_STROKE * ss)))
        inset = self.ORB_STROKE + max(2.0, self.STROKE)
        rr = D / 2.0 - inset
        box = (X(cx - rr), Y(cy - rr), X(cx + rr), Y(cy + rr))
        # a faint full track under every state
        d.ellipse(box, outline=_rgba(_mix(COLORS["ring"], COLORS["surface"], 0.9)),
                  width=stroke)
        if st == "loading":
            d.ellipse(box, outline=_rgba(COLORS["coral"]), width=stroke)
        elif st == "rec":
            lv = self._levels[-1] if self._levels else 0.0
            # the coral arc fills clockwise from the top with the level (PIL
            # angles run clockwise from 3 o'clock, so top is -90)
            end = -90.0 + 360.0 * (0.06 + 0.94 * lv)
            d.arc(box, start=-90.0, end=max(-82.0, end),
                  fill=_rgba(COLORS["coral"]), width=stroke)
            d.text((X(cx), Y(cy)), self._elapsed(), font=self._timer_font,
                   fill=_rgba(COLORS["text"]), anchor="mm")
        elif st == "proc":
            d.arc(box, start=self._arc, end=self._arc + 96,
                  fill=_rgba(COLORS["coral"]), width=stroke)
            d.text((X(cx), Y(cy)), self._frozen, font=self._timer_font,
                   fill=_rgba(COLORS["muted"]), anchor="mm")
        elif st == "flash":
            d.ellipse(box, outline=_rgba(COLORS["aqua"] if self._ok
                                         else COLORS["muted"]), width=stroke)
            if self._ok:
                g = D * 0.5
                gx, gy = cx - g / 2, cy - g / 2
                d.line([X(gx + .20 * g), Y(gy + .55 * g),
                        X(gx + .42 * g), Y(gy + .74 * g),
                        X(gx + .80 * g), Y(gy + .30 * g)],
                       fill=_rgba(COLORS["aqua"]), width=stroke, joint="curve")
            else:
                g = D * 0.40
                gx, gy = cx - g / 2, cy - g / 2
                d.line([X(gx), Y(gy + g), X(gx + g), Y(gy)],
                       fill=_rgba(COLORS["muted"]), width=stroke, joint="curve")
        return img.resize((D + 2 * pad, D + 2 * pad), self._Image.LANCZOS)

    def _render_pill(self, w: int):
        """Render the whole window bitmap (pill + shadow) at the current state.

        Everything is drawn at SS x size and downscaled with LANCZOS, so the
        rounded corners, the dot, the arc, the check/strike and the wave are all
        anti-aliased — the flat, aliased 90s look is gone."""
        Image, Draw = self._Image, self._Draw
        st = self._state
        ss = self.SS
        pad = self.SHADOW
        Wd = (w + 2 * pad) * ss
        Hd = (self.H + 2 * pad) * ss
        ox, oy = pad * ss, pad * ss           # pill origin inside the bitmap

        def X(lx):
            return ox + lx * ss

        def Y(ly):
            return oy + ly * ss

        img = Image.new("RGBA", (Wd, Hd), (0, 0, 0, 0))

        # --- soft drop shadow (restrained Soft Studio elevation) ---
        rec = st == "rec"
        sh = Image.new("RGBA", (Wd, Hd), (0, 0, 0, 0))
        sd = Draw(sh)
        off = int(round((2.5 if rec else 1.8) * self.scale)) * ss
        Rd = self.R * ss
        sd.rounded_rectangle((ox, oy + off, ox + w * ss, oy + self.H * ss + off),
                             radius=Rd, fill=(9, 6, 11, 190 if rec else 150))
        blur = pad * ss * (0.50 if rec else 0.42)
        sh = sh.filter(self._ImageFilter.GaussianBlur(blur))
        img = Image.alpha_composite(img, sh)
        d = Draw(img)

        # --- surface + hairline edge ---
        d.rounded_rectangle((ox, oy, ox + w * ss, oy + self.H * ss),
                            radius=Rd, fill=_rgba(COLORS["ring"], self._alpha))
        ins = self.HAIR * ss
        d.rounded_rectangle((ox + ins, oy + ins, ox + w * ss - ins,
                             oy + self.H * ss - ins),
                            radius=max(1.0, Rd - ins),
                            fill=_rgba(COLORS["surface"], self._alpha))

        cyL = self.H / 2.0
        lx = float(self.PAD)
        stroke = max(1, int(round(self.STROKE * ss)))

        # --- the dot: geometry carries the state ---
        gxL = lx + self.GLYPH / 2.0
        rrL = self.DOT_R
        if st == "rec":
            rrL *= 1 + 0.16 * self._levels[N_BARS // 2]
        ring_box = (X(gxL - rrL), Y(cyL - rrL), X(gxL + rrL), Y(cyL + rrL))
        fill, outline = None, COLORS["coral"]
        if st == "rec":
            fill = COLORS["coral"]
        elif st == "proc":
            outline = _mix(COLORS["coral"], COLORS["surface"], 0.30)
        elif st == "flash":
            fill = COLORS["aqua"] if self._ok else None
            outline = COLORS["aqua"] if self._ok else COLORS["muted"]
        d.ellipse(ring_box, fill=_rgba(fill) if fill else None,
                  outline=_rgba(outline), width=stroke)

        if st == "proc":
            aL = self.DOT_R * 1.55
            arc_box = (X(gxL - aL), Y(cyL - aL), X(gxL + aL), Y(cyL + aL))
            d.arc(arc_box, start=self._arc, end=self._arc + 96,
                  fill=_rgba(COLORS["coral"]), width=stroke)

        gL = float(self.GLYPH)
        oxL, oyL = gxL - gL / 2.0, cyL - gL / 2.0
        if st == "flash" and self._ok:
            d.line([X(oxL + .28 * gL), Y(oyL + .53 * gL),
                    X(oxL + .44 * gL), Y(oyL + .69 * gL),
                    X(oxL + .72 * gL), Y(oyL + .34 * gL)],
                   fill=_rgba(COLORS["check"]), width=stroke, joint="curve")
        elif st == "flash" and not self._ok:
            d.line([X(oxL + .28 * gL), Y(oyL + .72 * gL),
                    X(oxL + .72 * gL), Y(oyL + .28 * gL)],
                   fill=_rgba(COLORS["muted"]), width=stroke, joint="curve")
        lx += self.GLYPH + self.GAP

        # --- the level wave: soft, rounded, centre-weighted ---
        if st == "rec":
            for i in range(N_BARS):
                hL = self.LANE_H * (0.17 + self._levels[i] * BAR_GAIN[i] * 0.83)
                bxL = lx + i * (self.BAR_W + self.BAR_GAP)
                d.rounded_rectangle((X(bxL), Y(cyL - hL / 2), X(bxL + self.BAR_W),
                                     Y(cyL + hL / 2)),
                                    radius=self.BAR_W * ss / 2.0,
                                    fill=_rgba(COLORS["coral"]))
            lx += self.LANE_W + self.GAP

        # --- copy ---
        label, timer_txt, _sb, show_timer, _w = self._content()
        if label:
            colour = COLORS["muted"]
            if st == "flash":
                colour = COLORS["text"] if self._ok else COLORS["muted"]
            d.text((X(lx), Y(cyL)), label, font=self._label_font,
                   fill=_rgba(colour), anchor="lm")
            lx += self._measure(self._label_font, label) + self.GAP

        if show_timer:
            tcol = COLORS["text"] if st == "rec" else COLORS["muted"]
            tw = self._timer_w(timer_txt)
            d.text((X(lx + tw), Y(cyL)), timer_txt, font=self._timer_font,
                   fill=_rgba(tcol), anchor="rm")

        return img.resize((w + 2 * pad, self.H + 2 * pad),
                          self._Image.LANCZOS)

    def _render_push(self):
        """Render the current state and push it; reposition + show if needed."""
        w = self._win_w()
        px, py = self._position(w)
        self._pill_w = w
        self._win_pos = (px, py)
        try:
            img = self._render(w)
            self._push(img, px - self.SHADOW, py - self.SHADOW)
        except Exception as e:
            _log(f"overlay: layered push failed ({e.__class__.__name__}: {e})")
            return
        u = self._g["user32"]
        if not self._shown:
            u.ShowWindow(self._hwnd, _SW_SHOWNOACTIVATE)
            self._shown = True
        # keep it pinned on top without ever activating it
        u.SetWindowPos(self._hwnd, ctypes.c_void_p(_HWND_TOPMOST), 0, 0, 0, 0,
                       _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE)
        self._pump()

    # ---- state machine (tk thread only) ----
    def _apply(self, name: str):
        if name == "rec":
            self._frozen = "0:00"
        elif name == "proc" and self._state == "rec":
            self._frozen = self._elapsed()
        self._state = name
        self._cancel_timer()
        self._cancel_anim()
        self._render_push()
        if name == "rec":
            self._timer_job = self.root.after(FRAME_MS, self._tick)
        elif name == "proc" and self.style in ("pill", "orb"):
            # the dock's processing state is static (frozen timer + label), so
            # only the pill/orb turning arc needs the spin loop
            self._anim_job = self.root.after(PROC_MS, self._spin)

    def _flash(self, text: str, ok: bool):
        text = (text or "").replace("\n", " ⏎ ")
        shown = (text if len(text) <= FLASH_MAX_CHARS
                 else text[:FLASH_MAX_CHARS - 1] + "…")
        self._text, self._ok = shown, ok
        self._apply("flash")
        self._timer_job = self.root.after(1800, self._hide)

    def _tick(self):
        self._advance_wave()
        self._render_push()
        self.frames += 1
        self._timer_job = self.root.after(FRAME_MS, self._tick)

    def _advance_wave(self):
        if self._level is not None:
            v = self._level
        else:
            self._phase += 0.42
            v = (0.34 + 0.18 * math.sin(self._phase)
                 + 0.10 * math.sin(self._phase * 2.7))
        self._levels = self._levels[1:] + [min(1.0, max(0.0, v))]

    def _spin(self):
        self._arc = (self._arc - 34) % 360
        self._render_push()
        self.frames += 1
        self._anim_job = self.root.after(PROC_MS, self._spin)

    def _elapsed(self) -> str:
        e = int(time.time() - self._t0)
        return f"{e // 60}:{e % 60:02d}"

    def _hide(self):
        self._cancel_timer()
        self._cancel_anim()
        self._state = None
        if self._shown:
            try:
                self._g["user32"].ShowWindow(self._hwnd, _SW_HIDE)
            except Exception:
                pass
            self._shown = False

    def _cancel_timer(self):
        if self._timer_job is not None:
            self.root.after_cancel(self._timer_job)
            self._timer_job = None

    def _cancel_anim(self):
        if self._anim_job is not None:
            self.root.after_cancel(self._anim_job)
            self._anim_job = None

    def destroy(self):
        self._cancel_timer()
        self._cancel_anim()
        g = self._g
        try:
            if self._hwnd:
                g["user32"].DestroyWindow(self._hwnd)
                self._hwnd = None
        except Exception:
            pass
        try:
            if self._dib:
                g["gdi32"].SelectObject(self._memdc, self._old_bmp)
                g["gdi32"].DeleteObject(self._dib)
                self._dib = None
        except Exception:
            pass
        try:
            if self._memdc:
                g["gdi32"].DeleteDC(self._memdc)
                self._memdc = None
        except Exception:
            pass


class StatusOverlay:
    """Public pill: the layered-window renderer, or the Tk fallback if it can't.

    Same thread-safe API as before — loading/recording/processing/flash/hide/
    level/destroy, all marshalled onto the Tk loop. `.renderer` says which path
    won ("layered" or "tk"); everything else (H, timer_family, frames, the
    public methods) is forwarded to whichever renderer is live."""

    def __init__(self, root: tk.Tk, config: dict | None = None):
        self.root = root
        self._impl = None
        try:
            self._impl = _LayeredOverlay(root, config)
            self.renderer = "layered"
            _log("overlay: layered-window renderer active")
        except Exception as e:
            self._impl = _TkOverlay(root, config)
            self.renderer = "tk"
            _log(f"overlay: layered renderer unavailable "
                 f"({e.__class__.__name__}: {e}) — Tk colour-key fallback")

    # explicit forwards keep the public signatures stable and obvious
    def loading(self):
        return self._impl.loading()

    def recording(self):
        return self._impl.recording()

    def processing(self):
        return self._impl.processing()

    def flash(self, text: str, ok: bool = True):
        return self._impl.flash(text, ok)

    def hide(self):
        return self._impl.hide()

    def level(self, value: float):
        return self._impl.level(value)

    def destroy(self):
        return self._impl.destroy()

    def __getattr__(self, name):
        # H, timer_family, frames, … live on the chosen renderer
        impl = self.__dict__.get("_impl")
        if impl is None:
            raise AttributeError(name)
        return getattr(impl, name)
