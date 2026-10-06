"""Unit tests for the report's reasoning: security rules, scorecard, posture, CVSS, data grouping, dispositions,
anonymization and the missing-component list. Every rule is tested firing and not firing."""
import pytest

from core.report import dataarch as DA
from core.report import options as OP
from core.report import ratings as RT
from core.report.redact import Redactor
from core.security.rules import family, scan_text


def rules(text, name, lang=""):
    return {(h["rule"], h["severity"]) for h in scan_text(text, name, lang)}


def rule_ids(text, name, lang=""):
    return {r for r, _ in rules(text, name, lang)}


# ── security rules ──────────────────────────────────────────────────────────────────────────────────────────────

PLSQL = """CREATE OR REPLACE PACKAGE BODY P AS
  PROCEDURE post(p IN VARCHAR2) IS
    v VARCHAR2(400);
  BEGIN
    v := 'DELETE FROM t WHERE k = ''' || p || '''';
    EXECUTE IMMEDIATE v || ' AND s = 1';
  EXCEPTION
    WHEN OTHERS THEN NULL;
  END post;
END P;
"""


def test_sql_file_with_plsql_is_plsql_family():
    assert family("pkg.sql", "", PLSQL) == "plsql"
    assert family("pkg.sql", "PL/SQL", "select 1 from dual") == "plsql"
    assert family("schema.sql", "SQL", "CREATE TABLE t (id INT);") == "sql"


def test_plsql_swallowed_errors_and_dynamic_sql():
    ids = rule_ids(PLSQL, "pkg.sql")
    assert {"SEC-ERR", "SEC-SQLI"} <= ids


def test_plsql_with_real_handler_is_clean():
    ok = PLSQL.replace("WHEN OTHERS THEN NULL;", "WHEN OTHERS THEN log_error(SQLERRM); RAISE;").replace(
        "EXECUTE IMMEDIATE v || ' AND s = 1';", "DELETE FROM t WHERE k = p;")
    assert not {"SEC-ERR", "SEC-SQLI"} & rule_ids(ok, "pkg.sql")


def test_vb_resume_next_is_swallowed_error():
    vb = "Private Sub X()\n    On Error Resume Next\n    Call Y\nEnd Sub\n"
    assert "SEC-ERR" in rule_ids(vb, "form.bas", "Visual Basic 6")
    assert "SEC-ERR" not in rule_ids("Private Sub X()\n    On Error GoTo H\nH:\n    MsgBox 1\nEnd Sub\n", "form.bas")


@pytest.mark.parametrize("conn, hit", [
    ('var c = "Data Source=srv;Initial Catalog=db;User ID=u;Password=p";', True),
    ('var c = "Server=srv;Database=db;Integrated Security=true";', True),
    ('var c = "Data Source=srv;Initial Catalog=db;Encrypt=True;Integrated Security=true";', False),
    ('var url = "https://example.org/api";', False),
])
def test_unencrypted_connection_string(conn, hit):
    assert ("SEC-TLS" in rule_ids(f"class A {{ {conn} }}", "A.cs")) is hit


MVC = """using System.Web.Mvc;
public class PayController : Controller
{
    [HttpPost]
    public ActionResult Approve(string id)
    {
        return null;
    }
    [HttpGet]
    public ActionResult Show(string id) { return null; }
}
"""


def test_state_changing_post_without_authorize_or_antiforgery():
    r = rules(MVC, "PayController.cs")
    assert ("SEC-AUTHZ", "high") in r and ("SEC-CSRF", "medium") in r
    assert sum(1 for x, _ in r if x == "SEC-AUTHZ") == 1          # the GET action is not flagged


def test_authorize_and_antiforgery_clear_the_findings():
    ok = MVC.replace("public class PayController", "[Authorize]\npublic class PayController").replace(
        "[HttpPost]", "[HttpPost]\n    [ValidateAntiForgeryToken]")
    assert not {"SEC-AUTHZ", "SEC-CSRF"} & rule_ids(ok, "PayController.cs")
    anon = MVC.replace("[HttpPost]", "[HttpPost]\n    [AllowAnonymous]")
    assert "SEC-AUTHZ" not in rule_ids(anon, "PayController.cs")


def test_non_controller_class_is_not_checked_for_authorization():
    assert not {"SEC-AUTHZ", "SEC-CSRF"} & rule_ids(MVC.replace(": Controller", ""), "Pay.cs")


RPG = """     C                EVAL     CMD = 'SBMJOB CMD(CALL RPT) JOB(' + %TRIM(PERIOD) + ')'
     C                CALL     'QCMDEXC'
"""


