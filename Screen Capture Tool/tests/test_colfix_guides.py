"""Editor indent guides (thin vertical lines through the code) must not be read as text ink."""
import numpy as np

from core import colfix


def _screen(rows=12, row_h=14, gap=8, width=300):
    ink = np.zeros((rows * (row_h + gap), width), dtype=bool)
    tops = [i * (row_h + gap) + 4 for i in range(rows)]
    for t in tops:
        ink[t:t + 10, 60:70] = True          # a glyph on every row, starting at x=60
    return ink, tops


def test_a_one_pixel_guide_through_many_rows_is_removed_and_the_glyphs_stay():
    ink, tops = _screen()
    ink[:, 47] = True                         # the guide, continuous through the gaps between rows
    out = colfix._drop_guides(ink)
    assert not out[:, 47].any()
    for t in tops:
        assert out[t:t + 10, 60:70].all()


def test_the_first_ink_of_each_row_is_the_glyph_not_the_guide():
    ink, tops = _screen()
    ink[:, 47] = True
    rows = colfix._rows(colfix._drop_guides(ink))
    assert len(rows) == 12 and all(r[0][0] == 60 for r in rows)
    assert len(colfix._rows(ink)) < 12        # without the filter the guide fuses the rows into one band and they are lost


def test_short_strokes_and_stacked_pipe_characters_are_not_guides():
    ink, tops = _screen()
    for t in tops[:3]:
        ink[t:t + 12, 100] = True             # a vertical bar glyph taller than a letter: one row only
    out = colfix._drop_guides(ink)
    assert out[tops[0]:tops[0] + 12, 100].all()
    pipes = np.zeros((300, 60), dtype=bool)
    for t in range(0, 280, 22):
        pipes[t:t + 14, 20] = True            # a column of '|' with a gap between rows
    assert colfix._drop_guides(pipes).sum() == pipes.sum()


def test_a_thick_rule_is_kept():
    ink, _ = _screen()
    ink[:, 200:204] = True                    # four pixels wide: a scrollbar or border, not a guide
    assert colfix._drop_guides(ink)[:, 200:204].all()


def _clicked(n):
    return [{"spacing": {"calibrated": True}} for _ in range(n)]


def test_a_real_click_offset_that_moves_every_line_is_removed():
    """Labels that belong in column one show at indent one on a large share of the lines (BMS 48%, SQL 56% on real captures)."""
    from core import analysis
    part = "\n".join([" LABEL%d EQU *" % i if i % 2 == 0 else "          DC X'00'" for i in range(60)])
    out = analysis._drop_margin_offset([part], _clicked(1))
    assert out[0].split("\n")[0] == "LABEL0 EQU *" and out[0].split("\n")[1] == "         DC X'00'"


def test_a_few_stray_rows_at_indent_one_do_not_shift_a_fixed_format_capture():
    """A copybook had 16 rows at indent one out of 2,153; shifting the whole file undid its measured columns."""
    from core import analysis
    rows = ["          05 FIELD-%03d PIC X(8)." % i for i in range(190)] + [" STRAY"] * 4 + ["      * COMMENT"] * 6
    part = "\n".join(rows)
    assert analysis._drop_margin_offset([part], _clicked(1)) == [part]


def test_a_wavy_diagnostic_underline_under_a_row_is_not_a_row_of_its_own():
    """Editors draw a red squiggle under code they flag; read as an extra row it doubles the count and breaks the matching."""
    ink = np.zeros((300, 400), dtype=bool)
    tops = [10 + i * 30 for i in range(8)]
    for t in tops:
        ink[t:t + 18, 150:170] = True            # the text row, 18 px tall
        ink[t + 20:t + 25, 190:212] = True       # the squiggle, 5 px tall, two pixels below the text
    assert len(colfix._rows(ink)) == 8


def test_a_short_row_of_real_text_is_still_a_row():
    ink = np.zeros((200, 300), dtype=bool)
    for t in (10, 60, 110):
        ink[t:t + 18, 50:80] = True              # tall rows
    ink[160:166, 50:90] = True                   # a short row, but far from any row above it
    assert len(colfix._rows(ink)) == 4


def test_a_column_review_cut_off_by_the_token_limit_keeps_the_issues_that_arrived_whole(tmp_path):
    from types import SimpleNamespace
    from PIL import Image
    from core.cobol.columns import review_columns
    img = tmp_path / "a.png"
    Image.new("RGB", (10, 10)).save(img)
    cut = ('{"issues": [{"line_text": "MOVE A TO B", "problem": "area B"}, {"line_text": "ADD 1 TO C", "problem": "area A"}, '
           '{"line_text": "STOP RU')
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(
        content=[SimpleNamespace(text=cut)], stop_reason="max_tokens")))
    got = review_columns(client, [img], "MOVE A TO B\nADD 1 TO C\nSTOP RUN.")
    assert [i["line_text"] for i in got] == ["MOVE A TO B", "ADD 1 TO C"]
