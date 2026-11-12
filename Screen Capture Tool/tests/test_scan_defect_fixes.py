"""Regression tests for the defects found in the full-program scan: files lost on project rename, a model call sent
nothing for a one-line file, a rejected request that still took effect, secrets left readable in evidence, a CLR version
read as an end-of-life framework, wrong repeats / columns / counts, and undo that did not undo. All offline."""
import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core import control, crossrefs, jclreads, limits, outputs, report_numbers, status, verify
from core.extractors.sql import parse_sql
from core.model import corrections, folder_import, removal
from core.model.store import ProgramStore
from core.report.redact import Redactor
from core.security import eol
from core.security.rules import scan_text
from webapp import server


@pytest.fixture()
def dirs(tmp_path, monkeypatch):
    rep, pend = tmp_path / "reports", tmp_path / "reports" / "pending"
    pend.mkdir(parents=True)
    monkeypatch.setattr(server, "REPORTS", rep)
    monkeypatch.setattr(server, "PENDING", pend)
    return rep, pend


@pytest.fixture()
def client():
    return TestClient(server.app, raise_server_exceptions=False)


@pytest.fixture()
def store(tmp_path):
    return ProgramStore.create("scan-fixes", root=str(tmp_path))


# ── web server ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_project_analysis_keeps_the_code_files_it_renames(dirs, client, monkeypatch):
    rep, _ = dirs
    for n in ("Calc", "Util"):
        outputs.save_report_bundle({"code": f"print('{n}')\n", "extension": "py", "language": "Python"}, rep,
                                   f"Report_{n}", code_name=f"Code_{n}")
    monkeypatch.setattr(server, "analyze_project", lambda client, files: {
        "language": "Project", "project_name": "Demo", "overview": "o", "errors": "None", "tech_stack": "", "diagrams": "",
        "extension": "txt", "code": "m"})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-offline-test-000000000000")
    r = client.post("/api/project/analyze", json={"items": [{"report": "Report_Calc", "filename": "Code_Calc.py"},
                                                            {"report": "Report_Util", "filename": ""}]})
    assert r.status_code == 200, r.text
    for n in ("Calc", "Util"):
        bundle = json.loads((rep / f"Code_{n}.json").read_text())
        code = rep / bundle["code_file"]
        assert code.exists() and code.read_text().strip() == f"print('{n}')"      # was deleted as "the old copy"
        assert not (rep / f"Report_{n}.json").exists()                        # the old bundle itself is gone


def test_park_without_a_program_is_refused_before_the_flag_is_written(client, tmp_path, monkeypatch):
    class Proc:
        pid = 99999
        def poll(self):
            return None
    monkeypatch.setattr(server, "captures_dir", lambda: tmp_path, raising=False)
    import webapp.session as session
    monkeypatch.setattr(session, "captures_dir", lambda: tmp_path)
    monkeypatch.setattr(server._session, "_proc", Proc())
    monkeypatch.setattr(server._session, "program", None)
    r = client.post("/api/session/park")
    assert r.status_code == 400
    assert not control.read(tmp_path, 99999).get("park")


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf"])
def test_budget_rejects_values_that_are_not_finite(client, bad):
    assert client.post("/api/programs/no-such-program/budget", json={"budget_usd": bad}).status_code == 400


def test_a_saved_area_file_that_is_not_an_object_falls_back_to_defaults(tmp_path, monkeypatch):
    import webapp.session as session
    monkeypatch.setattr(session, "captures_dir", lambda: tmp_path)
    (tmp_path / ".last_area.json").write_text("[]")
    assert session.SessionManager().saved() is not None


# ── limits, outputs, status ─────────────────────────────────────────────────────────────────────────────────────

