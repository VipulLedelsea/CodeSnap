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


def test_a_run_of_identical_closers_is_shortened_by_the_majority_reading():
    from core.analysis import _collapse_doubled_lines
    shown = ["User.is_active == True,", ")", ")", "target = x"]
    three = ["User.is_active == True,", ")", ")", ")", "target = x"]
    fixed, dropped = _collapse_doubled_lines("\n".join(three), ["\n".join(shown)] * 3)
    assert fixed.split("\n") == shown and dropped == [4]
    kept, none = _collapse_doubled_lines("\n".join(three), ["\n".join(three)] * 3)
    assert none == [] and kept.split("\n") == three


def test_a_bare_comment_marker_beside_a_divider_is_flagged():
    from core.verify import banner_debris, summarize
    lines = ["x = 1", "# -------------------------------", "# Title", "#", "# -------------------------------", "y = 2"]
    assert banner_debris(lines) == {4}
    out = summarize("\n".join(lines), {l: "verified" for l in lines})
    assert any(f["line"] == 4 and "bare comment marker" in f["reason"] for f in out["flags"])
    assert banner_debris(["x = 1", "#", "y = 2"]) == set()


def test_rows_the_calibration_misplaces_by_a_column_are_not_character_mismatches(monkeypatch):
    """When the editor shifts sideways the calibrated column one is a column off for the whole screenshot; the rows that only the
    rows' own geometry verifies are returned (and are not called measured), but a row running to the right edge never is."""
    from core import analysis, colfix
    shown = [f"line_{i} = {i}" for i in range(10)] + ["x" * 130]
    calls = []

    def fake_check(path, text, source_x=None):
        calls.append(source_x)
        if source_x is None:
            return {"grid": True, "status": ["verified"] * len(shown), "pitch": 10.0, "x0": 0}
        return {"grid": True, "status": ["mismatch"] * len(shown), "rows": {}, "pitch": 10.0, "x0": 0}
    monkeypatch.setattr(colfix, "check", fake_check)
    from PIL import Image
    import tempfile, os
    path = os.path.join(tempfile.mkdtemp(), "f.png")
    Image.new("RGB", (1300, 400)).save(path)
    chk = fake_check(path, "\n".join(shown), source_x=29.0)
    rows = analysis._shifted_origin_rows(path, "\n".join(shown), chk, 29.0)
    assert rows == set(range(10))               # the 130-character row reaches the edge of the 1300 px picture
    assert analysis._shifted_origin_rows(path, "\n".join(shown), chk, None) == set()


def test_a_dash_style_doubt_does_not_make_a_line_unreliable_for_the_reviewer():
    from core import deepdive
    from core.verify import REASONS

    class Store:
        def verification(self, _id):
            return {"flags": [{"line": 2, "reason": REASONS["glyph"]}, {"line": 3, "reason": REASONS["mismatch"]}]}

        def get_meta(self, *_a, **_k):
            return {}

        def pending_captures(self):
            return {}

    art = {"id": 1, "name": "a.json", "artifact_type": "other", "transcription": "{\n  \"d\": \"x — y\",\n  \"e\": 1\n}", "language": "json"}
    q = deepdive.capture_quality(Store(), art)
    assert q["bad_lines"] == [3]                        # the mismatch is unreliable; the dash doubt is only listed
    assert any(i["kind"] == "glyph" for i in q["issues"])


def test_a_titled_divider_is_recognised_only_when_title_widths_and_dash_ink_agree():
    from core.colfix import _measured_word, _titled_divider
    line = "# — Web framework ----------------"
    row = [(0, 1), (2, 2), (5, 3), (9, 9), (19, 17)]
    joined = [False, True, False, False, True]
    assert _titled_divider(line, row, joined)
    assert not _titled_divider(line, [(0, 1), (2, 2), (5, 4), (9, 9), (19, 17)], joined)     # a title word of another width
    assert not _titled_divider(line, row, [False, False, False, False, False])                  # dashes that are not one unbroken line
    assert not _titled_divider("x = a -- b -- c", [(0, 1), (2, 1), (4, 1), (6, 2), (9, 1), (11, 2), (14, 1)], [False] * 7)
    assert _measured_word("—", 2, joined=True) == "──"


