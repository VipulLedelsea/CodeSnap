from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("tree_sitter")

from core import feedback
from core import deepdive as DD
from core.assess import run_assessment
from core.diagrams import all_diagrams
from core.model import ProgramStore
from core.model import corrections as C
from core.report import build
from core.verify import REASONS, headline

from test_linker import COBOL, LEGACY, add

SEC = Path(__file__).resolve().parent / "samples" / "security"
CALC = (COBOL / "AIDCALC.cbl").read_text()


@pytest.fixture
def program(tmp_path):
    store = ProgramStore.create("Fix", root=tmp_path)
    for f in ("AIDCALC.cbl", "AIDINQ.cbl", "AIDREC.cpy", "AIDMAP.bms", "AIDJOB.jcl"):
        add(store, f, (COBOL / f).read_text(), "COBOL", f.split(".")[1])
    for f, l, e in (("StudentLookup.aspx.cs", "C#", "cs"), ("STUPAY.cbl", "COBOL", "cbl"), ("web.config", "XML", "config")):
        add(store, f, (SEC / f).read_text(), l, e)
    add(store, "AIDSCHEMA.sql", (LEGACY / "AIDSCHEMA.sql").read_text(), "SQL", "sql")
    run_assessment(store)
    yield store
    store.close()


def calls(store, frm):
    ids = C._subtree(store, store.entity_by_key(frm)["id"])
    return {store.entity(r["to_id"])["name"] for r in store.relations("calls") if r["from_id"] in ids}


def test_relation_correction_survives_recapture(program):
    assert "AIDAUDIT" in calls(program, "program:AIDCALC")
    out = feedback.apply(program, [
        {"op": "relation.delete", "payload": {"kind": "calls", "from_key": "program:AIDCALC", "to_key": "program:AIDAUDIT"}},
        {"op": "relation.add", "payload": {"kind": "calls", "from_key": "program:AIDCALC", "to_name": "AIDERR"}}],
        note="AIDCALC calls AIDERR, not AIDAUDIT")
    assert not out["warnings"]
    assert calls(program, "program:AIDCALC") >= {"AIDERR"} and "AIDAUDIT" not in calls(program, "program:AIDCALC")
    add(program, "AIDCALC.cbl", CALC, "COBOL", "cbl")
    run_assessment(program)
    assert "AIDAUDIT" not in calls(program, "program:AIDCALC") and "AIDERR" in calls(program, "program:AIDCALC")
    cls = next(d for d in all_diagrams(program) if d["id"] == "class")
    titles = {n["id"]: n["title"] for n in cls["nodes"]}
    edges = {(titles[e["from"]], titles[e["to"]]) for e in cls["edges"]}
    assert ("AIDCALC", "AIDERR") in edges and ("AIDCALC", "AIDAUDIT") not in edges


def test_no_student_data_correction(program):
    before = [f for f in program.findings("privacy") if "STUDENT-REC" in f["title"]]
    assert before
    out = feedback.apply(program, [{"op": "entity.set_attrs", "payload": {"key": "field:STUPAY.STUDENT-REC", "attrs": {"no_pii": True}}}],
                         note="test data only")
    assert not [f for f in program.findings("privacy") if "STUDENT-REC" in f["title"]]
    assert any("findings" in i.lower() or "score" in i.lower() or "→" in i for i in out["impact"])
    run_assessment(program)
    assert not [f for f in program.findings("privacy") if "STUDENT-REC" in f["title"]]


def test_not_a_secret_and_dismiss_survive_rescan(program):
    cfg = next(e for e in program.entities("config_item") if (e.get("attrs") or {}).get("hardcoded_secret"))
    feedback.apply(program, [{"op": "entity.set_attrs", "payload": {"key": cfg["key"], "attrs": {"hardcoded_secret": False}}}])
    assert not any(f["rule"] == "SEC-CRED" and cfg["name"] in f["detail"] for f in program.findings("security"))
    f = next(x for x in program.findings("security") if x["rule"] == "SEC-SQLI")
    feedback.apply(program, [{"op": "finding.status", "payload": {"sig": C.finding_sig(f), "status": "dismissed"}}])
    run_assessment(program)
    assert next(x for x in program.findings("security") if x["title"] == f["title"])["status"] == "dismissed"


