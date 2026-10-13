from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("tree_sitter")

from core.assess import run_assessment, set_inputs
from core.assess.decide import disposition, likelihood, risk_level
from core.assess.scores import score_component, text_metrics
from core.model import ProgramStore

from test_linker import COBOL, LEGACY, add

SEC = Path(__file__).resolve().parent / "samples" / "security"
TODAY = date(2026, 9, 25)


def load(store, sec=True, cobol=True):
    if sec:
        for f, l, e in [("StudentLookup.aspx.cs", "C#", "cs"), ("StudentExport.java", "Java", "java"),
                        ("LEGACY.CPP", "C++", "cpp"), ("STUPAY.cbl", "COBOL", "cbl"), ("web.config", "XML", "config"),
                        ("Lookup.html", "HTML", "html")]:
            add(store, f, (SEC / f).read_text(), l, e)
    if cobol:
        for f in ("AIDCALC.cbl", "AIDINQ.cbl", "AIDREC.cpy", "AIDMAP.bms", "AIDJOB.jcl"):
            add(store, f, (COBOL / f).read_text(), "COBOL", f.split(".")[1])


@pytest.fixture
def mixed(tmp_path):
    store = ProgramStore.create("Mixed", root=tmp_path)
    load(store)
    yield store
    store.close()


def _scores(**vals):
    base = {d: {"score": 90} for d in ("health", "tech_debt", "security", "supportability", "complexity", "coupling")}
    for k, v in vals.items():
        base[k] = {"score": v}
    return base


def test_disposition_rules():
    assert disposition(_scores(), {}, {})["code"] == "retain"
    assert disposition(_scores(security=40), {"sec_high": 3}, {})["code"] == "refactor"
    assert disposition(_scores(supportability=45, tech_debt=80), {}, {})["code"] == "replatform"
    assert disposition(_scores(supportability=30, tech_debt=30), {}, {})["code"] == "rearchitect"
    assert disposition(_scores(), {"no_path": ["ASP.NET Web Forms: legacy"], "no_path_share": 0.7}, {})["code"] == "rearchitect"
    assert disposition(_scores(supportability=60, tech_debt=70), {"cobol_share": 0.9}, {})["code"] == "rehost"
    assert disposition(_scores(tech_debt=50), {}, {"cots": "Vendor package X"})["code"] == "replace"
    assert disposition(_scores(), {}, {"retire": True})["code"] == "retire"
    d = disposition(_scores(supportability=45, tech_debt=80), {}, {})
    assert d["bucket"] == "patch" and any("Supportability 45" in r for r in d["reasons"])


def test_likelihood_and_levels():
    assert likelihood(_scores(security=20))[0] == 5
    assert likelihood(_scores())[0] == 1
    assert [risk_level(s) for s in (25, 15, 8, 3)] == ["critical", "high", "medium", "low"]


def test_text_metrics_skip_comments():
    m = text_metrics("if (a) { x(); }\n// if (b) {}\nwhile (c) {}\ngoto end;\n", "a.c")
    assert m == {"lines": 3, "decisions": 2, "gotos": 1, "family": "cpp"}
    cob = text_metrics("000100     IF A > 1\n000200*    IF B\n000300        GO TO P1.\n", "a.cbl")
    assert cob["decisions"] == 2 and cob["gotos"] == 1


def test_component_factors_explain_scores():
    c = {"artifact": {"status": "validated", "validation_ok": 0, "validation_errors": "L3: error", "artifact_type": "code"},
         "file": {"attrs": {"profile": {"legacy_markers": ["void main"], "dialect": "pre-standard C++ (before ISO C++98)"}}},
         "metrics": {"lines": 300, "decisions": 10, "gotos": 0, "family": "cpp"}, "units": [], "findings": [
             {"id": 1, "category": "security", "severity": "high", "rule": "SEC-SQLI", "title": "SQL", "detail": ""},
             {"id": 2, "category": "eol", "severity": "high", "rule": "EOL", "title": "Pre-standard C++: end of life",
              "detail": "", "refs": {"eol_status": "eol"}}],
         "missing_code": 2, "student_data": False, "fan_out": 0, "fan_in": 0, "shared_writes": set(), "external": set()}
    s = score_component(c)
    assert s["health"]["score"] == 100 - 6
    assert s["tech_debt"]["score"] == 100 - 7 - 20
    assert s["security"]["score"] == 85 and s["supportability"]["score"] == 65
    assert {f["rule"] for f in s["health"]["factors"]} == {"HLT-GAPS"}


