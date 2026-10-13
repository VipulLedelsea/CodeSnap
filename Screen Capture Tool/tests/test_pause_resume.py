import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from core import control  # noqa: E402
from core.model import ProgramStore, complete_capture  # noqa: E402
from test_capture_files import _frames, _report  # noqa: E402


def _session(tmp_path, name, seed, n=2):
    d = tmp_path / "captures" / name
    d.mkdir(parents=True)
    for p in _frames(tmp_path, n=n, seed=seed):
        (d / p.name).write_bytes(p.read_bytes())
    return d


@pytest.fixture
def worker(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "progs"))
    monkeypatch.chdir(tmp_path)
    import hotkey_capture as hk
    with ProgramStore.create("Pause test") as s:
        slug = s.info["slug"]
    app = hk.App(None)
    app.program, app.project_mode, app.team_mode = slug, True, True
    return hk, app, slug


def test_control_flags_are_per_worker(tmp_path):
    control.write(tmp_path, 111, paused=True)
    assert control.read(tmp_path, 111)["paused"] is True
    assert control.read(tmp_path, 222) == {}            # a stale file from another worker is ignored
    control.reset(tmp_path, 111)
    assert not control.read(tmp_path, 111)["paused"]


def test_parked_capture_is_saved_but_not_analysed(worker, tmp_path):
    hk, app, slug = worker
    aid = app._register_capture(_session(tmp_path, "s1", 1), park=True)
    with ProgramStore.open(slug) as s:
        assert s.artifact(aid)["status"] == "captured" and s.pending_captures()[aid]["paused"]
        assert not s.pending_captures()[aid]["claim"]
        from core import deepdive
        assert deepdive.file_state(s, s.artifact(aid)) == "paused"
    assert app._pending_work() == []                      # the pending worker leaves it alone


def test_resume_extends_the_same_file_then_analyses_once(worker, tmp_path):
    hk, app, slug = worker
    first = app._register_capture(_session(tmp_path, "s1", 1), park=True)
    with ProgramStore.open(slug) as s:
        s.set_meta("recapture_target", {"name": s.artifact(first)["name"], "artifact_id": first,
                                        "version": 1, "mode": "append", "paused": True})
    d = _session(tmp_path, "s2", 2, n=3)
    assert app._can_park()
    again = app._register_capture(d, park=True)           # paused a second time: still the same file
    assert again == first
    with ProgramStore.open(slug) as s:
        assert len(s.artifact_evidence(first)) == 5 and s.pending_captures()[first]["paused"]
        s.set_meta("recapture_target", {"name": s.artifact(first)["name"], "artifact_id": first,
                                        "version": 1, "mode": "append", "paused": True})
    d3 = _session(tmp_path, "s3", 3, n=2)
    done = app._register_capture(d3)                       # finished: becomes an ordinary waiting capture
    assert done == first
    assert len(list(d3.glob("0000_*.png"))) == 5          # earlier screenshots are analysed with the new ones
    with ProgramStore.open(slug) as s:
        info = s.pending_captures()[first]
        assert not info["paused"] and info["claim"] and len(s.artifact_evidence(first)) == 7
        assert len(s.artifacts()) == 1
        complete_capture(s, None, first, _report())
        assert s.artifact(first)["status"] == "structured" and s.artifact(first)["version"] == 1
        assert s.get_meta("recapture_target") is None


def test_cannot_park_while_replacing_an_analysed_file(worker):
    hk, app, slug = worker
    with ProgramStore.open(slug) as s:
        s.set_meta("recapture_target", {"name": "X.cbl", "artifact_id": 1, "version": 1, "mode": "append"})
    assert not app._can_park()
    app.program = None
    assert not app._can_park()


def test_resuming_a_removed_file_is_refused(worker, tmp_path):
    hk, app, slug = worker
    aid = app._register_capture(_session(tmp_path, "s1", 1), park=True)
    with ProgramStore.open(slug) as s:
        s.update_pending(aid, paused=False)
        with pytest.raises(ValueError):
            s.extend_paused(aid, [], park=False)


def test_burst_loop_holds_while_paused_and_parks(worker, tmp_path, monkeypatch):
    hk, app, slug = worker
    import itertools
    from core import capture
    shots = itertools.count()
    taken = []

    def grab():
        taken.append(1)
        return _frames(tmp_path, n=1, seed=100 + next(shots))[0].read_bytes()

    monkeypatch.setattr(capture, "capture_full_png", grab)
    monkeypatch.setattr(capture, "content_changed", lambda a, b: True)
    monkeypatch.setattr(hk, "BURST_INTERVAL", 0.01)
    monkeypatch.setattr(app, "_own_window_in_front", lambda: False)
    monkeypatch.setattr(app, "_refresh_capture_area", lambda: False)
    monkeypatch.setattr(app, "_safe_extract", lambda *a, **k: None)
    import os
    import threading
    import time
    d = _session(tmp_path, "live", 9, n=0)
    for f in d.glob("*.png"):
        f.unlink()
    app.running, app.idle_stop = True, 0
    control.reset(hk.CAPTURES_ROOT, os.getpid())
    t = threading.Thread(target=app._burst_loop, args=(d,))
    t.start()
    time.sleep(0.2)
    control.write(hk.CAPTURES_ROOT, os.getpid(), paused=True)
    time.sleep(0.1)
    held = len(taken)
    time.sleep(0.3)
    assert len(taken) <= held + 1 and app.paused          # nothing is captured while paused
    control.write(hk.CAPTURES_ROOT, os.getpid(), paused=False)
    time.sleep(0.2)
    assert len(taken) > held + 1 and not app.paused       # and capturing carries on afterwards
    control.write(hk.CAPTURES_ROOT, os.getpid(), park=True)
    t.join(5)
    assert not t.is_alive() and not app.running
    with ProgramStore.open(slug) as s:
        (aid, info), = s.pending_captures().items()
        assert info["paused"] and s.artifact(aid)["status"] == "captured"


def test_server_resume_and_finish(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "progs"))
    from webapp import server
    monkeypatch.setattr(server._session, "running", lambda: False)
    monkeypatch.setattr(server._session, "process_pending", lambda slug: True)
    api = TestClient(server.app)
    with ProgramStore.create("API pause") as s:
        slug = s.info["slug"]
        aid = s.add_pending_capture(_frames(tmp_path, seed=1))
        s.update_pending(aid, paused=True)
    prog = api.get(f"/api/programs/{slug}").json()
    row = next(a for a in prog["artifacts"] if a["id"] == aid)
    assert row["state"] == "paused" and row["pending"]["paused"] and prog["progress"]["paused"] == 1
    assert api.post(f"/api/programs/{slug}/pending/process").json()["waiting"] == 0   # nothing to analyse yet
    r = api.post(f"/api/programs/{slug}/recapture", json={"artifact_id": aid}).json()
    assert r["recapture_target"]["paused"] and r["recapture_target"]["mode"] == "append"
    assert api.post("/api/session/pause").status_code == 409                          # no capture running
    assert api.post(f"/api/programs/{slug}/artifacts/{aid}/finish").status_code == 200
    with ProgramStore.open(slug) as s:
        assert not s.pending_captures()[aid]["paused"] and s.get_meta("recapture_target") is None
    assert api.post(f"/api/programs/{slug}/artifacts/{aid}/finish").status_code == 400
