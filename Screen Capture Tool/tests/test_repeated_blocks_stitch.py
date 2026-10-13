from core import analysis


def _para(n, amount):
    return [f"       50{n:02d}-CHECK-{n:02d}.",
            f"      * FIX-20{n:02d}-3{n:02d}: HISTORICAL RECEIPT ROUTE {n:02d}.",
            f'           IF REQ-RECEIPT(1:2) = "{n:02d}"',
            f"               IF WS-AMOUNT > {amount}",
            '                   MOVE "HOLD" TO WS-RESULT',
            "               END-IF",
            "               IF WS-AMOUNT < ZERO",
            '                   MOVE "REVERSE" TO WS-RESULT',
            "               END-IF",
            "               IF REQ-RECEIPT(13:4) = SPACES",
            '                   MOVE "REVIEW" TO WS-RESULT',
            "               END-IF",
            "               IF WS-AMOUNT = ZERO",
            '                   MOVE "IGNORE" TO WS-RESULT',
            "               END-IF",
            "           END-IF."]


def _source():
    out = []
    for n in range(1, 9):
        out += _para(n, 10000 + n * 275)
    return out


def _frames(source, height, step, junk_after=None):
    """Screens of `height` rows scrolled by `step`. With junk_after, the last row of every screen is a guess at a clipped row."""
    frames = []
    for top in range(0, len(source) - height + step, step):
        rows = list(source[top:top + height])
        if junk_after and len(rows) == height:
            rows[-1] = junk_after
        frames.append(rows)
    return frames


def test_repeated_paragraphs_are_not_appended_twice_when_a_clipped_last_row_was_misread():
    source = _source()
    frames = _frames(source, height=30, step=18, junk_after="           END-IF")
    merged = frames[0]
    for frame in frames[1:]:
        merged = analysis._stitch_two(merged, frame) or merged + [""] + frame
    headers = [l.strip() for l in merged if l.strip().endswith(".") and "-CHECK-" in l]
    assert len(headers) == len(set(headers)), "a paragraph was appended twice"
    # every real paragraph is present and in order
    assert headers == [l.strip() for l in source if "-CHECK-" in l and l.strip().endswith(".")]


def test_clean_overlap_still_merges_exactly():
    source = _source()
    frames = _frames(source, height=30, step=18)
    merged = frames[0]
    for frame in frames[1:]:
        merged = analysis._stitch_two(merged, frame)
        assert merged is not None
    assert [l.strip() for l in merged] == [l.strip() for l in source]
