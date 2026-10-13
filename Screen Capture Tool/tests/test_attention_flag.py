"""A file that needs a look is flagged as soon as it is read, with a notification, and a capture only warns about its own program."""
import threading
from types import SimpleNamespace

import hotkey_capture
from core import status


def _app():
    return type("A", (), {"_state_lock": threading.Lock()})()


def test_flag_publishes_and_notifies_once_per_file(monkeypatch):
    sent, published = [], []
    monkeypatch.setattr("core.notify.notify", lambda title, msg: sent.append(msg))
    monkeypatch.setattr(status, "publish", lambda msg, kind="info", stage=None, program=None: published.append((msg, kind)))
    app = _app()
    cls = hotkey_capture.App
    issues = [{"reason": "a gap between two screens"}, {"reason": "lines cut off"}, {"reason": "third"}]
    cls._flag_attention(app, "AIDPAY.cbl", issues)
    cls._flag_attention(app, "AIDPAY.cbl", issues)       # the same file again: shown again, but no second pop-up
    cls._flag_attention(app, "OTHER.cbl", issues)
    assert len(published) == 3 and all(k == "error" for _, k in published)
    assert "a gap between two screens; lines cut off" in published[0][0] and "third" not in published[0][0]
    assert len(sent) == 2 and "AIDPAY.cbl needs attention" in sent[0]
    assert "other files continues" in sent[0]


def test_starting_a_capture_only_warns_about_its_own_program(monkeypatch):
    from webapp import server
    monkeypatch.setattr(server, "_programs_being_analysed", lambda: ["other-program"])
    monkeypatch.setattr(server, "_program_exists", lambda slug: True)
    monkeypatch.setattr(server, "_session", SimpleNamespace(running=lambda: False, program=None,
                                                             start=lambda **kw: True))
    monkeypatch.setattr(server, "api_session_kind", lambda kind: None)
    monkeypatch.setattr("core.usage.program_budget", lambda store: None, raising=False)

    class Store:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def usage(self): return {"cost": 0}

    monkeypatch.setattr(server, "_open_program", lambda slug: Store())
    own = server.api_session_start(program="other-program")
    assert getattr(own, "status_code", 200) == 409                       # its own program is being analysed: ask first
    mine = server.api_session_start(program="my-program")
    assert isinstance(mine, dict) and mine["started"] is True            # another program's analysis is not held up
