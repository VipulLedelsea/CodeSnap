"""Render source code to a PNG (for the accuracy harness).

Uses Pillow + a monospace font to draw plain code on a flat background — a
controllable stand-in for an editor screenshot. Optional line numbers let us
test that extraction ignores gutter chrome.
"""

from pathlib import Path

# Common monospace fonts across macOS / Linux; falls back to PIL's default.
_FONT_CANDIDATES = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
    "/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/Library/Fonts/Courier New.ttf",
]


def _load_font(size: int):
    from PIL import ImageFont
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_code(
    text: str,
    out_path,
    font_size: int = 22,
    line_numbers: bool = False,
    padding: int = 28,
    bg=(30, 30, 34),
    fg=(222, 224, 228),
    gutter_fg=(120, 124, 132),
):
    """Render `text` to a PNG at out_path. Returns the Path."""
    from PIL import Image, ImageDraw

    font = _load_font(font_size)
    lines = text.splitlines() or [""]

    # Measure with a dummy canvas.
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    char_w = probe.textlength("M", font=font) or font_size * 0.6
    line_h = int(font_size * 1.5)

    gutter_w = int(char_w * (len(str(len(lines))) + 2)) if line_numbers else 0
    max_chars = max((len(ln) for ln in lines), default=1)
    width = int(padding * 2 + gutter_w + char_w * max(max_chars, 1)) + 4
    height = padding * 2 + line_h * len(lines)

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        y = padding + i * line_h
        x = padding
        if line_numbers:
            draw.text((x, y), str(i + 1).rjust(len(str(len(lines)))), font=font, fill=gutter_fg)
            x += gutter_w
        draw.text((x, y), ln, font=font, fill=fg)

    out_path = Path(out_path)
    img.save(out_path, format="PNG")
    return out_path
