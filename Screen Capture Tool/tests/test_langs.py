from pathlib import Path

import pytest

pytest.importorskip("tree_sitter")

from core import validate
from core.langs.check import check_legacy_source
from core.langs.grammars import lang_for, prepare
from core.langs.profile import technology_profile
from core.langs.structure import connection_target, mask_connection, parse_source
from core.langs.syntax import syntax_errors
from core.model import ProgramStore, ingest_capture

SAMPLES = Path(__file__).resolve().parent / "samples" / "legacy"


def sample(name):
    return (SAMPLES / name).read_text()


def rels(r, kind=None):
    return {(x["kind"], x["source"], x["target"]) for x in r["relations"] if kind in (None, x["kind"])}


def ents(r, kind=None):
    return {(e["kind"], e["name"], e["parent"]) for e in r["entities"] if kind in (None, e["kind"])}


def test_lang_for():
    assert lang_for(extension="CPP") == "cpp" and lang_for(extension="cs") == "c_sharp"
    assert lang_for("Java") == "java" and lang_for("C#") == "c_sharp" and lang_for("C++") == "cpp"
    assert lang_for("COBOL") is None and lang_for(extension="py") is None


def test_java_servlet_structure():
    r = parse_source(sample("AidLookupServlet.java"), "AidLookupServlet.java")
    assert ("class", "AidLookupServlet", None) in ents(r)
    assert {e[1] for e in ents(r, "function")} == {"doGet", "loadAid", "sourceName"}
    assert ("api_endpoint", "GET servlet:AidLookupServlet", None) in ents(r)
    assert {
        ("inherits", "AidLookupServlet", "class:HttpServlet"),
        ("implements", "AidLookupServlet", "interface:AuditSource"),
        ("calls", "doGet", "function:AidLookupServlet.loadAid"),
        ("calls", "doGet", "function:AidCalculator.total"),
        ("calls", "doGet", "function:AuditLog.record"),
        ("reads", "loadAid", "table:MDE.DISTRICT_AID"),
        ("connects_to", "AidLookupServlet", "data_store:AIDPROD"),
        ("calls", "GET servlet:AidLookupServlet", "doGet"),
    } <= rels(r)
    assert not any(t.startswith("function:ResultSet") or t.startswith("class:Vector") for _, _, t in rels(r))


def test_csharp_mvc_structure():
    r = parse_source(sample("AidPaymentController.cs"), "AidPaymentController.cs")
    assert {e[1] for e in ents(r, "api_endpoint")} == {"GET /aid/district/{id}", "POST /aid/Approve"}
    assert {
        ("inherits", "AidPaymentController", "class:Controller"),
        ("implements", "AidPaymentController", "interface:IAuditable"),
        ("calls", "District", "function:PaymentService.TotalFor"),
        ("calls", "District", "function:AidPaymentController.LoadHistory"),
        ("writes", "Approve", "table:DBO.PAYMENTBATCH"),
        ("reads", "LoadHistory", "table:DBO.PAYMENTHISTORY"),
        ("reads", "LoadHistory", "table:DBO.DISTRICT"),
        ("imports", "__file__", "module:System.Web.Mvc"),
    } <= rels(r)
    conn = next(x for x in r["relations"] if x["kind"] == "connects_to")
    assert conn["target"] == "data_store:SCHOOLFINANCE" and conn["attrs"]["hardcoded_secret"] is True
    assert "P@ssw0rd1" not in conn["attrs"]["connection"] and "Password=****" in conn["attrs"]["connection"]
    writes = [x for x in r["relations"] if x["kind"] == "writes"]
    assert [w["line"] for w in writes] == [28]


def test_cobol_translated_csharp():
    r = parse_source(sample("AidCalcTranslated.cs"), "AidCalcTranslated.cs")
    p = r["file_attrs"]["profile"]
    assert p["cobol_translated"] is True
    assert {("calls", "P0000_MAIN_PARA", "function:AIDCALC.P1000_READ_DISTRICT_PARA"),
            ("calls", "P2000_CALC_AID_PARA", "function:AIDCALC.P1000_READ_DISTRICT_PARA")} <= rels(r)


def test_prestandard_cpp():
    code = sample("AIDRPT.CPP")
    assert syntax_errors(code, "cpp") == []
    assert len(prepare(code, "cpp")) == len(code) and " far " not in prepare(code, "cpp")
    r = parse_source(code, "AIDRPT.CPP")
    assert ents(r, "function") >= {("function", "Print", "AidReport"), ("function", "main", None)}
    assert {("inherits", "AidReport", "class:ReportBase"), ("includes", "__file__", "module:aidrec.h"),
            ("calls", "Print", "function:AidRecord.Load"), ("calls", "main", "function:AidReport.Print")} <= rels(r)
    p = r["file_attrs"]["profile"]
    assert p["dialect"].startswith("pre-standard")
    assert {"pre-standard C++ headers", "void main", "no std namespace (pre-1998 style)",
            "far/near/huge pointers (16-bit)"} <= set(p["legacy_markers"])
    assert p["evidence"]["void main"] == [25]


