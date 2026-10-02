import json
from types import SimpleNamespace

import pytest

from core.model import ProgramStore, dependency_mermaid, import_reports, ingest_artifact, ingest_capture
from core.model.extract import CHUNK_LINES, chunks, extract_structure, numbered
from core.model.ingest import artifact_name, validation_from_errors


class FakeClient:
    def __init__(self, responses=None, fail=False, stop_reason="tool_use"):
        self.responses = list(responses or [])
        self.fail = fail
        self.stop_reason = stop_reason
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("api down")
        data = self.responses.pop(0) if self.responses else {"entities": [], "relations": []}
        block = SimpleNamespace(type="tool_use", name="record_structure", input=data)
        return SimpleNamespace(content=[block], usage=SimpleNamespace(input_tokens=120, output_tokens=40),
                               stop_reason=self.stop_reason)


BILLING = {
    "entities": [
        {"kind": "function", "name": "calculate", "parent": "Billing", "line_start": 3, "line_end": 9,
         "attrs": {"params": ["amount"]}},
        {"kind": "class", "name": "Billing", "parent": None, "line_start": 1, "line_end": 12},
    ],
    "relations": [
        {"kind": "reads", "source": "Billing.calculate", "target": "PAYMENTS", "target_kind": "table", "line": 5},
        {"kind": "calls", "source": "calculate", "target": "taxlib.rate", "target_kind": "function", "line": 6},
        {"kind": "teleports", "source": "calculate", "target": "X", "target_kind": "bogus"},
    ],
}

MAIN = {
    "entities": [{"kind": "function", "name": "main", "parent": None, "line_start": 1, "line_end": 4}],
    "relations": [{"kind": "calls", "source": "main", "target": "Billing.calculate", "target_kind": "function"}],
}


@pytest.fixture
def store(tmp_path):
    s = ProgramStore.create("Aid", root=tmp_path / "programs")
    yield s
    s.close()


def shots(tmp_path, n, tag):
    out = []
    for i in range(n):
        p = tmp_path / f"{tag}_{i}.png"
        p.write_bytes(b"\x89PNG" + f"{tag}{i}".encode())
        out.append(p)
    return out


NAMES = "  # names the fake model reports: Billing calculate PAYMENTS taxlib.rate main X"   # extraction keeps only names in the code


def report(code, ext="py", language="Python", name="Code_Billing", errors="None"):
    return {"is_code": True, "code": code + NAMES, "extension": ext, "language": language, "errors": errors,
            "code_name": name, "out_name": name.replace("Code_", "Report_")}


def test_numbered_and_chunks():
    assert numbered(["a", "b"], 9) == " 9| a\n10| b"
    code = "\n".join(f"line {i}" for i in range(1, CHUNK_LINES * 2 + 1))
    parts = list(chunks(code))
    assert parts[0][0] == 1 and len(parts) == 3
    assert parts[1][0] == CHUNK_LINES - 19
    assert parts[-1][1][-1] == f"line {CHUNK_LINES * 2}"


def test_extract_forces_tool_and_merges_chunks():
    client = FakeClient([MAIN, BILLING])
    code = "\n".join("x" for _ in range(CHUNK_LINES + 50)) + NAMES
    out = extract_structure(client, code, filename="big.py", language="Python", model="m")
    assert len(client.calls) == 2
    assert client.calls[0]["tool_choice"] == {"type": "tool", "name": "record_structure"}
    assert "Part 2 of 2" in client.calls[1]["messages"][0]["content"]
    assert len(out["entities"]) == 3 and len(out["calls"]) == 2


def test_names_and_validation():
    assert artifact_name(report("x")) == "Billing.py"
    assert artifact_name({"out_name": "report_2026", "extension": ""}) == "report_2026"
    assert validation_from_errors("None") == (True, "")
    assert validation_from_errors("line 3: error") == (False, "line 3: error")


