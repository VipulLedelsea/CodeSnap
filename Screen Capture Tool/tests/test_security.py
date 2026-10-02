import json
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("tree_sitter")

from core.model import ProgramStore
from core.security import cves, eol, run_scan
from core.security.rules import mask_snippet, pii_class, scan_text

from test_linker import LEGACY, add

SEC = Path(__file__).resolve().parent / "samples" / "security"
TODAY = date(2026, 9, 25)
FILES = [("StudentLookup.aspx.cs", "C#", "cs"), ("StudentExport.java", "Java", "java"), ("LEGACY.CPP", "C++", "cpp"),
         ("STUPAY.cbl", "COBOL", "cbl"), ("web.config", "XML", "config"), ("Lookup.html", "HTML", "html")]


@pytest.fixture
def scanned(tmp_path):
    store = ProgramStore.create("Sec", root=tmp_path)
    for name, lang, ext in FILES:
        add(store, name, (SEC / name).read_text(), lang, ext)
    run_scan(store, today=TODAY)
    yield store
    store.close()


def rules_at(store, file):
    return {(f["rule"], f["evidence"][0]["line"]) for f in store.findings("security")
            if f["evidence"][0]["file"] == file}


def test_eol_cycle_matching():
    data = eol.load_data()
    fx = data["products"]["dotnetfx"]
    assert eol.find_cycle(fx, "4.0")["cycle"] == "4.0"
    assert eol.find_cycle(fx, "v4.5.2")["cycle"] == "4.5.2"
    assert eol.find_cycle(fx, "3.5")["cycle"] == "3.5-sp1"
    assert eol.find_cycle(data["products"]["jquery"], "1.4.2")["cycle"] == "1"
    assert eol.cycle_status(eol.find_cycle(fx, "4.0"), TODAY)["status"] == "eol"
    assert eol.cycle_status(eol.find_cycle(fx, "4.8"), TODAY)["status"] == "supported"
    jdk8 = eol.find_cycle(data["products"]["oracle-jdk"], "1.8" if False else "8")
    assert eol.cycle_status(jdk8, TODAY) == {"status": "extended", "eol": "2022-03-31", "extended_until": "2030-12-31"}
    assert eol.cycle_status(eol.find_cycle(data["products"]["dotnet"], "8"), TODAY)["status"] == "ending"


def test_profile_technologies():
    techs = eol.technologies({"settings": {"targetFramework": "4.0"}, "libraries": ["jquery 1.4.2", "Newtonsoft.Json 4.5.0.0"],
                              "frameworks": ["ASP.NET Web Forms (Page)", "log4j 1.x (EOL)"],
                              "legacy_markers": ["Flash (L12)"]})
    keys = {(t["product"] or t["curated"], t["version"]) for t in techs}
    assert {("dotnetfx", "4.0"), ("jquery", "1.4.2"), ("webforms", None), ("log4j1", None), ("flash", None)} <= keys
    assert next(t for t in techs if t["curated"] == "flash")["lines"] == [12]


def test_eol_findings_cite_source_and_evidence(scanned):
    eols = {f["title"]: f for f in scanned.findings("eol")}
    fx = eols[".NET Framework 4.5: end of life"]
    assert "endoflife.date snapshot" in fx["source"] and fx["severity"] == "high"
    assert fx["evidence"][0]["file"] == "web.config" and "SA-22" in fx["refs"]["nist"]
    assert "Adobe Flash Player: end of life" in eols and "Apache log4j 1.x: end of life" in eols
    assert not any(t.startswith(".NET Framework:") for t in eols)


def test_curated_cves(scanned):
    ids = {f["refs"]["cve"] for f in scanned.findings("vulnerability")}
    assert {"CVE-2020-11022", "CVE-2019-8331", "CVE-2019-17571"} <= ids
    assert all("curated" in f["source"] for f in scanned.findings("vulnerability"))
    assert cves.curated("jquery", "3.5.1") == []
    assert [v["id"] for v in cves.curated("jquery", "3.4.1")] == ["CVE-2020-11022", "CVE-2020-11023"]


