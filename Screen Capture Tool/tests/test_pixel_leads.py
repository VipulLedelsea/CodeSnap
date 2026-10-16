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


def test_a_screenshot_whose_pixel_columns_sit_at_another_origin_is_moved_onto_the_rest():
    same = ["alpha_line_one(1)", "beta_line_two(2)", "gamma_line_three(3)", "delta_line_four(4)", "epsilon_line_five(5)", "zeta_line_six(6)"]
    metas = [{"spacing": {"lead_px": [4, 8, 4, 8, 4, 8]}}, {"spacing": {"lead_px": [4, 8, 4, 8, 4, 8]}},
             {"spacing": {"lead_px": [1, 5, 1, 5, 1, 5]}}]
    parts = ["\n".join(" " * x + l for l, x in zip(same, [4, 8, 4, 8, 4, 8])), "\n".join(" " * x + l for l, x in zip(same, [4, 8, 4, 8, 4, 8])),
             "\n".join(" " * x + l for l, x in zip(same, [1, 5, 1, 5, 1, 5]))]
    out = analysis._align_pixel_frames(parts, metas)
    assert out[2] == parts[0] and metas[2]["spacing"]["lead_px"] == [4, 8, 4, 8, 4, 8]


def test_the_pixel_readings_of_a_line_settle_on_the_clear_majority():
    from core import spacing
    assert spacing._pick_lead([4, 4, 4, 1, 1]) is None          # three against two is not clear
    assert spacing._pick_lead([4, 4, 4, 4, 1]) == 4
    assert spacing._pick_lead([5]) == 5
    assert spacing._pick_lead([5, 2]) is None


def test_a_picture_found_origin_is_moved_onto_the_click_origin_in_free_form_code():
    lines = ["def alpha_function(value):", "    return value + 1", "def beta_function(value):", "    return value + 2"]
    click = {"spacing": {"calibrated": True, "calibration": {"source_x": 30.0, "pitch": 10.0}, "lead_px": [0, 4, 0, 4]}}
    metas = [dict(click), dict(click), dict(click),
             {"spacing": {"calibrated": True, "auto": True, "calibration": {"source_x": 60.0, "pitch": 10.0}, "lead_px": [0, 1, 0, 1]}}]
    parts = ["\n".join(lines)] * 3 + ["\n".join(l if i % 2 == 0 else l for i, l in enumerate(lines))]
    out = analysis._align_auto_frames(parts, metas)
    assert metas[3]["spacing"]["lead_px"] == [3, 4, 3, 4] and out[3].split("\n")[0].startswith("   def")


def test_an_underline_that_touches_red_text_above_it_is_removed_and_the_text_stays():
    rgb = np.zeros((60, 240, 3), dtype=int)
    ink = np.zeros((60, 240), dtype=bool)
    for x0 in range(10, 200, 10):                                # red letters, six pixels wide with gaps, eleven tall
        rgb[10:21, x0:x0 + 6] = (230, 90, 90)
        ink[10:21, x0:x0 + 6] = True
    for x in range(10, 200):                                      # a wavy underline right under them, touching the letters
        y = 25 + int(3 * np.sin(x / 2))
        rgb[y - 1:y + 2, x] = (230, 80, 80)
        ink[y - 1:y + 2, x] = True
    rgb[20:22, 10:200] = (230, 80, 80)                            # and the bridge that joins the two into one component
    ink[20:22, 10:200] = True
    out = colfix._drop_squiggles(rgb, ink)
    assert not out[23:32, 10:200].any()                           # the underline is gone
    assert out[10:19, 12].all() and out[10:19, 52].all()          # the letters are not


def test_a_star_line_of_a_block_comment_is_put_back_one_column_right_of_the_opener():
    text = "/**\n * one\n * two\n * three\n* four\n * five\n */\nx = 1"
    fixed, n = analysis._align_block_comment_stars(text)
    assert fixed.split("\n")[4] == " * four" and n == 1
    assert analysis._align_block_comment_stars("/*\n* a\n* b\n*/")[1] == 0            # too few lines to say what the layout is
