import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from core.analysis import clean_source, merge_frames  # noqa: E402
from core.langpacks.formats import restore_asm_columns  # noqa: E402
from legacy_fidelity_eval import FILES, frames, line_exact  # noqa: E402

S = HERE / "samples"


def test_every_sample_survives_frame_merge_exactly():
    bad = [p.name for p in FILES if line_exact(p.read_text(errors="replace"),
                                               merge_frames(frames(p.read_text(errors="replace")))[0]) < 1]
    assert not bad


def test_mid_file_cobol_frame_keeps_sequence_numbers():
    text = (S / "cobol" / "AIDCALC.cbl").read_text()
    second = frames(text)[1]
    merged, _ = merge_frames(frames(text))
    assert merged.splitlines()[-1].startswith("004200 ")
    assert all(l[:6].isdigit() for l in merged.splitlines() if l.strip())
    assert second.splitlines()[0] in merged


def test_six_digit_numbers_are_not_a_gutter():
    assert clean_source("003300     READ X\n003400     END-READ.\n003500     STOP RUN.").startswith("003300")


def test_real_gutter_still_stripped():
    assert clean_source("1  def f():\n2      return 1\n3\n4  print(f())").splitlines()[0] == "def f():"


def test_dedented_dbd_psb_preserves_observed_columns_until_reviewed():
    for name in ("AIDDBD.dbd", "AIDPSB.psb"):
        t = (S / "langpacks" / name).read_text()
        merged, _ = merge_frames([textwrap.dedent(t)])
        assert merged.splitlines() == [l.rstrip() for l in textwrap.dedent(t).splitlines() if l.strip()]


def test_labelled_asm_line_untouched():
    src = "AIDEDIT  CSECT\n         USING *,15\n         END"
    assert restore_asm_columns(src) == src


def test_indented_cl_first_line_kept():
    t = (S / "langpacks" / "AIDNIGHT.clle").read_text()
    assert merge_frames([t])[0].splitlines()[0] == t.splitlines()[0].rstrip()


def test_first_line_indent_preserved_until_pixels_or_reviewer_resolve_it():
    assert merge_frames(['    """doc"""\nimport os\nprint(os.name)'])[0].startswith('    """doc"""')


def _scroll(text, n, ov):
    lines, out, i = text.splitlines(), [], 0
    while True:
        if i + n >= len(lines):
            out.append("\n".join(lines[max(0, len(lines) - n):]))
            return out
        out.append("\n".join(lines[i:i + n]))
        i += n - ov


def test_scroll_shapes_with_overlap_lose_nothing():
    bad = []
    for p in FILES:
        t = p.read_text(errors="replace")
        for n, ov in ((12, 4), (20, 4), (20, 8), (36, 1)):
            fr = _scroll(t, n, ov)
            for c in (fr, fr[:1] + fr, fr + fr[-1:]):
                if len(c) > 1 and line_exact(t, merge_frames(c)[0]) < 0.999:
                    bad.append((p.name, n, ov))
    assert not bad, bad[:10]


def test_short_closing_frame_not_dropped():
    t = (HERE / "evals" / "heldout" / "LevyDao.java").read_text()
    assert merge_frames(_scroll(t, 20, 4))[0].rstrip().endswith("}")


def test_different_sequence_numbers_never_overlap():
    a = "\n".join(f"{i:04d}00     EXEC CICS RETURN END-EXEC" for i in range(1, 6))
    b = "\n".join(f"{i:04d}00     EXEC CICS RETURN END-EXEC" for i in range(6, 11))
    assert len(merge_frames([a, b])[0].split()) >= 10 * 5


def test_cut_off_line_replaced_by_whole_copy_from_next_screen():
    a = "\n".join(f"{i:04d}00     MOVE A{i} TO B{i}" for i in range(1, 9)) + "\n000900     MOVE ZERO TO WS-ADJ [CUT OFF]"
    b = "000800     MOVE A8 TO B8\n000900     MOVE ZERO TO WS-ADJ-TOTAL\n001000     PERFORM 8200-READ-ADJUST."
    out = merge_frames([a, b])[0]
    assert "[CUT OFF]" not in out and "000900     MOVE ZERO TO WS-ADJ-TOTAL" in out and out.count("000900") == 1


def test_cut_off_kept_when_no_whole_copy_exists():
    a = "public class A {\n    void f() {\n        int x = compute(1,"
    assert "[CUT OFF]" in merge_frames([a + " [CUT OFF]"])[0]


