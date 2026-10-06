import shutil
from pathlib import Path

import pytest

from core import deepdive as DD, pipeline
from core.model import ProgramStore
from tests.test_deepdive import FakeClient, fact, RUN1


@pytest.fixture
def store(tmp_path):
    shutil.copytree(RUN1, tmp_path / "run1")
    with ProgramStore.open("run1", root=tmp_path) as st:
        yield st


def models(client):
    return [(c["model"], (c.get("tools") or [{}])[0].get("name")) for c in client.calls]


def test_draft_then_final_uses_each_model_and_grounds_the_second_pass(store):
    art = next(a for a in store.artifacts() if (a.get("transcription") or "").strip())
    text = art["transcription"].splitlines()
    first = next(i for i, l in enumerate(text, 1) if l.strip())
    quote = text[first - 1].strip()
    f = fact("Draft claim about the first line", [first, first], quote)
    client = FakeClient({"facts": [f], "capture_concerns": []}, review={"verdicts": []})
    res = pipeline.run_staged(store, client, report=False)
    seen = models(client)
    assert seen[0] == (pipeline.DRAFT_MODEL, "record_analysis")
    assert any(m == pipeline.FINAL_MODEL and t == "record_analysis" for m, t in seen)
    final_prompts = [c for c in client.calls if c["model"] == pipeline.FINAL_MODEL and (c.get("tools") or [{}])[0].get("name") == "record_analysis"]
    body = str(final_prompts[0]["messages"])
    assert "Draft claim about the first line" in body and "Claims:" in body
    assert not any(m == pipeline.DRAFT_MODEL and t == "record_review" for m, t in seen)
    assert res["draft_files"] >= 1 and res["final_files"] >= 1
    assert store.get_meta("deepdive")[str(art["id"])]["stage"] == "final"
    assert store.get_meta("analysis_stage") == "final"
    assert store.get_meta("deepdive_draft")[str(art["id"])]["stage"] == "draft"


def test_failed_final_pass_leaves_the_report_marked_draft(store, monkeypatch):
    client = FakeClient({"facts": []}, review={"verdicts": []})
    real = DD.analyse_file

    def boom(store_, client_, art, model=None, **kw):
        if model == pipeline.FINAL_MODEL:
            raise ValueError("final pass failed")
        return real(store_, client_, art, model=model, **kw)
    monkeypatch.setattr(DD, "analyse_file", boom)
    res = pipeline.run_staged(store, client, report=False)
    assert res["errors"] and not res["complete"]
    assert store.get_meta("analysis_stage") == "draft"


def test_staged_is_opt_in(monkeypatch):
    monkeypatch.delenv("CODESNAP_PIPELINE", raising=False)
    assert not pipeline.staged()
    monkeypatch.setenv("CODESNAP_PIPELINE", "staged")
    assert pipeline.staged()


def test_report_review_verdicts_filter_report(store, monkeypatch):
    from core import report_review as RR
    store.set_meta("report_review", {"verdicts": {
        RR.claim_key(RR.risk_text("Fake risk", [])): {"verdict": "unsupported"},
        RR.claim_key("Real debt"): {"verdict": "partly", "correction": "x"}}})
    v = RR.verdicts(store)
    assert v[RR.claim_key("Fake risk")]["verdict"] == "unsupported"
    assert "1 not shown" in RR.summary_line(store)


def test_unfinished_run_is_found_for_resume(store, tmp_path):
    from core.model.workspace import programs_root
    pipeline._job(store, "running")
    assert pipeline.interrupted(tmp_path) == ["run1"]
    pipeline._job(store, "done")
    assert pipeline.interrupted(tmp_path) == []


def test_models_without_thinking_are_called_once_without_it():
    seen = []

    class C:
        class messages:
            @staticmethod
            def create(**kw):
                seen.append("thinking" in kw)
                return object()
    DD._call(C, "claude-sonnet-5", "s", {"name": "t"}, "x")
    assert seen == [False]
