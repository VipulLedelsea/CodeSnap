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
    assert _squeeze_dashes("# ── Core ────") == "#-Core-"
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
