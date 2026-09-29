"""Screen capture helpers — shared by hotkey_capture.py and the agent's tools.

Full-screen via mss; region via macOS `screencapture -i` (native crosshair).
Both return PNG bytes.
"""

import io
import os
import subprocess
import tempfile

MAX_CAPTURE_PX = 1568  # cap the long side; images above this cost more tokens for no gain


def _native_resolution():
    """mss on macOS grabs at 'nominal' (1x) resolution by default, so on a Retina screen code is captured at half
    its real pixel density and small fonts become hard to read. Drop that flag so region captures keep full detail."""
    try:
        import mss.darwin as _d
        _d.IMAGE_OPTIONS = _d.kCGWindowImageBoundsIgnoreFraming | _d.kCGWindowImageShouldBeOpaque
    except Exception:  # noqa: BLE001 - not macOS, or an mss without this switch
        pass


_native_resolution()


LAST = {"native": None, "saved": None, "scale": 1.0, "display": None, "points": None}


def _downscale_png(data: bytes, max_px: int = MAX_CAPTURE_PX) -> bytes:
    """Shrink a PNG so its longest side <= max_px (keeps aspect). Cuts image tokens."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        w, h = img.size
        longest = max(w, h)
        LAST.update(native=(w, h), saved=(w, h), scale=1.0)
        if longest <= max_px:
            return data
        scale = max_px / longest
        LAST.update(saved=(int(w * scale), int(h * scale)), scale=scale)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001 - never let resizing break a capture
        return data


_DISPLAY = None   # mss monitor index (1 = primary); None = CODESNAP_DISPLAY, else the display under the mouse


def displays() -> list:
    """Every attached display with its size in points and pixels (pixels differ on Retina / scaled screens)."""
    import mss
    out = []
    with mss.mss() as sct:
        for i, m in enumerate(sct.monitors[1:], 1):
            try:
                px = sct.grab({"left": m["left"], "top": m["top"], "width": 1, "height": 1}).size
                scale = px[0] or 1
            except Exception:  # noqa: BLE001
                scale = 1
            out.append({"index": i, "left": m["left"], "top": m["top"], "width": m["width"], "height": m["height"],
                        "scale": scale, "pixels": [m["width"] * scale, m["height"] * scale], "primary": i == 1})
    return out


def _cursor_display(monitors) -> int:
    try:
        from pynput.mouse import Controller
        x, y = Controller().position
        for i, m in enumerate(monitors[1:], 1):
            if m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]:
                return i
    except Exception:  # noqa: BLE001 - no mouse access: fall back to the primary display
        pass
    return 1


def pick_display(choice=None) -> int:
    """Fix the display for this capture session: an explicit index, CODESNAP_DISPLAY, or the one under the mouse."""
    global _DISPLAY
    import mss
    with mss.mss() as sct:
        mons = sct.monitors
        raw = choice if choice not in (None, "", "auto") else os.environ.get("CODESNAP_DISPLAY")
        try:
            idx = int(raw) if raw not in (None, "", "auto") else _cursor_display(mons)
        except ValueError:
            idx = _cursor_display(mons)
        _DISPLAY = idx if 1 <= idx < len(mons) else 1
    return _DISPLAY


def _monitor(sct):
    idx = _DISPLAY or 1
    mons = sct.monitors
    m = mons[idx] if 1 <= idx < len(mons) else mons[1]
    LAST.update(display=idx if 1 <= idx < len(mons) else 1, points=(m["width"], m["height"]))
    return m


def clarity_warning() -> str | None:
    """Plain-English warning when the last capture had to be shrunk so much that small text may be misread."""
    if LAST["scale"] >= 0.75 or not LAST["native"]:
        return None
    return (f"This screen is large ({LAST['native'][0]}x{LAST['native'][1]} px), so each capture is shrunk to "
            f"{round(LAST['scale'] * 100)}% and small text may be misread. Use Pick code area (or zoom the editor) "
            f"for sharper text.")


def capture_full_png() -> bytes:
    """Full-screen capture of the session's display via mss -> PNG bytes."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        raw = sct.grab(_monitor(sct))
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
        mon = _monitor(sct)
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
