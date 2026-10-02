"""Transcription quality: how sensitive the pixel check is, and that it never vouches for a wrong line (no API calls).

Code is drawn to a PNG (tests/render.py) at several font sizes, dark and light, with and without line numbers, then a
known error is put into the text and the check is run. For every kind of error the rule is the same: the line is
flagged or left unchecked, never marked verified. Real captures (tests/real) are then used to prove the newer checks
raise no false alarms on real editor screenshots.

Known limits, asserted so they stay visible: a same-length wrong character (O for 0) and two same-shape lines swapped
pass the pixel check. Those are caught later by the compile check and the line-by-line code review, not here.
"""
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import colfix, verify
from core.analysis import verify_screenshot
from core.colfix import respace
from render import render_code

LINES = [f"       MOVE WS-FIELD-{i:02d} TO OUT-FIELD-{i:02d}." if i % 3 else
         f"       COMPUTE WS-TOTAL-{i} = WS-A + WS-B * {i}." for i in range(1, 27)]
TEXT = "\n".join(LINES)
DARK = {}
LIGHT = {"bg": (250, 250, 250), "fg": (30, 30, 30), "gutter_fg": (150, 150, 150)}
LOOKS = [pytest.param(fs, theme, num, id=f"{fs}px-{name}{'-numbers' if num else ''}")
         for fs in (12, 14, 18, 22) for name, theme in (("dark", DARK), ("light", LIGHT)) for num in (False, True)]


def check(tmp_path, fs, theme, num, text):
    png = render_code(TEXT, tmp_path / "s.png", font_size=fs, line_numbers=num, **theme)
    return colfix.check(png, text)["status"]


def edit(i, new):
    return "\n".join(LINES[:i] + ([new] if new is not None else []) + LINES[i + 1:])


@pytest.mark.parametrize("fs,theme,num", LOOKS)
def test_perfect_text_is_verified_line_by_line(tmp_path, fs, theme, num):
    st = check(tmp_path, fs, theme, num, TEXT)
    assert Counter(st) == {"verified": len(LINES)}


@pytest.mark.parametrize("fs,theme,num", LOOKS)
@pytest.mark.parametrize("kind,i,new", [
    ("dropped character", 4, LINES[4].replace("WS-FIELD-05", "WS-FIEL-05")),
    ("added character", 7, LINES[7].replace("OUT-FIELD-08", "OUT-FIELDS-08")),
    ("dropped word", 10, LINES[10].replace(" TO", "")),
    ("added word", 13, LINES[13].replace("MOVE", "MOVE ALL")),
    ("two lines joined", 16, LINES[16] + " " + LINES[17].strip()),
])
def test_a_wrong_line_is_flagged_never_verified(tmp_path, fs, theme, num, kind, i, new):
    text = edit(i, new)
    if kind == "two lines joined":
        text = "\n".join(LINES[:16] + [new] + LINES[18:])
    st = check(tmp_path, fs, theme, num, text)
    assert st[i] != "verified", kind
    assert st[i] in ("mismatch", "rows", "unchecked")


@pytest.mark.parametrize("fs,theme,num", LOOKS)
def test_a_skipped_line_is_flagged_on_the_line_after_it(tmp_path, fs, theme, num):
    st = check(tmp_path, fs, theme, num, edit(10, None))
    assert st[10] == "rows"                                    # LINES[11] now sits where LINES[10] was
    assert Counter(st)["verified"] == len(LINES) - 2


@pytest.mark.parametrize("fs,theme,num", LOOKS)
def test_an_invented_line_is_flagged_never_verified(tmp_path, fs, theme, num):
    text = "\n".join(LINES[:10] + ["       MOVE ZERO TO WS-X."] + LINES[10:])
    st = check(tmp_path, fs, theme, num, text)
    assert st[10] == "rows"


def test_blank_lines_are_neither_verified_nor_flagged(tmp_path):
    lines = LINES[:5] + [""] + LINES[5:]
    png = render_code("\n".join(lines), tmp_path / "s.png", font_size=14)
    st = colfix.check(png, "\n".join(lines))["status"]
    assert st[5] == "" and Counter(st)["verified"] == len(LINES)


def test_cut_off_lines_are_marked_cut_and_do_not_raise_a_line_count_flag(tmp_path):
    png = render_code(TEXT, tmp_path / "s.png", font_size=14)
    text = edit(8, LINES[8][:20] + " [CUT OFF]")
    st = colfix.check(png, text)["status"]
    assert st[8] == "cut" and "rows" not in st


def test_the_check_is_repeatable(tmp_path):
    png = render_code(TEXT, tmp_path / "s.png", font_size=14)
    text = edit(4, LINES[4].replace("WS-FIELD-05", "WS-FIEL-05"))
    assert colfix.check(png, text) == colfix.check(png, text)


def test_known_limit_same_length_wrong_character_passes_the_pixel_check(tmp_path):
    """The pixels give word lengths and columns, not letters: O for 0 is caught by the compile check or the review."""
    st = check(tmp_path, 14, DARK, False, edit(4, LINES[4].replace("05", "O5")))
    assert st[4] == "verified"


def test_known_limit_two_same_shape_lines_swapped_pass_the_pixel_check(tmp_path):
    text = "\n".join(LINES[:3] + [LINES[4], LINES[3]] + LINES[5:])
    st = check(tmp_path, 14, DARK, False, text)
    assert st[3] == st[4] == "verified"


def test_a_screenshot_without_a_character_grid_leaves_lines_unchecked(tmp_path):
    from PIL import Image
    png = tmp_path / "blank.png"
    Image.new("RGB", (400, 300), (255, 255, 255)).save(png)
    out = colfix.check(png, TEXT)
    assert not out["grid"] and set(out["status"]) == {"unchecked"}


def test_the_line_count_flag_is_explained_and_asks_for_the_part_again():
    s = verify.summarize("a\nb", {"a": "verified", "b": "rows"})
    assert s["flagged"] == 1 and "different number of lines" in s["flags"][0]["reason"]
    from core import deepdive
    assert "rows" in deepdive.ADVICE and "missing or extra" in deepdive.REPORT_REASON["rows"]
    assert not any(w in deepdive.REPORT_REASON["rows"] for w in ("screen", "captur", "scan"))


# ── real captures: the new line-count check must not cry wolf ──────────────────────────────────────────────────────

REAL = Path(__file__).resolve().parent / "real"
CASES = sorted(p for p in REAL.glob("2*/*") if (p / "case.json").exists())


@pytest.mark.parametrize("case", CASES, ids=[f"{p.parent.name.split('-')[-1]}/{p.name}" for p in CASES])
def test_real_screens_raise_no_false_line_count_flags(case):
    meta = json.loads((case / "case.json").read_text())
    truth = [l.strip() for l in (case / meta["truth"]).read_text().splitlines() if l.strip()]
    pairs = set(zip(truth, truth[1:]))
    false = []
    for png in sorted(case.glob("*.png")):
        text, _ = respace(png, png.with_suffix(".txt").read_text())
        v = verify_screenshot(None, png, text)
        lines = v["text"].split("\n")
        nb = [j for j, l in enumerate(lines) if l.strip()]
        for k, j in enumerate(nb):
            if v["status"][j] == "rows" and k and (lines[nb[k - 1]].strip(), lines[j].strip()) in pairs:
                false.append(f"{png.name}:{j + 1}")
    assert not false, false
