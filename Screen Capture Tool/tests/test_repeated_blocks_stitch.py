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


def test_screens_read_a_column_off_their_neighbours_are_brought_to_one_offset():
    source = [row for n in range(1, 8) for row in _routine(n)]
    frames = _frames(source, height=30, step=14)
    shifted = [("\n".join(" " + l if l.strip() else l for l in f) if i in (2, 3, 4) else "\n".join(f))
               for i, f in enumerate(frames)]
    fixed = analysis._equalize_frame_offsets(shifted)
    for original, got in zip(["\n".join(f) for f in frames], fixed):
        # every screen ends up at one common offset: 0 or the same number of spaces for all of them
        assert got in (original, "\n".join(" " + l if l.strip() else l for l in original.split("\n")))
    leading = {len(f.split("\n")[0]) - len(f.split("\n")[0].lstrip(" ")) - (len(frames[i][0]) - len(frames[i][0].lstrip(" ")))
               for i, f in enumerate(fixed)}
    assert len(leading) == 1


def test_screens_that_agree_are_left_alone():
    source = [row for n in range(1, 8) for row in _routine(n)]
    frames = ["\n".join(f) for f in _frames(source, height=30, step=14)]
    assert analysis._equalize_frame_offsets(frames) == frames


def test_a_line_one_screen_read_twice_is_not_kept_twice():
    rows = [f"  STATUS_{n} = {n};" for n in range(1, 9)]
    twice = rows[:4] + [rows[3]] + rows[4:]
    final = "\n".join(twice)
    parts = ["\n".join(rows[:6]), "\n".join(rows[2:]), "\n".join(rows[1:7]), "\n".join(twice[1:8])]
    out, dropped = analysis._collapse_doubled_lines(final, parts)
    assert out.split("\n") == rows and dropped


def test_a_line_that_really_repeats_is_kept():
    rows = [f"  STATUS_{n} = {n};" for n in range(1, 9)]
    twice = rows[:4] + [rows[3]] + rows[4:]
    parts = ["\n".join(twice[:6]), "\n".join(twice[2:]), "\n".join(twice[1:8])]
    out, dropped = analysis._collapse_doubled_lines("\n".join(twice), parts)
    assert out.split("\n") == twice and not dropped


def test_a_map_set_continuation_line_goes_back_to_column_16():
    first = "         DFHMDF POS=(3,2),LENGTH=7,INITIAL='RECEIPT'," + " " * 11 + "X"
    for wrong in (12, 14, 16, 17):
        text = "\n".join(["M00      DFHMDI SIZE=(24,80)", first, " " * wrong + "ATTRB=ASKIP", "         END"])
        fixed, lines = analysis._fix_macro_continuations(text)
        assert fixed.split("\n")[2] == " " * 15 + "ATTRB=ASKIP" and (lines == [3] or wrong == 15)
    other = "\n".join(["foo bar", first, "      ATTRB=ASKIP"])
    assert analysis._fix_macro_continuations(other)[0] == other   # not a map set: left alone


def test_a_vote_settles_a_line_read_at_another_indent_by_the_screens_that_agree():
    rows = ["    05 A PIC X.", "    05 B PIC 9(9)V99 COMP-3.", "    05 C PIC X(8)."]
    odd = [r.lstrip() for r in rows]
    parts = ["\n".join(rows), "\n".join(rows), "\n".join(odd)]
    out, changed = analysis._vote_lines("\n".join(odd), parts, [{}, {}, {}])
    assert out.split("\n") == rows


def test_a_schema_script_that_loads_a_table_it_never_creates_is_reported_as_missing_its_start():
    from core.model.completeness import check
    whole = ("-- schema\nCREATE TABLE a (x INT);\nCREATE TABLE b (y INT);\nINSERT INTO a VALUES (1);\nINSERT INTO b VALUES (2);\n")
    cut = ("INSERT INTO a VALUES (1);\nINSERT INTO a VALUES (2);\nCREATE TABLE b (y INT);\nINSERT INTO b VALUES (2);\n")
    loads_only = "INSERT INTO a VALUES (1);\nINSERT INTO a VALUES (2);\n"
    assert not [r for r in check(whole, "s.sql")["reasons"] if "never creates" in r]
    assert any("start probably not captured" in r for r in check(cut, "s.sql")["reasons"])
    assert not [r for r in check(loads_only, "load.sql")["reasons"] if "never creates" in r]   # no CREATE at all: a plain data load