def test_rpg_command_built_on_one_line_run_on_another():
    assert "SEC-CMD" in rule_ids(RPG, "POST.rpg", "RPG")
    assert "SEC-CMD" not in rule_ids(RPG.replace("CALL     'QCMDEXC'", "CALL     'OTHER'"), "POST.rpg", "RPG")


# ── scorecard and posture ───────────────────────────────────────────────────────────────────────────────────────

def comp(name, score, lines=100, **dims):
    base = {d: {"score": dims.get(d, score), "factors": []} for d in
            ("health", "tech_debt", "security", "supportability", "complexity", "coupling", "ux")}
    return {"name": name, "lines": lines, "type": "code", "scores": base}


def am(names, platforms=("Python runtime",), writes=False):
    return {"components": [{"name": n, "layer": "Application", "role": "Program", "writes": writes,
                            "platform": platforms[0], "language": "Python", "routines": []} for n in names],
            "platforms": list(platforms), "stores": {}}


FACTS = {"tests": 1, "skills": [], "platforms": 1, "silent_errors": [], "file_only": False, "apis": 1, "files": 0,
         "confidence": "high", "max_copies": 0}


def test_dimension_rates_on_weakest_material_component():
    comps = [comp("bad", 40)] + [comp(f"ok{i}", 100) for i in range(5)]
    sc = RT.scorecard(comps, am([c["name"] for c in comps]), 2, "", FACTS)
    assert sc["Technology currency"][0] == 4                    # 40 -> 4 Poor, not the ~90 average
    assert "bad" in sc["Technology currency"][1] and "average" in sc["Technology currency"][1]


def test_small_components_are_not_material():
    comps = [comp("tiny", 10, lines=3), comp("main", 95)]
    sc = RT.scorecard(comps, am(["tiny", "main"]), 1, "", FACTS)
    assert sc["Code quality"][0] == 1


def test_unrated_dimensions_are_insufficient_evidence_and_excluded():
    sc = RT.scorecard([comp("a", 95)], am(["a"]), 1, "", FACTS)
    for k in ("Performance and scalability", "Documentation and knowledge"):
        assert sc[k][0] is None and sc[k][1].startswith("Insufficient evidence")
    assert sc["overall"][2] == pytest.approx(1.0)      # coverage counts only what source code can show


def test_overall_is_capped_at_fair_when_coverage_is_low():
    sc = RT.scorecard([comp("a", 99)], am(["a"]), None, "", FACTS)      # security posture could not be rated
    assert sc["overall"][0] == 3 and "Capped at 3" in sc["overall"][3]


def test_cap_never_improves_a_worse_rating():
    sc = RT.scorecard([comp("a", 30)], am(["a"]), 5, "", {**FACTS, "platforms": 6})
    assert sc["overall"][0] >= 4 and sc["overall"][3] == ""


def test_missing_tests_and_silent_errors_move_ratings():
    base = RT.scorecard([comp("a", 95)], am(["a"]), 1, "", FACTS)
    worse = RT.scorecard([comp("a", 95)], am(["a"]), 1, "", {**FACTS, "tests": 0, "silent_errors": ["a"]})
    assert worse["Code quality"][0] == base["Code quality"][0] + 1
    assert worse["Stability and reliability"][0] == base["Stability and reliability"][0] + 1


@pytest.mark.parametrize("platforms, rating", [(1, 1), (2, 2), (3, 3), (5, 4), (6, 5)])
def test_business_fit_reflects_platform_count(platforms, rating):
    sc = RT.scorecard([comp("a", 100)], am(["a"]), 1, "", {**FACTS, "platforms": platforms})
    assert sc["Business fit and adaptability"][0] == rating


def test_data_fragmentation_is_in_the_scorecard():
    sc = RT.scorecard([comp("a", 100)], am(["a"]), 1, "", {**FACTS, "max_copies": 5, "frag_entity": "Payment"})
    assert sc["Business fit and adaptability"][0] >= 4 and "payment data is held in 5 places" in sc["Business fit and adaptability"][1].lower()


def control_rows(ratings):
    return [{"area": f"C{i}", "rating": r} for i, r in enumerate(ratings)]


@pytest.mark.parametrize("ratings, posture", [([2, 2, 5], 4), ([4, 4, 4], 4), ([1, 1, 1], 1), ([2, 3], 3),
                                              ([None, None], None)])
def test_posture_is_never_more_than_one_level_better_than_the_worst_control(ratings, posture):
    assert RT.posture(control_rows(ratings))[0] == posture


def test_controls_the_code_cannot_show_are_not_assessed():
    rows = RT.controls([], [], lambda _: set(), ["Visual Basic 6.0"], financial=True)
    by = {r["area"]: r for r in rows}
    for area in ("Patch management", "Third-party", "Backup", "Encryption in transit", "Authentication"):
        assert by[area]["rating"] is None and by[area]["why"].startswith("Not assessed")
    assert "Visual Basic 6.0" in by["Patch management"]["seen"]


