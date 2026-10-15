import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from core import analysis, colfix  # noqa: E402
from render import render_code  # noqa: E402

TEXT = ["class A:", "    def f(self):", "        return 1", "", "    def g(self):", "        return 2", "x = A()", "y = x.f()",
        "z = x.g()", "print(y, z)", "if y:", "    print(y)", "    print(z)", "else:", "    pass"]


def test_every_line_gets_its_leading_column_from_the_pixels_even_when_its_words_are_misread(tmp_path):
    png = render_code("\n".join(TEXT), tmp_path / "x.png")
    sx = colfix._measure(png, "\n".join(TEXT))
    assert sx is not None
    origin = (-sx["base"] + sx["offset"]) * sx["pitch"]          # pixel position of column one on this rendering
    misread = [l.replace("print", "prlnt") if "print" in l else l for l in TEXT]
    got = colfix.leads(png, "\n".join(misread), source_x=origin)
    want = [len(l) - len(l.lstrip()) if l.strip() else None for l in TEXT]
    assert got == want


def test_red_wavy_underlines_are_removed_but_text_and_straight_rules_stay():
    rgb = np.zeros((60, 200, 3), dtype=int)
    ink = np.zeros((60, 200), dtype=bool)
    for x in range(10, 150):                                     # a wavy red underline, five pixels tall
        y = 40 + int(2 * np.sin(x / 2))
        rgb[y - 1:y + 2, x] = (230, 80, 80)
        ink[y - 1:y + 2, x] = True
    rgb[10:22, 20:28] = (230, 80, 80)                            # a red letter
    ink[10:22, 20:28] = True
    rgb[20:22, 60:150] = (230, 80, 80)                           # a straight red divider
    ink[20:22, 60:150] = True
    out = colfix._drop_squiggles(rgb, ink)
    assert not out[36:46, 10:150].any()
    assert out[10:22, 20:28].all() and out[20:22, 60:150].all()


def test_the_click_error_is_taken_off_when_no_line_sits_at_the_margin():
    leads = [1, 5, 5, 9, 5, 1, 1, 5, 9, 13] * 3
    metas = [{"spacing": {"lead_px": list(leads)}}]
    assert analysis._pixel_margin(metas) == 1
    assert min(metas[0]["spacing"]["lead_px"]) == 0
    assert analysis._pixel_margin([{"spacing": {"lead_px": [0] * 20 + [4] * 20}}]) == 0