def test_osv_lookup_uses_cache(tmp_path):
    calls = []

    def post(url, body):
        calls.append(body)
        return {"vulns": [{"id": "GHSA-gxr4-xjj5-5px2", "aliases": ["CVE-2020-11022"], "summary": "XSS",
                           "database_specific": {"severity": "MODERATE"}}]}

    first = cves.lookup("jquery", "1.4.2", online=True, cache_dir=tmp_path, post=post)
    second = cves.lookup("jquery", "1.4.2", online=True, cache_dir=tmp_path, post=post)
    assert first == second and first["source"] == "OSV" and len(calls) == 1
    assert calls[0]["package"] == {"name": "jquery", "ecosystem": "npm"}
    assert first["vulns"][0]["id"] == "CVE-2020-11022" and first["vulns"][0]["severity"] == "medium"

    def down(url, body):
        raise OSError("offline")

    fallback = cves.lookup("jquery", "1.7.1", online=True, cache_dir=tmp_path, post=down)
    assert fallback["source"] == "curated" and "offline" in fallback["error"] and fallback["vulns"]


def test_code_rules(scanned):
    cs = rules_at(scanned, "StudentLookup.aspx.cs")
    assert {("SEC-CRED", 10), ("SEC-SQLI", 15), ("SEC-TLS", 16), ("SEC-XSS", 17), ("SEC-CONF", 19),
            ("SEC-CRYPTO", 24), ("SEC-DESER", 31)} <= cs
    assert not any(r == "SEC-SQLI" and l > 30 for r, l in cs)
    assert ("SEC-DESER", 30) not in cs
    java = rules_at(scanned, "StudentExport.java")
    assert {("SEC-CRED", 11), ("SEC-SQLI", 20), ("SEC-XSS", 22), ("SEC-PATH", 23), ("SEC-CRYPTO", 24),
            ("SEC-CMD", 25), ("SEC-CONF", 27)} <= java
    cpp = rules_at(scanned, "LEGACY.CPP")
    assert {("SEC-MEM", 9), ("SEC-MEM", 10), ("SEC-SQLI", 12), ("SEC-CMD", 13)} <= cpp
    cbl = rules_at(scanned, "STUPAY.cbl")
    assert ("SEC-CRED", 5) in cbl and ("SEC-SQLDYN", 12) in cbl and ("SEC-CRED", 6) not in cbl
    cfg = rules_at(scanned, "web.config")
    assert {("SEC-CRED", 4), ("SEC-CONF", 7), ("SEC-CONF", 8), ("SEC-CONF", 9), ("SEC-XSS", 10), ("SEC-AUTH", 13),
            ("SEC-AUTH", 19), ("SEC-TLS", 25)} <= cfg
    assert not any(l == 21 for _, l in cfg)


def test_secrets_masked_in_evidence(scanned):
    blob = json.dumps(scanned.findings())
    for secret in ("Summer2009!", "db2admin", "AIDPW01", "sa2005"):
        assert secret not in blob
    assert mask_snippet('pwd = "hunter22";') == 'pwd = "****";'


def test_student_data_and_escalation(scanned):
    privacy = {f["title"] for f in scanned.findings("privacy")}
    assert any("STUDENT-REC" in t for t in privacy) and any("Lookup" in t for t in privacy)
    sqli = next(f for f in scanned.findings("security") if f["rule"] == "SEC-SQLI"
                and f["evidence"][0]["file"] == "StudentLookup.aspx.cs")
    assert sqli["severity"] == "critical" and "ferpa" in sqli["refs"] and "SI-10" in sqli["refs"]["nist"]
    cmd = next(f for f in scanned.findings("security") if f["rule"] == "SEC-CMD" and f["evidence"][0]["file"] == "LEGACY.CPP")
    assert cmd["severity"] == "high" and "ferpa" not in cmd["refs"]
    assert pii_class("STU-SSN")[0] == "social security number"
    assert pii_class("WS-MARSS-NBR")[0] == "student identifier"
    assert pii_class("DistrictName") is None and pii_class("TOTAL_AMOUNT") is None


