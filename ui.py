# ui.py — floating status pill (Wispr-style bottom bar). Tkinter only.
# Thread-safe: public methods schedule work onto the tk main loop via after().
#
# Uses a magenta color-key (-transparentcolor) for true rounded transparency —
# something WebView2 can't do on Windows, which is why the pill lives in Tk even
# when the main window runs under pywebview. Positioned with winfo_screen* so it
# lands dead-centre at the screen bottom regardless of DPI scaling.

import time
import tkinter as tk
import tkinter.font as tkfont

TRANSPARENT = "#ff00ff"  # colorkey — never appears in the design

# new design palette (mirrors web/index.html)
COLORS = {
    "bg": "#16161C",
    "text": "#F2F2F5",
    "muted": "#9B9BA5",
    "accent": "#F0555C",
    "green": "#4CAF6D",
}


class StatusOverlay:
    """Small always-on-top pill at the bottom-center of the screen.

    Hidden while idle; appears for loading / recording / processing and flashes
    the result before hiding again."""

    H, R, MARGIN = 44, 22, 60
    PAD_L, DOT, GAP, PAD_R = 20, 9, 11, 20

    def __init__(self, root: tk.Tk):
        self.root = root
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", TRANSPARENT)
        self.font = tkfont.Font(family="Segoe UI", size=11)
        self.canvas = tk.Canvas(self.win, height=self.H,
                                bg=TRANSPARENT, highlightthickness=0)
        self.canvas.pack()
        self._t0 = 0.0
        self._timer_job = None
        self.win.withdraw()

    # ---- public, thread-safe ----
    def loading(self):
        self.root.after(0, self._render, COLORS["muted"], "Завантаження моделі…",
                        COLORS["muted"])

    def recording(self):
        self._t0 = time.time()
        self.root.after(0, self._show_recording)

    def processing(self):
        self.root.after(0, self._render, COLORS["muted"], "Розпізнаю…",
                        COLORS["muted"])

    def flash(self, text: str, ok: bool = True):
        self.root.after(0, self._flash, text, ok)

    def hide(self):
        self.root.after(0, self._hide)

    # ---- internals (tk thread only) ----
    def _pill(self, w: int):
        c, H, R = self.canvas, self.H, self.R
        c.delete("all")
        c.create_oval(0, 0, 2 * R, H, fill=COLORS["bg"], outline="")
        c.create_oval(w - 2 * R, 0, w, H, fill=COLORS["bg"], outline="")
        c.create_rectangle(R, 0, w - R, H, fill=COLORS["bg"], outline="")

    def _render(self, dot_color, text, text_color, dot=True):
        """Size the pill to its content, recenter it, draw dot + text."""
        tw = self.font.measure(text)
        x = self.PAD_L
        w = self.PAD_L + (self.DOT + self.GAP if dot else 0) + tw + self.PAD_R
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        self.win.geometry(f"{w}x{self.H}+{(sw - w) // 2}+{sh - self.H - self.MARGIN}")
        self.canvas.config(width=w)
        self._pill(w)
        cy = self.H // 2
        if dot:
            r = self.DOT // 2
            self.canvas.create_oval(x, cy - r, x + self.DOT, cy + r,
                                    fill=dot_color, outline="")
            x += self.DOT + self.GAP
        self.canvas.create_text(x, cy, anchor="w", fill=text_color,
                                font=self.font, text=text)
        self.win.deiconify()

    def _show_recording(self):
        self._cancel_timer()
        self._tick()

    def _tick(self):
        elapsed = int(time.time() - self._t0)
        self._render(COLORS["accent"],
                     f"Запис  {elapsed // 60}:{elapsed % 60:02d}",
                     COLORS["text"])
        self._timer_job = self.root.after(500, self._tick)

    def _flash(self, text: str, ok: bool):
        self._cancel_timer()
        text = text.replace("\n", " ⏎ ")
        shown = text if len(text) <= 30 else text[:29] + "…"
        color = COLORS["green"] if ok else COLORS["accent"]
        self._render(color, ("✓ " if ok else "✗ ") + shown, COLORS["text"],
                     dot=False)
        self._timer_job = self.root.after(1800, self._hide)

    def _hide(self):
        self._cancel_timer()
        self.win.withdraw()

    def _cancel_timer(self):
        if self._timer_job is not None:
            self.root.after_cancel(self._timer_job)
            self._timer_job = None