def test_a_character_doubt_inside_a_docstring_is_listed_but_does_not_send_the_file_to_needs_attention():
    from core import deepdive
    from core.verify import REASONS

    def store(lines):
        class Store:
            def verification(self, _id):
                return {"flags": [{"line": n, "reason": REASONS["mismatch"]} for n in lines]}

            def get_meta(self, *_a, **_k):
                return {}

            def pending_captures(self):
                return {}
        return Store()

    text = '"""\nModule docs that may be read slightly off.\n"""\nx = 1\ny = 2\n'
    doc = {"id": 1, "name": "a.py", "artifact_type": "other", "transcription": text, "language": "python"}
    in_doc = deepdive.capture_quality(store([2]), doc)
    assert in_doc["status"] != "rescan" and any(i["kind"] == "prose" for i in in_doc["issues"]) and in_doc["bad_lines"] == []
    in_code = deepdive.capture_quality(store([4]), doc)
    assert in_code["status"] == "rescan" and in_code["bad_lines"] == [4]


def test_a_multiplication_sign_the_picture_cannot_tell_from_an_x_is_flagged_in_text_only():
    from core.verify import _dash_glyph_doubt
    assert _dash_glyph_doubt('formula_detail=f"${allowable} x {RATE}",')
    assert _dash_glyph_doubt("area = width x height  # in cells")
    assert not _dash_glyph_doubt("box = x * 2")
    assert not _dash_glyph_doubt("y = a x b")                     # no string or comment: not prose


def test_an_unconfirmed_start_is_reported_for_the_card_without_holding_up_the_report(tmp_path, monkeypatch):
    from PIL import Image
    from core import deepdive
    from core.model import ProgramStore, edges
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "programs"))
    text = "import os\n\n\ndef run():\n    return os.name\n"
    with ProgramStore.create("Edges") as store:
        def file_from(note, name):
            png = tmp_path / f"{name}.png"
            Image.new("RGB", (40, 20), (ord(name[0]) % 250, 2, 2)).save(png)
            evidence = store.add_evidence(png, session_id=store.add_session(mode="burst", note=note))
            aid = store.add_artifact(name, language="Python", transcription=text, evidence_ids=[evidence])
            store.set_status(aid, "structured")
            store.set_verification(aid, {"lines": 5, "flags": []})
            return store.artifact(aid)
        unproven = deepdive.capture_quality(store, file_from("", "a.py"))
        assert unproven["status"] != "rescan" and {i["kind"] for i in unproven["issues"]} >= {"start"}
        proven = deepdive.capture_quality(store, file_from("top_proven", "b.py"))
        assert "start" not in {i["kind"] for i in proven["issues"]}


def test_a_top_proof_never_cancels_a_structural_finding_that_the_start_is_missing(tmp_path, monkeypatch):
    from PIL import Image
    from core import deepdive
    from core.model import ProgramStore
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "programs"))
    cobol = "       ENVIRONMENT DIVISION.\n       DATA DIVISION.\n       PROCEDURE DIVISION.\n           STOP RUN.\n"
    with ProgramStore.create("Structure") as store:
        png = tmp_path / "f.png"
        Image.new("RGB", (40, 20), (9, 9, 9)).save(png)
        evidence = store.add_evidence(png, session_id=store.add_session(mode="burst", note="top_proven"))
        aid = store.add_artifact("PAY.cbl", language="COBOL", transcription=cobol, evidence_ids=[evidence])
        store.set_status(aid, "structured")
        store.set_verification(aid, {"lines": 4, "flags": []})
        q = deepdive.capture_quality(store, store.artifact(aid))
        assert q["status"] == "rescan" and any(i["kind"] == "partial" for i in q["issues"])


def test_a_pixel_scroll_estimate_that_calls_unrelated_rows_a_repeat_is_rejected():
    """On repetitive content the image alignment can claim a screenshot mostly repeats the text above it. If the rows it calls repeats do
    not read like that text, the claim is dropped and the screenshot is kept whole instead of losing its new rows."""
    from core.analysis import _guided_agrees
    row = lambda table, i: f"INSERT INTO {table} VALUES ('{table[-1].upper()}-{i:04d}', {i * 7}, 'x{i}');"
    earlier = [row("mun_a", i) for i in range(40)]                      # what the text already holds
    new_rows = [row("mun_b", i) for i in range(4)]
    # a real overlap: the screenshot's first 35 rows are the last 35 rows of the text, then 4 new rows
    real = earlier[5:] + new_rows
    assert _guided_agrees(real, (earlier + new_rows, 4))
    # a false one: the screenshot is all new rows, yet the estimate calls 35 of them repeats
    unrelated = [row("mun_b", i + 100) for i in range(39)]
    assert not _guided_agrees(unrelated, (earlier + unrelated[35:], 4))
    # too few repeated rows to judge: accepted as before
    assert _guided_agrees(real, (earlier + new_rows, 36))


