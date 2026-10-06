import time

import pytest

from core.cobol.parser import parse_cobol, parse_jcl
from core.model import ProgramStore
from core.model import corrections as C
from core.security.rules import _whole_file, scan_text, student_data_lines

COBOL_HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTP.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE
               ASSIGN TO INDD.
       DATA DIVISION.
       PROCEDURE DIVISION.
       MAIN-PARA.
"""


# ---- 1. secret masking
@pytest.mark.parametrize("name,text,lang,secret", [
    ("a.cs", 'if (password == "hunter2") { ok(); }', "", "hunter2"),
    ("a.cs", 'if (pwd.Equals("hunter2")) { ok(); }', "", "hunter2"),
    ("a.sql", "CREATE USER app IDENTIFIED BY s3cretPw;", "", "s3cretPw"),
    ("a.bat", "sqlcmd -S srv -U sa -P Sup3rS3cret", "batch", "Sup3rS3cret"),
    ("a.pbl", 'SQLCA.DBPass = "tiger"', "powerbuilder", "tiger"),
    ("a.php", 'mysql_connect("h","root","rootpw");', "php", "rootpw"),
])
def test_secrets_never_survive_in_snippet(name, text, lang, secret):
    hits = [h for h in scan_text(text, name, lang) if h["rule"] == "SEC-CRED"]
    assert hits, "rule should fire"
    for h in hits:
        assert secret not in h["snippet"], h["snippet"]


def test_scan_evidence_uses_masked_snippet(tmp_path):
    from test_linker import add
    from core.security import run_scan
    store = ProgramStore.create("Mask", root=tmp_path)
    add(store, "Login.cs", 'class L { void f() { if (password == "hunter2") { go(); } } }\n', "C#", "cs")
    run_scan(store)
    blob = " ".join(str(f["evidence"]) + f["title"] + f["detail"] for f in store.findings())
    assert "hunter2" not in blob
    store.close()


# ---- 2. langpack performance
def test_vba_800_functions_parses_fast():
    from core.langpacks import parse
    parts = ['Attribute VB_Name = "Mod1"', "Option Explicit"]
    for i in range(800):
        parts += [f"Public Function F{i}(x As Long) As Long", "    Dim r As Long", f"    r = F{(i + 1) % 800}(x) + 1",
                  "    ' note", f"    F{i} = r", "End Function", ""]
    text = "\n".join(parts)
    assert len(text.splitlines()) >= 4000
    t = time.perf_counter()
    result = parse(text, "mod1.bas", "VBA")
    assert time.perf_counter() - t < 5
    calls = [r for r in result["relations"] if r["kind"] == "calls"]
    assert any(r["source"] == "F0" and r["target"] == "function:F1" for r in calls)


# ---- 3. END-EXEC
def test_missing_end_exec_does_not_swallow_file():
    body = "".join("           MOVE 1 TO X\n" for _ in range(8000))
    text = COBOL_HEAD + "           EXEC SQL SELECT A INTO :B FROM T1\n" + body + \
        "       NEXT-PARA.\n           PERFORM X-PARA.\n       X-PARA.\n           EXIT.\n"
    t = time.perf_counter()
    out = parse_cobol(text, "t.cbl")
    assert time.perf_counter() - t < 5
    assert any(r["kind"] == "calls" and r["line"] > 8000 and "X-PARA" in r["target"] for r in out["relations"])
    assert any("END-EXEC" in w for w in out.get("warnings", []))


def test_proper_end_exec_still_multiline():
    text = COBOL_HEAD + "           EXEC SQL SELECT A INTO :B\n               FROM T2\n           END-EXEC.\n"
    rels = parse_cobol(text, "t.cbl")["relations"]
    assert any(r["kind"] == "reads" and r["target"] == "table:T2" for r in rels)


# ---- 4. JCL continuation
def test_jcl_continuation_disp_new_is_write():
    jcl = "//J1 JOB\n//S1 EXEC PGM=ABC\n//OUT DD DSN=A.B.C,\n//  DISP=(NEW,CATLG)\n//IN DD DSN=X.Y,DISP=SHR  a comment\n"
    rels = {r["target"]: r for r in parse_jcl(jcl)["relations"] if r["kind"] in ("reads", "writes")}
    assert rels["data_store:A.B.C"]["kind"] == "writes" and rels["data_store:A.B.C"]["attrs"]["disp"] == "NEW"
    assert rels["data_store:X.Y"]["kind"] == "reads"


# ---- 5. SELECT across lines
def test_select_assign_on_next_line():
    out = parse_cobol(COBOL_HEAD, "t.cbl")
    stores = [e for e in out["entities"] if e["kind"] == "data_store"]
    assert [(e["name"], e["attrs"]["assign"]) for e in stores] == [("IN-FILE", "INDD")]


# ---- 6. [Authorize]
CS_CTRL = """public class A : Controller
{
    [Authorize]
    public ActionResult Index() { return View(); }

    [HttpPost]
    public ActionResult DeleteStudent(int id) { return View(); }
}
"""


def test_authorize_elsewhere_in_file_does_not_hide_post():
    out = _whole_file(CS_CTRL.splitlines(), "cs")
    assert any(r == "SEC-AUTHZ" for r, *_ in out)


def test_class_level_and_action_level_authorize_count():
    cls = "[Authorize]\n" + CS_CTRL.replace("    [Authorize]\n", "")
    assert not any(r == "SEC-AUTHZ" for r, *_ in _whole_file(cls.splitlines(), "cs"))
    act = CS_CTRL.replace("    [HttpPost]\n", "    [HttpPost]\n    [Authorize]\n")
    assert not any(r == "SEC-AUTHZ" for r, *_ in _whole_file(act.splitlines(), "cs"))


# ---- 7. lowercase PII names
def test_lowercase_ddl_columns_count_as_personal_data():
    assert student_data_lines(["create table s (ssn char(9), dob date)"]) == {1}
    assert student_data_lines(["// there is a race condition here", 'x = "ssn"']) == set()


# ---- 8. stable signatures
def test_status_survives_line_shift(tmp_path):
    from test_linker import add
    from core.security import run_scan
    code = 'class L { void f() { var s = "SELECT * FROM t WHERE id=" + id; } }\n'
    store = ProgramStore.create("Sig", root=tmp_path)
    add(store, "A.cs", code, "C#", "cs")
    run_scan(store)
    f = next(x for x in store.findings("security") if x["rule"] == "SEC-SQLI")
    store.set_finding_status(f["id"], "dismissed")
    add(store, "A.cs", "// header\n// header2\n" + code, "C#", "cs")
    run_scan(store)
    g = next(x for x in store.findings("security") if x["rule"] == "SEC-SQLI")
    assert g["status"] == "dismissed" and g["title"] != f["title"]
    assert C.finding_sig(g) == C.finding_sig(f)
    store.close()


def test_legacy_signature_still_matches(tmp_path):
    store = ProgramStore.create("Legacy", root=tmp_path)
    fid = store.add_finding("security", "high", "Title: a.cs:3", rule="SEC-X")
    f = store.finding(fid)
    assert C.finding_sig(f) == "SEC-X|Title: a.cs:3"
    C.add(store, "finding.status", {"sig": "SEC-X|Title: a.cs:3", "status": "dismissed"})
    C.apply_corrections(store)
    assert store.finding(fid)["status"] == "dismissed"
    store.close()


# ---- 9. SQL concat
def test_unrelated_concat_not_flagged_as_sqli():
    src = 'String q = "SELECT * FROM t WHERE id = 1"\nint k = 0\nString m = "Hello " + userName;\n'
    assert not [h for h in scan_text(src, "A.java") if h["rule"] == "SEC-SQLI"]
    real = 'String q = "SELECT * FROM t WHERE id = " + userId;\n'
    assert [h for h in scan_text(real, "A.java") if h["rule"] == "SEC-SQLI"]
    chained = 'String q = "SELECT * FROM t " + "WHERE n = \'" + name + "\'";\n'
    assert [h for h in scan_text(chained, "A.java") if h["rule"] == "SEC-SQLI"]


# ---- 10. TLS config noise
def test_schema_urls_are_not_tls_findings():
    xml = ('<beans xmlns="http://www.springframework.org/schema/beans"\n'
           '  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
           '  xsi:schemaLocation="http://www.springframework.org/schema/beans http://www.springframework.org/schema/beans/spring-beans.xsd">\n'
           '<!DOCTYPE hibernate-mapping PUBLIC "-//Hibernate" "http://hibernate.sourceforge.net/hibernate-mapping-3.0.dtd">\n'
           '<project xmlns="http://maven.apache.org/POM/4.0.0">\n')
    assert not [h for h in scan_text(xml, "pom.xml") if h["rule"] == "SEC-TLS"]
    assert [h for h in scan_text('<add key="u" value="http://evil.example.com/api"/>', "app.config") if h["rule"] == "SEC-TLS"]


# ---- 11. store transactions
def test_fill_artifact_removes_previous_source_file(tmp_path):
    from test_linker import add
    store = ProgramStore.create("Src", root=tmp_path)
    add(store, "A.cs", "class A {}\n", "C#", "cs")
    art = store.artifacts()[0]
    old = store.sources_dir / art["source_path"]
    assert old.exists()
    store.fill_artifact(art["id"], artifact_type=art["artifact_type"], language=art["language"], transcription="class B {}\n")
    new = store.artifact(art["id"])["source_path"]
    assert not old.exists() and (store.sources_dir / new).read_text() == "class B {}\n"
    store.close()


def test_set_verification_round_trip(tmp_path):
    store = ProgramStore.create("Ver", root=tmp_path)
    store.set_verification(1, {"ok": True})
    store.set_verification(2, {"ok": False})
    store.set_verification(1, None)
    assert store.verification() == {"2": {"ok": False}}
    store.close()


# ---- 12. one-line corrections
@pytest.mark.parametrize("sep", ["\n", "\r", "\x0b", "\x0c", "\x85", " ", " ", "\x1c"])
def test_replace_line_rejects_embedded_line_breaks(sep):
    with pytest.raises(C.CorrectionError):
        C.validate("artifact.replace_line", {"artifact": "A.cs", "line": 1, "old_text": "x", "new_text": f"a{sep}b"})
    with pytest.raises(C.CorrectionError):
        C.validate("artifact.replace_line", {"artifact": "A.cs", "line": 1, "old_text": "x", "new_text": ""[:0] + sep})
    C.validate("artifact.replace_line", {"artifact": "A.cs", "line": 1, "old_text": "x", "new_text": "ab"})