def test_severity_correction_changes_scores(program):
    comp = lambda: next(c for c in program.get_meta("assessment")["components"] if c["name"] == "StudentLookup.aspx.cs")
    before = comp()["scores"]["security"]["score"]
    crits = [f for f in program.findings("security") if f["severity"] == "critical" and "StudentLookup" in f["title"]]
    out = feedback.apply(program, [{"op": "finding.severity", "payload": {"sig": C.finding_sig(f), "severity": "low"}} for f in crits])
    assert comp()["scores"]["security"]["score"] > before
    assert out["impact"] and not out["impact"][0].startswith("No change"), out["impact"]


def test_delete_entity_survives_reingest_and_undo_restores(program):
    r = feedback.apply(program, [{"op": "entity.delete", "payload": {"key": "paragraph:AIDCALC.0000-MAIN.2000-CALC-AID"}}])
    cid = r["applied"][0]["id"]
    assert program.entity_by_key("paragraph:AIDCALC.0000-MAIN.2000-CALC-AID") is None
    add(program, "AIDCALC.cbl", CALC, "COBOL", "cbl")
    assert program.entity_by_key("paragraph:AIDCALC.0000-MAIN.2000-CALC-AID") is None
    feedback.undo(program, cid)
    e = program.entity_by_key("paragraph:AIDCALC.0000-MAIN.2000-CALC-AID")
    assert e is not None and program.relations(to_id=e["id"])
    assert not program.correction(cid)["active"]


def test_rename_undo_restores_name(program):
    r = feedback.apply(program, [{"op": "entity.rename", "payload": {"key": "program:AIDCALC", "name": "Temp"}}])
    feedback.undo(program, r["applied"][0]["id"])
    e = program.entity_by_key("program:AIDCALC")
    assert e["name"] == "AIDCALC" and e["origin"] != "corrected"


def test_rename_add_merge(program):
    feedback.apply(program, [{"op": "entity.rename", "payload": {"key": "program:AIDCALC", "name": "AIDCALC (aid calculator)"}}])
    add(program, "AIDCALC.cbl", CALC, "COBOL", "cbl")
    assert program.entity_by_key("program:AIDCALC")["name"] == "AIDCALC (aid calculator)"
    r = feedback.apply(program, [{"op": "entity.add", "payload": {"kind": "external_system", "name": "MDE Data Warehouse"}},
                                 {"op": "relation.add", "payload": {"kind": "writes", "from_key": "program:AIDCALC",
                                                                    "to_key": "external_system:MDE Data Warehouse"}}])
    assert program.entity_by_key("external_system:MDE Data Warehouse")["origin"] == "corrected"
    feedback.undo(program, r["applied"][0]["id"])
    assert program.entity_by_key("external_system:MDE Data Warehouse") is None
    feedback.apply(program, [{"op": "entity.merge", "payload": {"from_key": "table:DISTRICT_AID", "to_key": "table:MDE.DISTRICT_AID"}}])
    with pytest.raises(C.CorrectionError):
        feedback.undo(program, program.corrections()[-1]["id"])


def test_validation_errors(program):
    for op, payload in (("nope", {}), ("entity.rename", {"key": "program:AIDCALC"}), ("finding.status", {"sig": "x", "status": "meh"}),
                        ("relation.add", {"kind": "eats", "from_key": "a", "to_key": "b"}),
                        ("entity.set_attrs", {"key": "program:AIDCALC", "attrs": "x"})):
        with pytest.raises(C.CorrectionError):
            C.validate(op, payload)
    with pytest.raises(C.CorrectionError):
        feedback.apply(program, [{"op": "relation.add", "payload": {"kind": "calls", "from_key": "program:AIDCALC", "to_name": "ZZZNOPE"}}])


def test_report_lists_corrections(program):
    feedback.apply(program, [{"op": "entity.set_attrs", "payload": {"key": "field:STUPAY.STUDENT-REC", "attrs": {"no_pii": True}}}],
                   note="synthetic record")
    r = build(program, rescan=False)
    cov = next(s for s in r["sections"] if s["id"] == "coverage")
    table = next(b for b in cov["blocks"] if b["type"] == "table")
    assert any("no_pii" in row[1] and row[2] == "synthetic record" for row in table["rows"])


