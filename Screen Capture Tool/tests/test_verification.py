"""Transcription verification: pixel word check, zoomed re-read, editor line numbers, sideways pieces, summaries."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from core import colfix, verify
from core.analysis import _normalize_extract, merge_verified, verify_screenshot
from render import render_code

COBOL = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. AIDCHK.
000300 DATA DIVISION.
000400 WORKING-STORAGE SECTION.
000500 01  WS-TOTAL            PIC S9(9)V99 COMP-3.
000600 01  WS-DISTRICT-ID      PIC X(6).
000700 01  WS-COUNT            PIC 9(4)     VALUE ZERO.
000800 PROCEDURE DIVISION.
000900     MOVE ZERO TO WS-TOTAL
001000     ADD 1 TO WS-COUNT
001100     DISPLAY 'TOTAL ' WS-TOTAL
001200     STOP RUN."""


@pytest.fixture()
def shot(tmp_path):
    return render_code(COBOL, tmp_path / "c.png", font_size=18)


# ── pixel word check ───────────────────────────────────────────────────────────

def test_correct_transcription_is_verified(shot):
    c = colfix.check(shot, COBOL)
    assert c["grid"] and c["status"] == ["verified"] * 12


def test_dropped_character_is_a_mismatch(shot):
    bad = COBOL.replace("WS-DISTRICT-ID", "WS-DISTRCT-ID")
    c = colfix.check(shot, bad)
    i = bad.split("\n").index(next(l for l in bad.split("\n") if "DISTRCT" in l))
    assert c["status"][i] == "mismatch" and i in c["rows"]
    assert c["status"].count("verified") == 11


def test_no_grid_means_unchecked(tmp_path):
    from PIL import Image
    p = tmp_path / "blank.png"
    Image.new("RGB", (400, 200), (255, 255, 255)).save(p)
    c = colfix.check(p, "hello world\nfoo")
    assert not c["grid"] and c["status"] == ["unchecked", "unchecked"]


def test_cut_lines_are_marked_cut(shot):
    t = COBOL.split("\n")
    t[-1] = "001200     STOP [CUT OFF]"
    assert colfix.check(shot, "\n".join(t))["status"][-1] == "cut"


def test_underscores_do_not_split_words(tmp_path):
    src = "BEGIN\n  IF v_total > 0 THEN\n    x := 1;\n  END IF;\n  SELECT a INTO :WS_TOTAL\nEND;\nfoo bar baz"
    png = render_code(src, tmp_path / "u.png", font_size=16)
    assert set(colfix.check(png, src)["status"]) == {"verified"}


# ── zoomed re-read ─────────────────────────────────────────────────────────────

class _Msg:
    def __init__(self, text):
        self.content = [type("B", (), {"text": text})()]


class FakeClient:
    def __init__(self, lines):
        self.lines, self.calls = lines, 0
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        n = sum(1 for c in kw["messages"][0]["content"] if c["type"] == "image")
        return _Msg(json.dumps({"lines": [{"text": t, "overlay": False} for t in self.lines[:n]]}))


def test_reread_fixes_a_dropped_character(shot):
    bad = COBOL.replace("WS-DISTRICT-ID", "WS-DISTRCT-ID")
    client = FakeClient(["000600 01  WS-DISTRICT-ID      PIC X(6)."])
    v = verify_screenshot(client, shot, bad)
    assert client.calls == 1
    assert v["text"] == COBOL and v["reread"] == 1 and "reread" in v["status"]


def test_wrong_reread_is_not_accepted(shot):
    bad = COBOL.replace("WS-DISTRICT-ID", "WS-DISTRCT-ID")
    v = verify_screenshot(FakeClient(["000600 01  WS-DISTRCTT-IDD PIC X(6)."]), shot, bad)
    assert v["text"] == bad and "mismatch" in v["status"]


def test_no_client_no_reread(shot):
    bad = COBOL.replace("WS-DISTRICT-ID", "WS-DISTRCT-ID")
    v = verify_screenshot(None, shot, bad)
    assert v["text"] == bad and v["status"].count("mismatch") == 1


def test_reread_can_be_switched_off(shot, monkeypatch):
    monkeypatch.setenv("CODESNAP_REREAD", "0")
    client = FakeClient(["000600 01  WS-DISTRICT-ID      PIC X(6)."])
    verify_screenshot(client, shot, COBOL.replace("WS-DISTRICT-ID", "WS-DISTRCT-ID"))
    assert client.calls == 0


def test_verified_text_makes_no_call(shot):
    client = FakeClient([])
    v = verify_screenshot(client, shot, COBOL)
    assert client.calls == 0 and v["text"] == COBOL


# ── editor line numbers ────────────────────────────────────────────────────────