def test_program_assessment(mixed):
    a = run_assessment(mixed, today=TODAY)
    assert a["verdict"]["code"] in ("replatform", "refactor", "rearchitect") and a["verdict"]["reasons"]
    comps = {c["name"]: c for c in a["components"]}
    assert comps["AIDCALC.cbl"]["risk"]["level"] == "low" and comps["AIDCALC.cbl"]["disposition"]["code"] == "retain"
    assert comps["Lookup.html"]["disposition"]["code"] == "rearchitect"
    assert comps["StudentLookup.aspx.cs"]["risk"]["level"] == "critical" and comps["StudentLookup.aspx.cs"]["student_data"]
    assert sum(len(cell) for row in a["matrix"]["cells"] for cell in row) == len(a["components"])
    titles = [i["title"] for p in a["roadmap"]["phases"] for i in p["items"]]
    assert "Parameterize SQL" in titles and "Remove hard-coded credentials" in titles and "Confirm business criticality" in titles
    phase1 = next(p for p in a["roadmap"]["phases"] if p["phase"] == "stabilize")
    assert all(i["low"] <= i["high"] for i in phase1["items"])
    assert a["roadmap"]["total"]["low"] > 0 and a["roadmap"]["unit"] == "person-weeks"
    assert mixed.get_meta("assessment")["verdict"] == a["verdict"]


def test_every_score_deduction_is_explained(mixed):
    a = run_assessment(mixed, today=TODAY)
    for c in a["components"]:
        for dim, s in c["scores"].items():
            assert abs(s["score"] - max(0, 100 + sum(f["points"] for f in s["factors"]))) <= 1 or s["score"] == 0


def test_staff_inputs_change_impact_and_disposition(mixed):
    run_assessment(mixed, today=TODAY)
    set_inputs(mixed, {"components": {"AIDCALC.cbl": {"impact": 5}, "LEGACY.CPP": {"retire": "report no longer used"}}})
    a = run_assessment(mixed, scan=False)
    comps = {c["name"]: c for c in a["components"]}
    assert comps["AIDCALC.cbl"]["risk"]["impact"] == 5 and comps["AIDCALC.cbl"]["risk"]["impact_source"] == "staff"
    assert comps["LEGACY.CPP"]["disposition"]["code"] == "retire"
    assert "business criticality not entered" not in " ".join(a["confidence"]["notes"])
    set_inputs(mixed, {"components": {"AIDCALC.cbl": {}}})
    assert "AIDCALC.cbl" not in mixed.get_meta("assessment_inputs")["components"]


def test_dismissed_findings_raise_scores(mixed):
    a = run_assessment(mixed, today=TODAY)
    before = next(c for c in a["components"] if c["name"] == "LEGACY.CPP")["scores"]["security"]["score"]
    for f in mixed.findings("security"):
        if f["evidence"][0]["file"] == "LEGACY.CPP":
            mixed.set_finding_status(f["id"], "dismissed")
    after = next(c for c in run_assessment(mixed, today=TODAY)["components"] if c["name"] == "LEGACY.CPP")
    assert after["scores"]["security"]["score"] > before


def test_clean_cobol_program_is_retain_or_rehost(tmp_path):
    store = ProgramStore.create("Clean COBOL", root=tmp_path)
    load(store, sec=False)
    a = run_assessment(store, today=TODAY)
    assert a["verdict"]["code"] in ("retain", "rehost")
    assert a["confidence"]["level"] in ("low", "medium", "high")
    store.close()


def test_empty_program(tmp_path):
    store = ProgramStore.create("Empty", root=tmp_path)
    a = run_assessment(store, today=TODAY)
    assert a["verdict"] is None and a["components"] == [] and a["confidence"]["level"] == "low"
    store.close()


def test_assessment_api(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "programs"))
    from webapp import server
    client = TestClient(server.app)
    slug = client.post("/api/programs", json={"name": "Assess API"}).json()["program"]["slug"]
    with ProgramStore.open(slug) as store:
        add(store, "web.config", (SEC / "web.config").read_text(), "XML", "config")
        add(store, "AIDCALC.cbl", (COBOL / "AIDCALC.cbl").read_text(), "COBOL", "cbl")
    assert client.get(f"/api/programs/{slug}/assessment").json()["assessment"] is None
    a = client.post(f"/api/programs/{slug}/assessment").json()["assessment"]
    assert a["verdict"]["label"] and len(a["components"]) == 2
    d = client.post(f"/api/programs/{slug}/assessment/inputs", json={"components": {"AIDCALC.cbl": {"impact": 5}}}).json()
    assert next(c for c in d["assessment"]["components"] if c["name"] == "AIDCALC.cbl")["risk"]["impact"] == 5
    assert client.post(f"/api/programs/{slug}/assessment/inputs",
                       json={"components": {"AIDCALC.cbl": {"impact": "x"}}}).status_code == 400
    assert client.get(f"/api/programs/{slug}/export").status_code == 200
