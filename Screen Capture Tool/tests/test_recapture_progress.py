"""A recapture says whether it fixed the file, and the program shows plainly how many files are done and how many to go."""
import shutil
from pathlib import Path

import pytest

from core import deepdive as DD
from core.model import ProgramStore
from core.model.ingest import complete_capture

HERE = Path(__file__).resolve().parent
RUN1 = HERE / "fixtures" / "run1_program"
TRUTH = next((HERE / "real" / "2026-09-29-run2" / "aidpayrn_cobol").glob("truth.*")).read_text()
SHOT = next((HERE / "real" / "2026-09-29-run2" / "aidpayrn_cobol").glob("01.png"))


@pytest.fixture
def store(tmp_path):
    shutil.copytree(RUN1, tmp_path / "p")
    st = ProgramStore.open("p", root=tmp_path)
    yield st
    st.close()


def cur(store, name):
    return store.current_artifact(name)


def recapture(store, name, code):
    old = cur(store, name)
    aid = store.add_pending_capture([SHOT], recapture_of=name, keep_frames_of=old["id"])
    return complete_capture(store, None, aid, {"code": code, "language": "COBOL", "errors": "None", "validation_tool": "cobc"})


def outcome(store, name):
    a = cur(store, name)
    return DD.recapture_outcome(store, a, DD.capture_quality(store, a, DD.current_concerns(store, a)))


def test_a_recapture_that_fixes_the_file_says_so(store):
    assert DD.capture_quality(store, cur(store, "AIDPAYRN.cbl"))["status"] == "rescan"
    recapture(store, "AIDPAYRN.cbl", TRUTH)
    o = outcome(store, "AIDPAYRN.cbl")
    assert o["result"] == "fixed" and o["was"] == "rescan" and o["now"] != "rescan"
    assert any(i["kind"] == "cut" for i in o["fixed"]) and not o["remaining"]
    assert "AIDPAYRN.cbl" not in {r["name"] for r in DD.rescan_requests(store)}


def test_a_recapture_that_still_has_problems_says_what_is_left(store):
    lines = TRUTH.split("\n")
    lines[40] = lines[40][:30] + " [CUT OFF]"
    recapture(store, "AIDPAYRN.cbl", "\n".join(lines))
    o = outcome(store, "AIDPAYRN.cbl")
    assert o["result"] == "still" and o["remaining"][0]["kind"] == "cut" and o["remaining"][0]["lines"] == ["41"]


def test_old_review_concerns_do_not_outlive_the_text_they_were_about(store):
    a = cur(store, "AidPaymentController.cs")
    store.set_meta("deepdive", {str(a["id"]): {"hash": "old", "capture_concerns": [{"line": 3, "reason": "garbled"}]}})
    assert DD.current_concerns(store, a) is None
    assert DD.capture_quality(store, a, DD.current_concerns(store, a))["status"] != "rescan"


def test_file_states_and_the_program_progress(tmp_path, monkeypatch, store):
    pytest.importorskip("fastapi")
    from webapp import server
    arts = [server._artifact_summary(store, a) for a in store.artifacts()]
    p = server._progress(arts)
    assert p == {**p, "total": 9, "finished": 9, "to_go": 0, "needs_recapture": 1, "done": 8, "pct": 100}
    old = cur(store, "AIDPAYRN.cbl")
    store.add_pending_capture([SHOT], recapture_of="AIDPAYRN.cbl", keep_frames_of=old["id"])
    arts = [server._artifact_summary(store, a) for a in store.artifacts()]
    p = server._progress(arts)
    assert p["total"] == 9 and p["waiting"] == 1 and p["to_go"] == 1 and p["finished"] == 8
    DD._set_active(store, cur(store, "AIDINQ.cbl")["id"], True)
    assert DD.file_state(store, cur(store, "AIDINQ.cbl")) == "reviewing"
    DD._set_active(store, cur(store, "AIDINQ.cbl")["id"], False)
    assert DD.file_state(store, cur(store, "AIDINQ.cbl")) == "done"


@pytest.mark.parametrize('reverse', [False, True])
def test_failed_recapture_counts_as_failed_instead_of_old_done(reverse):
    from webapp.server import _progress
    arts = [{'name': 'schema.sql', 'state': 'done'},
            {'name': 'Capture 2', 'state': 'failed', 'pending': {'recapture_of': 'schema.sql'}}]
    p = _progress(arts[::-1] if reverse else arts)
    assert p['total'] == 1 and p['failed'] == 1 and p['done'] == 0
    arts[1]['state'] = 'waiting'
    p = _progress(arts[::-1] if reverse else arts)
    assert p['waiting'] == 1 and p['to_go'] == 1 and p['finished'] == 0


def test_the_deep_review_marks_a_file_as_being_reviewed_while_it_runs(store):
    seen = []

    class Boom:
        messages = None

    def fake(store_, client, art, **kw):
        seen.append(DD.file_state(store_, art))
        raise RuntimeError("stop")

    import core.deepdive as mod
    orig = mod.analyse_file
    mod.analyse_file = fake
    try:
        a = cur(store, "AIDINQ.cbl")
        DD.run(store, Boom(), artifact_ids=[a["id"]], force=True)
    finally:
        mod.analyse_file = orig
    assert seen == ["reviewing"] and DD.file_state(store, cur(store, "AIDINQ.cbl")) == "done"


def test_cross_file_observations_are_drawn_once_not_after_every_file(store):
    from tests_helpers_fake import counting_client
    client = counting_client()
    arts = store.artifacts()
    store.set_meta("deepdive", {str(a["id"]): {"name": a["name"], "hash": DD._hash(a["transcription"]),
                                               "prompt_version": DD.PROMPT_VERSION, "ran_at": f"t{a['id']}",
                                               "facts": [{"id": 1, "category": "calculation", "statement": "x",
                                                          "lines": [1, 1]}]} for a in arts})
    DD.run(store, client, program=False)
    assert client.program_calls == 0 and DD.program_stale(store)
    DD.run(store, client)
    assert client.program_calls == 1 and not DD.program_stale(store)
    DD.run(store, client)
    assert client.program_calls == 1


def test_files_are_reviewed_in_parallel_and_all_results_are_kept(store, monkeypatch):
    import threading
    import time as _t
    live, peak, lock = [0], [0], threading.Lock()

    def slow(store_, client, art, **kw):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        _t.sleep(0.2)
        with lock:
            live[0] -= 1
        return {"name": art["name"], "hash": DD._hash(art["transcription"]), "prompt_version": DD.PROMPT_VERSION,
                "ran_at": "t", "facts": []}

    monkeypatch.setattr(DD, "analyse_file", slow)
    monkeypatch.setenv("CODESNAP_DEEP_WORKERS", "3")
    res = DD.run(store, None, program=False)
    assert peak[0] == 3 and not res["errors"]
    assert not DD.pending(store) and len(store.get_meta("deepdive")) == res["analysed"] >= 6