def test_source_line_correction_reextracts_and_can_be_undone(program):
    from webapp import server
    art = program.current_artifact("AIDCALC.cbl")
    old = CALC.splitlines()[28]
    new = old.replace("AIDAUDIT", "AIDCHECK")
    verification = {"lines": len(CALC.splitlines()), "verified": len(CALC.splitlines()) - 1, "reread": 0,
                    "confirmed": 0, "joined": 0, "flagged": 1, "unchecked": 0, "gaps": [],
                    "flags": [{"line": 29, "text": old.strip(), "reason": REASONS["mismatch"]}]}
    verification["headline"] = headline(verification)
    program.set_verification(art["id"], verification)
    assert DD.file_state(program, art, DD.capture_quality(program, art)) == "needs_recapture"
    assert server._artifact_summary(program, art)["state"] == "needs_recapture"
    out = feedback.apply(program, [{"op": "artifact.replace_line", "payload": {
        "artifact": "AIDCALC.cbl", "line": 29, "old_text": old, "new_text": new}}], note="manual reading correction")
    assert not out["warnings"]
    current = program.current_artifact("AIDCALC.cbl")
    assert current["transcription"].splitlines()[28] == new
    assert program.verification(art["id"])["manual"] == 1 and not program.verification(art["id"])["flags"]
    assert DD.file_state(program, current, DD.capture_quality(program, current)) == "done"
    assert server._artifact_summary(program, current)["state"] == "done"
    assert "AIDCHECK" in calls(program, "program:AIDCALC") and "AIDAUDIT" not in calls(program, "program:AIDCALC")
    correction_id = out["applied"][0]["id"]
    undone = feedback.undo(program, correction_id)
    assert not undone["warnings"]
    current = program.current_artifact("AIDCALC.cbl")
    assert current["transcription"].splitlines()[28] == old
    assert program.verification(art["id"])["flags"][0]["line"] == 29
    assert DD.file_state(program, current, DD.capture_quality(program, current)) == "needs_recapture"
    assert server._artifact_summary(program, current)["state"] == "needs_recapture"
    assert "AIDAUDIT" in calls(program, "program:AIDCALC") and "AIDCHECK" not in calls(program, "program:AIDCALC")


def test_source_correction_keeps_unrelated_recapture_issues(program):
    art = program.current_artifact("AIDCALC.cbl")
    old = CALC.splitlines()[2]
    new = old + " REVIEWED"
    verification = {"lines": len(CALC.splitlines()), "verified": len(CALC.splitlines()) - 2, "reread": 0,
                    "confirmed": 0, "joined": 0, "flagged": 2, "unchecked": 0, "gaps": [], "flags": [
                        {"line": 3, "text": old.strip(), "reason": REASONS["mismatch"]},
                        {"line": 10, "text": CALC.splitlines()[9].strip(), "reason": REASONS["rows"]}]}
    verification["headline"] = headline(verification)
    program.set_verification(art["id"], verification)
    program.set_meta("deepdive", {str(art["id"]): {"hash": DD._hash(art["transcription"]), "capture_concerns": [
        {"line": 3, "reason": "the comment was garbled"}, {"line": 11, "reason": "the declaration cannot be right"}]}})
    feedback.apply(program, [{"op": "artifact.replace_line", "payload": {
        "artifact": "AIDCALC.cbl", "line": 3, "old_text": old, "new_text": new}}])
    current = program.current_artifact("AIDCALC.cbl")
    concerns = DD.current_concerns(program, current)
    assert concerns == [{"line": 11, "reason": "the declaration cannot be right"}]
    quality = DD.capture_quality(program, current, concerns)
    assert quality["status"] == "rescan"
    assert {i["kind"] for i in quality["issues"]} >= {"rows", "model"}
    assert program.verification(art["id"])["manual"] == 1
    assert [f["line"] for f in program.verification(art["id"])["flags"]] == [10]


class _Msg:
    def __init__(self, changes):
        self.content = [SimpleNamespace(type="tool_use", name="propose_corrections",
                                        input={"changes": changes, "unclear": None})]
        self.usage = SimpleNamespace(input_tokens=500, output_tokens=80)


class FakeClient:
    def __init__(self, changes):
        self.changes = changes
        self.messages = self
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        return _Msg(self.changes)