def test_rescan_is_stable_and_keeps_status(scanned):
    before = [(f["rule"], f["title"], f["severity"]) for f in scanned.findings()]
    target = scanned.findings("eol")[0]
    scanned.set_finding_status(target["id"], "accepted")
    run_scan(scanned, today=TODAY)
    after = [(f["rule"], f["title"], f["severity"]) for f in scanned.findings()]
    assert before == after
    assert next(f for f in scanned.findings("eol") if f["title"] == target["title"])["status"] == "accepted"


def test_manual_findings_survive_scan(scanned):
    scanned.add_finding("security", "low", "Reviewer note", origin="user")
    run_scan(scanned, today=TODAY)
    assert any(f["title"] == "Reviewer note" for f in scanned.findings())


def test_clean_samples_have_no_false_code_findings(tmp_path):
    store = ProgramStore.create("Clean", root=tmp_path)
    for name, lang, ext in (("AidLookupServlet.java", "Java", "java"), ("AidPaymentController.cs", "C#", "cs"),
                            ("AIDSCHEMA.sql", "SQL", "sql")):
        add(store, name, (LEGACY / name).read_text(), lang, ext)
    run_scan(store, today=TODAY)
    rules = {f["rule"] for f in store.findings("security")}
    assert "SEC-SQLI" not in rules and "SEC-XSS" not in rules
    assert any(f["rule"] == "SEC-CRED" for f in store.findings("security"))
    store.close()


def test_comments_are_ignored():
    code = '// Response.Write(Request["x"]);\n/* strcpy(a, b); */\nint x = 1;\n'
    assert scan_text(code, "a.cs") == [] and scan_text(code, "a.cpp") == []
    assert scan_text('string u = "http://example.org/api";\n', "a.cs")[0]["rule"] == "SEC-TLS"
    assert scan_text('string u = "https://example.org/api";\n', "a.cs") == []


def test_eol_refresh_writes_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(eol, "cache_path", lambda: tmp_path / "eol.json")
    rows = [{"cycle": "4.0", "releaseDate": "2010-04-12", "eol": "2016-01-12"}]
    out = eol.refresh(fetch=lambda url: rows if "dotnetfx" in url else (_ for _ in ()).throw(OSError("x")),
                      today=date(2027, 1, 1))
    assert out["updated"] == ["dotnetfx"] and out["failed"]
    data = eol.load_data()
    assert data["snapshot"] == "2027-01-01" and len(data["products"]["dotnetfx"]["cycles"]) == 1


def test_security_api(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "programs"))
    from webapp import server
    client = TestClient(server.app)
    slug = client.post("/api/programs", json={"name": "Sec API"}).json()["program"]["slug"]
    with ProgramStore.open(slug) as store:
        add(store, "web.config", (SEC / "web.config").read_text(), "XML", "config")
    assert client.get(f"/api/programs/{slug}/findings").json()["summary"]["total"] == 0
    d = client.post(f"/api/programs/{slug}/security/scan").json()
    assert d["ok"] and d["summary"]["by_category"]["security"] > 0 and d["technologies"]
    fid = d["findings"][0]["id"]
    r = client.post(f"/api/programs/{slug}/findings/{fid}/status", json={"status": "dismissed"}).json()
    assert r["finding"]["status"] == "dismissed"
    assert client.post(f"/api/programs/{slug}/findings/{fid}/status", json={"status": "bogus"}).status_code == 400
    after = client.get(f"/api/programs/{slug}/findings").json()
    assert after["summary"]["total"] == d["summary"]["total"] - 1
    techs = client.get(f"/api/programs/{slug}/technologies").json()["technologies"]
    assert any(t["name"] == ".NET Framework" and t["status"] == "eol" for t in techs)
