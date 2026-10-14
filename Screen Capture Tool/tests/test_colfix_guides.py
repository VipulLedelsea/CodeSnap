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


def _meas(lines, cols, absolute=True):
    """What colfix._measure returns for rows matched one to one with `lines`, each row's words starting at `cols`."""
    body = [(i, l) for i, l in enumerate(lines) if l.strip()]
    measured = [[(c, len(w)) for c, w in zip(cs, l.split())] for (_, l), cs in zip(body, cols)]
    return {"lines": lines, "body": body, "plain": [l for _, l in body], "measured": measured,
            "pairs": [(i, i) for i in range(len(body))], "base": 0, "absolute_columns": absolute,
            "deco": [False] * len(body)}


def test_a_row_whose_every_word_is_off_by_the_same_amount_gets_the_pixel_indentation(monkeypatch):
    """The model wrote WHEN at indent 0 where the pixels place it at 16; only the leading indentation was misread."""
    lines = ['WHEN "A"', "PERFORM 2000-A", 'WHEN "B"']
    cols = [[16, 21], [20, 28], [16, 21]]
    monkeypatch.setattr(colfix, "_measure", lambda *a, **k: _meas(lines, cols))
    out, changed = colfix.respace("unused.png", "\n".join(lines), source_x=40.0)
    assert changed == 3 and [len(l) - len(l.lstrip()) for l in out.split("\n")] == [16, 20, 16]


def test_a_far_off_row_is_still_left_alone_without_a_known_margin_or_when_words_disagree(monkeypatch):
    lines = ['WHEN "A"', "PERFORM 2000-A", 'WHEN "B"']
    cols = [[16, 21], [20, 28], [16, 21]]
    monkeypatch.setattr(colfix, "_measure", lambda *a, **k: _meas(lines, cols, absolute=False))
    assert colfix.respace("unused.png", "\n".join(lines))[1] == 0                      # no calibrated margin
    skewed = [[16, 40], [20, 28], [16, 21]]                                             # the words do not shift together
    monkeypatch.setattr(colfix, "_measure", lambda *a, **k: _meas(lines, skewed))
    out, changed = colfix.respace("unused.png", "\n".join(lines), source_x=40.0)
    assert out.split("\n")[0] == 'WHEN "A"'


def test_a_screenshot_calibrated_from_a_click_a_character_off_follows_the_anchored_ones():
    """Frames that found column one from the picture (a COBOL comment's '*') agree; one calibrated by a click 13.7 px (one
    character) to the left of them shows every line one column too far right."""
    from core import analysis
    anchored = {"spacing": {"calibrated": True, "auto": True, "calibration": {"source_x": 47.0}}}
    clicked = {"spacing": {"calibrated": True, "calibration": {"source_x": 33.3, "pitch": 13.74}}}
    metas = [anchored, anchored, anchored, clicked]
    parts = ["       01 A.\n          05 B PIC X."] * 3 + ["        01 A.\n           05 B PIC X."]
    out = analysis._align_origins(parts, metas)
    assert out[3] == parts[0] and out[:3] == parts[:3]
    clicked_far = {"spacing": {"calibrated": True, "calibration": {"source_x": 38.0, "pitch": 13.74}}}   # not a whole character
    assert analysis._align_origins(parts, metas[:3] + [clicked_far]) == parts


def test_a_line_read_only_from_a_screenshots_edge_row_loses_to_the_same_line_read_whole():
    """The bottom row of a screenshot is clipped by the edge: a Q loses its tail (REQ read as REO) and a hyphen is lost (END-IF
    read as END IF). The pixel check cannot tell, so the screenshot that shows the row whole decides, even alone."""
    from core import analysis
    a = ["IF A", "MOVE 1 TO X", "COMPUTE X = REO-AMOUNT * 2"]                       # clipped: the last row of its screenshot
    b = ["MOVE 1 TO X", "COMPUTE X = REQ-AMOUNT * 2", "IF B", "MOVE 2 TO Y", "STOP"]  # the same place, whole, inside the next
    final = "\n".join(a + b[2:])
    out, changed = analysis._vote_lines(final, ["\n".join(a), "\n".join(b)], [{}, {}])
    assert "REQ-AMOUNT" in out and "REO-AMOUNT" not in out and changed
    c = ["END IF"]
    keep = "\n".join(["X", "END IF", "Y"])                                          # the only reading, nothing to compare
    assert analysis._vote_lines(keep, [keep], [{}])[0] == keep


def test_two_interior_readings_still_need_the_usual_two_to_one():
    from core import analysis
    a = ["ALPHA", "COMPUTE X = REO-AMOUNT * 2", "OMEGA"]                            # an interior row, not at the edge
    b = ["ALPHA", "COMPUTE X = REQ-AMOUNT * 2", "OMEGA"]
    final = "\n".join(a)
    assert analysis._vote_lines(final, ["\n".join(a), "\n".join(b)], [{}, {}])[0] == final   # a 1 to 1 tie is not decided


def test_an_indentation_only_disagreement_is_not_decided_by_the_edge_rule():
    """Edge clipping loses part of a glyph, never the row's indentation: MUNREV.cbl had the right indent on the edge row and a
    misread one on an interior row, and the edge rule must leave that to the pixel check and the usual vote."""
    from core import analysis
    a = ["IF A", '               WHEN "JUNIPER"']                                  # last row of its screenshot, indent 15
    b = ['        WHEN "JUNIPER"', "MOVE 1 TO X", "STOP"]                            # the same row inside the next, indent 8
    final = "\n".join(a + b[1:])
    out, _ = analysis._vote_lines(final, ["\n".join(a), "\n".join(b)], [{}, {}])
    assert '               WHEN "JUNIPER"' in out