def test_valid_numbers():
    lines = ["a", "b", "", "c", "d"]
    assert verify.valid_numbers([10, 11, 12, 13, 14], lines) == [10, 11, 12, 13, 14]
    assert verify.valid_numbers(["10", "11", "12", "13", "14"], lines) == [10, 11, 12, 13, 14]
    assert verify.valid_numbers([], lines) == []
    assert verify.valid_numbers([1, 2, 3], lines) == []              # wrong length
    assert verify.valid_numbers([4, 9, 2, 7, 1], lines) == []        # misread gutter
    assert verify.valid_numbers([None] * 5, lines) == []             # no gutter visible
    seq = ["000100 X.", "000200 Y.", "000300 Z."]
    assert verify.valid_numbers([100, 200, 300], seq) == []          # COBOL sequence numbers, not a gutter


def test_sticky_scroll_headers_are_allowed():
    # VS Code keeps the enclosing lines pinned at the top: a few jumps, then consecutive rows
    nums = [2, 27, 32, 33] + list(range(50, 80))
    lines = ["x"] * len(nums)
    assert verify.valid_numbers(nums, lines) == nums


def _frames(lines, spans):
    return ["\n".join(lines[a:b]) for a, b in spans], [{"numbers": list(range(a + 1, b + 1))} for a, b in spans]


_W = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec "
      "romeo sierra tango uniform victor whiskey xray yankee zulu").split()
SRC = [f"    {_W[i % 26]}_{_W[(i * 7) % 26]} = {_W[(i * 3) % 26]}({i}, {_W[(i * 11) % 26]})  # {_W[(i * 5) % 26]}"
       for i in range(1, 61)]


def test_merge_by_numbers_orders_and_dedups():
    parts, metas = _frames(SRC, [(0, 25), (20, 45), (40, 60)])
    code, _, notes, _ = merge_verified(parts, metas)
    assert code.split("\n") == SRC and notes["numbers"] and notes["gaps"] == []


def test_merge_by_numbers_reports_gaps():
    parts, metas = _frames(SRC, [(0, 20), (30, 60)])
    code, _, notes, st = merge_verified(parts, metas)
    assert notes["gaps"] == [[21, 30]]
    s = verify.summarize(code, st, notes)
    assert "Never on screen (editor source): lines 21–30" in s["headline"]


def test_numbered_frame_reports_final_and_editor_line_separately():
    parts = ["open\ncalculate\nclose"]
    metas = [{"numbers": [5, 6, 7], "status": ["verified", "verified", "mismatch"]}]
    code, _, notes, st = merge_verified(parts, metas)
    s = verify.summarize(code, st, notes, read_code=code)
    assert s["flags"] == [{"line": 3, "source_line": 7, "text": "close",
                            "reason": verify.REASONS["mismatch"]}]
    assert s["gap_coordinate"] == "editor"


def test_duplicate_lines_keep_their_own_screenshot_status():
    code = "start\nrepeat\nmiddle\nrepeat\nend"
    meta = {"status": ["verified", "mismatch", "verified", "verified", "verified"]}
    merged, _, notes, st = merge_verified([code], [meta])
    s = verify.summarize(merged, st, notes, read_code=merged)
    assert [(f["line"], f["text"]) for f in s["flags"]] == [(2, "repeat")]


def test_final_line_numbers_are_recounted_after_repair_inserts_a_line():
    read = "start\none\ntwo\nwrong\nend"
    meta = {"numbers": [10, 11, 12, 13, 14],
            "status": ["verified", "verified", "verified", "mismatch", "verified"]}
    stitched, _, notes, st = merge_verified([read], [meta])
    final = "header\n" + stitched
    s = verify.summarize(final, st, notes, read_code=stitched)
    assert [(f["line"], f.get("source_line"), f["text"]) for f in s["flags"]] == [
        (1, None, "header"), (5, 13, "wrong")]


def test_screens_added_out_of_order_are_placed_by_number():
    parts, metas = _frames(SRC, [(30, 60), (0, 35)])
    assert merge_verified(parts, metas)[0].split("\n") == SRC


def test_sticky_rows_land_at_their_own_number():
    parts, metas = _frames(SRC, [(0, 30)])
    p2 = "\n".join([SRC[1], SRC[4]] + SRC[28:60])
    m2 = {"numbers": [2, 5] + list(range(29, 61))}
    assert merge_verified(parts + [p2], metas + [m2])[0].split("\n") == SRC


def test_wrapped_continuation_rows_are_joined():
    parts = ["\n".join(SRC[:3]) + "\n" + "      and more"]
    metas = [{"numbers": [1, 2, 3, None]}]
    code, _, notes, st = merge_verified(parts, metas)
    assert code.split("\n")[-1] == SRC[2] + " and more" and notes["wrapped"] == 1
    assert verify.summarize(code, st, notes)["flagged"] == 1


def test_disagreeing_numbers_fall_back_to_overlap():
    parts, metas = _frames(SRC, [(0, 25), (20, 45)])
    metas[1]["numbers"] = list(range(1, 26))       # second screen misnumbered: every line conflicts
    code, _, notes, _ = merge_verified(parts, metas)
    assert not notes["numbers"] and code.split("\n") == SRC[:45]


