"""Watch the floating status pill cycle through every state: python tools/overlay_demo.py [position] [scale]."""

import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import StatusOverlay  # noqa: E402


def main() -> None:
    pos = sys.argv[1] if len(sys.argv) > 1 else "bottom-center"
    if "," in pos:  # free coordinate, e.g. "25,75" = 25% / 75% of the free space
        x, y = pos.split(",")
        pos = {"x": float(x), "y": float(y)}
    scale = int(sys.argv[2]) if len(sys.argv) > 2 else 100

    root = tk.Tk()
    root.withdraw()
    pill = StatusOverlay(root, {"overlay_position": pos, "overlay_scale": scale})
    print(f"pill: position={pos} scale={scale}% height={pill.H}px "
          f"timer font={pill.timer_family}")

    # each step is (delay from the previous step in ms, what to do)
    steps = [
        (0, lambda: pill.loading()),
        (2500, lambda: pill.recording()),
        (6000, lambda: pill.processing()),
        (2500, lambda: pill.flash("Привіт! Це KuubWave, локальна диктовка", True)),
        (2600, lambda: pill.processing()),
        (1500, lambda: pill.flash("тихо в мікрофоні", False)),
        (2600, lambda: pill.hide()),
        (1200, lambda: root.destroy()),
    ]
    t = 0
    for delay, fn in steps:
        t += delay
        root.after(t, fn)
    root.mainloop()


if __name__ == "__main__":
    main()