def test_the_reviewers_concerns_stop_reopening_a_file_once_its_review_is_closed(tmp_path, monkeypatch):
    """One pass: before the analysis starts a concern is a question for the person; once the analysis has started (every question was
    answered) the same concern is a note, still in the report's open items, and no longer puts the file back in 'needs attention'."""
    from PIL import Image
    from core import deepdive
    from core.model import ProgramStore
    from core.model.line_review import items
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "programs"))
    text = "import os\n\n\ndef run():\n    return os.name\n"
    with ProgramStore.create("One pass") as store:
        png = tmp_path / "f.png"
        Image.new("RGB", (40, 20), (7, 7, 7)).save(png)
        evidence = store.add_evidence(png, session_id=store.add_session(mode="burst", note="top_proven"))
        aid = store.add_artifact("a.py", language="Python", transcription=text, evidence_ids=[evidence])
        store.set_status(aid, "structured")
        store.set_verification(aid, {"lines": 5, "flags": []})
        store.set_meta("deepdive", {str(aid): {"hash": deepdive._hash(text), "capture_concerns": [{"line": 5, "reason": "looks wrong"}]}})
        art = store.artifact(aid)
        assert deepdive.current_concerns(store, art) and any("looks wrong" in r for i in items(store, art) for r in i["reasons"])
        assert deepdive.capture_quality(store, art, deepdive.current_concerns(store, art))["status"] == "rescan"
        deepdive.close_review(store, [aid])
        art = store.artifact(aid)
        assert deepdive.review_closed(store, art) and deepdive.current_concerns(store, art) == []
        assert not any("looks wrong" in r for i in items(store, art) for r in i["reasons"])
        assert deepdive.all_concerns(store, art)                                     # still there for the report
        quality = deepdive.capture_quality(store, art, deepdive.current_concerns(store, art))
        assert quality["status"] != "rescan" and any(i["kind"] == "concern" for i in quality["issues"])


def test_accept_all_clears_structural_findings_and_batch_defers_per_file_starts(tmp_path):
    from core.model import confirmed
    class S:
        def __init__(self): self.m = {}
        def get_meta(self, k): return self.m.get(k)
        def set_meta(self, k, v): self.m[k] = v
    st, art = S(), {"id": 7, "transcription": "A\nB"}
    confirmed.accept_reasons(st, art, ["paragraph 5120 is missing"])
    assert confirmed.accepted_reasons(st, art) == {"paragraph 5120 is missing"}
    assert confirmed.accepted_reasons(st, dict(art, transcription="A\nC")) == set()


def test_accept_everything_leaves_a_file_with_every_kind_of_flag_no_longer_needing_attention(tmp_path, monkeypatch):
    from PIL import Image
    from core import deepdive
    from core.model import ProgramStore
    from core.model.accept import accept_all
    from core.model.line_review import items
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "programs"))
    cobol = "       ENVIRONMENT DIVISION.\n       DATA DIVISION.\n       PROCEDURE DIVISION.\n           MOVE A TO B [CUT OFF]\n           STOP RUN.\n"
    with ProgramStore.create("Accept") as store:
        png = tmp_path / "f.png"
        Image.new("RGB", (40, 20), (5, 9, 9)).save(png)
        evidence = store.add_evidence(png, session_id=store.add_session(mode="burst", note=""))
        aid = store.add_artifact("PAY.cbl", language="COBOL", transcription=cobol, evidence_ids=[evidence])
        store.set_status(aid, "structured")
        store.set_verification(aid, {"lines": 5, "flags": [{"line": 3, "reason": "character count differs from the screenshot"}]})
        before = deepdive.capture_quality(store, store.artifact(aid))
        assert before["status"] == "rescan" and {"partial", "cut"} <= {i["kind"] for i in before["issues"]}
        accept_all(store, store.artifact(aid))
        art = store.artifact(aid)
        after = deepdive.capture_quality(store, art, deepdive.current_concerns(store, art))
        assert after["status"] != "rescan", after["issues"]
        assert not items(store, art)
        art["transcription"] += "x"                                    # a changed file is a different file: acceptance does not carry over
        assert deepdive.capture_quality(store, art)["status"] == "rescan"


