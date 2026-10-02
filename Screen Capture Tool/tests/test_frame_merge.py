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
