import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.extractors import parse_artifact
from core.extractors.dispatch import kind_for
from core.extractors.ui import MARKER, extract_ui_screen, parse_ui_json, to_transcription
from core.model import ProgramStore, ingest_capture

LEGACY = Path(__file__).resolve().parent / "samples" / "legacy"


def sample(name):
    return (LEGACY / name).read_text()


def rels(r, kind=None):
    return {(x["kind"], x["source"], x["target"]) for x in r["relations"] if kind in (None, x["kind"])}


def by(r, kind):
    return {e["name"]: e for e in r["entities"] if e["kind"] == kind}


def test_kinds():
    assert kind_for("x", "a.aspx") == "web" and kind_for("x", "a.jsp") == "web"
    assert kind_for(sample("StudentService.wsdl"), "s.wsdl") == "wsdl"
    assert kind_for(sample("aid-api.json"), "aid-api.json") == "openapi"
    assert kind_for(sample("appsettings.json"), "appsettings.json") == "json"
    assert kind_for(sample("AIDREPORT.sps"), "r.sps") == "spss"
    assert kind_for(sample("ScreenAidInquiry.screen"), "x.screen") == "ui"
    assert kind_for("<html><body><form><input name=a></form></body></html>", "capture", "") == "web"


def test_aspx_page():
    r = parse_artifact(sample("DistrictAid.aspx"), "DistrictAid.aspx")
    screen = by(r, "screen")["DistrictAid"]
    assert screen["attrs"]["title"] == "District Aid Lookup"
    els = by(r, "ui_element")
    assert els["txtDistrict"]["attrs"]["label"] == "District ID" and els["txtDistrict"]["attrs"]["max_length"] == 6
    assert els["txtYear"]["attrs"]["has_label"] is False
    assert els["btnLookup"]["attrs"]["text"] == "Look up"
    assert {("calls", "btnLookup", "function:DistrictAidPage.btnLookup_Click"),
            ("uses", "DistrictAid", "class:DistrictAidPage"),
            ("navigates_to", "DistrictAid", "screen:PaymentHistory"),
            ("connects_to", "DistrictAid", "external_system:education.mn.gov")} <= rels(r)
    p = r["file_attrs"]["profile"]
    assert p["frameworks"] == ["ASP.NET Web Forms (Page)"] and p["libraries"] == ["jquery 1.4.2"]
    assert any("jQuery 1.4.2" in m for m in p["legacy_markers"]) and "IE conditional comments" in p["legacy_markers"]
    assert p["settings"]["unlabeled_fields"] == 2


def test_jsp_page():
    r = parse_artifact(sample("AidLookup.jsp"), "AidLookup.jsp")
    assert ("calls", "AidLookup", "GET /aid/lookup") in rels(r)
    assert ("includes", "AidLookup", "screen:header") in rels(r)
    assert by(r, "ui_element")["district"]["attrs"]["required"] is True
    p = r["file_attrs"]["profile"]
    assert p["frameworks"] == ["JSP"] and "ActiveX control (L10)" in p["legacy_markers"] and "Flash (L10)" in p["legacy_markers"]


def test_wsdl_and_openapi():
    w = parse_artifact(sample("StudentService.wsdl"), "StudentService.wsdl")
    assert set(by(w, "api_endpoint")) == {"SOAP StudentService/GetEnrollment", "SOAP StudentService/GetStudentCount"}
    assert ("connects_to", "SOAP StudentService/GetEnrollment", "external_system:mnit-esb01") in rels(w)
    o = parse_artifact(sample("aid-api.json"), "aid-api.json")
    eps = by(o, "api_endpoint")
    assert set(eps) == {"GET /aid/district/{id}", "POST /aid/Approve"} and eps["POST /aid/Approve"]["attrs"]["deprecated"]


def test_spss():
    r = parse_artifact(sample("AIDREPORT.sps"), "AIDREPORT.sps")
    assert set(by(r, "job")) == {"AIDREPORT.sps"}
    assert rels(r) == {("reads", "AIDREPORT.sps", "data_store:district_aid_fy2019.sav"),
                       ("reads", "AIDREPORT.sps", "data_store:district_lookup.sav"),
                       ("writes", "AIDREPORT.sps", "data_store:aid_summary.sav"),
                       ("writes", "AIDREPORT.sps", "data_store:aid_summary.xls")}
    p = r["file_attrs"]["profile"]
    assert "Python programmability" in p["frameworks"] and "Macros (DEFINE-!ENDDEFINE)" in p["frameworks"]
    assert p["settings"]["analyses"] == "DESCRIPTIVES, FREQUENCIES"


def test_ui_json():
    r = parse_ui_json(sample("ScreenAidInquiry.screen"), "x.screen")
    screen = by(r, "screen")["AIDQ - District Aid Inquiry"]
    assert screen["attrs"]["screen_type"] == "terminal" and len(screen["attrs"]["issues"]) == 2
    els = by(r, "ui_element")
    assert els["District ID"]["attrs"]["required"] is True and els["Total Aid"]["attrs"]["input"] is False
    assert els["PF3=Exit"]["attrs"]["action"] is True
    assert r["file_attrs"]["profile"]["legacy_markers"] == ["3270 terminal"]
    assert parse_ui_json('{"a": 1}') is None and parse_ui_json("not json") is None