def test_requested_platforms_resolve_from_names_and_file_extensions():
    from core import technology_support as t
    want = {("Micro Focus COBOL", ""): "Micro Focus COBOL", ("microfocus cobol", ""): "Micro Focus COBOL", ("", "a.cob"): "COBOL",
            ("CICS application", ""): "CICS", ("CICS code", ""): "CICS", ("", "m.bms"): "CICS", ("Assembly", ""): "Assembler",
            ("", "a.mac"): "Assembler", ("ASP.NET Web Forms", ""): "Web Forms", ("ASP.NET forms", ""): "Web Forms",
            ("", "a.ascx"): "ASP.NET", ("", "a.master"): "ASP.NET", ("PowerBuilder app", ""): "PowerBuilder", ("", "w.srw"): "PowerBuilder",
            ("", "d.srd"): "PowerBuilder", ("", "x.pbl"): "PowerBuilder"}
    for (label, name), tech in want.items():
        found = t.resolve(name, label)
        assert found and found["technology"] == tech, (label, name, found and found["technology"])
    assert "Micro Focus" in t.analysis_context("", "Micro Focus COBOL")


def test_a_fix_may_not_add_lines_and_the_readers_are_told_to_report_only_what_is_visible():
    from core import analysis
    assert analysis.fix_looks_complete("A\nB\nC", "A\nB\nC\nD")
    assert analysis.fix_looks_complete("A\nB\nC", "A\nB\nX") is None
    for prompt in (analysis.EXTRACT_SYSTEM_PROMPT, analysis.EXTRACT_JSON_SYSTEM_PROMPT, analysis.EXTRACT_PLAIN_SYSTEM_PROMPT):
        assert "REPORT ONLY WHAT YOU SEE" in prompt


def test_a_scroll_estimate_one_repeated_block_out_is_rejected_and_never_drops_earlier_lines():
    """RPG routines repeat an 18-line block with only the name, number and limit changed. A pixel scroll estimate can land one block
    out; the rows it calls repeats then differ from the text only in those few lines. They must still be called different."""
    from core.analysis import _guided_agrees, _pixel_guided_checked
    def block(n):
        return [f"      * CHG-199{n}-10{n}: DISTRICT{n} treasury cap.", f"     C     R0{n}           BEGSR",
                "     C                   EVAL      Status = 'ACCEPT'", f"     C                   IF        Amount > {18000 + 750 * n}",
                "     C                   EVAL      Status = 'DEFER'", "     C                   ENDIF",
                "     C                   IF        Priority = 'TREASURY'", "     C                   EVAL      Status = 'ACCEPT'",
                "     C                   ENDIF", "      * FIX-1999: old feed supports whole currency units only.",
                "     C                   IF        Channel = 'BANK-V1'", "     C                   EVAL      LegacyWhole = %INT(Amount)",
                "     C                   EVAL      ExportAmount = LegacyWhole", "     C                   ENDIF",
                "      * INC-2002: operators requested account in spool diagnostics.",
                "     C                   EVAL      Reason = Status + ':' + Account", "     C                   DSPLY                   Reason",
                "     C                   ENDSR"]
    merged = block(0) + block(1) + block(2)[:5]
    screen = block(1)[3:] + block(2) + block(3)[:6]             # the true screen: starts in R01, runs through R02 into R03
    wrong = (merged + screen[-8:], 8)                           # the estimate: "only 8 rows are new", so 36 rows are repeats
    assert not _guided_agrees(screen, wrong)
    overlap = block(2)                                          # a true overlap: the screen's first 18 rows are the text's last 18
    truth = (block(0) + block(1) + overlap + block(3)[:6], 6)
    assert _guided_agrees(overlap + block(3)[:6], truth)


