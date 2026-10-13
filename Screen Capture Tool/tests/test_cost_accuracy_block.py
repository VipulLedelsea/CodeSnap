"""The report accuracy and cost block: models for structure and fix, the batch tool_choice retry, the verdict, the
summary's severity scale and capture artifacts staying out of findings."""
import types

from core import analysis, deepdive, exec_summary
from core.assess.decide import disposition
from core.batching import BatchBadRequest
from core.model import extract


def test_structure_and_fix_use_the_reading_model_not_opus(monkeypatch):
    seen = []

    class Messages:
        def create(self, **kw):
            seen.append(kw["model"])
            block = types.SimpleNamespace(type="tool_use", name="record_structure", input={"entities": [], "relations": []})
            return types.SimpleNamespace(content=[block], usage=None, stop_reason="end_turn")

    extract.extract_structure(types.SimpleNamespace(messages=Messages()), "MOVE 1 TO X.", filename="A.cbl")
    assert seen and set(seen) == {analysis.READ_MODEL} and "opus" not in analysis.READ_MODEL + analysis.MODEL

    seen.clear()

    class Fixer:
        def create(self, **kw):
            seen.append(kw["model"])
            return types.SimpleNamespace(content=[types.SimpleNamespace(text="x = 1")], stop_reason="end_turn")

    analysis.fix_source(types.SimpleNamespace(messages=Fixer()), "x = ", "python", "SyntaxError")
    assert seen == [analysis.READ_MODEL]


def test_a_forced_tool_choice_rejected_in_batch_is_retried_with_auto(monkeypatch):
    calls = []

    class Messages:
        def create(self, **kw):
            calls.append(kw["tool_choice"]["type"])
            if kw["tool_choice"]["type"] == "tool":
                raise BatchBadRequest("batch request errored: tool_choice: type tool and any are not supported for this model")
            return "ok"

    monkeypatch.setattr(extract, "_NO_FORCED_TOOL", set())
    assert extract._create(types.SimpleNamespace(messages=Messages()), "some-model", "h", "b") == "ok"
    assert calls == ["tool", "auto"]
    calls.clear()
    extract._create(types.SimpleNamespace(messages=Messages()), "some-model", "h", "b")
    assert calls == ["auto"]      # remembered: the model is not asked for a forced tool again


def _scores(**kw):
    base = {"security": 90, "supportability": 90, "health": 90, "tech_debt": 90}
    base.update(kw)
    return {k: {"score": v} for k, v in base.items()}


def test_high_severity_review_findings_stop_a_retain_verdict():
    clean = disposition(_scores(), {"components": 3}, {})
    assert clean["code"] == "retain"
    flagged = disposition(_scores(), {"components": 3, "review_high": 2}, {})
    assert flagged["code"] == "refactor"
    assert any("2 high-severity defect" in r for r in flagged["reasons"])


def test_summary_severity_uses_the_risk_register_scale():
    assert [exec_summary._severity(x) for x in ("Critical", "critical", "High", "medium", "Low", "weird", None)] == \
        ["High", "High", "High", "Medium", "Low", "Medium", "Medium"]
    assert "Critical" not in exec_summary.SEVERITIES


def test_capture_artifacts_are_recognised_and_real_defects_are_not():
    assert deepdive.is_capture_artifact("Duplicate COBOL paragraph names create compile-time ambiguity")
    assert deepdive.is_capture_artifact("The paragraph 5050-CHECK-05 is defined twice")
    assert not deepdive.is_capture_artifact("Payment amount is not validated before posting")


def test_editor_status_bar_is_not_kept_as_a_source_line():
    text = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. DEMO.\nLn 150, Col 12   Spaces: 4   UTF-8   LF\n"
    assert analysis.clean_source(text).split("\n")[-1].strip() == "PROGRAM-ID. DEMO."
    code = "x = 1\nprint('Line 3, Column 4 is fine')\ny = 2"
    assert analysis.drop_status_bar(code) == code


