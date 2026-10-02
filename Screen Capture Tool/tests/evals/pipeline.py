"""Diagram validity/coverage/determinism and verdict stability/consistency/explainability on sample programs."""
import io
import random
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
S = HERE.parent / "samples"
TODAY = date(2026, 9, 26)
PROGRAMS = {
    "COBOL/CICS batch + online": ["cobol/AIDCALC.cbl", "cobol/AIDINQ.cbl", "cobol/AIDREC.cpy", "cobol/AIDMAP.bms", "cobol/AIDJOB.jcl",
                                  "legacy/AIDSCHEMA.sql"],
    ".NET / Java web": ["legacy/AidPaymentController.cs", "legacy/AidCalcTranslated.cs", "legacy/AidLookupServlet.java",
                        "legacy/AidLookup.jsp", "legacy/DistrictAid.aspx", "legacy/web.config", "legacy/web.xml",
                        "legacy/PaymentSchema.sql", "legacy/aid-api.json", "legacy/StudentService.wsdl"],
    "Mixed legacy (VB6/ASP/RPG/PLSQL/SAS)": ["langpacks/AIDCALC.frm", "langpacks/aidlookup.asp", "langpacks/AIDPOST.rpgle",
                                             "langpacks/AIDNIGHT.clle", "langpacks/aid_pkg.pkb", "langpacks/aid_forecast.sas",
                                             "langpacks/LoadAid.dtsx", "langpacks/AIDIDMS.cbl", "langpacks/aidform_fmb.xml"],
    "Modern-ish held-out (Java/C#/PLSQL)": ["heldout/LevyDao.java", "heldout/LevyReview.aspx.cs", "heldout/levy_cert.prc",
                                            "heldout/usp_LevyLoad.sql"],
}
LANG = {"cbl": "COBOL", "cpy": "COBOL copybook", "bms": "CICS BMS map", "jcl": "JCL", "cs": "C#", "java": "Java"}


def _path(rel):
    return HERE / rel if rel.startswith("heldout/") else S / rel


def build(files, order_seed=None, inputs=None, extra=()):
    from core.model import ProgramStore, ingest_capture
    from test_linker import NoApi
    files = list(files)
    if order_seed is not None:
        random.Random(order_seed).shuffle(files)
    store = ProgramStore.create("Eval", root=Path(tempfile.mkdtemp()))
    for rel in files:
        p = _path(rel)
        ext = p.suffix[1:].lower()
        ingest_capture(store, NoApi(), [], {"is_code": True, "code": p.read_text(), "extension": ext,
                                            "language": LANG.get(ext, ""), "errors": "None"}, name=p.name)
    for name, code in extra:
        ingest_capture(store, NoApi(), [], {"is_code": True, "code": code, "extension": name.rsplit(".", 1)[-1],
                                            "language": "", "errors": "None"}, name=name)
    if inputs:
        from core.assess import set_inputs
        set_inputs(store, inputs)
    return store


def _valid_diagrams(ds):
    from core.diagrams import drawio, png, svg, vsdx
    bad = []
    for d in ds:
        try:
            ET.fromstring(svg(d))
        except ET.ParseError as exc:
            bad.append(f"{d['id']} svg: {exc}")
    ET.fromstring(drawio(ds))
    with zipfile.ZipFile(io.BytesIO(vsdx(ds))) as z:
        for n in z.namelist():
            if n.endswith((".xml", ".rels")):
                ET.fromstring(z.read(n))
    from PIL import Image
    for d in ds[:3]:
        Image.open(io.BytesIO(png(d, scale=1.0))).verify()
    return bad


def _titles(ds):
    return {d["id"].split("-")[0] + ":" + d.get("title", ""): sorted(n["title"] for n in d["nodes"]) for d in ds}


def diagrams_eval():
    from core.assess import run_assessment
    from core.diagrams import all_diagrams, diagram_coverage, svg
    rows = []
    for name, files in PROGRAMS.items():
        st = build(files)
        run_assessment(st, today=TODAY)
        ds = all_diagrams(st)
        cov = diagram_coverage(st, ds)
        bad = _valid_diagrams(ds)
        st2 = build(files)
        run_assessment(st2, today=TODAY)
        same_bytes = [svg(d) for d in ds] == [svg(d) for d in all_diagrams(st2)]
        st3 = build(files, order_seed=11)
        run_assessment(st3, today=TODAY)
        same_titles = _titles(ds) == _titles(all_diagrams(st3))
        rows.append({"program": name, "diagrams": len(ds), "coverage": cov["ratio"], "invalid": bad,
                     "identical_rerun": same_bytes, "order_independent": same_titles})
        for s in (st, st2, st3):
            s.close()
    return rows


