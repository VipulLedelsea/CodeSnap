import threading
import time

from core import slots, status
from webapp.session import SessionManager


def test_status_streams_are_per_program(tmp_path, monkeypatch):
    monkeypatch.setattr(status, "_DIR", tmp_path)
    status.publish("a1", program="alpha")
    status.publish("b1", program="beta")
    assert [e["msg"] for e in status.recent(program="alpha")] == ["a1"]
    assert [e["msg"] for e in status.recent(program="beta")] == ["b1"]
    status.clear("alpha")
    assert status.recent(program="alpha") == [] and status.recent(program="beta")


def test_status_follows_env_program(tmp_path, monkeypatch):
    monkeypatch.setattr(status, "_DIR", tmp_path)
    monkeypatch.setenv("CODESNAP_PROGRAM", "gamma")
    status.publish("hello")
    assert status.recent(program="gamma")[0]["msg"] == "hello"


def test_slots_cap_distinct_programs_but_share_within_one(monkeypatch):
    monkeypatch.setenv("CODESNAP_MAX_PARALLEL", "1")
    order = []
    with slots.slot("alpha"):
        with slots.slot("alpha"):          # same program reuses its slot, no deadlock
            order.append("alpha-nested")
        def other():
            with slots.slot("beta", poll=0.05):
                order.append("beta")
        t = threading.Thread(target=other)
        t.start()
        time.sleep(0.3)
        assert "beta" not in order          # queued behind alpha
    t.join(5)
    assert order == ["alpha-nested", "beta"]


def test_slots_unlimited(monkeypatch):
    monkeypatch.setenv("CODESNAP_MAX_PARALLEL", "0")
    with slots.slot("a"), slots.slot("b"):
        pass


def test_workers_are_per_program(monkeypatch):
    spawned = []

    class Proc:
        def __init__(self, argv, **kw):
            spawned.append((argv[-3:], kw["env"].get("CODESNAP_PROGRAM")))
        def poll(self): return None
        def terminate(self): pass

    monkeypatch.setattr("webapp.session.subprocess.Popen", Proc)
    m = SessionManager()
    assert m.process_pending("a") and m.process_pending("b")
    assert not m.process_pending("a")       # a's own worker is busy; b never blocked a
    assert m.active_programs() == ["a", "b"]
    assert [p for _, p in spawned] == ["a", "b"]