def test_repeated_legacy_paragraphs_keep_distinct_identifiers_and_values():
    source = "\n".join(
        f'       {5000 + i * 10}-CHECK-{i:02d}.\n'
        f'           IF REQ-RECEIPT(1:2) = "{i:02d}"\n'
        '               IF WS-AMOUNT > 10000\n'
        '                   MOVE "IGNORE" TO WS-RESULT\n'
        '               END-IF\n'
        '           END-IF.'
        for i in range(20)
    )
    result = merge_frames(_scroll(source, 24, 8))[0]
    assert result.splitlines() == source.splitlines()


def test_contained_frame_with_one_new_paragraph_is_not_discarded():
    from core.analysis import _mostly_contained
    original = ['           MOVE ZERO TO WS-COUNT'] * 39 + ['       5030-CHECK-03.']
    changed = original[:-1] + ['       5050-CHECK-05.']
    assert not _mostly_contained(changed, original)


def test_overlap_does_not_equate_distinct_amounts_or_routine_names():
    from core.analysis import _sim
    assert _sim('           IF WS-AMOUNT > 10000', '           IF WS-AMOUNT > 20000') == 0
    assert _sim('       CALCULATE-RELIEF.', '       CALCULATE-REFUND.') == 0


def test_numeric_read_conflict_uses_unique_paragraph_anchor_and_stays_flagged():
    from core.analysis import merge_verified
    from core.verify import summarize
    first = '\n'.join(['           MOVE ZERO TO WS-COUNT',
                       '       2150-PINECREST.',
                       '      * CHG-2000-115: PINECREST COUNCIL EXCEPTION.',
                       '           IF REQ-BALANCE >= 1750'])
    second = first.replace('1750', '2000') + '\n               ADD 9 TO WS-AMOUNT\n           END-IF.'
    code, _, notes, statuses = merge_verified([first, second])
    assert code.count('2150-PINECREST.') == 1
    assert 'IF REQ-BALANCE >= 2000' in code
    assert not notes.get('breaks')
    verification = summarize(code, statuses, notes, read_code=code)
    assert any('IF REQ-BALANCE >= 2000' in flag['text'] for flag in verification['flags'])


def test_numeric_conflict_without_position_anchor_is_not_silently_merged():
    from core.analysis import _stitch_two
    first = ['           MOVE ZERO TO WS-COUNT', '           MOVE ZERO TO WS-TOTAL',
             '           ADD 1 TO WS-COUNT', '           IF WS-TOTAL > 1000']
    second = first[:-1] + ['           IF WS-TOTAL > 2000', '               DISPLAY WS-TOTAL']
    assert _stitch_two(first, second) is None


def test_bad_bottom_row_does_not_duplicate_an_anchored_paragraph():
    from core.analysis import merge_verified
    first = ['       5050-CHECK-05.', '      * RECEIPT ROUTE 05.',
             '           IF REQ-RECEIPT(1:2) = "05"', '               IF WS-AMOUNT < ZERO',
             '                   MOVE "REVERSE" TO WS-RESULT', '               END-IF',
             '               IF REQ-RECEIPT(13:4) = SPACES', '                   MOVE "REVIEW" TO WS-RESULT',
             '               END-IF', '               IF WS-AMOUNT > 10825']
    second = first[:-1] + ['               IF WS-AMOUNT = ZERO', '                   MOVE "IGNORE" TO WS-RESULT',
                           '               END-IF', '           END-IF.']
    code, _, notes, _ = merge_verified(['\n'.join(first), '\n'.join(second)])
    assert code.splitlines() == second
    assert notes['overlap_conflicts']


def test_column_recovery_only_uses_a_valid_copy_seen_in_another_frame():
    from core.analysis import _observed_cobol_columns
    bad = '     5000-CHECK-00.\n    * RECEIPT ROUTE 00.'
    good = '       5000-CHECK-00.\n      * RECEIPT ROUTE 00.'
    assert _observed_cobol_columns([bad, good]) == [good, good]
    assert _observed_cobol_columns([bad]) == [bad]