def finding(rule, sev, file="A.cs", snippet=""):
    return {"rule": rule, "severity": sev, "title": f"x: {file}:1", "detail": "d",
            "evidence": [{"file": file, "snippet": snippet}], "category": "security"}


def test_findings_rate_their_control_and_shared_accounts_rate_privileged():
    rows = RT.controls([finding("SEC-TLS", "medium"), finding("SEC-CRED", "high", snippet="User ID=web;Password=****")],
                       [], lambda _: set(), [])
    by = {r["area"]: r for r in rows}
    assert by["Encryption in transit"]["rating"] == 3 and by["Secrets management"]["rating"] == 4
    assert by["Privileged"]["rating"] == 4 and "web" in by["Privileged"]["seen"]


def test_local_audit_log_is_poor_for_payments_fair_otherwise():
    log = [{"id": 1, "name": "C:\\APP\\AUDIT.LOG"}]
    fin = {r["area"]: r for r in RT.controls([], log, lambda _: {"calc.frm"}, [], financial=True)}
    other = {r["area"]: r for r in RT.controls([], log, lambda _: {"calc.frm"}, [], financial=False)}
    assert fin["Audit logging"]["rating"] == 4 and other["Audit logging"]["rating"] == 3


# ── CVSS ───────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rule, exposure, score", [
    ("SEC-SQLI", "Network (web or API)", 8.1),       # AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:N
    ("SEC-CMD", "Network", 8.8),                     # ... /A:H
    ("SEC-CSRF", "Internal", 6.5),                   # AV:N fixed, UI:R, I:H
    ("SEC-XSS", "Internet facing", 6.1),             # scope changed
])
def test_cvss_matches_published_calculator(rule, exposure, score):
    assert RT.cvss(rule, exposure)[0] == score


def test_cvss_attack_vector_follows_exposure_and_unknown_rules_are_unscored():
    assert RT.cvss("SEC-SQLI", "Internal desktop")[1].startswith("CVSS:3.1/AV:L")
    assert RT.cvss("SEC-ERR", "Network") == (None, "")


# ── data grouping ──────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, entity", [("AIDPAY", "Payment"), ("DBO.PAYMENTBATCH", "Payment"), ("DISTMST", "District"),
                                          ("DISTRICT_ADM", "District"), ("CUST_MASTER", "Customer"),
                                          ("ACCT-FILE", "Account"), ("ZZQ_WORK", None)])
def test_entity_grouping(name, entity):
    assert DA.entity_of(name, prefix="AID") == entity


def test_application_prefix_needs_three_names():
    assert DA._prefix(["AIDPAY", "AID_RUN", "AIDDSP"]) == "AID"
    assert DA._prefix(["AIDPAY", "ORDERS"]) is None


def test_sql_server_detection():
    assert DA.sql_server('new SqlConnection("x")') and DA.sql_server("Provider=SQLOLEDB;Data Source=s")
    assert DA.sql_server("SELECT * FROM dbo.Orders") and not DA.sql_server("SELECT * FROM orders")
    assert DA.catalog("Data Source=S1;Initial Catalog=Fin;") == "Fin" and DA.host("Server=S2;Database=x") == "S2"


def test_lineage_and_matrix_from_occurrences():
    occ = [{"store": "IN-FILE", "component": "calc.cbl", "access": "DR", "engine": "IBM mainframe (files)", "business": "Payment",
            "role": "file", "skip": False, "placeholder": False},
           {"store": "OUT-FILE", "component": "calc.cbl", "access": "DW", "engine": "IBM mainframe (files)", "business": "Payment",
            "role": "file", "skip": False, "placeholder": False}]
    lin = DA.lineage(occ)
    assert lin[0]["in"] == ["IN-FILE"] and lin[0]["out"] == ["OUT-FILE"] and lin[0]["out_to"]["OUT-FILE"] == []


# ── dispositions and options ───────────────────────────────────────────────────────────────────────────────────

def am_comp(name, platform, role="Program", layer="Application", language="", writes=False):
    return {"name": name, "platform": platform, "role": role, "layer": layer, "language": language, "writes": writes,
            "routines": [], "lines": 50}


def dispo(cs, techs=(), fin=False, legacy_ui=(), texts=None):
    return {c["name"]: c["code"] for c in OP.components({"components": cs}, list(techs), [], texts or {}, fin, set(legacy_ui))}


def test_vb6_rearchitecture_does_not_assume_terminal_replacement():
    d = dispo([am_comp("calc.frm", "Windows desktop (VB6)", language="Visual Basic 6"),
               am_comp("inq.screen", "IBM mainframe (z/OS)", role="3270 terminal screen", layer="Presentation")],
              techs=[{"file": "calc.frm", "status": "eol", "name": "Visual Basic 6.0"}])
    assert d == {"calc.frm": "rearchitect", "inq.screen": "retain"}