@pytest.mark.parametrize("code,lang,label", [
    ("#include <afxwin.h>\nclass A : public CWinApp {};", "cpp", "MFC"),
    ("#include <windows.h>\nint WinMain() { return 0; }", "cpp", "Win32 API"),
    ("using System.ServiceModel;\n[ServiceContract] interface I {}", "c_sharp", "WCF"),
    ("using System.Runtime.Remoting;\nclass A : MarshalByRefObject {}", "c_sharp", ".NET Remoting (obsolete)"),
    ("import org.apache.struts.action.Action;\nclass A extends Action {}", "java", "Struts 1"),
    ("import javax.ejb.SessionBean;\nclass A implements SessionBean {}", "java", "EJB 2.x (home/remote)"),
    ("import java.applet.Applet;\nclass A extends Applet {}", "java", "Applet (removed)"),
])
def test_framework_signals(code, lang, label):
    assert label in technology_profile(code, lang)["frameworks"]


def test_levels_and_comment_ignored():
    assert technology_profile("class A { void f() { list.forEach(x -> g(x)); } }", "java")["level_signal"] == "Java 8 lambdas/streams"
    assert technology_profile("// using System.Web.UI;\nclass A {}", "c_sharp")["frameworks"] == []
    assert technology_profile("class A { async Task F() { await G(); } }", "c_sharp")["level_signal"] == "C# 5.0 async"


def test_syntax_errors_report_lines():
    bad = sample("AidLookupServlet.java").replace("Vector rows = loadAid(districtId);", "Vector rows = loadAid(districtId;")
    errs = syntax_errors(bad, "java")
    assert errs and errs[0]["line"] == 20
    bad_cs = sample("AidPaymentController.cs").replace("cmd.ExecuteNonQuery();", "cmd.ExecuteNonQuery()")
    assert syntax_errors(bad_cs, "c_sharp")[0]["line"] in (28, 29)


def test_validate_routes_to_tree_sitter(tmp_path):
    f = tmp_path / "Bad.java"
    f.write_text("class Bad { void f() { g( } }")
    res = validate.check_source(f)
    assert res["checked"] and not res["ok"] and "Bad.java:1:" in res["errors"] and "tree-sitter" in res["tool"]
    ok = tmp_path / "Ok.cs"
    ok.write_text(sample("AidPaymentController.cs"))
    assert validate.check_source(ok)["ok"]


def test_cpp_missing_header_is_a_gap_not_an_error():
    res = check_legacy_source(SAMPLES / "AIDRPT.CPP")
    assert res["checked"] and res["ok"]
    if "g++" in res["tool"] or "clang" in res["tool"]:
        assert "aidrec.h" in res["note"]


def test_connection_helpers():
    assert connection_target("jdbc:db2://mdedb01:50000/AIDPROD") == "AIDPROD"
    assert connection_target("jdbc:oracle:thin:@//host:1521/FINPDB") == "FINPDB"
    assert connection_target("Server=SQL1;Database=Finance;Trusted_Connection=True") == "Finance"
    assert connection_target("DSN=AIDODBC;UID=x") == "AIDODBC"
    assert mask_connection("Data Source=A;Password=secret;User ID=b") == "Data Source=A;Password=****;User ID=b"


class NoApi:
    @property
    def messages(self):
        raise AssertionError("legacy languages should be parsed without the API")


def test_ingest_links_across_languages(tmp_path):
    store = ProgramStore.create("Mixed", root=tmp_path)
    for name, lang, ext in [("AidLookupServlet.java", "Java", "java"), ("AidPaymentController.cs", "C#", "cs"),
                            ("AIDRPT.CPP", "C++", "cpp"), ("AidCalcTranslated.cs", "C#", "cs")]:
        ingest_capture(store, NoApi(), [], {"is_code": True, "code": sample(name), "extension": ext, "language": lang,
                                            "errors": "None"}, name=name)
    assert all(a["status"] == "structured" for a in store.artifacts())
    runs = {r["model"] for r in store.runs()}
    assert runs == {"ts-parser-v1"} and store.usage()["input_tokens"] == 0
    f = store.entity_by_key("file:AidPaymentController.cs")
    assert "ASP.NET MVC" in f["attrs"]["profile"]["frameworks"]
    table = store.entity_by_key("table:DBO.PAYMENTBATCH")
    assert {e["name"] for e in store.neighbors(table["id"], "in", kind="writes")} == {"Approve"}
    ep = store.entity_by_key("api_endpoint:GET /aid/district/{id}")
    assert ep and {e["name"] for e in store.neighbors(ep["id"], "out", kind="calls")} == {"District"}
    missing = {m["name"] for m in store.coverage()["missing"]}
    assert "AidCalculator.total" in missing and "PaymentService.TotalFor" in missing
    store.close()
