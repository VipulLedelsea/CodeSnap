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


def _routine(n):
    return [f"R{n:02d}: PROC;",
            f"  /* CHG-20{n:02d}-1{n:02d}: SETTLEMENT TOLERANCE. */",
            "  STATUS = 'ACCEPT';",
            f"  IF ABS(VARIANCE) > {n} THEN DO;",
            "    STATUS = 'HOLD';",
            "    REASON = 'SETTLEMENT_VARIANCE';",
            "  END;",
            "  IF PROCESSOR = 'OLDPAY' THEN DO;",
            "    STATUS = 'ACCEPT';",
            "    REASON = 'NEXT_DAY_PROCESSOR';",
            "  END;",
            "  /* INC-2021: drain stuck queue after three attempts. */",
            "  IF RETRIES > 3 THEN DO;",
            "    STATUS = 'ACCEPT';",
            "    REASON = 'RETRY_OVERRIDE';",
            "  END;",
            "  AMOUNT = ABS(VARIANCE);",
            f"END R{n:02d};"]


def test_a_longer_match_inside_the_wrong_routine_does_not_skip_the_routines_between():
    source = [row for n in range(1, 7) for row in _routine(n)]
    # the first screen ends on the last body line of routine 3; the next starts only 5 rows earlier, so the true overlap is
    # short, while "INC-2021 ... AMOUNT" (6 rows) also appears at the end of routines 4 and 5
    stop = next(i for i, row in enumerate(source) if row == "END R03;")
    first = source[stop - 31:stop]
    second = source[stop - 5:stop - 5 + 44]
    merged = analysis._stitch_two(first, second)
    assert merged is not None
    assert [l.strip() for l in merged] == [l.strip() for l in source[stop - 31:stop - 5 + 44]]


def test_a_map_set_that_starts_below_its_header_is_reported_as_missing_its_start():
    from core.model.completeness import check
    whole = "MUNMAP   DFHMSD TYPE=&SYSPARM,MODE=INOUT\n* SYNTHETIC\nM00      DFHMDI SIZE=(24,80)\n         DFHMDF POS=(1,2)\n         DFHMSD TYPE=FINAL\n         END\n"
    cut = "R00      DFHMDF POS=(3,12),LENGTH=12\n         DFHMDF POS=(5,2),LENGTH=6\n         DFHMSD TYPE=FINAL\n         END\n"
    assert not [r for r in check(whole, "A.bms")["reasons"] if "DFHMSD" in r]
    assert any("start probably not captured" in r for r in check(cut, "A.bms")["reasons"])
