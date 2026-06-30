"""Screen capture helpers — shared by hotkey_capture.py and the agent's tools.

Full-screen via mss; region via macOS `screencapture -i` (native crosshair).
Both return PNG bytes.
"""

import io
import os
import subprocess
import tempfile


def capture_full_png() -> bytes:
    """Full primary-screen capture via mss -> PNG bytes."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        raw = sct.grab(sct.monitors[1])  # [1] = primary display ([0] = all combined)
    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


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
            return f.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def next_png_path(session_dir):
    """Next free NNN.png in session_dir (so concurrent capturers don't collide)."""
    from pathlib import Path
    session_dir = Path(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    n = 1
    while (session_dir / f"{n:03d}.png").exists():
        n += 1
    return session_dir / f"{n:03d}.png"
