import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from PIL import Image  # noqa: E402

from core.model import ProgramStore, complete_capture, new_version_from  # noqa: E402

COBOL = (HERE / "samples" / "cobol" / "AIDCALC.cbl").read_text()


def _frames(tmp, n=2, seed=0):
    d = tmp / f"s{seed}"
    d.mkdir()
    out = []
    for i in range(n):
        p = d / f"{i + 1:03d}.png"
        Image.new("RGB", (40, 20), (seed * 40 % 255, i * 60, 90)).save(p)
        out.append(p)
    return out


def _report(code=COBOL, name="AIDCALC", ext="cbl"):
    return {"is_code": True, "code": code, "code_name": name, "extension": ext, "language": "COBOL", "errors": "None"}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "progs"))
    with ProgramStore.create("Cap test") as s:
        yield s


def test_capture_is_a_file_before_analysis(store, tmp_path):
    aid = store.add_pending_capture(_frames(tmp_path))
    art = store.artifact(aid)
    assert art["status"] == "captured" and art["name"].startswith("Capture ")
    assert len(store.artifact_evidence(aid)) == 2
    assert aid in store.pending_captures()


def test_every_capture_is_its_own_file_even_with_same_name(store, tmp_path):
    a = store.add_pending_capture(_frames(tmp_path, seed=1))
    b = store.add_pending_capture(_frames(tmp_path, seed=2))
    complete_capture(store, None, a, _report())
    complete_capture(store, None, b, _report())
    names = sorted(x["name"] for x in store.artifacts())
    assert names == ["AIDCALC (2).cbl", "AIDCALC.cbl"]
    assert all(x["version"] == 1 for x in store.artifacts())


def test_user_rename_before_analysis_is_kept(store, tmp_path):
    aid = store.add_pending_capture(_frames(tmp_path))
    store.rename_artifact(aid, "PAYROLL.cbl")
    complete_capture(store, None, aid, _report())
    assert store.artifact(aid)["name"] == "PAYROLL.cbl" and store.artifact(aid)["status"] == "structured"


def test_recapture_becomes_new_version_and_keeps_history(store, tmp_path):
    first = store.add_pending_capture(_frames(tmp_path, seed=1))
    complete_capture(store, None, first, _report())
    store.rename_artifact(first, "AIDCALC-prod.cbl")
    second = store.add_pending_capture(_frames(tmp_path, seed=2), recapture_of="AIDCALC-prod.cbl")
    new_id = complete_capture(store, None, second, _report(COBOL.replace("AIDCALC", "AIDCALX")))
    cur = store.current_artifact("AIDCALC-prod.cbl")
    assert cur["id"] == new_id and cur["version"] == 2 and "AIDCALX" in cur["transcription"]
    assert store.artifact(first)["status"] == "superseded"
    assert store.artifact(second) is None and len(store.artifacts()) == 1
    assert len(store.artifact_evidence(new_id)) == 2


def test_version_of_after_the_fact(store, tmp_path):
    a = store.add_pending_capture(_frames(tmp_path, seed=1))
    complete_capture(store, None, a, _report())
    b = store.add_pending_capture(_frames(tmp_path, seed=2))
    complete_capture(store, None, b, _report(name="Something"))
    new_id = new_version_from(store, None, b, "AIDCALC.cbl")
    assert store.artifact(new_id)["version"] == 2 and store.artifact(b) is None
    assert [x["name"] for x in store.artifacts()] == ["AIDCALC.cbl"]


def test_empty_analysis_marks_failed_but_keeps_capture(store, tmp_path):
    aid = store.add_pending_capture(_frames(tmp_path))
    complete_capture(store, None, aid, {"is_code": False, "code": ""})
    assert store.artifact(aid)["status"] == "failed"
    assert store.pending_captures()[aid]["error"]


def test_claims_stop_double_analysis(store, tmp_path, monkeypatch):
    aid = store.add_pending_capture(_frames(tmp_path))
    assert store.claim_pending(aid, "worker-1")
    assert not store.claim_pending(aid, "worker-2")
    assert not store.claim_pending(aid, "worker-2", stale_after=0)
    monkeypatch.setattr("core.model.store._owner_alive", lambda owner: False)
    assert store.claim_pending(aid, "worker-2", stale_after=0)


class _FakeCtx:
    pass


def test_worker_saves_and_resumes_after_being_stopped(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "progs"))
    monkeypatch.chdir(tmp_path)
    import hotkey_capture as hk
    with ProgramStore.create("Worker test") as s:
        slug = s.info["slug"]
    calls = []

    def fake_team(client, ctx, goal=None, verbose=True, audit=None, **kw):
        calls.append(len(ctx.images))
        ctx.last_report = _report(name=f"FILE{len(calls)}")
        return "done", None

    monkeypatch.setattr(hk, "run_team_fast", fake_team)
    app = hk.App(None)
    app.program, app.project_mode, app.team_mode = slug, True, True
    sessions = []
    for i in range(3):
        d = tmp_path / "captures" / f"session_{i}"
        d.mkdir(parents=True)
        for p in _frames(tmp_path, n=2, seed=10 + i):
            (d / p.name).write_bytes(p.read_bytes())
        sessions.append(app._register_capture(d))
    with ProgramStore.open(slug) as s:
        assert [s.artifact(a)["status"] for a in sessions] == ["captured"] * 3
    app2 = hk.App(None)   # a fresh worker, as after the app switched capture mode
    app2.program, app2.project_mode, app2.team_mode = slug, True, True
    assert app2.process_pending() == 0          # still claimed by the first worker
    with ProgramStore.open(slug) as s:
        for a in sessions:
            info = s.pending_captures()[a]
            info["claim"]["at"] = 0               # age alone does not establish that a worker exited
            s.update_pending(a, claim=info["claim"])
    monkeypatch.setattr("core.model.store._owner_alive", lambda owner: owner != app._owner)
    assert app2.process_pending() == 3
    with ProgramStore.open(slug) as s:
        arts = s.artifacts()
        assert sorted(a["name"] for a in arts) == ["FILE1.cbl", "FILE2.cbl", "FILE3.cbl"]
        assert all(a["status"] == "structured" for a in arts) and not s.pending_captures()
    assert app2.process_pending() == 0


def test_worker_recapture_target_is_one_shot(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "progs"))
    monkeypatch.chdir(tmp_path)
    import hotkey_capture as hk
    with ProgramStore.create("Recap test") as s:
        slug = s.info["slug"]
        first = s.add_pending_capture(_frames(tmp_path, seed=1))
        complete_capture(s, None, first, _report())
        s.set_meta("recapture_target", {"name": "AIDCALC.cbl", "artifact_id": first, "version": 1})
    monkeypatch.setattr(hk, "run_team_fast", lambda c, ctx, **k: (setattr(ctx, "last_report", _report(name="X")), ("", None))[1])
    app = hk.App(None)
    app.program, app.project_mode, app.team_mode = slug, True, True
    d = tmp_path / "captures" / "s_recap"
    d.mkdir(parents=True)
    for p in _frames(tmp_path, seed=5):
        (d / p.name).write_bytes(p.read_bytes())
    aid = app._register_capture(d)
    app._analyse_burst(d, artifact_id=aid)
    with ProgramStore.open(slug) as s:
        cur = s.current_artifact("AIDCALC.cbl")
        assert cur["version"] == 2 and len(s.artifacts()) == 1
        assert s.get_meta("recapture_target") is None
