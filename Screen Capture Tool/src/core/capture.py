"""Screen capture helpers — shared by hotkey_capture.py and the agent's tools.

Full-screen via mss; region via macOS `screencapture -i` (native crosshair).
Both return PNG bytes.
"""

import io
import os
import subprocess
import tempfile

MAX_CAPTURE_PX = 1568  # cap the long side; images above this cost more tokens for no gain


def _downscale_png(data: bytes, max_px: int = MAX_CAPTURE_PX) -> bytes:
    """Shrink a PNG so its longest side <= max_px (keeps aspect). Cuts image tokens."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        w, h = img.size
        longest = max(w, h)
        if longest <= max_px:
            return data
        scale = max_px / longest
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001 - never let resizing break a capture
        return data


def capture_full_png() -> bytes:
    """Full primary-screen capture via mss -> PNG bytes."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        raw = sct.grab(sct.monitors[1])  # [1] = primary display ([0] = all combined)
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return _downscale_png(buf.getvalue())


def capture_region_png() -> "bytes | None":
    """Interactive region capture via macOS `screencapture -i`.

    Native crosshair; user drags a box. Returns PNG bytes, or None if cancelled.
    """
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    subprocess.run(["screencapture", "-i", "-x", path])  # -i interactive, -x silent
    try:
        if os.path.getsize(path) == 0:
            return None  # cancelled
        with open(path, "rb") as f:
            return _downscale_png(f.read())
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def capture_region_fixed(fracs) -> bytes:
    """Grab a fixed sub-rectangle of the primary screen, given as fractions
    (left, top, width, height) in 0..1 of the screen. Used by region-locked burst
    so scrolling code registers as change and off-code chrome (Zoom tiles, side
    panels) is excluded. Fractions keep it resolution-independent."""
    import mss
    from PIL import Image
    left, top, width, height = fracs
    with mss.mss() as sct:
        mon = sct.monitors[1]
        box = {
            "left": mon["left"] + int(left * mon["width"]),
            "top": mon["top"] + int(top * mon["height"]),
            "width": max(1, int(width * mon["width"])),
            "height": max(1, int(height * mon["height"])),
        }
        raw = sct.grab(box)
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return _downscale_png(buf.getvalue())


def next_png_path(session_dir):
    """Next free NNN.png in session_dir (so concurrent capturers don't collide)."""
    from pathlib import Path
    session_dir = Path(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    n = 1
    while (session_dir / f"{n:03d}.png").exists():
        n += 1
    return session_dir / f"{n:03d}.png"