class Vision:
    def __init__(self, data, as_text=False):
        self.data, self.as_text, self.calls = data, as_text, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.as_text:
            block = SimpleNamespace(type="text", text=json.dumps(self.data))
        else:
            block = SimpleNamespace(type="tool_use", name="record_screen", input=self.data)
        return SimpleNamespace(content=[block], usage=SimpleNamespace(input_tokens=1500, output_tokens=300),
                               stop_reason="tool_use", model=kw["model"])


SCREEN = {"title": "Payment Approval", "screen_type": "form", "technology_hints": ["ASP.NET Web Forms"],
          "fields": [{"label": "Batch", "kind": "text", "required": True}, {"label": "Amount", "kind": "currency"}],
          "actions": [{"label": "Approve", "kind": "button"}], "issues": ["Amount field has no label association"]}


def test_extract_ui_screen_tool_and_text(tmp_path):
    shot = tmp_path / "s.png"
    shot.write_bytes(b"\x89PNGx")
    client = Vision(SCREEN)
    out = extract_ui_screen(client, [shot])
    assert out[MARKER] == 1 and out["title"] == "Payment Approval"
    assert client.calls[0]["tool_choice"] == {"type": "auto"} and client.calls[0]["messages"][0]["content"][0]["type"] == "image"
    assert extract_ui_screen(Vision(SCREEN, as_text=True), [shot])["title"] == "Payment Approval"
    with pytest.raises(ValueError):
        extract_ui_screen(Vision({}), [shot])


def test_screen_capture_flows_into_program(tmp_path, monkeypatch):
    import hotkey_capture as hk
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path))
    ProgramStore.create("Screens", root=tmp_path).close()
    shot = tmp_path / "001.png"
    shot.write_bytes(b"\x89PNGscreen")
    app = hk.App(Vision(SCREEN))
    app.program, app.capture_kind = "screens", "screen"
    ctx = SimpleNamespace(last_report=None)
    app._analyse_screen([shot], ctx)
    assert ctx.last_report["artifact_type"] == "ui_screen"
    app._ingest_into_program([shot], ctx, app.tracker.take(everything=True))
    with ProgramStore.open("screens", root=tmp_path) as store:
        [art] = store.artifacts()
        assert art["name"] == "Payment_Approval.screen" and art["artifact_type"] == "ui_screen"
        assert art["status"] == "structured"
        screen = store.entity_by_key("screen:Payment Approval")
        assert {e["name"] for e in store.entities(kind="ui_element")} == {"Batch", "Amount", "Approve"}
        assert {r["step"] for r in store.runs()} == {"structure", "ui_screen"} and store.usage()["cost"] > 0


def test_openapi_merges_with_controller_endpoints(tmp_path):
    class NoApi:
        @property
        def messages(self):
            raise AssertionError("no API")
    store = ProgramStore.create("Api", root=tmp_path)
    for name, lang, ext in [("AidPaymentController.cs", "C#", "cs"), ("aid-api.json", "JSON", "json"),
                            ("DistrictAid.aspx", "ASPX", "aspx"), ("AIDREPORT.sps", "SPSS", "sps")]:
        ingest_capture(store, NoApi(), [], {"is_code": True, "code": sample(name), "extension": ext, "language": lang,
                                            "errors": "None"}, name=name)
    types = {a["name"]: a["artifact_type"] for a in store.artifacts()}
    assert types == {"AidPaymentController.cs": "code", "aid-api.json": "config", "DistrictAid.aspx": "web",
                     "AIDREPORT.sps": "job"}
    ep = store.entity_by_key("api_endpoint:GET /aid/district/{id}")
    assert ep["attrs"]["operation_id"] == "District"
    assert {e["name"] for e in store.neighbors(ep["id"], "out", kind="calls")} == {"District"}
    assert len(store.entities(kind="api_endpoint")) == 3
    store.close()


def test_type_override_route(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from webapp import server
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path))
    client = TestClient(server.app)
    slug = client.post("/api/programs", json={"name": "T"}).json()["program"]["slug"]
    with ProgramStore.open(slug, root=tmp_path) as store:
        aid = store.add_artifact("capture_7", "other", "", sample("PaymentSchema.sql"))
    assert client.post(f"/api/programs/{slug}/artifacts/{aid}/type", json={"artifact_type": "nope"}).status_code == 400
    r = client.post(f"/api/programs/{slug}/artifacts/{aid}/type", json={"artifact_type": "sql"}).json()
    assert r["ok"] and r["artifact"]["artifact_type"] == "sql" and r["entities"] > 5
    started = {}
    monkeypatch.setattr(server._session, "start", lambda **kw: started.update(kw) or True)
    monkeypatch.setattr(server._session, "running", lambda: True)
    assert client.post("/api/session/start?capture_kind=video").status_code == 400
    assert client.post("/api/session/start?capture_kind=screen").json()["capture_kind"] == "screen"
    assert started["capture_kind"] == "screen"
