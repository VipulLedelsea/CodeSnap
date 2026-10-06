"""Regressions for the report, diagram and site-scan hardening pass: honest ratings, XML-safe output, truthful figure
references, bounded diagrams, and a site scanner that cannot be steered to internal addresses."""
import io
import re
import tracemalloc
import xml.dom.minidom as minidom
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.diagrams import build as B
from core.diagrams import drawio, layout, png, svg, vsdx
from core.diagrams.xmlsafe import xml_safe
from core.report import ratings as RT
from core.report import settings as RS

TODAY = date(2026, 9, 25)
CTRL = "\x0b\x00\x01\x1f"


# ── ratings ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _comp(score):
    names = ("supportability", "tech_debt", "complexity", "health", "coupling")
    return {"name": "A.cbl", "type": None, "lines": 100, "scores": {d: {"score": score, "factors": []} for d in names}}


AM = {"components": [{"name": "A.cbl", "layer": "Application", "writes": [], "role": "Batch program"}]}
FACTS = {"platforms": 1, "confidence": "high", "tests": True, "skills": []}


def test_empty_program_rates_nothing():
    sc = RT.scorecard([], {"components": []}, None, "", {"platforms": 0, "confidence": "low"})
    assert all(sc[k][0] is None for k, _ in RT.DIMS)
    assert sc["overall"][0] is None
    assert RT.overall_text(sc, "low") == "Insufficient evidence"


def test_business_fit_is_not_invented_without_platform_facts():
    sc = RT.scorecard([_comp(95)], AM, 1, "ok", {"confidence": "high", "tests": True})
    assert sc["Business fit and adaptability"][0] in (1, 2)       # from code coupling only, not a made-up platform
    sc = RT.scorecard([_comp(95)], AM, 1, "ok", {"platforms": 0, "confidence": "high", "tests": True})
    assert "1 platform" not in sc["Business fit and adaptability"][1]


def test_everything_rateable_present_can_beat_fair():
    sc = RT.scorecard([_comp(95)], AM, 1, "ok", FACTS)
    overall, raw, cov, cap = sc["overall"]
    assert cov == 1.0 and not cap
    assert overall is not None and overall < 3


def test_missing_rateable_evidence_still_caps_at_fair():
    sc = RT.scorecard([_comp(95)], AM, None, "", FACTS)           # security posture could not be rated
    overall, raw, cov, cap = sc["overall"]
    assert cov < RT.COVERAGE_CAP and overall == 3 and "Capped at 3" in cap


# ── XML-invalid characters ────────────────────────────────────────────────────────────────────────────────────────

def test_xml_safe_strips_control_characters():
    assert xml_safe("Jane\x0bDoe") == "Jane Doe"
    assert xml_safe("a\x00b\x1fc\td\ne") == "abc\td\ne"
    assert xml_safe(None) is None and xml_safe(5) == 5


def test_diagram_exports_stay_valid_xml():
    scene = {"id": "x", "kind": "context", "title": f"Title{CTRL}", "width": 400, "height": 200, "groups": [],
             "nodes": [{"id": "n", "title": f"Node{CTRL}", "kind": "system", "x": 10, "y": 40, "w": 120, "h": 50,
                        "sections": [[f"line{CTRL}"]], "stereotype": f"st{CTRL}"}], "edges": []}
    minidom.parseString(svg(scene))
    minidom.parseString(drawio([scene]))
    with zipfile.ZipFile(io.BytesIO(vsdx([scene], f"Deck{CTRL}"))) as z:
        for name in z.namelist():
            if name.endswith(".xml") or name.endswith(".rels"):
                minidom.parseString(z.read(name))


def test_redactor_cleans_even_when_inactive():
    from core.report.redact import Redactor
    r = Redactor({})
    assert r.map({"a": ["x\x0by", ("z\x00",)]}) == {"a": ["x y", ("z",)]}


