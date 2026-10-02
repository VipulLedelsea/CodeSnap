import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from test_ingest import BILLING, MAIN, FakeClient, report


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "programs"))
    from webapp import server
    reports = tmp_path / "reports"
    (reports / "pending").mkdir(parents=True)
    monkeypatch.setattr(server, "REPORTS", reports)
    monkeypatch.setattr(server, "PENDING", reports / "pending")
    fake = FakeClient([BILLING, MAIN, BILLING])
    monkeypatch.setattr(server, "_client", lambda: fake)
    started = {}
    monkeypatch.setattr(server._session, "start", lambda **kw: started.update(kw) or True)
    monkeypatch.setattr(server._session, "running", lambda: True)
    client = TestClient(server.app)
    client.reports, client.started = reports, started
    return client


def seed(slug, tmp_path):
    from core.model import ProgramStore, ingest_capture
    with ProgramStore.open(slug) as store:
        shot = tmp_path / "s.png"
        shot.write_bytes(b"\x89PNGshot")
        return ingest_capture(store, FakeClient([BILLING]), [shot], report("class Billing: ..."))


def test_create_list_and_detail(api, tmp_path):
    assert api.post("/api/programs", json={"name": ""}).status_code == 400
    slug = api.post("/api/programs", json={"name": "MDE Aid Calc"}).json()["program"]["slug"]
    assert [p["slug"] for p in api.get("/api/programs").json()["programs"]] == [slug]
    aid = seed(slug, tmp_path)
    d = api.get(f"/api/programs/{slug}").json()
    assert d["coverage"]["files"] == 1 and d["artifacts"][0]["entities"] == 3 and d["artifacts"][0]["frames"] == 1
    assert d["artifacts"][0]["cost"] == 0.0013 and isinstance(d["usage_by_step"], list)
    assert d["usage_by_step"][0]["step"] == "structure"
    art = api.get(f"/api/programs/{slug}/artifacts/{aid}").json()
    assert {e["name"] for e in art["entities"]} == {"Billing.py", "Billing", "calculate"}
    ev = art["evidence"][0]["id"]
    assert api.get(f"/api/programs/{slug}/evidence/{ev}").content == b"\x89PNGshot"
    assert api.get(f"/api/programs/{slug}/artifacts/999").status_code == 404
    assert api.get("/api/programs/nope").status_code == 404
    assert api.get("/api/programs/..%2F..").status_code == 404


def test_graph_coverage_export(api, tmp_path):
    slug = api.post("/api/programs", json={"name": "P"}).json()["program"]["slug"]
    seed(slug, tmp_path)
    g = api.get(f"/api/programs/{slug}/graph").json()
    assert g["mermaid"].startswith("flowchart LR") and g["edges"]
    assert {m["name"] for m in api.get(f"/api/programs/{slug}/coverage").json()["missing"]} >= {"PAYMENTS"}
    exported = json.loads(api.get(f"/api/programs/{slug}/export").content)
    assert exported["program"]["slug"] == slug and exported["entities"]


def test_rename_and_reextract(api, tmp_path):
    slug = api.post("/api/programs", json={"name": "P"}).json()["program"]["slug"]
    aid = seed(slug, tmp_path)
    r = api.post(f"/api/programs/{slug}/artifacts/{aid}/rename", json={"name": "billing.py"})
    assert r.json()["artifact"]["name"] == "billing.py"
    r = api.post(f"/api/programs/{slug}/artifacts/{aid}/reextract").json()
    assert r["ok"] and r["entities"] == 2


def test_import_and_session_start(api, tmp_path):
    slug = api.post("/api/programs", json={"name": "P"}).json()["program"]["slug"]
    (api.reports / "Report_Main.json").write_text(json.dumps(
        {"language": "Python", "code": "def main(): ...", "extension": "py", "code_file": "Code_Main.py"}))
    r = api.post(f"/api/programs/{slug}/import").json()
    assert [i["name"] for i in r["imported"]] == ["Main.py"]
    assert api.post("/api/session/start?program=missing").status_code == 404
    r = api.post(f"/api/session/start?program={slug}&idle_stop=3").json()
    assert r["program"] == slug and r["project_mode"] is True and api.started["program"] == slug