def test_stop_interrupts_a_request_waiting_in_a_batch(monkeypatch, tmp_path):
    import pytest
    from core import batching, capture_gate

    class Client:
        messages = types.SimpleNamespace(batches=types.SimpleNamespace(create=lambda requests: types.SimpleNamespace(id="b1"),
                                                                       retrieve=lambda i: types.SimpleNamespace(processing_status="in_progress")))
    monkeypatch.setattr(batching, "journal_path", lambda: tmp_path / "journal.json")
    monkeypatch.setattr(capture_gate, "CANCEL", tmp_path / ".cancel")
    batch = batching.BatchMessages(Client(), window=0, poll=0.05)
    capture_gate.cancel_analysis(30)
    with pytest.raises(capture_gate.AnalysisCancelled):
        batch.create(model="m", max_tokens=1, messages=[{"role": "user", "content": "x"}])


def test_a_batch_that_vanished_is_resubmitted(monkeypatch, tmp_path):
    from core import batching

    class Gone(Exception):
        status_code = 404

    made, fetched = [], []

    def results(batch_id):
        fetched.append(batch_id)
        if len(fetched) == 1:
            raise Gone("Message Batch not found")
        ok = types.SimpleNamespace(type="succeeded", message="answer")
        return [types.SimpleNamespace(custom_id="r0", result=ok)]

    def create(requests):
        made.append(1)
        return types.SimpleNamespace(id=f"b{len(made)}")

    batches = types.SimpleNamespace(create=create, results=results,
                                    retrieve=lambda i: types.SimpleNamespace(processing_status="ended"))
    monkeypatch.setattr(batching, "journal_path", lambda: tmp_path / "journal.json")
    batch = batching.BatchMessages(types.SimpleNamespace(messages=types.SimpleNamespace(batches=batches)), window=0, poll=0.01)
    assert batch.create(model="m", max_tokens=1, messages=[{"role": "user", "content": "x"}]) == "answer"
    assert len(made) == 2


def test_preflight_names_a_model_that_does_not_answer():
    from core import preflight

    class Bad(Exception):
        status_code = 404

    class Messages:
        def create(self, **kw):
            if kw["model"] == "claude-nope":
                raise Bad("model: claude-nope")

    client = types.SimpleNamespace(messages=Messages())
    preflight._OK.clear()
    failed = preflight.check_models(client, ["claude-ok", "claude-nope", "claude-ok", None])
    assert [m for m, _ in failed] == ["claude-nope"]
    assert "claude-nope" in preflight.describe(failed) and "404" in preflight.describe(failed)


def test_preflight_uses_the_sdk_client_whose_internal_http_client_has_no_messages():
    """The SDK client keeps its HTTP client in `_client` (no `.messages`); only the app's wrappers keep a real client there."""
    from core import preflight

    asked = []

    class Messages:
        def create(self, **kw):
            asked.append(kw["model"])

    sdk = types.SimpleNamespace(messages=Messages(), _client=types.SimpleNamespace())       # like anthropic.Anthropic
    wrapper = types.SimpleNamespace(_client=types.SimpleNamespace(messages=Messages()))      # like the usage/batch wrappers
    preflight._OK.clear()
    assert preflight.check_models(sdk, ["claude-a"]) == []
    preflight._OK.clear()
    assert preflight.check_models(wrapper, ["claude-b"]) == []
    assert asked == ["claude-a", "claude-b"]


def test_number_check_flags_a_stated_total_that_differs_from_the_model():
    from core import report_numbers as N
    text = ("## 1.2 Key findings\nAll 12 provided files were reviewed with no concerns. 9 of 12 files use COBOL.\n"
            "## 5.1 Data\nThe source defines 14 tables.\nThree screens were supplied.")
    got = N.check(text, {"files": 11, "screens": 3, "tables": 14})
    assert [(i["topic"], i["first_section"]) for i in got] == [("Number of files", "1.2 Key findings")]
    assert "12 files" in got[0]["why"] and "11" in got[0]["why"]
    assert N.check(text, {"files": 12, "screens": 3, "tables": 14}) == []      # all agree, and "9 of 12" is not a total
    assert {i["topic"] for i in N.check(text, {"files": 12, "screens": 4, "tables": 15})} == {"Number of tables", "Number of screens"}


def test_wording_does_not_turn_capture_concerns_into_provide_concerns():
    from core.report import wording
    out = wording.clean("All 12 files were reviewed with no capture concerns.")
    assert "provide concerns" not in out and "reading concerns" in out