def _docx_xml(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read("word/document.xml").decode("utf8")


def test_settings_and_program_name_with_control_characters_make_a_valid_docx(tmp_path):
    pytest.importorskip("docx")
    from core.model import ProgramStore
    from core.report import docx_bytes
    store = ProgramStore.create("Pay\x0broll", root=tmp_path)
    try:
        saved = RS.save(store, {"business_owner": "Jane\x0bDoe", "purpose": "a\x00b"})
        assert saved["business_owner"] == "Jane Doe" and saved["purpose"] == "ab"
        xml = _docx_xml(docx_bytes(store, rescan=False, today=TODAY))
        assert not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", xml)
        minidom.parseString(xml.encode("utf8"))
    finally:
        store.close()


# ── test-file detection ───────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("LATEST.cbl", False), ("ATTESTRPT.cbl", False), ("Contest.cs", False), ("Protest.java", False),
    ("test_pay.py", True), ("pay_test.go", True), ("tests/pay.py", True), ("PaymentTest.java", True),
    ("a.test.js", True), ("UnitTests.cs", True), ("PAY-TEST.cbl", True)])
def test_is_test_file(name, expected):
    from core.report.template_docx import is_test_file
    assert is_test_file(name) is expected


# ── figures are only claimed when inserted ────────────────────────────────────────────────────────────────────────

def test_no_figure_claims_when_figure_insertion_fails(tmp_path, monkeypatch):
    pytest.importorskip("tree_sitter")
    docx = pytest.importorskip("docx")
    from core.model import ProgramStore
    from core.report import docx_bytes
    from test_linker import COBOL, add
    store = ProgramStore.create("Figures", root=tmp_path)
    for f in ("AIDCALC.cbl", "AIDINQ.cbl", "AIDREC.cpy"):
        add(store, f, (COBOL / f).read_text(), "COBOL", f.split(".")[1])

    def boom(*a, **k):
        raise RuntimeError("renderer down")
    monkeypatch.setattr("core.diagrams.render.png", boom)
    try:
        d = docx.Document(io.BytesIO(docx_bytes(store, rescan=False, today=TODAY)))
    finally:
        store.close()
    text = "\n".join([p.text for p in d.paragraphs] + [c.text for t in d.tables for r in t.rows for c in r.cells])
    assert not re.search(r"\(Figure [34]\)", text) and not re.search(r"^Figure [34]\.", text, re.M)
    assert "Appendix E: Current-state process (Figure 1)" not in text


# ── diagrams stay bounded ─────────────────────────────────────────────────────────────────────────────────────────

def test_png_area_is_capped():
    from PIL import Image
    scene = {"title": "big", "width": 30000, "height": 30000, "nodes": [], "edges": []}
    img = Image.open(io.BytesIO(png(scene)))
    assert img.size[0] * img.size[1] <= 25_000_000


def _fake_model(n_tables, n_cols):
    ents, children = {}, {}
    for t in range(n_tables):
        ents[t] = {"id": t, "kind": "table", "name": f"T{t:04d}", "origin": "parsed", "attrs": {}, "line_start": 1}
        children[t] = [{"id": 10_000 + t * 100 + c, "kind": "column", "name": f"COL_{c}", "line_start": c,
                        "attrs": {"type": "VARCHAR(20)"}} for c in range(n_cols)]
    return SimpleNamespace(ents=ents, children=children, rels=[])


def test_huge_data_model_stays_small():
    store = SimpleNamespace(_diagram_model=_fake_model(300, 60), info={"name": "Big"})
    tracemalloc.start()
    scene = B.data_model(store)
    png(scene)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert len(scene["nodes"]) <= B.MAX_TABLES and "showing" in scene["title"]
    assert all(sum(len(s) for s in n["sections"]) <= B.MAX_TABLE_COLS + 1 for n in scene["nodes"])
    assert peak < 200 * 1024 * 1024


def test_edges_to_unknown_nodes_do_not_crash_layout():
    nodes = [{"id": "a", "title": "A", "kind": "system"}, {"id": "b", "title": "B", "kind": "system"}]
    edges = [{"from": "a", "to": "b", "label": ""}, {"from": "a", "to": "ghost", "label": ""}]
    scene = layout.layered(nodes, [dict(e) for e in edges], "TB")
    assert all(e["to"] != "ghost" for e in scene["edges"])
    cols = layout.columns([[{"id": "a", "title": "A", "kind": "system"}], [{"id": "b", "title": "B", "kind": "system"}]],
                          [dict(e) for e in edges])
    assert len(cols["edges"]) == 1
    seq = layout.sequence([{"id": "a", "title": "A"}], [{"from": "a", "to": "ghost", "label": "x"}])
    assert not [e for e in seq["edges"] if e.get("message")]