def test_later_read_missing_body_rows_keeps_the_earlier_observed_rows():
    from core.analysis import merge_verified
    source = ['       2130-NORTHGATE.', '      * CHG-1998-113: NORTHGATE COUNCIL EXCEPTION.',
              '           IF REQ-INCOME > 27750', '               MOVE "DENY" TO WS-RESULT',
              '               MOVE "INCOME-LIMIT" TO WS-REASON', '           END-IF',
              '      * ENH-2020-144: EMERGENCY OVERRIDE HAS NO SUNSET CHECK.',
              '           IF REQ-RELIEF = "Y"', '               MOVE "ACCEPT" TO WS-RESULT',
              '           END-IF.', '       2140-OAKRIDGE.',
              '      * CHG-1999-114: OAKRIDGE COUNCIL EXCEPTION.',
              '           IF REQ-INCOME > 28500', '               MOVE "DENY" TO WS-RESULT',
              '           END-IF.']
    earlier = source[:13]
    later = source[1:3] + source[5:]
    code, _, _, _ = merge_verified(['\n'.join(earlier), '\n'.join(later)])
    assert code.splitlines() == source


def test_conflict_warning_context_includes_unique_paragraph():
    from core.analysis import _conflict_context
    rows = ['       5000-FIRST.', '           IF READY', '               MOVE 1 TO VALUE',
            '           END-IF.', '       5010-SECOND.', '           IF READY',
            '               MOVE 1 TO VALUE', '           END-IF.']
    context = _conflict_context(rows, 3)
    assert context[0] == '5000-FIRST.'
    matches = [i for i in range(len(context) - 1, len(rows))
               if [r.strip() for r in rows[i-len(context)+1:i+1]] == context]
    assert matches == [3]


def test_truncated_response_only_recovers_complete_strings():
    from core.analysis import _normalize_extract
    result = _normalize_extract('{"raw_transcription": ["MOVE A TO B", "END-IF", "PERFORM 30')
    assert result['raw'] == 'MOVE A TO B\nEND-IF'


def test_sticky_header_does_not_duplicate_partial_overlap():
    from core.analysis import _anchored_frame
    old = ['MAIN: PROC(REQUEST);', 'DCL 1 REQUEST,', '  2 VALUE FIXED BIN;', 'SELECT(DISTRICT);', "WHEN('A') CALL R01;", "WHEN('B') CALL R02;", "WHEN('C') CALL R03;"]
    incoming = ['MAIN: PROC(REQUEST);', 'DCL 1 REQUEST,', 'SELECT(DISTRICT);', "WHEN('A') CALL R01;", "WHEN('B') CALL R02;", "WHEN('C') CALL R03;", "WHEN('D') CALL R04;"]
    out = _anchored_frame(old, incoming, frozenset(), {})
    assert out == old + ["WHEN('D') CALL R04;"]


def test_sql_tables_with_same_field_body_are_distinct():
    from core.analysis import _sim, merge_frames
    one = 'CREATE TABLE mun_installment0 (\n receipt CHAR(16),\n amount DECIMAL(11,2),\n status CHAR(8),\n changed_at TIMESTAMP\n);\nCREATE INDEX ix_installment0 ON mun_installment0(receipt);'
    two = one.replace('installment0', 'reversal0')
    assert _sim('CREATE TABLE mun_installment0 (', 'CREATE TABLE mun_reversal0 (') == 0
    out = merge_frames([one, one.splitlines()[-2]+'\n'+one.splitlines()[-1]+'\n'+two])[0]
    assert 'CREATE TABLE mun_installment0 (' in out and 'CREATE TABLE mun_reversal0 (' in out
    assert out.count('receipt CHAR(16)') == 2


def test_complete_sql_inserts_are_not_sideways_fragments():
    from core.verify import sideways_views, join_sideways
    first = [f"INSERT INTO policy VALUES ('FIRST', {1990+i}, {100+i}, 1, 1);" for i in range(30)]
    second = [f"INSERT INTO policy VALUES ('SECOND', {1990+i}, {200+i}, 1, 1);" for i in range(30)]
    assert sideways_views([first, second]) == set()
    assert join_sideways(first[0], second[0]) is None


def test_ambiguous_cut_prefix_never_gets_an_arbitrary_sql_row():
    from core.analysis import _upgrade_cut
    cut = 'INSERT INTO policy VALUES [CUT OFF]'
    rows = ["INSERT INTO policy VALUES ('A', 1);", "INSERT INTO policy VALUES ('B', 2);"]
    assert _upgrade_cut([cut], rows) == [cut]


def test_revisited_sql_prefix_can_reconcile_a_skipped_overlap_row():
    from core.analysis import _anchored_frame
    old = [f"INSERT INTO policy VALUES ('A', {i});" for i in range(10)]
    incoming = old[5:8] + old[9:] + ["INSERT INTO policy VALUES ('A', 10);"]
    assert _anchored_frame(old, incoming, frozenset(), {}) == old + incoming[-1:]