def test_fit_text_keeps_the_start_and_end_of_a_single_long_line():
    text = "var a=1;" * 30000
    out = limits.fit_text(text)
    assert out.startswith("var a=1;") and out.rstrip().endswith("var a=1;")
    assert limits.MAX_CHARS * 0.9 < len(out) <= limits.MAX_CHARS + 200
    long_first = limits.fit_text("x" * 200000 + "\nline2\nline3")
    assert long_first.startswith("xxxx") and long_first.endswith("line3")
    many = "\n".join(f"line {i}" for i in range(40000))
    assert "lines of 40000 left out" in limits.fit_text(many)                 # ordinary files still cut at line breaks


def test_a_json_code_file_is_not_overwritten_by_its_bundle(tmp_path):
    code = outputs.save_report_bundle({"code": '{"port": 8080}', "extension": "json", "language": "JSON"}, tmp_path, "report_1")
    bundle = json.loads((tmp_path / "report_1.json").read_text())
    assert code.read_text() == '{"port": 8080}' and code.name != "report_1.json"
    assert bundle["code_file"] == code.name and bundle["language"] == "JSON"


def test_one_half_written_status_line_does_not_hide_the_others(tmp_path, monkeypatch):
    f = tmp_path / "status.jsonl"
    f.write_text('{"message": "one"}\n{"message": "tw\n{"message": "three"}\n')
    monkeypatch.setattr(status, "status_file", lambda program=None: f)
    assert [e["message"] for e in status.recent()] == ["one", "three"]


# ── security scan ───────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,text,secret", [
    ("Upload.cs", 'var req = WebRequest.Create("ftp://batchuser:Sup3rS3cret@ftp.example.org/in/file.csv");', "Sup3rS3cret"),
    ("push.sh", "curl -T out.csv ftp://batchuser:Sup3rS3cret@ftp.example.org/in/", "Sup3rS3cret"),
    ("app.properties", "feed.url=http://svc:Sup3rS3cret@feeds.example.org/api", "Sup3rS3cret"),
    ("web.config", '<add name="Db" connectionString="Data Source=srv;Initial Catalog=db;User ID=sa;Password=My Pass 123;" />', "Pass 123"),
])
def test_passwords_are_masked_in_evidence_snippets(name, text, secret):
    hits = scan_text(text, name)
    assert hits
    for h in hits:
        assert secret not in h["snippet"] and "****" in h["snippet"], h["snippet"]


def test_a_bare_clr_v4_runtime_is_not_a_confirmed_end_of_life_framework():
    data = eol.load_data()
    for rt in ("v4.0", "v4.0.30319"):
        (tech,) = eol.technologies({"settings": {"supportedRuntime": [rt]}})
        assert tech["confidence"] == "unconfirmed" and tech["version"] is None and "CLR" in tech["label"]
        assert not (eol.assess(tech, data, date(2026, 11, 12))["status"] == "eol"
                    and eol.assess(tech, data, date(2026, 11, 12))["confidence"] == "confirmed")
    (sku,) = eol.technologies({"settings": {"supportedRuntime": [".NETFramework,Version=v4.8"]}})
    assert sku["version"] == "4.8" and sku["confidence"] == "confirmed"
    assert eol.technologies({"libraries": [""]}) == []                        # an empty entry used to raise IndexError


def test_the_same_attribute_read_in_two_files_is_not_a_repeated_secret(store):
    store.add_artifact("a.py", "code", "Python", "class A:\n    def f(self, user):\n        password = user.password\n        return password\n")
    store.add_artifact("b.py", "code", "Python", "def g(user):\n    password = user.password\n    return check(password)\n")
    assert crossrefs.repeated_secrets(store) == []
    store.add_artifact("a.env", "code", "Shell", "API_TOKEN=Zx81kQp77Lm2\n")
    store.add_artifact("b.env", "code", "Shell", "API_TOKEN=Zx81kQp77Lm2\n")
    assert len(crossrefs.repeated_secrets(store)) == 1                        # a real repeated literal is still found


# ── transcription checks ────────────────────────────────────────────────────────────────────────────────────────