def test_ingest_capture_builds_model(store, tmp_path):
    client = FakeClient([BILLING])
    aid = ingest_capture(store, client, shots(tmp_path, 3, "b"), report("class Billing: ...\n" * 11 + "class Billing: ..."))
    art = store.artifact(aid)
    assert art["name"] == "Billing.py" and art["status"] == "structured" and art["validation_ok"] == 1
    assert len(store.artifact_evidence(aid)) == 3
    calc = store.entity_by_key("function:Billing.calculate")
    assert calc["parent_id"] == store.entity_by_key("class:Billing")["id"]
    assert calc["attrs"] == {"params": ["amount"]} and calc["line_start"] == 3
    assert {r["kind"] for r in store.relations()} == {"contains", "reads", "calls", "depends_on"}
    missing = {m["name"] for m in store.coverage()["missing"]}
    assert missing == {"PAYMENTS", "taxlib.rate", "X"}
    assert store.entity_by_key("file:Billing.py")["line_end"] == 12
    assert store.usage()["input_tokens"] == 120
    assert len(store.evidence_for("entity", calc["id"])) == 3


def test_cross_file_resolution(store, tmp_path):
    client = FakeClient([MAIN, BILLING])
    ingest_capture(store, client, shots(tmp_path, 1, "m"), report("def main(): ...", name="Code_Main"))
    assert "Billing.calculate" in {m["name"] for m in store.coverage()["missing"]}
    ingest_capture(store, client, shots(tmp_path, 1, "b"), report("class Billing: ..."))
    calc = store.entity_by_key("function:Billing.calculate")
    assert calc["origin"] == "extracted" and calc["name"] == "calculate"
    callers = {e["name"] for e in store.neighbors(calc["id"], direction="in", kind="calls")}
    assert callers == {"main"}
    assert "Billing.calculate" not in {m["name"] for m in store.coverage()["missing"]}


def test_reingest_is_idempotent(store, tmp_path):
    client = FakeClient([BILLING, BILLING])
    aid = ingest_capture(store, client, shots(tmp_path, 1, "b"), report("class Billing: ..."))
    before = (len(store.entities()), len(store.relations()))
    ingest_artifact(store, client, aid)
    assert (len(store.entities()), len(store.relations())) == before


def test_recapture_creates_new_version(store, tmp_path):
    client = FakeClient([BILLING, {"entities": [{"kind": "class", "name": "Billing"}], "relations": []}])
    v1 = ingest_capture(store, client, shots(tmp_path, 1, "a"), report("v1"))
    v2 = ingest_capture(store, client, shots(tmp_path, 1, "b"), report("v2"))
    assert store.artifact(v2)["version"] == 2 and store.artifact(v1)["status"] == "superseded"
    assert store.entity_by_key("function:Billing.calculate") is None
    assert [a["name"] for a in store.artifacts()] == ["Billing.py"]


def test_extraction_failure_keeps_file(store, tmp_path):
    aid = ingest_capture(store, FakeClient(fail=True), shots(tmp_path, 1, "f"), report("code", ext="zzz", language="Unknown"))
    assert store.artifact(aid)["status"] == "failed"
    assert store.runs()[-1]["ok"] == 0 and "api down" in store.runs()[-1]["error"]
    ingest_artifact(store, FakeClient([BILLING]), aid)
    assert store.artifact(aid)["status"] == "structured"


def test_truncated_output_flagged(store, tmp_path):
    ingest_capture(store, FakeClient([BILLING], stop_reason="max_tokens"), [], report("code"))
    assert store.usage()["failures"] == 1


def test_non_code_not_structured(store, tmp_path):
    client = FakeClient()
    aid = ingest_capture(store, client, shots(tmp_path, 1, "d"),
                         {"is_code": False, "code": "Meeting notes", "extension": "txt", "code_name": "Code_Notes"})
    assert store.artifact(aid)["artifact_type"] == "other" and client.calls == []


