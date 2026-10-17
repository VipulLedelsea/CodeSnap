"""The executive summary as its own Word file: built from the current saved summary, and only from that."""
import io

import pytest

docx = pytest.importorskip("docx")

from core import exec_summary as ES
from core.model import ProgramStore
from core.report import summary_doc

SUMMARY = {
    "verdict": "Remediate", "provisional": True, "needed_to_finalize": ["Annual hosting cost.", "Number of users."],
    "what_it_does": "It posts municipal payments overnight [A.cbl:F1].",
    "reasons": ["The district rules are copied thirty times [A.cbl:F1].", "Reversal flags are lost [B.cbl:F2].", "The platform still runs."],
    "risks": [{"text": "An override forces ACCEPT with no audit trail [A.cbl:F1].", "severity": "Medium", "facts": ["A.cbl:F1"]},
              {"text": "Batch errors are swallowed [B.cbl:F2].", "severity": "High", "facts": ["B.cbl:F2"]}],
    "lifecycle": "Vendor support dates are not confirmed.", "lifecycle_verified": False,
    "decision": "Approve the remediation plan now.", "confidence": "medium", "confidence_and_coverage": "All files read; five have reading concerns.",
    "ran_at": "2026-10-14T07:27:22",
}
INDEX = {"A.cbl:F1": {"lines": [10, 20], "statement": "Override forces ACCEPT.", "severity": "high", "category": "defect"},
         "B.cbl:F2": {"lines": [5, 5], "statement": "Errors are swallowed.", "severity": "medium", "category": "defect"}}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "programs"))
    with ProgramStore.create("Summary fixture") as st:
        st.add_artifact("A.cbl", transcription="       STOP RUN.\n")
        monkeypatch.setattr(ES, "current", lambda store_: SUMMARY)
        monkeypatch.setattr(ES, "finding_index", lambda store_: INDEX)
        yield st


def _read(store):
    d = docx.Document(io.BytesIO(summary_doc.docx_bytes(store)))
    return "\n".join(p.text for p in d.paragraphs), [[c.text for c in r.cells] for t in d.tables for r in t.rows]


def test_the_file_holds_the_whole_summary_in_plain_text(store):
    body, rows = _read(store)
    assert "Executive summary" in body and "Remediate (provisional)" in body
    assert "Annual hosting cost" in body and "Number of users" in body                 # what is needed to finalize
    assert "It posts municipal payments overnight" in body and "Approve the remediation plan now." in body
    assert "Not verified. Vendor support dates are not confirmed." in body and "Confidence medium." in body
    assert "[A.cbl:F1]" not in body + str(rows)                                       # finding tags become file and line references
    assert "line 5" in str(rows) and "lines 10-20" in str(rows)                       # one line reads "line 5", not "lines 5-5"


def test_risks_are_listed_most_serious_first_with_where_they_were_found(store):
    _, rows = _read(store)
    risks = [r for r in rows if r[0] in ("High", "Medium")]
    assert [r[0] for r in risks] == ["High", "Medium"]
    assert "B.cbl line 5" in risks[0][2] and "A.cbl lines 10-20" in risks[1][2]


def test_a_draft_review_is_said_to_be_a_draft(store, monkeypatch):
    from core import deepdive
    monkeypatch.setattr(deepdive, "report_stage", lambda store_: "draft")
    assert "DRAFT: first-pass review" in _read(store)[0]
    monkeypatch.setattr(deepdive, "report_stage", lambda store_: "final")
    assert "DRAFT" not in _read(store)[0]


def test_no_current_summary_means_no_file(store, monkeypatch):
    monkeypatch.setattr(ES, "current", lambda store_: None)
    assert summary_doc.docx_bytes(store) is None


def test_the_download_says_why_when_the_summary_is_not_ready(store, monkeypatch):
    from fastapi.testclient import TestClient
    from webapp import server
    client = TestClient(server.app)
    ok = client.get(f"/api/programs/{store.info['slug']}/executive-summary.docx")
    assert ok.status_code == 200 and ok.headers["content-disposition"].endswith(f'{store.info["slug"]}_executive_summary.docx"')
    monkeypatch.setattr(ES, "current", lambda store_: None)
    late = client.get(f"/api/programs/{store.info['slug']}/executive-summary.docx")
    assert late.status_code == 409 and "not ready" in late.json()["error"]
    assert client.get(f"/api/programs/{store.info['slug']}/executive-summary.txt").status_code == 404