def test_user_flow_nodes_with_a_shared_prefix_stay_distinct(monkeypatch):
    prefix = "S" * 40
    ents = {i: {"id": i, "kind": "screen", "name": f"{prefix}{i}", "origin": "parsed", "attrs": {}, "artifact_id": None}
            for i in (1, 2)}
    store = SimpleNamespace(_diagram_model=SimpleNamespace(ents=ents, rels=[], arts={}), info={"name": "UF"})
    monkeypatch.setattr("core.uireview.flows.canonical_screens", lambda *a, **k: set())
    monkeypatch.setattr("core.uireview.flows.journeys", lambda *a, **k: {"edges": [(f"{prefix}1", f"{prefix}2", "next")]})
    scene = B.user_flow(store)
    assert len(scene["nodes"]) == 2 and len(scene["edges"]) == 1
    e = scene["edges"][0]
    assert e["from"] != e["to"] and {e["from"], e["to"]} == {n["id"] for n in scene["nodes"]}


# ── site scanning ─────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("host", ["127.0.0.1", "10.1.2.3", "192.168.0.5", "169.254.169.254", "::1", "0.0.0.0"])
def test_internal_targets_are_refused(host):
    from core.uireview import site
    assert site._internal_address(host)
    r = site.fetch(f"http://[{host}]/" if ":" in host else f"http://{host}/")
    assert r["status"] is None and r["error"].startswith("refused")


class _Resp:
    def __init__(self, status, headers):
        self.status, self._h = status, headers
        self.headers = SimpleNamespace(get_content_charset=lambda: "utf-8")

    def getheaders(self):
        return list(self._h)

    def read(self, n):
        return b"<html></html>"


def _fake_http(monkeypatch, routes, seen=None):
    from core.uireview import site
    monkeypatch.setattr(site.socket, "getaddrinfo", lambda host, *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])

    class Conn:
        def __init__(self, host, port, timeout=0, context=None):
            self.host, self.sock = host, None

        def request(self, method, path, headers=None):
            if seen is not None:
                seen.append((self.host, path))
            self.resp = routes[(self.host, path)]

        def getresponse(self):
            return self.resp

        def close(self):
            pass
    monkeypatch.setattr(site.http.client, "HTTPConnection", Conn)
    monkeypatch.setattr(site.http.client, "HTTPSConnection", Conn)
    return site


def test_redirect_to_another_site_is_refused(monkeypatch):
    seen = []
    site = _fake_http(monkeypatch, {("a.example", "/"): _Resp(302, [("location", "http://evil.example/x")])}, seen)
    r = site.fetch("http://a.example/")
    assert r["status"] is None and "another site" in r["error"]
    assert seen == [("a.example", "/")]


def test_https_to_http_downgrade_is_refused(monkeypatch):
    site = _fake_http(monkeypatch, {("a.example", "/"): _Resp(301, [("location", "http://a.example/")])})
    r = site.fetch("https://a.example/")
    assert r["status"] is None and "HTTPS to HTTP" in r["error"]


def test_same_site_redirect_is_followed(monkeypatch):
    site = _fake_http(monkeypatch, {("a.example", "/"): _Resp(301, [("location", "https://www.a.example/")]),
                                    ("www.a.example", "/"): _Resp(200, [("content-type", "text/html")])})
    r = site.fetch("http://a.example/")
    assert r["status"] == 200 and r["url"] == "https://www.a.example/"


def test_error_pages_do_not_get_header_findings():
    from core.uireview.site import scan_site

    def fetcher(url):
        return {"url": url, "status": 404 if url.startswith("https") else 200, "headers": [("content-type", "text/html")],
                "body": "", "chain": [(url, 404)], "tls": None}
    rules = {f["rule"] for f in scan_site("https://a.example/", fetcher=fetcher)["findings"]}
    assert not rules & {"WEB-HSTS", "WEB-CSP", "WEB-XCTO", "WEB-REFERRER", "WEB-FRAME"}