def test_same_named_methods_of_two_classes_are_not_stitched_in_twice():
    code = ("class A:\n    def __init__(self):\n        self.a = 1\n\n    def run(self):\n        return self.a\n\n\n"
            "class B:\n    def __init__(self):\n        self.b = 2\n\n    def run(self):\n        return self.b\n")
    assert verify.repeated_definitions(code.split("\n")) == set()
    twice = "class A:\n    def run(self):\n        pass\n    def run(self):\n        pass\n"
    assert verify.repeated_definitions(twice.split("\n")) == {4}              # a real repeat in one class is still found
    assert verify.repeated_definitions(("def f():\n    pass\n" * 2).split("\n")) == {3}


def test_a_toml_error_is_reported_on_its_own_line():
    assert verify.syntax_error("a = 1\nb = 2\nc = [1,\nd = 3\n", "x.toml")[0] == 4


# ── SQL extractor ───────────────────────────────────────────────────────────────────────────────────────────────

def _columns(sql):
    return {e["name"]: e["attrs"] for e in parse_sql(sql)["entities"] if e["kind"] == "column"}


def test_columns_named_like_constraint_words_are_kept():
    cols = _columns("CREATE TABLE ledger (\n  id INT NOT NULL,\n  period CHAR(6) NOT NULL,\n  key VARCHAR(10),\n"
                    "  index INT,\n  PRIMARY KEY (id),\n  UNIQUE (period),\n  CONSTRAINT fk FOREIGN KEY (key) REFERENCES other (k),\n"
                    "  KEY idx_period (period),\n  CHECK (id > 0)\n);")
    assert set(cols) == {"ID", "PERIOD", "KEY", "INDEX"}
    assert cols["PERIOD"]["type"] == "CHAR(6)" and cols["ID"].get("primary_key", True)


def test_column_types_keep_their_length():
    cols = _columns("CREATE TABLE a (\n  receipt CHARACTER VARYING(20) NOT NULL,\n  acct VARCHAR (12),\n  amt DECIMAL (10,2),\n"
                    "  plain INT NOT NULL,\n  rate DOUBLE PRECISION\n);")
    assert cols["RECEIPT"]["type"] == "CHARACTER VARYING(20)" and cols["ACCT"]["type"] == "VARCHAR(12)"
    assert cols["AMT"]["type"] == "DECIMAL(10,2)" and cols["PLAIN"]["type"] == "INT" and cols["RATE"]["type"] == "DOUBLE PRECISION"


# ── report checks ───────────────────────────────────────────────────────────────────────────────────────────────

def test_stated_counts_are_not_read_from_the_tail_of_a_longer_number():
    assert report_numbers.check("Twenty-five files were reviewed.", {"files": 25}) == []
    assert report_numbers.check("In total 1,204 files were reviewed.", {"files": 1204}) == []
    assert report_numbers.check("In total 1,204 files were reviewed.", {"files": 1200})[0]["why"].startswith("The report says 1204")
    assert report_numbers.check("Twelve files were reviewed.", {"files": 9})[0]["why"].startswith("The report says 12")


def test_redaction_keeps_the_part_of_a_file_name_that_tells_files_apart():
    names = ["Texas_Department_of_Education_Payroll_Report.cbl", "Texas_Department_of_Education_Invoice.cbl"]
    r = Redactor({"client": "Northwind", "client_short": "NW"}, names)
    assert [r(n) for n in names] == ["Payroll_Report.cbl", "Invoice.cbl"]
    assert r("The Texas Department of Education requires payroll") == "The NW requires payroll"


def test_jcl_steps_that_run_different_procs_are_not_one_program_named_proc():
    assert jclreads._STEP.match("//STEP1    EXEC PROC=LOADA").group(2) == "LOADA"
    assert jclreads._STEP.match("//STEP1    EXEC PGM=AIDCALC").group(2) == "AIDCALC"