def _scores(a):
    return {k: v["score"] for k, v in a["scores"].items()}


def disp(a, name):
    c = next(c for c in a["components"] if c["name"] == name)
    return (c["disposition"] or a["verdict"])["code"]


def verdict_eval():
    from core.assess import run_assessment
    out = {"stability": [], "scenarios": [], "monotonic": [], "explainability": {}}
    for name, files in PROGRAMS.items():
        base = run_assessment(st := build(files), today=TODAY)
        st.close()
        same = True
        for seed in (1, 2, 3):
            a = run_assessment(s := build(files, order_seed=seed), today=TODAY)
            s.close()
            same &= a["verdict"]["code"] == base["verdict"]["code"] and _scores(a) == _scores(base)
        out["stability"].append({"program": name, "verdict": base["verdict"]["label"], "stable_across_orders": same})
    mixed = PROGRAMS["Mixed legacy (VB6/ASP/RPG/PLSQL/SAS)"]
    scen = [
        ("VB6 / Classic ASP components", mixed, None, lambda a: disp(a, "AIDCALC.frm") == "rearchitect" and disp(a, "aidlookup.asp") == "rearchitect"),
        ("Program with VB6 / ASP / SQL-injection components is not 'Retain'", mixed, None,
         lambda a: a["verdict"]["code"] not in ("retain",)),
        ("Clean COBOL batch program is not sent to rebuild", PROGRAMS["COBOL/CICS batch + online"], None,
         lambda a: a["verdict"]["code"] in ("retain", "rehost", "refactor", "replatform")),
        ("Staff COTS note on a component", mixed, {"components": {"AIDPOST.rpgle": {"cots": "Vendor finance package"}}},
         lambda a: disp(a, "AIDPOST.rpgle") == "replace"),
        ("Staff retire note on the program", mixed, {"program": {"retire": "Replaced by state system"}},
         lambda a: a["verdict"]["code"] == "retire"),
        ("Python 2.7 script (EOL runtime, upgrade path)", ["langpacks/aid_merge.py"], None,
         lambda a: disp(a, "aid_merge.py") == "replatform"),
        ("Mostly modern code (one Web Forms page) is not sent to a full rebuild", PROGRAMS["Modern-ish held-out (Java/C#/PLSQL)"], None,
         lambda a: a["verdict"]["code"] not in ("rearchitect", "replace", "retire")),
    ]
    for label, files, inputs, check in scen:
        a = run_assessment(s := build(files, inputs=inputs), today=TODAY)
        s.close()
        out["scenarios"].append({"scenario": label, "verdict": a["verdict"]["label"], "pass": bool(check(a))})
    base_files = PROGRAMS["Modern-ish held-out (Java/C#/PLSQL)"]
    a0 = run_assessment(s := build(base_files), today=TODAY)
    s.close()
    vuln = ("Evil.cs", 'public class Evil { void M(string id) { var c = new SqlCommand("SELECT * FROM T WHERE Id = " + id); '
                       'string password = "Hunter22!"; } }')
    a1 = run_assessment(s := build(base_files, extra=[vuln]), today=TODAY)
    s.close()
    old = ("frmOld.frm", (S / "langpacks/AIDCALC.frm").read_text())
    a2 = run_assessment(s := build(base_files, extra=[old]), today=TODAY)
    s.close()
    s0, s1, s2 = _scores(a0), _scores(a1), _scores(a2)
    out["monotonic"] = [
        {"check": "adding a file with SQL injection + hard-coded password does not raise security", "pass": s1["security"] <= s0["security"],
         "before": s0["security"], "after": s1["security"]},
        {"check": "adding a VB6 form (EOL) does not raise supportability", "pass": s2["supportability"] <= s0["supportability"],
         "before": s0["supportability"], "after": s2["supportability"]},
    ]
    a = run_assessment(s := build(mixed), today=TODAY)
    factors = [f for c in a["components"] for sc in c["scores"].values() for f in sc["factors"]]
    findings = s.findings()
    out["explainability"] = {
        "score_deductions": len(factors),
        "deductions_with_rule_and_reason": sum(1 for f in factors if f.get("rule") and f.get("text")),
        "findings": len(findings),
        "findings_with_source_and_evidence": sum(1 for f in findings if f.get("source") and f.get("evidence")),
        "verdict_has_reasons": bool(a["verdict"].get("reasons")),
    }
    s.close()
    return out