def test_no_client_stores_without_structure(store, tmp_path):
    aid = ingest_capture(store, None, shots(tmp_path, 1, "n"), report("code", errors="E1: bad"))
    art = store.artifact(aid)
    assert art["status"] == "validated" and art["validation_ok"] == 0 and art["validation_errors"] == "E1: bad"


def test_import_v1_reports(store, tmp_path):
    reports = tmp_path / "reports"
    (reports / "pending").mkdir(parents=True)
    (reports / "Report_Billing.json").write_text(json.dumps(
        {"language": "Python", "code": "class Billing: ...", "extension": "py", "code_file": "Code_Billing.py",
         "errors": "None"}))
    (reports / "pending" / "report_1.json").write_text(json.dumps(
        {"language": "C", "code": "int main(){}", "extension": "c", "code_file": "report_1.c", "errors": "None"}))
    (reports / "ProjectReport_X.json").write_text(json.dumps({"language": "Project", "code": ""}))
    (reports / "broken.json").write_text("{not json")
    imported = import_reports(store, [reports, reports / "pending"], client=FakeClient([BILLING, MAIN]))
    assert sorted(i["name"] for i in imported) == ["Billing.py", "report_1.c"]
    assert import_reports(store, [reports, reports / "pending"]) == []
    assert store.entity_by_key("class:Billing") is not None


def test_rename_artifact(store, tmp_path):
    aid = ingest_capture(store, FakeClient([BILLING]), [], report("x"))
    store.rename_artifact(aid, "billing_calc.py")
    assert store.artifact(aid)["name"] == "billing_calc.py"
    assert store.entity_by_key("file:billing_calc.py") is not None
    other = ingest_capture(store, FakeClient([MAIN]), [], report("y", name="Code_Main"))
    with pytest.raises(ValueError):
        store.rename_artifact(other, "billing_calc.py")


def test_dependency_mermaid(store, tmp_path):
    client = FakeClient([MAIN, BILLING])
    ingest_capture(store, client, [], report("m", name="Code_Main"))
    ingest_capture(store, client, [], report("b"))
    text = dependency_mermaid(store.graph())
    assert text.startswith("flowchart LR")
    assert "-->|calls|" in text and "-->|reads|" in text
    assert "class " in text and "missing" in text
    assert "contains" not in text


class NoForcedToolClient(FakeClient):
    def create(self, **kwargs):
        if kwargs.get("tool_choice", {}).get("type") == "tool":
            self.calls.append(kwargs)
            raise RuntimeError("tool_choice: type \"tool\" and \"any\" are not supported for this model.")
        return super().create(**kwargs)


def test_falls_back_to_auto_tool_choice_once_per_model():
    from core.model import extract
    extract._NO_FORCED_TOOL.discard("m-auto")
    client = NoForcedToolClient([BILLING, MAIN])
    out = extract_structure(client, "class Billing: ..." + NAMES, filename="b.py", model="m-auto")
    assert len(out["entities"]) == 2
    assert [c["tool_choice"]["type"] for c in client.calls] == ["tool", "auto"]
    extract_structure(client, "def main(): ...", filename="m.py", model="m-auto")
    assert [c["tool_choice"]["type"] for c in client.calls] == ["tool", "auto", "auto"]


class TextOnlyClient(FakeClient):
    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(BILLING))],
                               usage=SimpleNamespace(input_tokens=5, output_tokens=5), stop_reason="end_turn")


def test_json_text_reply_accepted_and_missing_call_raises():
    out = extract_structure(TextOnlyClient(), "x" + NAMES, filename="b.py", model="m-text")
    assert len(out["relations"]) == 3

    class Silent(FakeClient):
        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="sorry")], usage=None, stop_reason="end_turn")

    silent = Silent()
    with pytest.raises(ValueError):
        extract_structure(silent, "x", filename="b.py", model="m-silent")
    assert len(silent.calls) == 2


def test_empty_program_resolved_is_unknown(store):
    assert store.coverage()["resolved_ratio"] is None
