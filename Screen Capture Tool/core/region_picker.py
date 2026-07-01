"""Standalone region picker — run as a subprocess so its GUI owns the main thread.

Shows a translucent full-screen overlay; the user drags a rectangle. Prints the
selected region as JSON {top,left,width,height} in PHYSICAL pixels (Retina-aware)
on the last stdout line, then exits.

Run:  python core/region_picker.py   (normally invoked via core.capture.pick_region)
"""

import json
import sys


def main() -> int:
    try:
        import tkinter as tk
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: tkinter unavailable: {exc}", file=sys.stderr)
        return 1

    # Physical-pixel size (Retina) vs logical points, to scale tkinter coords.
    scale = 1.0
    offset_x = offset_y = 0
    try:
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[1]
        root_probe = tk.Tk(); root_probe.withdraw()
        logical_w = root_probe.winfo_screenwidth()
        root_probe.destroy()
        if logical_w:
            scale = mon["width"] / logical_w
        offset_x, offset_y = mon.get("left", 0), mon.get("top", 0)
    except Exception:  # noqa: BLE001 - fall back to 1x, no offset
        pass

    sel = {}
    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.configure(bg="gray12")
    root.attributes("-topmost", True)
    canvas = tk.Canvas(root, cursor="cross", bg="gray12", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_text(60, 30, anchor="w", fill="white",
                       text="Drag to select the region to capture  (Esc to cancel)")
    # On macOS, transparency must be applied AFTER the window is realized.
    root.update_idletasks()
    try:
        root.wait_visibility(root)
        root.wm_attributes("-alpha", 0.30)
    except Exception:  # noqa: BLE001
        pass
    start = {}
    rect_id = [None]

    def on_press(e):
        start["x"], start["y"] = e.x, e.y
        rect_id[0] = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="red", width=2)

    def on_drag(e):
        if rect_id[0] is not None:
            canvas.coords(rect_id[0], start["x"], start["y"], e.x, e.y)

    def on_release(e):
        x1, y1 = min(start["x"], e.x), min(start["y"], e.y)
        x2, y2 = max(start["x"], e.x), max(start["y"], e.y)
        sel.update({
            "left": int(offset_x + x1 * scale),
            "top": int(offset_y + y1 * scale),
            "width": max(1, int((x2 - x1) * scale)),
            "height": max(1, int((y2 - y1) * scale)),
        })
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", lambda e: root.destroy())
    root.mainloop()

    if not sel:
        print("CANCELLED")
        return 1
    print(json.dumps(sel))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