def test_missing_numbers_on_one_screen_fall_back():
    parts, metas = _frames(SRC, [(0, 25), (20, 45)])
    metas[1] = {}
    code, _, notes, _ = merge_verified(parts, metas)
    assert not notes["numbers"] and code.split("\n") == SRC[:45]


# ── sideways-scrolled screenshots ──────────────────────────────────────────────

WIDE = ["<html>", "<body>", "<table>",
        '  <tr bgcolor="#DDDDDD"><td><b>District</b></td><td><b>Pupil Units</b></td><td><b>Gross Aid</b></td></tr>',
        "  <tr><td>000625 ST PAUL</td><td>34,112.500</td><td>$312,448,120.00</td><td>$31,244,812.00</td></tr>",
        "  <tr><td>000001 AITKIN</td><td>1,020.250</td><td>$9,388,201.00</td><td>$938,820.10</td></tr>",
        "</table>", '<p class="hint">Last updated 06/14/2004 &copy; Department of Education. Email support</p>',
        "</body>", "</html>"]


def _view(lines, left, width):
    return "\n".join((l[left:left + width] + (" [CUT OFF]" if len(l) > left + width else "")).rstrip() for l in lines)


def test_sideways_pieces_join_instead_of_being_appended():
    left, right = _view(WIDE, 0, 70), _view(WIDE, 45, 70)
    code, _, notes, _ = merge_verified([left, right])
    assert code.split("\n") == WIDE and notes["sideways"] >= 3


def test_sideways_pieces_join_by_line_number():
    left, right = _view(WIDE, 0, 70), _view(WIDE, 45, 70)
    n = {"numbers": list(range(1, len(WIDE) + 1))}
    code, _, notes, _ = merge_verified([left, right], [n, dict(n)])
    assert code.split("\n") == WIDE and notes["numbers"]


def test_line_never_seen_whole_is_flagged():
    code, _, notes, st = merge_verified([_view(WIDE, 0, 70)])
    s = verify.summarize(code, st, notes)
    assert s["flagged"] == 4 and all("word wrap" in f["reason"] for f in s["flags"])


def test_join_sideways():
    assert verify.join_sideways("  abc = compute(total, [CUT OFF]", "compute(total, rate)") == "  abc = compute(total, rate)"
    assert verify.join_sideways("short", "unrelated text here") is None
    assert verify.join_sideways("  abc = compute(total, rate)", "compute(total") == "  abc = compute(total, rate)"


# ── summaries ──────────────────────────────────────────────────────────────────

def test_summary_counts_and_edited_lines():
    st = {"a = 1": "verified", "b = 2": "reread", "c = 3": "unchecked", "d = 4": "mismatch"}
    s = verify.summarize("a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n", st, {}, read_code="a = 1\nb = 2\nc = 3\nd = 4\nE = 5")
    assert (s["lines"], s["verified"], s["reread"], s["unchecked"], s["flagged"]) == (5, 1, 1, 1, 2)
    assert {f["line"] for f in s["flags"]} == {4, 5}
    assert s["headline"].startswith("2 of 5 lines verified")


def test_normalize_extract_keeps_numbers_aligned():
    raw = json.dumps({"raw_transcription": ["", "a = 1", "b = 2", "c = 3", ""], "corrections_applied": [],
                      "line_numbers": [9, 10, 11, 12, 13]})
    out = _normalize_extract(raw)
    assert out["raw"] == "a = 1\nb = 2\nc = 3" and out["numbers"] == [10, 11, 12]
    assert _normalize_extract(json.dumps({"raw_transcription": ["x"], "corrections_applied": []}))["numbers"] == []


# ── end to end through the cache and the program ───────────────────────────────

def test_cache_sidecar_and_program_record(tmp_path, shot, monkeypatch):
    import core.analysis as A
    from core.model import ProgramStore
    from core.model.ingest import ingest_capture

    def fake_structured(client, path):
        return {"raw": COBOL, "corrections": [], "verify": {"grid": True, "status": ["verified"] * 12,
                                                            "reread": 0, "numbers": []}}
    monkeypatch.setattr(A, "extract_structured", fake_structured)
    cache = tmp_path / "cache"
    A.extract_to_cache(None, shot, cache)
    meta = A.verify_for(shot, cache)
    assert meta["status"] == ["verified"] * 12
    code, _, notes, st = A.merge_verified([COBOL], [meta])
    v = verify.summarize(code, st, notes, read_code=code)
    assert v["verified"] == 12
    store = ProgramStore.create("verify-test", root=tmp_path / "programs")
    with store:
        aid = ingest_capture(store, None, [shot], {"code": code, "language": "COBOL", "errors": "None",
                                                   "verification": v})
        assert store.verification(aid)["verified"] == 12
        store.delete_artifact(aid)
        assert store.verification(aid) is None
