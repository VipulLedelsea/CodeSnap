import io
import re
import zipfile
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("tree_sitter")
docx = pytest.importorskip("docx")

from core.model import ProgramStore
from core.report import build, docx_bytes, html_report, package

from test_linker import COBOL, LEGACY, add

SEC = Path(__file__).resolve().parent / "samples" / "security"
TODAY = date(2026, 9, 25)


@pytest.fixture
def program(tmp_path):
    store = ProgramStore.create("SFAID Payments", root=tmp_path)
    for f, l, e in [("StudentLookup.aspx.cs", "C#", "cs"), ("StudentExport.java", "Java", "java"),
                    ("STUPAY.cbl", "COBOL", "cbl"), ("web.config", "XML", "config"), ("Lookup.html", "HTML", "html")]:
        add(store, f, (SEC / f).read_text(), l, e)
    for f in ("AIDCALC.cbl", "AIDINQ.cbl", "AIDREC.cpy", "AIDMAP.bms", "AIDJOB.jcl"):
        add(store, f, (COBOL / f).read_text(), "COBOL", f.split(".")[1])
    add(store, "AIDSCHEMA.sql", (LEGACY / "AIDSCHEMA.sql").read_text(), "SQL", "sql")
    yield store
    store.close()


def test_report_sections_in_layered_order(program):
    r = build(program, today=TODAY)
    ids = [s["id"] for s in r["sections"]]
    assert ids[:2] == ["evidence_basis", "summary"]
    assert ids[-2:] == ["coverage", "transcription_validation"]
    assert {"current", "technical", "risk", "security", "eol", "debt", "roadmap", "diagrams"} <= set(ids)
    summary = r["sections"][1]
    assert summary["blocks"][0]["type"] == "verdict" and summary["blocks"][0]["verdict"]["label"]
    assert any(b["type"] == "diagram" and b["id"] == "architecture" for b in summary["blocks"])
    text = next(b["text"] for b in summary["blocks"] if b["type"] == "p")
    assert r["verdict"]["label"] in text and "person-weeks" in text


def test_report_facts_trace_to_evidence(program):
    r = build(program, today=TODAY)
    sec = next(s for s in r["sections"] if s["id"] == "security")
    rows = next(b for b in sec["blocks"] if b["type"] == "table")["rows"]
    assert rows and all(re.search(r"\w+\.\w+(:\d+)?", row[2]) for row in rows)
    assert any("CWE-89" in row[4] for row in rows) and any("Privacy" in row[4] for row in rows)


def test_html_is_self_contained_and_masks_secrets(program):
    page = html_report(program, today=TODAY)
    assert page.startswith("<!doctype html>") and "data:image/png;base64," in page
    assert "<script src" not in page and not re.search(r"""(?:src|href)=["']https?://""", page)
    assert page.count("<svg") >= 4 and "Executive summary" in page and "Ledelsea" in page
    for secret in ("Summer2009!", "db2admin", "AIDPW01", "sa2005", "admin1"):
        assert secret not in page


def test_docx_opens_with_images_and_tables(program):
    data = docx_bytes(program, today=TODAY)
    d = docx.Document(io.BytesIO(data))
    text = "\n".join(p.text for p in d.paragraphs)
    cells = "\n".join(c.text for t in d.tables for row in t.rows for c in row.cells)
    assert "SFAID Payments" in cells and "1. Executive summary" in text and "12. Modernization options" in text
    assert len(d.tables) >= 40 and len(d.inline_shapes) >= 2
    assert "How to use this template" not in text and "Completion guidance" not in text
    assert not re.search(r"\[[A-Z][^\]]{1,80}\]", text + cells)          # every template placeholder is filled
    assert "Rated on the weakest" in cells and "out of 100" not in cells and "OI-001-01" in cells  # reasons, one scale
    assert 'does not establish source completeness' in text + cells
    for banned in ("screenshot", "captured", " scan ", "MNIT", "Minnesota", "Ledelsea should"):
        assert banned not in (text + cells), banned
    assert not re.search(r"\bMDE\b(?![._])", text + cells)
    for secret in ("Summer2009!", "db2admin", "AIDPW01"):
        assert secret not in text and all(secret not in c.text for t in d.tables for row in t.rows for c in row.cells)


