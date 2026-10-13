"""A row clipped by the top or bottom of a screenshot must not discard the frame's measured margin."""
from core.analysis import _left_edge_cut

BODY = "\n".join(f"       LINE {i}" for i in range(12))


def test_a_row_clipped_at_the_top_or_bottom_is_not_a_left_edge_cut():
    assert not _left_edge_cut("       [CUT OFF]\n" + BODY)
    assert not _left_edge_cut("first row\n       [CUT OFF]\n" + BODY)
    assert not _left_edge_cut(BODY + "\n            [CUT OFF]")


def test_a_bare_marker_in_the_middle_still_counts_as_a_left_edge_cut():
    rows = BODY.split("\n")
    rows.insert(6, "   [CUT OFF]")
    assert _left_edge_cut("\n".join(rows))


def test_an_end_of_line_marker_is_never_a_left_edge_cut():
    assert not _left_edge_cut(BODY + "\n      MOVE X TO Y[CUT OFF]")
