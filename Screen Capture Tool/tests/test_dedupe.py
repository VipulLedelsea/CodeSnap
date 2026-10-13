from core.dedupe import drop_repeated_paragraphs, paragraph_headers
from core.analysis import stitch_parts


def _para(n, extra=()):
    return [f"       {n}-CHECK-{n:02d}.", f"      * route {n}", f'           IF REQ(1:2) = "{n:02d}"',
            f"               MOVE {n} TO WS-RESULT", *extra, "           END-IF."]


def test_cut_short_and_full_copies_collapse_to_the_complete_one():
    full = _para(6, ["               MOVE 'REVIEW' TO WS-RESULT"])
    lines = _para(5) + _para(6)[:-1] + _para(5) + full + full
    out, repeated = drop_repeated_paragraphs(lines)
    assert sorted(repeated) == ["5-CHECK-05", "6-CHECK-06"]
    assert out == _para(5) + full


def test_near_identical_template_blocks_with_different_names_are_kept():
    lines = _para(1) + _para(2) + _para(3)
    assert drop_repeated_paragraphs(lines) == (lines, [])


def test_repeated_name_with_different_bodies_is_left_for_review():
    a = _para(5, ["               MOVE 'A' TO X", "               MOVE 'B' TO Y", "               MOVE 'C' TO Z"])
    b = ["       5-CHECK-05.", "           PERFORM ALPHA", "           PERFORM BETA", "           GOBACK."]
    lines = a + b
    assert drop_repeated_paragraphs(lines) == (lines, [])


def test_statements_and_section_lines_are_not_paragraph_names():
    lines = ["       MAIN-SEC SECTION.", "           PERFORM A.", "           EXIT.", "       END-IF.", "       EXIT."]
    assert paragraph_headers(lines) == []


def test_stitching_records_repeated_paragraphs_for_cobol():
    head = ["       IDENTIFICATION DIVISION.", "       PROGRAM-ID. DEMO.", "       PROCEDURE DIVISION."]
    body = _para(5) + _para(6)
    frame1 = "\n".join(head + body)
    frame2 = "\n".join(body)   # nothing in common that the stitcher can anchor on beyond the paragraphs themselves
    text = stitch_parts([frame1, frame2])
    names = [n for _, n in paragraph_headers(text.split("\n"))]
    assert len(names) == len(set(names))
