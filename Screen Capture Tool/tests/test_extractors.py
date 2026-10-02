from pathlib import Path

import pytest

from core import validate
from core.extractors import parse_artifact
from core.extractors.dispatch import kind_for
from core.model import ProgramStore, ingest_capture

LEGACY = Path(__file__).resolve().parent / "samples" / "legacy"
COBOL = Path(__file__).resolve().parent / "samples" / "cobol"


def sample(name):
    return (LEGACY / name).read_text()


def rels(r, kind=None):
    return {(x["kind"], x["source"], x["target"]) for x in r["relations"] if kind in (None, x["kind"])}


def by_name(r, kind):
    return {e["name"]: e for e in r["entities"] if e["kind"] == kind}


def test_kind_detection():
    assert kind_for("x", "a.sql") == "sql" and kind_for("<configuration/>", "web.config") == "xml"
    assert kind_for("a=1", "db.properties") == "properties" and kind_for("{}", "appsettings.json") == "json"
    assert kind_for("CREATE TABLE T (A INT);", "capture", "") == "sql"
    assert kind_for("x = 'SELECT a FROM b'\ny = 'SELECT c FROM d'", "s.py", "Python") is None
    assert kind_for("print(1)", "a.py", "Python") is None


def test_db2_ddl():
    r = parse_artifact(sample("AIDSCHEMA.sql"), "AIDSCHEMA.sql")
    tables = by_name(r, "table")
    assert set(tables) == {"MDE.DISTRICT", "MDE.DISTRICT_AID", "MDE.V_AID_SUMMARY"}
    assert tables["MDE.V_AID_SUMMARY"]["attrs"]["view"] is True
    assert tables["MDE.DISTRICT_AID"]["attrs"]["indexes"][0]["columns"] == ["FISCAL_YEAR"]
    cols = {(e["parent"], e["name"]): e for e in r["entities"] if e["kind"] == "column"}
    assert cols[("MDE.DISTRICT_AID", "TOTAL_AMOUNT")]["attrs"] == {"type": "DECIMAL(13,2)", "nullable": True}
    assert cols[("MDE.DISTRICT_AID", "FISCAL_YEAR")]["attrs"]["primary_key"] is True
    assert cols[("MDE.DISTRICT", "DISTRICT_ID")]["line_start"] == 3
    assert rels(r) == {("depends_on", "MDE.DISTRICT_AID", "table:MDE.DISTRICT"),
                       ("reads", "MDE.V_AID_SUMMARY", "table:MDE.DISTRICT"),
                       ("reads", "MDE.V_AID_SUMMARY", "table:MDE.DISTRICT_AID")}


def test_tsql_ddl_procs_triggers():
    r = parse_artifact(sample("PaymentSchema.sql"), "PaymentSchema.sql")
    assert set(by_name(r, "table")) == {"DBO.PAYMENTBATCH", "DBO.PAYMENTHISTORY"}
    batch_id = next(e for e in r["entities"] if e["kind"] == "column" and e["name"] == "BATCHID"
                    and e["parent"] == "DBO.PAYMENTBATCH")
    assert batch_id["attrs"]["primary_key"] is True and batch_id["attrs"]["type"].startswith("INT")
    funcs = by_name(r, "function")
    assert funcs["DBO.USP_APPROVEBATCH"]["attrs"]["sql_object"] == "procedure"
    assert funcs["DBO.TRG_BATCHAUDIT"]["attrs"]["sql_object"] == "trigger"
    assert rels(r) == {
        ("depends_on", "DBO.PAYMENTHISTORY", "table:DBO.PAYMENTBATCH"),
        ("writes", "DBO.USP_APPROVEBATCH", "table:DBO.PAYMENTBATCH"),
        ("writes", "DBO.USP_APPROVEBATCH", "table:DBO.PAYMENTHISTORY"),
        ("calls", "DBO.USP_APPROVEBATCH", "function:DBO.USP_AUDITWRITE"),
        ("depends_on", "DBO.TRG_BATCHAUDIT", "table:DBO.PAYMENTBATCH"),
        ("writes", "DBO.TRG_BATCHAUDIT", "table:DBO.AUDITLOG"),
    }


def test_sql_comments_and_strings_ignored():
    r = parse_artifact("-- CREATE TABLE NOPE (A INT);\n/* CREATE TABLE NOPE2 (B INT); */\n"
                       "CREATE TABLE T1 (NOTE VARCHAR(10) DEFAULT 'CREATE TABLE X (');", "x.sql")
    assert set(by_name(r, "table")) == {"T1"}


def test_plain_script_becomes_job():
    r = parse_artifact("UPDATE MDE.DISTRICT_AID SET TOTAL_AMOUNT = 0;\nSELECT * FROM MDE.DISTRICT;\n", "reset.sql")
    assert set(by_name(r, "job")) == {"reset.sql"}
    assert rels(r) == {("writes", "reset.sql", "table:MDE.DISTRICT_AID"), ("reads", "reset.sql", "table:MDE.DISTRICT")}