def test_revisited_rpg_routine_restores_opening_without_appending_to_end():
    from core.analysis import _rpg_section_frame
    marker = '      * CHG-2021-121: VALLEYFORD treasury cap.'
    old = [marker, '', '     C                   ENDIF',
           '      * FIX-1999: whole units.', "     C                   IF        Channel = 'BANK-V1'",
           '     C                   EVAL      ExportAmount = LegacyWhole',
           '     C                   ENDIF', '     C                   ENDSR',
           '      * CHG-1996-122: WESTHAVEN treasury cap.', '     C     R22           BEGSR']
    fresh = [marker, '     C     R21           BEGSR',
             '     C                   IF        Priority = \'TREASURY\'',
             '     C                   ENDIF', '      * FIX-1999: whole units.',
             "     C                   IF        Channel = 'BANK-V1'"]
    result = _rpg_section_frame(old, fresh)
    assert result == fresh + old[5:]
    assert result.count(marker) == 1
    assert result[-1] == old[-1]


def test_revisited_rpg_does_not_discard_unidentified_prefix():
    from core.analysis import _rpg_section_frame
    marker = '      * CHG-2021-121: VALLEYFORD treasury cap.'
    rows = [marker, '     C     R21           BEGSR', '     C                   ENDIF', '     C                   ENDSR']
    assert _rpg_section_frame(rows, ['unidentified new code'] + rows) is None


def test_revisited_rpg_accepts_cut_comment_and_comment_indicator_spacing():
    from core.analysis import _rpg_section_frame, _mostly_contained
    old = ['      * CHG-2021-121: VALLEYFORD treasury cap [CUT OFF]',
           '     C                   ENDIF', '      * FIX-1999: whole units.',
           "     C                   IF        Channel = 'BANK-V1'", '     C                   ENDSR']
    fresh = ['      * CHG-2021-121: VALLEYFORD treasury cap.', '     C     R21           BEGSR',
             '     C                   ENDIF', '      * FIX-1999: whole units.',
             "     C                   IF        Channel = 'BANK-V1'"]
    result = _rpg_section_frame(old, fresh)
    assert result == fresh + old[-1:]
    assert _mostly_contained(['     *  FIX-1999: whole units.', fresh[-1]], result)


def test_removed_break_boundary_does_not_count_as_remaining_gap():
    from core.verify import summarize
    code = 'first\nrestored\nlast'
    summary = summarize(code, {line: 'verified' for line in code.splitlines()},
                        {'breaks': [('first', 'last')]}, read_code=code)
    assert summary['breaks'] == 0
    assert summary['flags'] == []


def test_repeated_rexx_routes_do_not_discard_new_labels_before_overlap():
    from core.analysis import merge_verified
    def route(number):
        return [f'route_{number}:', f'/* route {number} */', "queue = 'SYNTH.REVIEW'",
                'alloc_rc = rc', "if alloc_rc <> 0 then say 'ALLOC WARNING' alloc_rc",
                "row.1 = key || ' ' || action", 'row.0 = 1',
                '"EXECIO 1 DISKW REPLAY (STEM row. FINIS)"', 'write_rc = rc',
                "if write_rc <> 0 then say 'RETRY ON NEXT SHIFT'", '"FREE FI(REPLAY)"',
                '/* scheduler continues */', 'return 0']
    source = route(17) + route(18) + route(19) + route(20)
    frames = ['\n'.join(source[:13]), '\n'.join(source[9:39]), '\n'.join(source[32:])]
    assert merge_verified(frames)[0].splitlines() == source


def _procedure(n):
    return [f"R{n}: PROC;", f"  /* CHG-{n}: settlement tolerance. */", "  STATUS = 'ACCEPT';",
            f"  IF ABS(VARIANCE) > {n % 7} THEN DO;", "    STATUS = 'HOLD';", "  END;",
            "  IF PROCESSOR = 'OLDPAY' THEN DO;", "    STATUS = 'ACCEPT';", "    REASON = 'NEXT_DAY_PROCESSOR';", "  END;",
            "  /* INC-2021: drain stuck queue after three attempts. */", "  IF RETRIES > 3 THEN DO;",
            "    REASON = 'RETRY_OVERRIDE';", "  END;", "  AMOUNT = ABS(VARIANCE);", f"END R{n};"]


