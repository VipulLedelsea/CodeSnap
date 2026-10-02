import io
import xml.dom.minidom
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("tree_sitter")

from core.diagrams import all_diagrams, context, diagram_coverage, drawio, png, svg, vsdx
from core.diagrams.export import bundle, save
from core.diagrams.layout import layered, sequence
from core.model import ProgramStore

from test_linker import COBOL, LEGACY, add

SEC = Path(__file__).resolve().parent / "samples" / "security"


@pytest.fixture
def program(tmp_path):
    store = ProgramStore.create("Aid Demo", root=tmp_path)
    for f in ("AIDCALC.cbl", "AIDINQ.cbl", "AIDREC.cpy", "AIDMAP.bms", "AIDJOB.jcl"):
        add(store, f, (COBOL / f).read_text(), "COBOL", f.split(".")[1])
    for f, l, e in (("AidPaymentController.cs", "C#", "cs"), ("AIDSCHEMA.sql", "SQL", "sql"),
                    ("PaymentSchema.sql", "SQL", "sql"), ("DistrictAid.aspx", "ASPX", "aspx"),
                    ("AidLookupServlet.java", "Java", "java"), ("web.config", "XML", "config"), ("AIDRPT.CPP", "C++", "cpp")):
        add(store, f, (LEGACY / f).read_text(), l, e)
    add(store, "LEGACY.CPP", (SEC / "LEGACY.CPP").read_text(), "C++", "cpp")
    yield store
    store.close()


def overlaps(a, b):
    return not (a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"] or a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"])


def test_every_modelled_entity_is_drawn(program):
    ds = all_diagrams(program)
    cov = diagram_coverage(program, ds)
    assert cov["entities"] > 40 and cov["missing"] == [] and cov["ratio"] == 1.0
    kinds = {d["kind"] for d in ds}
    assert {"context", "component", "class", "data", "sequence"} <= kinds


def test_no_overlapping_boxes(program):
    for d in all_diagrams(program):
        boxes = d["nodes"]
        for i, a in enumerate(boxes):
            assert 0 <= a["x"] and a["x"] + a["w"] <= d["width"] + 1 and a["y"] + a["h"] <= d["height"] + 1, d["id"]
            for b in boxes[i + 1:]:
                assert not overlaps(a, b), (d["id"], a["title"], b["title"])


def test_context_shows_actors_systems_and_tables(program):
    d = context(program)
    titles = {n["title"] for n in d["nodes"]}
    assert {"Program users", "Batch scheduler", "Aid Demo"} <= titles
    assert any(t.startswith("Database tables") for t in titles)
    assert all(e["from"] in {n["id"] for n in d["nodes"]} for e in d["edges"])


def test_per_file_class_diagram_is_complete(program):
    ds = {d["title"]: d for d in all_diagrams(program)}
    calc = ds["Classes & programs — AIDCALC.cbl"]
    node = next(n for n in calc["nodes"] if n["title"] == "AIDCALC")
    text = " ".join(l for sec in node["sections"] for l in sec)
    assert "0000-MAIN" in text and "+" not in text.split("more")[0][-3:]
    assert any(n["stereotype"] == "file scope" for n in ds["Classes & programs — LEGACY.CPP"]["nodes"])


def test_sequence_for_job_entry(program):
    seq = next(d for d in all_diagrams(program) if d["kind"] == "sequence" and d["entry"] == "AIDJOB")
    labels = [e["label"] for e in seq["edges"] if e.get("message")]
    assert labels[0] == "runs" and any(l.startswith("calls") for l in labels)
    assert any(l.startswith("writes") for l in labels)


def test_svg_png_drawio_vsdx_are_valid(program):
    ds = all_diagrams(program)
    for d in ds[:3]:
        xml.dom.minidom.parseString(svg(d))
        assert png(d)[:8] == b"\x89PNG\r\n\x1a\n"
    doc = xml.dom.minidom.parseString(drawio(ds))
    assert len(doc.getElementsByTagName("diagram")) == len(ds)
    z = zipfile.ZipFile(io.BytesIO(vsdx(ds)))
    names = z.namelist()
    assert "visio/document.xml" in names and f"visio/pages/page{len(ds)}.xml" in names
    for n in names:
        xml.dom.minidom.parseString(z.read(n))
    pages = xml.dom.minidom.parseString(z.read("visio/pages/pages.xml")).getElementsByTagName("Page")
    assert len(pages) == len(ds)