def test_completeness_names_a_lost_numbered_block_and_a_bms_without_its_header():
    from core.model import completeness
    procs = []
    for n in range(10, 22):
        if n == 15:
            continue
        procs += [f"R{n}: PROC;", f"  STATUS = {n};", f"END R{n};"]
    out = completeness.check("\n".join(procs), "x.pli", "PL/I")
    assert any("R15 is missing between 14 and 16" in r for r in out["reasons"])
    whole = [l for n in range(10, 22) for l in (f"R{n}: PROC;", f"  STATUS = {n};", f"END R{n};")]
    assert not any("missing between" in r for r in completeness.check("\n".join(whole), "x.pli", "PL/I")["reasons"])
    bms = "R00      DFHMDF POS=(3,12),LENGTH=12\n         DFHMDF POS=(5,2),LENGTH=6"
    assert any("DFHMSD" in r for r in completeness.check(bms, "m.bms")["reasons"])
    assert not any("DFHMSD" in r for r in completeness.check("MAP DFHMSD TYPE=MAP\n" + bms, "m.bms")["reasons"])


def test_a_run_of_cobol_lines_read_one_column_to_the_side_is_flagged_not_rewritten():
    from core.model import completeness
    body = [f"           MOVE {i} TO X." for i in range(400)]                      # indent 11, remainder 3
    shifted = [" " + l for l in body[20:50]]                                         # a screenshot read one column right
    text = "\n".join(body[:20] + shifted + body[50:])
    head = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. A.\n       PROCEDURE DIVISION.\n"
    out = completeness.check(head + text, "A.cbl", "COBOL")
    assert out["spacing"] and "lines 24-53" in out["spacing"][0] and not out["partial"]
    clean = completeness.check(head + "\n".join(body), "A.cbl", "COBOL")
    assert clean["spacing"] == []


def test_business_inputs_are_fields_and_close_only_the_open_items_they_cover():
    from core.report import settings
    from core.report.template_docx import Doc
    keys = [k for k, _ in settings.FIELDS]
    assert all(k in keys for k in settings.BUSINESS_KEYS) and len(set(keys)) == len(keys)
    doc = Doc()
    doc.inputs, doc.supplied = {"users_volumes": "40 clerks, 12,000 payments a month", "incident_history": "9 tickets"}, []
    assert doc.unknown("Number of users by group", "2.2") == "40 clerks, 12,000 payments a month"
    assert doc.open_items == []
    # the ticket item needs incident history AND named people: only one was entered, so it stays open
    assert doc.unknown("Ticket counts for 24 months and the named people (10.2, 10.7)", "10.7", "IT").startswith("<insert")
    assert len(doc.open_items) == 1
    assert doc.supplied == [("Users by group and business volumes", "40 clerks, 12,000 payments a month", "2.2")]


def test_long_ranked_registers_keep_their_top_rows_and_move_the_rest_to_an_appendix():
    from core.report import template_docx as TD
    doc = TD.Doc()
    table = doc.d.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text, table.rows[0].cells[1].text = "Risk ID", "Score"
    for i in range(1, 21):
        row = table.add_row()
        row.cells[0].text, row.cells[1].text = f"R-{i:02d}", str(30 - i)
    short = doc.d.add_table(rows=1, cols=1)
    short.rows[0].cells[0].text = "Debt ID"
    for i in range(1, 12):
        short.add_row().cells[0].text = f"TD-{i:02d}"
    TD._move_tails_to_appendices(doc, tables=[("Risk ID", 5, "Risk register, continued", "score"),
                                              ("Debt ID", 10, "Debt register, continued", "priority")])
    ours = [t for t in doc.d.tables if t.rows[0].cells[0].text.strip() in ("Risk ID", "Debt ID")
            and t.rows[1].cells[0].text.startswith(("R-", "TD-"))]
    assert [len(t.rows) - 1 for t in ours[-3:]] == [5, 11, 15]       # kept 5; debt is only 1 over so it stays whole; appendix has 15
    assert ours[-1].rows[1].cells[0].text == "R-06"
    texts = [p.text for p in doc.d.paragraphs]
    assert "Appendix I: Risk register, continued" in texts
    assert any(t.startswith("Showing the first 5 of 20 rows") and "Appendix I" in t for t in texts)
    assert not any("Debt register, continued" in t for t in texts)
