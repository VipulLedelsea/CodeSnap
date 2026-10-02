import threading
from types import SimpleNamespace

import pytest

from core import analysis
from core.usage import UsageTracker, cost, price_for, step_for, summarize


class Fake:
    def __init__(self, fail=False, stop="end_turn"):
        self.fail, self.stop = fail, stop
        self.messages = self

    def create(self, **kw):
        if self.fail:
            raise RuntimeError("boom")
        return SimpleNamespace(model=kw["model"], stop_reason=self.stop, content=[],
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=200,
                                                     cache_read_input_tokens=0, cache_creation_input_tokens=0))


def test_prices_and_cost():
    assert price_for("claude-opus-5-5") == (4.0, 20.0)
    assert price_for("claude-opus-5-5-20260901") == (4.0, 20.0)
    assert price_for("claude-haiku-4-5-20251001") == (1.0, 5.0)
    assert price_for("mystery") is None
    assert cost("claude-opus-5-5", 20000, 6000) == 0.2
    assert cost("claude-sonnet-4-6", 20000, 6000) == 0.15
    assert cost("mystery", 1, 1) is None and cost("claude-opus-5-5", None, 1) is None


def test_step_detection():
    import team
    from core.cobol.columns import COLUMN_REVIEW_SYSTEM
    from core.model.extract import STRUCTURE_SYSTEM
    assert step_for(analysis.EXTRACT_JSON_SYSTEM_PROMPT) == "transcribe"
    assert step_for(analysis.FINALIZE_SYSTEM_PROMPT) == "classify"
    assert step_for(team.ANALYST_SYSTEM) == "analyst"
    assert step_for(team.DIAGRAMMER_SYSTEM) == "diagram"
    assert step_for(COLUMN_REVIEW_SYSTEM) == "column_review"
    assert step_for(STRUCTURE_SYSTEM) == "structure"
    assert step_for([{"type": "text", "text": analysis.FIX_SYSTEM_PROMPT}]) == "fix"
    assert step_for(None) == "other" and step_for("hello") == "other"


def test_tracked_client_records_and_passes_through():
    tracker = UsageTracker()
    client = tracker.wrap(Fake())
    tracker.default_bucket = "s1"
    msg = client.messages.create(model="claude-opus-5-5", system=analysis.FINALIZE_SYSTEM_PROMPT, max_tokens=5,
                                 messages=[])
    assert msg.usage.input_tokens == 1000
    [rec] = tracker.take("s1")
    assert rec["step"] == "classify" and rec["cost"] == pytest.approx(0.008) and rec["ok"]
    assert tracker.take("s1") == []


def test_failures_and_truncation_recorded():
    tracker = UsageTracker()
    with pytest.raises(RuntimeError):
        tracker.wrap(Fake(fail=True)).messages.create(model="claude-opus-5-5", messages=[])
    tracker.wrap(Fake(stop="max_tokens")).messages.create(model="claude-opus-5-5", messages=[])
    failed, truncated = tracker.take(everything=True)
    assert not failed["ok"] and "boom" in failed["error"] and failed["cost"] is None
    assert not truncated["ok"] and "max_tokens" in truncated["error"]


def test_thread_buckets_separate_sessions():
    tracker = UsageTracker()
    client = tracker.wrap(Fake())
    tracker.default_bucket = "analysis"

    def background():
        tracker.set_thread_bucket("next-file")
        client.messages.create(model="claude-opus-5-5", system=analysis.EXTRACT_JSON_SYSTEM_PROMPT, messages=[])

    t = threading.Thread(target=background)
    t.start(); t.join()
    client.messages.create(model="claude-opus-5-5", system=analysis.FINALIZE_SYSTEM_PROMPT, messages=[])
    assert [r["step"] for r in tracker.take("analysis")] == ["classify"]
    assert [r["step"] for r in tracker.take("next-file")] == ["transcribe"]


def test_summarize():
    recs = [{"step": "transcribe", "input_tokens": 1000, "output_tokens": 100, "cost": 0.006},
            {"step": "transcribe", "input_tokens": 1000, "output_tokens": 100, "cost": 0.006},
            {"step": "diagram", "input_tokens": 500, "output_tokens": None, "cost": None}]
    s = summarize(recs)
    assert s["calls"] == 3 and s["input_tokens"] == 2500 and s["cost"] == 0.012
    assert s["by_step"]["transcribe"]["calls"] == 2 and s["by_step"]["diagram"]["cost"] == 0


def test_store_usage_by_step_and_artifact_cost(tmp_path):
    from core.model import ProgramStore
    with ProgramStore.create("P", root=tmp_path) as store:
        v1 = store.add_artifact("a.py")
        store.log_run("transcribe", artifact_id=v1, model="claude-opus-5-5", input_tokens=10, output_tokens=5, cost=0.1)
        v2 = store.add_artifact("a.py")
        store.log_run("analyst", artifact_id=v2, model="claude-opus-5-5", input_tokens=10, output_tokens=5, cost=0.05)
        store.log_run("transcribe", artifact_id=v2, model="claude-opus-5-5", input_tokens=10, output_tokens=5, cost=0.1)
        assert store.artifact_cost(v2) == 0.25
        steps = {r["step"]: r for r in store.usage_by_step()["steps"]}
        assert steps["transcribe"]["calls"] == 2 and steps["transcribe"]["cost"] == pytest.approx(0.2)
        assert store.usage()["cost"] == pytest.approx(0.25)