def test_a_template_that_repeats_does_not_make_the_stitcher_drop_the_lines_between_two_screens():
    """R17 and R18 end with 13 identical lines. A second screen that shows five lines of R17's end, then R18 in full, must not be
    matched against R18's own tail, which would throw R18's first lines away."""
    from core.analysis import stitch_parts
    lines = [l for n in range(10, 24) for l in _procedure(n)]
    start = lines.index("R17: PROC;")
    first = lines[:start + 15]                         # ends with R17's 'AMOUNT = ABS(VARIANCE);'
    second = lines[start + 11:start + 11 + 40]         # overlaps the last four lines, then runs on through R18 and R19
    out = stitch_parts(["\n".join(first), "\n".join(second)]).split("\n")
    assert out == lines[:start + 11 + 40]


def test_a_stretch_read_one_column_to_the_right_is_moved_back_and_a_normal_screen_is_left_alone():
    from core.analysis import _align_frame_columns
    normal = [f"           MOVE {i} TO X." for i in range(150)]                 # indent 11, remainder 3
    screen = ["        01 RESPONSE-RECORD.", "           05 RES-AMOUNT PIC 9.", "        PROCEDURE DIVISION.", "        0000-MAIN."] \
        + [f"            MOVE {i} TO Y." for i in range(12)]                    # from PROCEDURE DIVISION on, one column right
    parts, moved = _align_frame_columns(["\n".join(normal), "\n".join(screen), "\n".join(normal[:20])])
    got = parts[1].split("\n")
    assert moved == [(1, 3, 16)] and got[0] == "        01 RESPONSE-RECORD." and got[2] == "       PROCEDURE DIVISION."
    assert got[4] == "           MOVE 0 TO Y." and parts[0] == "\n".join(normal) and parts[2] == "\n".join(normal[:20])
    # fewer than eight statements in a row, or a file with no single pattern, is not touched
    few = ["\n".join(normal), "\n".join([f"            MOVE {i} TO Y." for i in range(5)])]
    assert _align_frame_columns(few)[1] == []
    mixed = ["\n".join(["           MOVE 1.", "               MOVE 2.", "            MOVE 3.", "             MOVE 4."] * 40)]
    assert _align_frame_columns(mixed)[1] == []


def test_half_seen_rows_at_a_screen_edge_are_dropped_when_the_next_screen_shows_the_place_again():
    from core.analysis import _trim_unverified_edges, merge_verified
    body = [f"           MOVE {i} TO FIELD-{i}." for i in range(40)]
    first = body[:20] + ["        END-IF", "        END-IF"]                      # the last row was half cut: read twice, wrong indent
    second = body[16:40]
    parts = ["\n".join(first), "\n".join(second)]
    status = [["verified"] * 20 + ["unchecked", "unchecked"], ["verified"] * len(second)]
    trimmed, dropped = _trim_unverified_edges(parts, [{"status": status[0]}, {"status": status[1]}])
    assert dropped == [(0, "tail", 2)] and trimmed[0].split("\n") == body[:20]
    # the same rows are kept when the other screen does not show the lines before them (they are the only copy), or when the
    # pixel check did not work on the screen (most rows unchecked)
    far = ["\n".join(body[30:40])]
    assert _trim_unverified_edges([parts[0]] + far, [{"status": status[0]}, {"status": ["verified"] * 10}])[1] == []
    assert _trim_unverified_edges(parts, [{"status": ["unchecked"] * 22}, {"status": status[1]}])[1] == []


def test_a_line_misread_on_one_screen_is_settled_by_the_other_screens_that_show_it():
    from core.analysis import _vote_lines
    good = "          DFHMDF POS=(3,2),LENGTH=7,INITIAL='RECEIPT',           X"
    bad = good.replace(",", ".")
    context = [f"          DFHMDF POS=({i},2),LENGTH=7" for i in range(6)]
    final = "\n".join(context[:3] + [bad] + context[3:])
    shows = lambda line: "\n".join(context[:3] + [line] + context[3:])
    parts = [shows(good), shows(good), shows(bad), shows(good)]
    metas = [{"status": ["verified"] * 7}] * 4
    fixed, changed = _vote_lines(final, parts, metas)
    assert fixed.split("\n")[3] == good and changed == [(4, bad, good)]
    # one screen against one is a tie: nothing changes; a quite different line never replaces a line; a cut-off row is not a vote
    assert _vote_lines(final, [shows(good), shows(bad)], metas[:2])[1] == []
    other = "          MOVE ALPHA TO BETA PLEASE"
    assert _vote_lines(final, [shows(other), shows(other), shows(bad)], metas[:3])[1] == []
    assert _vote_lines(final, [shows(good + " [CUT OFF]")] * 3 + [shows(bad)], metas[:4] + [{}])[1] == []


