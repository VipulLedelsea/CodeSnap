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


def test_a_skipped_row_is_put_back_when_two_screens_show_it_with_the_same_context():
    from core.analysis import _restore_skipped_lines
    shown = ["<StatCard", "  icon={x}", '  label="Total"', "  value={n}", "  sub={s}"]
    skipped = [r for r in shown if "label" not in r]
    fixed, at = _restore_skipped_lines("\n".join(["<StatCard"] + skipped[1:]), ["\n".join(shown), "\n".join(shown)])
    assert fixed.split("\n")[2].strip() == 'label="Total"' and at == [3]


def test_a_skipped_row_is_not_put_back_on_one_reading_or_for_a_bare_bracket():
    from core.analysis import _restore_skipped_lines
    shown = ["a = 1", "b = 2", "c = 3", "d = 4", "e = 5"]
    short = ["a = 1", "b = 2", "d = 4", "e = 5"]
    assert _restore_skipped_lines("\n".join(short), ["\n".join(shown)])[1] == []
    brackets = ["x = 1", "y = 2", "))}", "z = 3", "w = 4"]
    assert _restore_skipped_lines("\n".join(["x = 1", "y = 2", "z = 3", "w = 4"]), ["\n".join(brackets)] * 2)[1] == []


def test_a_real_nested_closing_tag_is_not_collapsed_or_replaced():
    from core.analysis import _repair_doubled_lines
    shown = ["<p>text</p>", "</div>", "</div>", "<p>more</p>"]
    final = "\n".join(shown)
    assert _repair_doubled_lines(final, ["\n".join(shown)] * 3) == (final, [])


def test_a_duplicated_assignment_gives_way_to_the_one_line_another_screen_shows():
    from core.analysis import _repair_doubled_lines
    right = ['REQ = "r"', 'FUL = "f"', 'PAY = "p"', 'SCH = "s"']
    final = "\n".join(['REQ = "r"', 'PAY = "p"', 'PAY = "p"', 'SCH = "s"'])
    fixed, at = _repair_doubled_lines(final, ["\n".join(right), "\n".join(['REQ = "r"', 'PAY = "p"', 'PAY = "p"', 'SCH = "s"'])])
    assert fixed.split("\n")[1] == 'FUL = "f"' and at == [2]


def test_a_sideways_join_ignores_a_match_far_from_the_rest_of_the_screen():
    from core.verify import sideways_merge_ex
    merged = [f"    row_{i:03d} = compute({i}) + another_value_{i}" for i in range(120)]
    merged[5] = "    onChange={(e) =>"
    view = [f"row_{i:03d} = compute({i}) + another_value_{i}"[4:] for i in range(60, 70)]
    view.insert(0, "onChange={(e) => setApprovedAmount(e.target.value)}")
    got = sideways_merge_ex(merged, view, force=True)
    assert got is None or got[0][5] == "    onChange={(e) =>"


def test_the_capped_flag_list_drops_dash_doubts_before_real_mismatches():
    from core.verify import MAX_FLAGS, summarize
    lines = ["# " + "-" * 20] * 0
    code = "\n".join([f'x{i} = "a-b {i}-{i + 1}"' for i in range(MAX_FLAGS + 10)] + ["broken = 1"])
    statuses = {l: "verified" for l in code.split("\n")}
    statuses["broken = 1"] = "mismatch"
    out = summarize(code, statuses)
    assert len(out["flags"]) == MAX_FLAGS
    assert any(f["text"] == "broken = 1" for f in out["flags"])
    assert out["flagged"] == MAX_FLAGS + 11


def test_a_closing_pair_stitched_in_twice_is_collapsed_only_on_a_clear_majority():
    from core.analysis import _collapse_doubled_lines
    shown = ["<dd>x</dd>", "</div>", ");", "return (", "<div>"]
    doubled = ["<dd>x</dd>", "</div>", ");", "</div>", ");", "return (", "<div>"]
    fixed, dropped = _collapse_doubled_lines("\n".join(doubled), ["\n".join(shown)] * 3)
    assert fixed.split("\n") == shown and dropped == [4, 5]
    # one screen showing it once against one showing it twice is not enough
    kept, none = _collapse_doubled_lines("\n".join(doubled), ["\n".join(shown), "\n".join(doubled)])
    assert none == [] and kept.split("\n") == doubled