# ── program model ───────────────────────────────────────────────────────────────────────────────────────────────

def test_undoing_a_line_correction_keeps_later_changes_to_the_verification(store):
    a = store.add_artifact("a.cbl", "code", "COBOL", "\n".join(f"line {i}" for i in range(1, 11)))
    store.set_verification(a, {"lines": 10, "verified": 8, "reread": 0, "confirmed": 0, "unchecked": 0, "flagged": 2,
                               "flags": [{"line": 3, "reason": "x"}, {"line": 7, "reason": "y"}]})
    c1 = corrections.add(store, "artifact.replace_line", {"artifact": "a.cbl", "line": 3, "old_text": "line 3", "new_text": "line three"})
    corrections.add(store, "artifact.delete_line", {"artifact": "a.cbl", "line": 5, "old_text": "line 5"})
    corrections.undo(store, c1["id"])
    v = store.verification(a)
    assert v["lines"] == 9 == len(store.artifact(a)["transcription"].splitlines())
    assert [(f["line"], f["reason"]) for f in v["flags"]] == [(3, "x"), (6, "y")]


def test_undoing_the_only_line_correction_restores_the_verification_exactly(store):
    a = store.add_artifact("a.cbl", "code", "COBOL", "\n".join(f"line {i}" for i in range(1, 6)))
    before = {"lines": 5, "verified": 4, "reread": 0, "confirmed": 0, "unchecked": 0, "flagged": 1, "flags": [{"line": 3, "reason": "x"}]}
    store.set_verification(a, dict(before))
    c = corrections.add(store, "artifact.replace_line", {"artifact": "a.cbl", "line": 3, "old_text": "line 3", "new_text": "line three"})
    corrections.undo(store, c["id"])
    assert store.verification(a) == before and store.artifact(a)["transcription"].splitlines()[2] == "line 3"


def test_undo_reverts_a_finding_status_matched_by_its_stable_signature(store):
    sig = corrections.stable_sig("SEC-SQLI", "app.py", "db.execute(...)")
    store.add_finding("security", "high", "SQL built from input", rule="SEC-SQLI", refs={"sig": sig})
    store.add_finding("security", "medium", "Legacy titled")                 # no rule: signature is category|title
    for f in store.findings():
        c = corrections.add(store, "finding.status", {"sig": corrections.finding_sig(f), "status": "dismissed"})
        assert [x["status"] for x in store.findings() if x["id"] == f["id"]] == ["dismissed"]
        corrections.undo(store, c["id"])
        assert [x["status"] for x in store.findings() if x["id"] == f["id"]] == ["open"]


def test_undo_reverts_a_finding_severity(store):
    corrections.add(store, "finding.add", {"category": "security", "severity": "high", "title": "Admin page has no login"})
    (f,) = [x for x in store.findings() if x["origin"] == "user"]
    c = corrections.add(store, "finding.severity", {"sig": corrections.finding_sig(f), "severity": "low"})
    assert [x["severity"] for x in store.findings() if x["origin"] == "user"] == ["low"]
    corrections.undo(store, c["id"])
    assert [x["severity"] for x in store.findings() if x["origin"] == "user"] == ["high"]


def test_a_removed_folder_file_is_no_longer_treated_as_an_exact_read(store, tmp_path):
    d = tmp_path / "src"
    d.mkdir()
    (d / "PAY.cbl").write_text("       MOVE A TO B.\n       MOVE C TO D.\n")
    folder_import.add_folder_files(store, str(d))
    assert folder_import.is_exact(store, store.current_artifact("PAY.cbl"))
    removal.remove_file(store, store.current_artifact("PAY.cbl")["id"], force=True)
    n = store.add_artifact("PAY.cbl", "code", "COBOL", "       MOVE X TO Y.\n")      # a later screenshot capture, same name
    assert not folder_import.is_exact(store, store.artifact(n))