def test_plain_modern_web_page_is_retained_legacy_one_rebuilt():
    page = am_comp("index.html", "Web browser", role="Web page", layer="Presentation")
    assert dispo([page])["index.html"] == "retain"
    assert dispo([page], legacy_ui={"index.html"})["index.html"] == "rebuild"


def test_posting_consolidation_only_for_payment_apps():
    cs = [am_comp("post_pay.rpg", "IBM i (AS/400)", role="Batch program", writes=True),
          am_comp("post_pay.sql", "Oracle Database", role="Database procedures", layer="Data", writes=True)]
    assert set(dispo(cs, fin=True).values()) == {"consolidate"}
    assert "consolidate" not in dispo(cs, fin=False).values()


def test_program_recommendation_follows_components():
    many = [{"code": "rearchitect", "why": "w", "name": "a"}, {"code": "replace", "why": "w", "name": "b"},
            {"code": "retain", "why": "w", "name": "c"}]
    assert OP.program(many, 6)["code"] == "rearchitect"
    assert OP.program([{"code": "retain", "why": "w", "name": "c"}], 1)["code"] == "retain"


def test_refactor_scores_lower_risk_reduction_than_rearchitect_when_vb6_remains():
    opts = {n: sc for n, sc, _ in OP.scores({"no_path": ["Visual Basic 6.0"], "platforms": 6, "program_code": "rearchitect",
                                              "posting": 3})}
    assert opts["Refactor (keep all platforms)"][0] < opts["Re-architect (phased)"][0]


def test_estimate_includes_harness_and_parallel_runs_only_when_relevant():
    cds = [{"name": "a", "code": "rearchitect", "label": "Re-architect", "skill": "VB6 to .NET rewrite", "lines": 50,
            "findings": 0}]
    fin = OP.estimate(cds, {"fin": True, "copies": 2})
    work = " ".join(w for g in fin["lines"] for w in g["work"])
    assert "characterization" in work and "parallel runs" in work and "migration" in work
    plain = OP.estimate([{**cds[0], "code": "retain", "label": "Retain"}], {"fin": False, "copies": 0})
    assert not any(g["skill"] == "Test and QA" for g in plain["lines"])
    assert fin["low"] > plain["low"]


def test_sequence_has_no_payment_words_for_non_financial_apps():
    text = " ".join(t for _, t in OP.sequence({"fin": False, "fixes": [], "copies": 0, "changing": False}))
    assert "payment" not in text.lower() and "posting" not in text.lower()


# ── anonymization ──────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def red():
    return Redactor({"client": "Example Agency", "redact_terms": "Acme State Department of Finance, ASDF"},
                    ["INQUIRY_Acme_State_Department_of_Finance.screen"])


@pytest.mark.parametrize("text, out", [
    ("INQUIRY_Acme_State_Department_of_Finance.screen", "INQUIRY.screen"),
    ("reads ASDF.ORDERS", "reads CLIENT.ORDERS"),
    ("host ASDFSQL01", "host CLIENTSQL01"),
    ("Acme State Department of Finance portal", "CLIENT portal"),
    ("QCMDEXC and XASDF stay", "QCMDEXC and XASDF stay"),
])
def test_redaction(red, text, out):
    assert red(text) == out


def test_redaction_reaches_diagram_structures(red):
    scene = {"nodes": [{"title": "Owner of ASDF.ORDERS", "sub": ["ASDF"]}]}
    assert red.map(scene) == {"nodes": [{"title": "Owner of CLIENT.ORDERS", "sub": ["CLIENT"]}]}


def test_no_terms_and_matching_client_means_no_redaction():
    r = Redactor({"client": "Acme State Department of Finance"}, ["X_Acme_State_Department_of_Finance.screen"])
    assert not r.active and r("X_Acme_State_Department_of_Finance.screen") == "X_Acme_State_Department_of_Finance.screen"


# ── missing components ─────────────────────────────────────────────────────────────────────────────────────────

def test_routines_defined_in_provided_files_are_not_missing():
    from core.report.template_docx import _missing
    cov = {"missing": [{"category": "missing_code", "kind": "paragraph", "name": "CALCAID"},
                       {"category": "missing_code", "kind": "program", "name": "AIDRPT"},
                       {"category": "missing_code", "kind": "program", "name": "AIDRPT"},
                       {"category": "external", "kind": "table", "name": "T1"}]}
    arts = [{"transcription": "     C    CALCAID     BEGSR\n     C                ENDSR\n"}]
    assert [m["name"] for m in _missing(cov, arts)] == ["AIDRPT"]