def test_bundle_and_save(program):
    z = zipfile.ZipFile(io.BytesIO(bundle(program, with_png=False)))
    assert any(n.endswith(".vsdx") for n in z.namelist()) and "coverage.json" in z.namelist()
    out = save(program)
    assert Path(out["dir"]).exists() and out["coverage"]["ratio"] == 1.0


def test_layout_handles_cycles_and_self_edges():
    nodes = [{"id": i, "title": f"N{i}"} for i in range(4)]
    edges = [{"from": 0, "to": 1}, {"from": 1, "to": 2}, {"from": 2, "to": 0}, {"from": 3, "to": 3}]
    scene = layered(nodes, edges)
    assert all(len(e["points"]) >= 2 for e in scene["edges"])
    seq = sequence([{"id": "a", "title": "A"}, {"id": "b", "title": "B"}], [{"from": "a", "to": "b", "label": "x"},
                                                                          {"from": "b", "to": "b", "label": "self"}])
    assert sum(1 for e in seq["edges"] if e.get("lifeline")) == 2


def test_empty_program_diagrams(tmp_path):
    store = ProgramStore.create("Empty", root=tmp_path)
    ds = all_diagrams(store)
    assert [d["kind"] for d in ds] == ["architecture", "context", "component", "class"]
    assert vsdx(ds)[:2] == b"PK"
    store.close()


def test_diagram_api(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "programs"))
    from webapp import server
    client = TestClient(server.app)
    slug = client.post("/api/programs", json={"name": "Diag API"}).json()["program"]["slug"]
    with ProgramStore.open(slug) as store:
        add(store, "AIDCALC.cbl", (COBOL / "AIDCALC.cbl").read_text(), "COBOL", "cbl")
    d = client.get(f"/api/programs/{slug}/diagrams").json()
    assert d["coverage"]["ratio"] == 1.0
    first = d["diagrams"][0]["id"]
    assert client.get(f"/api/programs/{slug}/diagrams/{first}.svg").text.startswith("<svg")
    assert client.get(f"/api/programs/{slug}/diagrams/{first}.png").content[:4] == b"\x89PNG"
    r = client.get(f"/api/programs/{slug}/diagrams/export/vsdx")
    assert r.status_code == 200 and r.content[:2] == b"PK" and "attachment" in r.headers["content-disposition"]
    assert client.get(f"/api/programs/{slug}/diagrams/export/zip").content[:2] == b"PK"
    assert client.get(f"/api/programs/{slug}/diagrams/export/pdf").status_code == 404
    assert client.get(f"/api/programs/{slug}/diagrams/nope.svg").status_code == 404


def test_architecture_overview(program):
    from core.assess import run_assessment
    from core.diagrams.build import architecture
    run_assessment(program)
    d = architecture(program)
    lanes = [g["title"] for g in d["groups"] if g["style"] == "lane"]
    assert lanes == ["Users & triggers", "Presentation", "Application", "Integration", "Data", "External"]
    bars = [g["title"] for g in d["groups"] if g["style"] == "bar"]
    assert "Platform & runtime" in bars and "Coverage" in bars
    titles = {n["title"] for n in d["nodes"]}
    assert {"AIDCALC.cbl", "AIDMAP1", "AIDJOB", "Program users"} <= titles
    assert any(n.get("badge") for n in d["nodes"]) and "verdict" in d["title"]
    groups = {g["id"]: g for g in d["groups"] if g["style"] == "group"}
    for n in d["nodes"]:
        if n.get("chip"):
            continue
        assert any(g["x"] <= n["x"] and n["x"] + n["w"] <= g["x"] + g["w"] + 1 and g["y"] <= n["y"]
                   and n["y"] + n["h"] <= g["y"] + g["h"] + 1 for g in groups.values()), n["title"]
    for a in d["nodes"]:
        for b in d["nodes"]:
            if a is not b:
                assert not overlaps(a, b), (a["title"], b["title"])
    assert all(len(e["points"]) == 4 for e in d["edges"])
    xml.dom.minidom.parseString(svg(d))
    xml.dom.minidom.parseString(drawio([d]))
    assert png(d)[:4] == b"\x89PNG"