def test_app_logs_pipeline_usage_to_program(tmp_path, monkeypatch):
    import hotkey_capture as hk
    from core.model import ProgramStore
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path))
    monkeypatch.setenv("CODESNAP_DEEP", "0")      # the line-by-line analysis is tested in test_deepdive
    ProgramStore.create("Prog", root=tmp_path).close()
    app = hk.App(Fake())
    app.program = "prog"
    app.tracker.default_bucket = "b"
    app.client.messages.create(model="claude-opus-5-5", system=analysis.EXTRACT_JSON_SYSTEM_PROMPT, messages=[])
    app.client.messages.create(model="claude-opus-5-5", system=analysis.FINALIZE_SYSTEM_PROMPT, messages=[])
    records = app.tracker.take("b")
    ctx = SimpleNamespace(last_report={"is_code": False, "code": "notes", "extension": "txt", "code_name": "Code_N"})
    app._ingest_into_program([], ctx, records)
    with ProgramStore.open("prog", root=tmp_path) as store:
        assert {r["step"] for r in store.runs()} == {"transcribe", "classify"}
        assert store.usage()["cost"] == pytest.approx(0.016)
        assert store.artifact_cost(store.artifacts()[0]["id"]) == pytest.approx(0.016)


def test_text_steps_use_text_model_and_vision_steps_use_main_model(tmp_path):
    import team
    from core.cobol.columns import review_columns
    tracker = UsageTracker()
    client = tracker.wrap(Fake())
    analysis.synthesize_final(client, "print('x')")
    analysis.explain_error(client, "Python", "SyntaxError", "x")
    team._analyst_enrich(client, "print('x')", {"overview": "", "is_code": True, "language": "Python", "extension": "py"})
    team.agent_diagrammer(client, "print('x')", "Python")
    shot = tmp_path / "s.png"
    shot.write_bytes(b"\x89PNGx")
    analysis.extract_structured(client, shot)
    review_columns(client, [shot], "000100 MOVE A TO B.")
    models = {r["step"]: r["model"] for r in tracker.take(everything=True)}
    assert {models[s] for s in ("classify", "explain_error", "analyst", "diagram")} == {analysis.TEXT_MODEL}
    assert {models[s] for s in ("transcribe", "column_review")} == {analysis.MODEL}
    assert analysis.MODEL == "claude-opus-5-5" and analysis.TEXT_MODEL == "claude-sonnet-5"


def test_cache_prefix_preserves_prompt_and_leaves_images_uncached(monkeypatch):
    from core.usage import cached_request
    monkeypatch.delenv('CODESNAP_PROMPT_CACHE',raising=False)
    image={'type':'image','source':{'type':'base64','data':'original'}}
    kwargs={'model':'claude-opus-5-5','system':'Read exactly.','messages':[{'role':'user','content':[image]}]}
    result=cached_request(kwargs)
    assert result['system']==[{'type':'text','text':'Read exactly.','cache_control':{'type':'ephemeral'}}]
    assert result['messages'] is kwargs['messages'] and kwargs['system']=='Read exactly.'
    assert 'cache_control' not in image
    monkeypatch.setenv('CODESNAP_PROMPT_CACHE','0')
    assert cached_request(kwargs) is kwargs


def test_explicit_cache_configuration_is_preserved():
    from core.usage import cached_request
    kwargs={'model':'claude-opus-5-5','system':'Rules','cache_control':{'type':'ephemeral','ttl':'1h'}}
    assert cached_request(kwargs) is kwargs


def test_cached_costs_include_write_premium_and_read_discount():
    assert cost('claude-opus-5-5',1000,200,cache_write_tokens=2000,cache_read_tokens=3000)==pytest.approx(.0186)
    assert cost('claude-sonnet-5',1000,200,cache_write_1h_tokens=2000,cache_read_tokens=3000)==pytest.approx(.0126)
    tracker=UsageTracker()
    usage=SimpleNamespace(input_tokens=1000,output_tokens=200,cache_creation_input_tokens=2000,
        cache_read_input_tokens=3000,cache_creation=SimpleNamespace(ephemeral_1h_input_tokens=1000))
    rec=tracker.record('transcribe','claude-opus-5-5',usage,0)
    assert rec['input_tokens']==6000 and rec['cost']==pytest.approx(.0216)
    assert rec['cache_read_input_tokens']==3000 and rec['cache_creation_1h_input_tokens']==1000


def test_real_sdk_serializes_cache_marker_without_provider_call():
    import httpx,anthropic
    from core.usage import cached_request
    seen=[]
    def respond(request):
        import json
        seen.append(json.loads(request.content))
        return httpx.Response(200,json={'id':'msg_test','type':'message','role':'assistant','model':'claude-opus-5-5',
            'content':[{'type':'text','text':'OK'}],'stop_reason':'end_turn','stop_sequence':None,
            'usage':{'input_tokens':100,'output_tokens':1,'cache_creation_input_tokens':0,'cache_read_input_tokens':1000}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        with anthropic.Anthropic(api_key='offline-test',http_client=http) as provider:
            tracker=UsageTracker()
            # The offline runner forbids Messages.create globally. Exercise
            # SDK serialization only, with an in-memory HTTP transport.
            message = provider.post('/v1/messages',cast_to=anthropic.types.Message,body=cached_request({
                'model':'claude-opus-5-5','max_tokens':1,'system':'Verbatim instructions',
                'messages':[{'role':'user','content':'Read new source'}]}))
            tracker.record('transcribe',message.model,message.usage,0)
    assert seen[0]['system'][0]['cache_control']=={'type':'ephemeral'}
    assert seen[0]['messages']==[{'role':'user','content':'Read new source'}]
    assert tracker.total_cost==pytest.approx(.00062)