def test_interpret_validates_proposals(program):
    client = FakeClient([
        {"op": "relation.delete", "payload": {"kind": "calls", "from_key": "program:AIDCALC", "to_key": "program:AIDAUDIT"},
         "reason": "analyst says AIDAUDIT isn't called"},
        {"op": "entity.delete", "payload": {"key": "program:INVENTED"}},
        {"op": "finding.status", "payload": {"sig": "x", "status": "maybe"}}])
    out = feedback.interpret(program, "AIDCALC does not call AIDAUDIT", client)
    assert [c["op"] for c in out["changes"]] == ["relation.delete"] and len(out["rejected"]) == 2
    assert "AIDCALC" in client.calls[0]["messages"][0]["content"]
    assert calls(program, "program:AIDCALC") >= {"AIDAUDIT"}
    assert any(r["step"] == "interpret_correction" for r in program.runs())


def test_interpret_source_line_correction_includes_exact_source_context(program):
    old = CALC.splitlines()[28]
    new = old.replace("AIDAUDIT", "AIDCHECK")
    client = FakeClient([{"op": "artifact.replace_line", "payload": {
        "artifact": "AIDCALC.cbl", "line": 29, "old_text": old, "new_text": new},
        "reason": "the analyst supplied the correct call target"}])
    out = feedback.interpret(program, "In AIDCALC.cbl line 29, AIDAUDIT should be AIDCHECK", client)
    assert [c["op"] for c in out["changes"]] == ["artifact.replace_line"]
    prompt = client.calls[0]["messages"][0]["content"]
    assert '"artifact": "AIDCALC.cbl"' in prompt and '"line": 29' in prompt and old in prompt


def test_corrections_api(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "programs"))
    from webapp import server
    client = TestClient(server.app)
    slug = client.post("/api/programs", json={"name": "Fix API"}).json()["program"]["slug"]
    with ProgramStore.open(slug) as store:
        add(store, "AIDCALC.cbl", CALC, "COBOL", "cbl")
        add(store, "web.config", (SEC / "web.config").read_text(), "XML", "config")
    client.post(f"/api/programs/{slug}/assessment")
    old_line = CALC.splitlines()[2]
    new_line = old_line.replace("CALCULATION", "CALCULATION REVIEW")
    source = client.post(f"/api/programs/{slug}/corrections", json={"op": "artifact.replace_line", "payload": {
        "artifact": "AIDCALC.cbl", "line": 3, "old_text": old_line, "new_text": new_line}})
    assert source.status_code == 200 and source.json()["impact"][0].startswith("Corrected AIDCALC.cbl line 3")
    with ProgramStore.open(slug) as store:
        assert store.current_artifact("AIDCALC.cbl")["transcription"].splitlines()[2] == new_line
    source_id = source.json()["applied"][0]["id"]
    assert client.post(f"/api/programs/{slug}/corrections/{source_id}/undo").status_code == 200
    r = client.post(f"/api/programs/{slug}/corrections", json={"op": "entity.rename", "payload": {"key": "program:AIDCALC", "name": "Aid calc"}})
    assert r.status_code == 200 and r.json()["impact"]
    assert client.post(f"/api/programs/{slug}/corrections", json={"op": "bad"}).status_code == 400
    hist = client.get(f"/api/programs/{slug}/corrections").json()["corrections"]
    rename = next(c for c in hist if c["op"] == "entity.rename")
    assert rename["description"].startswith("Rename AIDCALC")
    fid = client.get(f"/api/programs/{slug}/findings").json()["findings"][0]["id"]
    client.post(f"/api/programs/{slug}/findings/{fid}/status", json={"status": "dismissed", "note": "known"})
    assert any(c["op"] == "finding.status" for c in client.get(f"/api/programs/{slug}/corrections").json()["corrections"])
    assert client.post(f"/api/programs/{slug}/corrections/{rename['id']}/undo").json()["ok"]
    s = client.get(f"/api/programs/{slug}/entities/search?q=aidcalc").json()["entities"]
    assert s and s[0]["name"] == "AIDCALC" and s[0]["kind"] == "program" and s[0]["relations"]
    monkeypatch.setattr(server, "_client", lambda: FakeClient([{"op": "entity.rename", "payload": {"key": "program:AIDCALC", "name": "X"}}]))
    p = client.post(f"/api/programs/{slug}/corrections/interpret", json={"text": "AIDCALC should be called X"}).json()
    assert p["changes"][0]["op"] == "entity.rename"
    assert client.post(f"/api/programs/{slug}/corrections/interpret", json={"text": ""}).status_code == 400
