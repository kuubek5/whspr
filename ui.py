# ui.py — floating status pill (Wispr-style bottom bar). Tkinter only.
# Thread-safe: public methods schedule work onto the tk main loop via after().

import time
import tkinter as tk
from tkinter import ttk

TRANSPARENT = "#ff00ff"  # colorkey — never appears in the design

COLORS = {
    "bg": "#1e1e28",
    "text": "#e8e8f0",
    "muted": "#9a9ab0",
    "recording": "#e5484d",
    "processing": "#f0b429",
    "ok": "#46a758",
}


class StatusOverlay:
    """Small always-on-top pill at the bottom-center of the screen."""

    W, H, R = 220, 44, 22

    def __init__(self, root: tk.Tk):
        self.root = root
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", TRANSPARENT)
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        self.win.geometry(f"{self.W}x{self.H}+{(sw - self.W) // 2}+{sh - self.H - 60}")
        self.canvas = tk.Canvas(
            self.win, width=self.W, height=self.H,
            bg=TRANSPARENT, highlightthickness=0,
        )
        self.canvas.pack()
        self._t0 = 0.0
        self._timer_job = None
        self.win.withdraw()

    # ---- public, thread-safe ----
    def recording(self):
        self._t0 = time.time()
        self.root.after(0, self._show_recording)

    def processing(self):
        self.root.after(0, self._show_processing)

    def flash(self, text: str, ok: bool = True):
        self.root.after(0, self._flash, text, ok)

    def hide(self):
        self.root.after(0, self._hide)

    # ---- internals (tk thread only) ----
    def _pill(self):
        c, W, H, R = self.canvas, self.W, self.H, self.R
        c.delete("all")
        c.create_oval(0, 0, 2 * R, H, fill=COLORS["bg"], outline="")
        c.create_oval(W - 2 * R, 0, W, H, fill=COLORS["bg"], outline="")
        c.create_rectangle(R, 0, W - R, H, fill=COLORS["bg"], outline="")

    def _show_recording(self):
        self._cancel_timer()
        self.win.deiconify()
        self._tick()

    def _tick(self):
        self._pill()
        elapsed = int(time.time() - self._t0)
        self.canvas.create_oval(20, 16, 32, 28, fill=COLORS["recording"], outline="")
        self.canvas.create_text(
            42, self.H // 2, anchor="w", fill=COLORS["text"],
            font=("Segoe UI", 11), text=f"Запис  {elapsed // 60}:{elapsed % 60:02d}",
        )
        self._timer_job = self.root.after(500, self._tick)

    def _show_processing(self):
        self._cancel_timer()
        self._pill()
        self.canvas.create_oval(20, 16, 32, 28, fill=COLORS["processing"], outline="")
        self.canvas.create_text(
            42, self.H // 2, anchor="w", fill=COLORS["text"],
            font=("Segoe UI", 11), text="Розпізнаю…",
        )
        self.win.deiconify()

    def _flash(self, text: str, ok: bool):
        self._cancel_timer()
        self._pill()
        color = COLORS["ok"] if ok else COLORS["recording"]
        text = text.replace("\n", " ⏎ ")
        shown = text if len(text) <= 24 else text[:23] + "…"
        self.canvas.create_text(
            20, self.H // 2, anchor="w", fill=color,
            font=("Segoe UI", 11), text=("✓ " if ok else "✗ ") + shown,
        )
        self.win.deiconify()
        self._timer_job = self.root.after(1500, self._hide)

    def _hide(self):
        self._cancel_timer()
        self.win.withdraw()

    def _cancel_timer(self):
        if self._timer_job is not None:
            self.root.after_cancel(self._timer_job)
            self._timer_job = None
