import json
from core import analysis, verify
from webapp import session as S


def test_edge_sliver_is_dropped_when_next_screen_covers_it():
    a = "A\nB\nC\nD\nE\n[CUT OFF]"
    b = "D\nE\nF\nG\nH"
    assert "[CUT OFF]" not in analysis.stitch_parts([a, b])
    assert analysis.stitch_parts([a]).endswith("[CUT OFF]")


def test_uniform_frame_shift_is_not_a_conflict():
    code = "\n".join(["    ONE", "      TWO", "    THREE", "    FOUR"])
    good = code
    shifted = "\n".join("    " + l for l in code.split("\n"))
    notes = {}
    verify.spacing_agreement(code, [good, shifted], [{}, {}], notes)
    assert notes["spacing_conflicts"] == []


def test_single_line_disagreement_stays_a_conflict():
    code = "\n".join(["    ONE", "      TWO", "    THREE", "    FOUR"])
    other = code.replace("      TWO", "    TWO")
    notes = {}
    verify.spacing_agreement(code, [code, other], [{}, {}], notes)
    assert notes["spacing_conflicts"] == [2]


def test_area_and_margin_survive_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "PROJECT", tmp_path)
    monkeypatch.setenv('CODESNAP_HOME', str(tmp_path))
    m = S.SessionManager()
    m.configure("0.1,0.1,0.5,0.5", 1)
    again = S.SessionManager()
    assert again.saved()["region"] == "0.1,0.1,0.5,0.5"
    m.configure(None, None)
    assert S.SessionManager().saved()["region"] is None


def test_unmeasured_frame_shifted_as_a_whole_is_corrected_from_measured_lines():
    from core import spacing
    a = ["      * C", "       P1.", "           MOVE A TO B", "           MOVE C TO D", "           MOVE E TO F"]
    b = ["      * C", "       P1.", "           MOVE A TO B", "           MOVE C TO D", "           MOVE E TO F",
         "           MOVE G TO H", "           MOVE I TO J"]
    wrong = ["            MOVE G TO H", "            MOVE I TO J"]
    top = a + [l for l in wrong]
    shifted = ["    " + l for l in a] + ["    " + l for l in b[5:]]
    code = "\n".join(a + b[5:])
    cal = {"spacing": {"calibrated": True, "line_status": ["measured"] * 5}}
    out, notes = spacing.reconcile(code, ["\n".join(a), "\n".join(shifted)], [cal, {"spacing": {"calibrated": False, "line_status": []}}])
    assert out.split("\n")[5] == "           MOVE G TO H"
    assert notes["spacing_conflicts"] == []


def test_confirmed_line_stays_clear_after_rebuild():
    from core.model import confirmed

    class Store:
        def __init__(self): self.m = {}
        def get_meta(self, k, d=None): return self.m.get(k, d)
        def set_meta(self, k, v): self.m[k] = v

    st = Store()
    text = "A\nMOVE X TO Y\nB\nC"
    confirmed.add(st, "f.cbl", text, 2)
    rebuilt = "A\n   MOVE X TO Y\nB\nC\nD"
    flags = [{"line": 2, "reason": "spacing"}, {"line": 4, "reason": "cut"}]
    assert confirmed.keep_unconfirmed(st, "f.cbl", rebuilt, flags) == [{"line": 4, "reason": "cut"}]
    assert confirmed.keep_unconfirmed(st, "other.cbl", rebuilt, flags) == flags


def test_spacing_only_rebuild_keeps_the_deep_review():
    from core import deepdive

    class Store:
        def __init__(self):
            self.m = {"deepdive": {"1": {"hash": "x", "prompt_version": deepdive.PROMPT_VERSION, "name": "f"}}}
            self.arts = {1: {"id": 1, "transcription": "A\n  B\nC", "supersedes_id": None, "status": "structured"},
                         2: {"id": 2, "transcription": "A\n    B\nC", "supersedes_id": 1, "status": "structured", "version": 2}}
        def get_meta(self, k, d=None): return self.m.get(k, d)
        def set_meta(self, k, v): self.m[k] = v
        def artifacts(self): return [self.arts[2]]
        def artifact(self, i): return self.arts.get(i)

    st = Store()
    assert deepdive.pending(st) == []
    assert st.m["deepdive"]["2"]["artifact_id"] == 2
    st.arts[2]["transcription"] = "A\n    B\nD"
    st.m["deepdive"].pop("2")
    assert [a["id"] for a in deepdive.pending(st)] == [2]