def test_web_config():
    r = parse_artifact(sample("web.config"), "web.config")
    items = by_name(r, "config_item")
    assert items["SchoolFinance"]["attrs"]["hardcoded_secret"] is True
    assert "P@ssw0rd1" not in items["SchoolFinance"]["attrs"]["value"]
    assert items["SmtpPassword"]["attrs"]["value"] == "****"
    assert items["StateAidRate"]["attrs"]["value"] == "7138.00"
    assert set(by_name(r, "data_store")) == {"SCHOOLFINANCE", "AIDPROD"}
    assert set(by_name(r, "external_system")) == {"tax.mn.gov", "mnit-esb01"}
    assert ("connects_to", "StudentSvc", "external_system:mnit-esb01") in rels(r)
    p = r["file_attrs"]["profile"]
    assert ".NET Framework 4.0" in p["frameworks"] and p["libraries"] == ["Newtonsoft.Json 4.5.0.0"]
    assert p["settings"] == {"targetFramework": "4.0", "debug": True, "customErrors": "Off", "authentication": "Forms"}


def test_web_xml_properties_json():
    r = parse_artifact(sample("web.xml"), "web.xml")
    assert ("calls", "ANY /aid/lookup", "class:AidLookupServlet") in rels(r)
    assert "Java Servlet 2.4" in r["file_attrs"]["profile"]["frameworks"]
    p = parse_artifact(sample("aid.properties"), "aid.properties")
    assert by_name(p, "config_item")["aid.db.password"]["attrs"] == {"value": "****", "hardcoded_secret": True}
    assert ("connects_to", "aid.db.url", "data_store:AIDPROD") in rels(p)
    j = parse_artifact(sample("appsettings.json"), "appsettings.json")
    assert by_name(j, "config_item")["ApiKey"]["attrs"]["hardcoded_secret"] is True
    assert ("connects_to", "Services:Enrollment", "external_system:mnit-api.mn.gov") in rels(j)


def test_xml_and_json_validation(tmp_path):
    bad = tmp_path / "web.config"
    bad.write_text("<configuration><appSettings></configuration>")
    res = validate.check_source(bad)
    assert res["checked"] and not res["ok"] and "web.config:1:" in res["errors"]
    assert validate.check_source(LEGACY / "web.config")["ok"]
    j = tmp_path / "a.json"
    j.write_text('{"a": 1,}')
    assert not validate.check_source(j)["ok"]


class NoApi:
    @property
    def messages(self):
        raise AssertionError("no API calls expected")


def test_program_links_code_ddl_and_config(tmp_path):
    store = ProgramStore.create("Mixed", root=tmp_path)
    files = [
        (COBOL / "AIDINQ.cbl", "COBOL", "cbl"),
        (LEGACY / "AidPaymentController.cs", "C#", "cs"),
        (LEGACY / "AidLookupServlet.java", "Java", "java"),
        (LEGACY / "AIDSCHEMA.sql", "SQL", "sql"),
        (LEGACY / "PaymentSchema.sql", "SQL", "sql"),
        (LEGACY / "web.config", "XML", "config"),
        (LEGACY / "web.xml", "XML", "xml"),
    ]
    for path, lang, ext in files:
        ingest_capture(store, NoApi(), [], {"is_code": True, "code": path.read_text(), "extension": ext,
                                            "language": lang, "errors": "None"}, name=path.name)
    assert {a["name"]: a["artifact_type"] for a in store.artifacts()}["web.config"] == "config"
    assert all(a["status"] == "structured" for a in store.artifacts())
    aid = store.entity_by_key("table:MDE.DISTRICT_AID")
    assert aid["origin"] == "extracted"
    readers = {e["name"] for e in store.neighbors(aid["id"], "in", kind="reads")}
    assert {"LOOKUP-AID", "loadAid", "MDE.V_AID_SUMMARY"} <= readers
    batch = store.entity_by_key("table:DBO.PAYMENTBATCH")
    assert batch["origin"] == "extracted"
    assert {"Approve", "DBO.USP_APPROVEBATCH"} <= {e["name"] for e in store.neighbors(batch["id"], "in", kind="writes")}
    db = store.entity_by_key("data_store:SCHOOLFINANCE")
    assert db["origin"] == "extracted"
    assert {e["name"] for e in store.neighbors(db["id"], "in", kind="connects_to")} >= {"SchoolFinance", "AidPaymentController"}
    servlet = store.entity_by_key("class:AidLookupServlet")
    assert "ANY /aid/lookup" in {e["name"] for e in store.neighbors(servlet["id"], "in", kind="calls")}
    missing = {(m["kind"], m["name"]) for m in store.coverage()["missing"]}
    assert ("table", "MDE.DISTRICT_AID") not in missing and ("table", "DBO.PAYMENTBATCH") not in missing
    assert ("table", "DBO.AUDITLOG") in missing
    store.close()