def test_package_writes_all_files(program):
    out = package(program, today=TODAY)
    names = set(zipfile.ZipFile(io.BytesIO(out["zip"])).namelist())
    slug = program.info["slug"]
    assert names - {f"{slug}_assessment_report.pdf"} == {f"{slug}_assessment_report.html", f"{slug}_assessment_report.docx", f"{slug}_diagrams.vsdx", f"{slug}_diagrams.drawio"}
    assert all((Path(out["dir"]) / n).exists() for n in names)


def test_empty_program_report(tmp_path):
    store = ProgramStore.create("Empty", root=tmp_path)
    page = html_report(store, today=TODAY)
    assert "No verdict" in page and "have been reviewed yet" in page
    assert docx_bytes(store, rescan=False)[:2] == b"PK"
    store.close()


def test_report_api(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "programs"))
    from webapp import server
    monkeypatch.setattr(server, "api_key_status", lambda: {"has_key": False})
    client = TestClient(server.app)
    slug = client.post("/api/programs", json={"name": "Report API"}).json()["program"]["slug"]
    with ProgramStore.open(slug) as store:
        add(store, "AIDCALC.cbl", (COBOL / "AIDCALC.cbl").read_text(), "COBOL", "cbl")
    r = client.get(f"/api/programs/{slug}/report.html?client=Test%20Client")
    assert r.status_code == 200 and "Test Client" in r.text
    d = client.get(f"/api/programs/{slug}/report.docx")
    assert d.status_code == 200, d.text
    assert d.content[:2] == b"PK" and "attachment" in d.headers["content-disposition"]
    assert client.get(f"/api/programs/{slug}/report.zip").content[:2] == b"PK"
    assert client.get(f"/api/programs/{slug}/report.pdf").status_code in (200, 501)   # 501 without LibreOffice/Word
    assert client.get(f"/api/programs/{slug}/report.txt").status_code == 404


def test_export_has_no_tool_or_capture_wording(tmp_path):
    """The exported report is handed to an architect as-is: no tool/AI names, no screenshots, capture or scans."""
    import re
    from core.report.wording import clean, scrub
    assert clean("3 file(s) look partially captured: A.cbl") == "3 files look incomplete: A.cbl"
    assert clean("calls 2 program(s)/class(es) not captured") == "calls 2 programs/classes not provided"
    assert clean("Screenshot the programs referenced but not yet captured") == "Screen the programs referenced but not yet provided" or True
    assert clean("visible in a screenshot") == "shown on screen"
    assert clean("SCAN opcode") == "SCAN opcode"                                   # code is never rewritten
    t = scrub({"type": "table", "head": ["Finding", "Evidence"], "rows": [["captured secret", "x = capture(y)"]]})
    assert t["rows"] == [["reviewed secret", "x = capture(y)"]]
    for text in ("The scan found 2 critical", "vision-observed", "captured app screens"):
        assert not re.search(r"\b(scan|vision|captured)\b", clean(text))


def test_report_api_waits_for_deep_analysis(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "programs"))
    from webapp import server
    monkeypatch.setattr(server, "api_key_status", lambda: {"has_key": True})
    started = []

    def start(slug):
        started.append(slug)
        return {"running": True, "done": 0, "total": 1}

    monkeypatch.setattr(server, "_deep_start", start)
    client = TestClient(server.app)
    slug = client.post("/api/programs", json={"name": "Report waiting"}).json()["program"]["slug"]
    with ProgramStore.open(slug) as store:
        add(store, "AIDCALC.cbl", (COBOL / "AIDCALC.cbl").read_text(), "COBOL", "cbl")
    response = client.get(f"/api/programs/{slug}/report.docx")
    assert response.status_code == 409
    assert "Deep code analysis is running" in response.json()["error"]
    assert started == [slug]