def test_screens_added_for_the_top_of_a_file_go_above_the_text_not_after_its_end():
    """Capturing the first screens of a file again (the part a capture missed) must place them before the lines already read, even when
    one overlapping line was read a little differently by the two screenshots."""
    from core.analysis import _prepend
    head = [f"         DFHMDF POS=({n},2),LENGTH={n + 6},INITIAL='LINE NUMBER {n}',ATTRB=ASKIP" for n in range(1, 31)]
    existing = head + ["         DFHMSD TYPE=FINAL", "         END"]
    top = ["MUNMAP   DFHMSD TYPE=&SYSPARM,MODE=INOUT,LANG=COBOL,               X", "               STORAGE=AUTO,TIOAPFX=YES"] + list(head)
    top[12] = top[12].replace("LINE NUMBER", "LlNE NUMBER")   # one overlapping line read a little differently
    got = _prepend(existing, top)
    assert got is not None and got[:2] == top[:2] and got[2:] == existing and len(got) == len(existing) + 2


def test_a_scroll_gap_is_still_flagged_when_the_final_text_was_respaced_after_stitching():
    """The gap was recorded with the two lines either side as stitched; the final text can carry them with other leading spaces. The
    flag must not be lost for want of an exact match (128 missing lines once went unflagged this way)."""
    from core.verify import _break_line
    lines = ["PAGE 05", " * CHG-2002-1006: EXCEPTION PAGE 06.", " X070     DFHMDF POS=(11,12),LENGTH=1", "ATTRB=ASKIP"]
    assert _break_line(lines, "* CHG-2002-1006: EXCEPTION PAGE 06.", "X070     DFHMDF POS=(11,12),LENGTH=1") == 2
    twice = ["A", "ATTRB=ASKIP", "ATTRB=ASKIP", "B", "ATTRB=ASKIP"]
    assert _break_line(twice, "ATTRB=ASKIP", "ATTRB=ASKIP") == 2
    assert _break_line(["A", "B"], "X", "never there at all") is None


def test_two_identical_substantial_lines_in_a_row_are_questioned_but_never_changed():
    from core.verify import identical_neighbours, summarize
    rows = ["INSERT INTO district_policy VALUES ('VALLEYFORD', 2020, 2750, 35550, 15, 1, 1);",
            "INSERT INTO district_policy VALUES ('WESTHAVEN', 1996, 2875, 34500, 5, 2, 1);",
            "INSERT INTO district_policy VALUES ('WESTHAVEN', 1996, 2875, 34500, 5, 2, 1);",
            "INSERT INTO district_policy VALUES ('WESTHAVEN', 1997, 2875, 34700, 5, 2, 1);"]
    assert identical_neighbours(rows) == {2, 3}
    assert identical_neighbours(["END-IF", "END-IF", "           MOVE A TO B", "           MOVE A TO B"]) == set()   # short, ordinary repeats
    code = "\n".join(rows)
    out = summarize(code, {l: "verified" for l in rows})
    assert [f["line"] for f in out["flags"]] == [2, 3] and "neighbour" in out["flags"][0]["reason"]
    assert code == "\n".join(rows)                                                                                # nothing was rewritten


def test_screenshots_whose_click_calibration_rounded_to_another_character_are_moved_back_only_with_the_lines_to_prove_it():
    from core.analysis import _align_clicked_origins
    lines = [f"X{n:02d}R     DFHMDF POS=({n},12),LENGTH=12,ATTRB=(UNPROT,IC)" for n in range(20)]
    def meta(x):
        return {"spacing": {"calibrated": True, "calibration": {"source_x": x, "pitch": 12.7}}}
    good = "\n".join(lines[:12])
    shifted = "\n".join(" " + l for l in lines[5:15])                         # read one column to the right
    parts = [good, good, good, good, shifted]
    metas = [meta(67.1)] * 4 + [meta(54.4)]
    out = _align_clicked_origins(parts, metas)
    assert out[:4] == parts[:4] and out[4] == "\n".join(lines[5:15])
    # the odd screenshot shares too few lines with the majority to be sure: it is left as it was read
    lonely = "\n".join(" " + l for l in lines[12:20])
    assert _align_clicked_origins([good] * 4 + [lonely], [meta(67.1)] * 4 + [meta(54.4)])[4] == lonely
    # too few screenshots to call any of them the odd one: nothing changes
    assert _align_clicked_origins(parts[:2] + [shifted], [meta(67.1)] * 2 + [meta(54.4)]) == parts[:2] + [shifted]