def test_a_stretch_one_column_off_a_two_space_grid_is_moved_back_but_a_lone_line_is_not():
    from core.analysis import _align_indent_grid
    base = []
    for n in range(120):
        base += [f"R{n}: PROC;", f"  STATUS = {n};", f"  IF A > {n} THEN DO;", f"    REASON = {n};", "  END;", f"END R{n};"]
    screen = [l[1:] if l.startswith(" ") else l for l in base[6:24]]            # read one column to the left
    fixed, moved = _align_indent_grid(["\n".join(base), "\n".join(screen), "\n".join(base[:30])])
    assert moved == [(1, 2, 17)] and fixed[1].split("\n") == base[6:24]
    lone = base[:]
    lone[3] = "   REASON = 3;"                                                    # one hand-aligned line, not a run
    assert _align_indent_grid(["\n".join(lone)])[1] == []
    assert _align_indent_grid(["\n".join(["   x = 1;"] * 80)])[1] == []           # a file with no grid is left alone


def test_a_cut_off_row_and_the_half_seen_row_above_it_are_both_dropped_at_a_screen_edge():
    from core.analysis import _trim_unverified_edges
    body = [f"           MOVE {i} TO FIELD-{i}." for i in range(40)]
    first = body[:20] + ["    END-IF", "    END-IF[CUT OFF]"]
    parts = ["\n".join(first), "\n".join(body[16:40])]
    status = ["verified"] * 20 + ["unchecked", "cut"]
    trimmed, dropped = _trim_unverified_edges(parts, [{"status": status}, {"status": ["verified"] * 24}])
    assert dropped == [(0, "tail", 2)] and trimmed[0].split("\n") == body[:20]


def test_a_cut_off_row_beside_its_whole_line_is_dropped_but_a_lone_one_is_kept():
    from core.analysis import _drop_cut_duplicates
    lines = ["-- note", "CREATE TABLE history0 ( [CUT OFF]", "CREATE TABLE mun_history0 (", "  id INTEGER,"]
    assert _drop_cut_duplicates(lines) == ["-- note", "CREATE TABLE mun_history0 (", "  id INTEGER,"]
    lone = ["-- note", "CREATE TABLE history0 ( [CUT OFF]", "  id INTEGER,"]
    assert _drop_cut_duplicates(lone) == lone


def test_a_line_read_twice_in_a_row_gives_way_to_a_different_reading_of_that_place():
    from core.analysis import _vote_lines
    row = lambda name, year: f"INSERT INTO district_policy VALUES ('{name}', {year}, 1500, 28250, 5, 5, 1);"
    above, below = row("LAKESIDE", 2020), row("MILLBROOK", 1997)
    twice = row("MILLBROOK", 1996)
    final = "\n".join([above, twice, twice, below])                       # the stitched text repeats MILLBROOK 1996
    screen_a = "\n".join([above, twice, twice, below])                    # one screen read it that way
    screen_b = "\n".join([above, row("LAKESIDE", 2021), twice, below])    # another read the true rows
    fixed, changed = _vote_lines(final, [screen_a, screen_b], [{"status": ["verified"] * 4}] * 2)
    assert fixed.split("\n") == [above, row("LAKESIDE", 2021), twice, below] and len(changed) == 1
    # without the repeated line a one-to-one disagreement still changes nothing
    plain = "\n".join([above, twice, below])
    assert _vote_lines(plain, [plain, "\n".join([above, row("LAKESIDE", 2021), below])], [{}, {}])[1] == []


def test_stitching_a_long_repetitive_file_stays_fast_and_exact():
    """A 3,000-line file of near-identical paragraphs on 86 screens. Stitching used to grow with the square of the file (20,000
    lines would have taken half an hour); it must stay well inside this limit, with the text exact."""
    import sys
    import time
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent / "quality"))
    import scale_bench
    from core.analysis import merge_verified
    lines = scale_bench.make_file(3000)
    parts = scale_bench.screens(lines)
    began = time.time()
    code, _, _, _ = merge_verified(parts, [{}] * len(parts))
    assert time.time() - began < 45
    assert [l for l in code.split("\n") if l.strip()] == [l for l in lines if l.strip()]
