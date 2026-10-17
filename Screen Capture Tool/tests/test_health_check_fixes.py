"""Fixes found by re-stitching saved program batch-test-10-09 against its originals."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.analysis import _agrees_above, _strip_md_headers, _stitch_two
from core.spacing import _same_line_shape, _squeeze_dashes


def test_banner_title_comment_is_kept_next_to_a_short_code_line():
    text = "x = 1\n)\n# Token refresh  (POST /auth/refresh)\ny = 2"
    assert "# Token refresh  (POST /auth/refresh)" in _strip_md_headers(text)


def test_header_that_repeats_a_real_code_line_is_still_dropped():
    text = "# user.failed_login_count += 1\nuser.failed_login_count += 1"
    assert "# user.failed" not in _strip_md_headers(text)


def test_separator_comments_with_different_dashes_are_the_same_line():
    assert _squeeze_dashes("# ── Core ────") == "# - Core -"
    assert _same_line_shape("# — Rate limiting ——————", "# ── Rate limiting ───────────────────")
    assert not _same_line_shape("# Rate limiting", "def other_function():")


def test_one_misread_blank_row_does_not_break_the_overlap_check():
    above = [f"    line_{i} = {i}" for i in range(8)]
    merged = above[:4] + [""] + above[4:] + ["tail_a()", "tail_b()", "tail_c()"]
    b = above + ["tail_a()", "tail_b()", "tail_c()", "after()"]
    assert _agrees_above(merged, len(merged) - 3, b, len(above))
    assert _stitch_two(merged, b) is not None


def test_a_different_routine_above_the_overlap_still_disagrees():
    merged = [f"alpha_{i}()" for i in range(8)] + ["", "tail_a()", "tail_b()", "tail_c()"]
    b = [f"beta_{i}()" for i in range(8)] + ["tail_a()", "tail_b()", "tail_c()"]
    assert not _agrees_above(merged, 9, b, 8)


def test_banners_with_different_dashes_overlap_as_one_line():
    from core.analysis import _sim
    assert _sim("# — Time limits ———————————————————", "# --- Time limits ------------------------") >= 0.9
    assert _sim("# — Time limits ———————————", "# — Result backend ———————————") < 0.7
    assert _sim("x = a --- b", "y = c --- d") < 0.9


def test_a_row_read_as_a_copy_of_its_neighbour_is_replaced_by_the_line_the_other_screens_show():
    from core.analysis import _repair_doubled_lines
    shown = ["<td>", "{app.submitted_at", "? new Date(app.submitted_at)", 'month: "short",', "</td>"]
    final = "\n".join(["<td>", "{app.submitted_at", "{app.submitted_at", 'month: "short",', "</td>"])
    fixed, at = _repair_doubled_lines(final, ["\n".join(shown), "\n".join(shown)])
    assert fixed.split("\n")[2] == "? new Date(app.submitted_at)" and at == [3]


def test_a_line_the_file_really_repeats_is_not_replaced():
    from core.analysis import _repair_doubled_lines
    shown = ["<td>", "print(total_amount)", "print(total_amount)", "</td>"]
    final = "\n".join(shown)
    assert _repair_doubled_lines(final, ["\n".join(shown), "\n".join(shown)]) == (final, [])


def test_dash_lines_the_pixels_cannot_settle_are_flagged_even_when_verified():
    from core.verify import _dash_glyph_doubt, summarize
    assert _dash_glyph_doubt("# ----------------------------------------------")
    assert _dash_glyph_doubt('errors.fiscal_year = "Enter a valid fiscal year (2000-2099).";')
    assert _dash_glyph_doubt(" * 1. Program Selection – aid program")
    assert _dash_glyph_doubt('msg = "range $5,000-$20,000"')
    assert _dash_glyph_doubt("# Stale ID - clean it up")
    assert not _dash_glyph_doubt('created = "2026-10-01"')
    assert not _dash_glyph_doubt("total = a - b")
    code = 'x = 1\ny = "pages 5-9"'
    out = summarize(code, {"x = 1": "verified", 'y = "pages 5-9"': "verified"})
    assert [f["line"] for f in out["flags"]] == [2]
