from pathlib import Path

import pytest

pytest.importorskip("tree_sitter")

from core.model import ProgramStore, ingest_capture
from core.model.linker import classify, link_program, trace_flows

TESTS = Path(__file__).resolve().parent
COBOL, LEGACY = TESTS / "samples" / "cobol", TESTS / "samples" / "legacy"


class NoApi:
    @property
    def messages(self):
        raise AssertionError("linking must not call the API")


def add(store, name, code, lang, ext, atype=None):
    report = {"is_code": True, "code": code, "extension": ext, "language": lang, "errors": "None"}
    if atype:
        report["artifact_type"] = atype
    return ingest_capture(store, NoApi(), [], report, name=name)


@pytest.fixture
def program(tmp_path):
    store = ProgramStore.create("Linked", root=tmp_path)
    for f in ("AIDCALC.cbl", "AIDINQ.cbl", "AIDREC.cpy", "AIDMAP.bms", "AIDJOB.jcl"):
        p = COBOL / f
        add(store, f, p.read_text(), {"cbl": "COBOL", "cpy": "COBOL copybook", "bms": "CICS BMS map",
                                      "jcl": "JCL"}[p.suffix[1:]], p.suffix[1:])
    for f, lang, ext in (("AidPaymentController.cs", "C#", "cs"), ("web.config", "XML", "config"),
                         ("AIDSCHEMA.sql", "SQL", "sql"), ("PaymentSchema.sql", "SQL", "sql")):
        add(store, f, (LEGACY / f).read_text(), lang, ext)
    add(store, "Settings.cs", 'using System.Configuration;\nclass Settings {\n  string Conn() {\n'
        '    return ConfigurationManager.ConnectionStrings["SchoolFinance"].ConnectionString;\n  }\n'
        '  string Rate() { return ConfigurationManager.AppSettings["StateAidRate"]; }\n}\n', "C#", "cs")
    add(store, "reset.sql", "UPDATE DISTRICT_AID SET TOTAL_AMOUNT = 0;\nSELECT * FROM DISTRICT;\n", "SQL", "sql")
    add(store, "AIDQ.screen", (LEGACY / "ScreenAidInquiry.screen").read_text(), "UI screen", "screen", "ui_screen")
    yield store
    store.close()


def test_unqualified_tables_merge_into_ddl(program):
    for name in ("DISTRICT_AID", "DISTRICT"):
        assert program.entity_by_key(f"table:{name}") is None
    aid = program.entity_by_key("table:MDE.DISTRICT_AID")
    assert "table:DISTRICT_AID" in aid["attrs"]["aliases"]
    writers = {e["name"] for e in program.neighbors(aid["id"], "in", kind="writes")}
    assert "reset.sql" in writers


def test_jcl_dd_reaches_cobol_file(program):
    file = program.entity_by_key("data_store:DISTRICT-FILE")
    targets = {e["name"] for e in program.neighbors(file["id"], "out", kind="connects_to")}
    assert targets == {"MDE.FIN.DISTRICT.INPUT"}
    out = program.entity_by_key("data_store:PAYMENT-FILE")
    assert {e["name"] for e in program.neighbors(out["id"], "out", kind="connects_to")} == {"MDE.FIN.AID.PAYMENTS"}


def test_config_keys_reach_code(program):
    conn = program.entity_by_key("config_item:SchoolFinance")
    readers = {e["name"] for e in program.neighbors(conn["id"], "in", kind="reads")}
    assert readers == {"Conn"}
    rate = program.entity_by_key("config_item:StateAidRate")
    assert {e["name"] for e in program.neighbors(rate["id"], "in", kind="reads")} == {"Rate"}


def test_screenshot_matches_bms_map(program):
    shot = program.entity_by_key("screen:AIDQ - District Aid Inquiry")
    assert {e["name"] for e in program.neighbors(shot["id"], "out", kind="same_as")} == {"AIDMAP1"}


def test_classification(program):
    cov = program.coverage()
    cats = {(m["kind"], m["name"]): m["category"] for m in cov["missing"]}
    assert cats[("program", "AIDAUDIT")] == "missing_code"
    assert cats[("transaction", "AIDQ")] == "external"
    assert cats[("table", "DBO.AUDITLOG")] == "external"
    assert cats[("module", "System.Web.Mvc")] == "library"
    assert cats[("class", "Controller")] == "library"
    assert ("table", "MDE.DISTRICT_AID") not in cats and ("screen", "AIDMAP1") not in cats
    assert cov["missing_counts"]["missing_code"] >= 1 and cov["missing_counts"]["library"] >= 3
    assert 0 < cov["resolved_ratio"] <= 1


def test_classify_rules():
    assert classify({"kind": "module", "name": "aidrec.h"}, [{"relation": "includes"}]) == "missing_code"
    assert classify({"kind": "module", "name": "iostream.h"}, [{"relation": "includes"}]) == "library"
    assert classify({"kind": "function", "name": "SqlCommand.ExecuteReader"}) == "library"
    assert classify({"kind": "function", "name": "PaymentService.TotalFor"}) == "missing_code"
    assert classify({"kind": "data_store", "name": "X"}) == "external"


def test_flows(program):
    flows = trace_flows(program)
    job = [f for f in flows if f["entry"] == "AIDJOB"]
    assert any(f["target"] == "DISTRICT-FILE" and f["access"] == "reads" for f in job)
    assert any(f["target"] == "MDE.FIN.DISTRICT.INPUT" for f in job)
    ep = [f for f in flows if f["entry"] == "POST /aid/Approve"]
    assert any(f["target"] == "DBO.PAYMENTBATCH" and f["access"] == "writes" for f in ep)
    step = next(f for f in ep if f["target"] == "DBO.PAYMENTBATCH")["steps"]
    assert step[0]["from"] == "POST /aid/Approve" and step[-1]["line"] == 28


def test_linker_is_idempotent(program):
    before = (len(program.entities()), len(program.relations()))
    first = link_program(program)
    assert (len(program.entities()), len(program.relations())) == before
    assert first["merged"] == 0


def test_cobol_call_to_translated_class(tmp_path):
    store = ProgramStore.create("T", root=tmp_path)
    add(store, "DRIVER.cbl", "000100 IDENTIFICATION DIVISION.\n000200 PROGRAM-ID. DRIVER.\n000300 PROCEDURE DIVISION.\n"
        "000400 MAIN-PARA.\n000500     CALL 'AIDCALC'\n000600     GOBACK.\n", "COBOL", "cbl")
    add(store, "AidCalcTranslated.cs", (LEGACY / "AidCalcTranslated.cs").read_text(), "C#", "cs")
    placeholder = store.entity_by_key("program:AIDCALC")
    assert {e["name"] for e in store.neighbors(placeholder["id"], "out", kind="same_as")} == {"AIDCALC"}
    assert "AIDCALC" not in {m["name"] for m in store.coverage()["missing"]}
    store.close()


def test_api_relink_and_flows(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from webapp import server
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path))
    client = TestClient(server.app)
    slug = client.post("/api/programs", json={"name": "F"}).json()["program"]["slug"]
    with ProgramStore.open(slug, root=tmp_path) as store:
        add(store, "AidPaymentController.cs", (LEGACY / "AidPaymentController.cs").read_text(), "C#", "cs")
    r = client.post(f"/api/programs/{slug}/relink").json()
    assert r["ok"] and "missing_counts" in r["coverage"]
    flows = client.get(f"/api/programs/{slug}/flows").json()
    assert flows["total"] >= 1 and flows["flows"][0]["steps"]
