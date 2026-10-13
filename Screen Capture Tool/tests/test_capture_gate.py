import threading
import time

from core import capture_gate


def test_wait_returns_when_idle():
    capture_gate.end()
    assert capture_gate.wait() is False


def test_wait_blocks_until_capture_ends(tmp_path, monkeypatch):
    monkeypatch.setattr(capture_gate, "FLAG", tmp_path / ".capturing")
    capture_gate.begin()
    assert capture_gate.capturing()
    waited = []
    t = threading.Thread(target=lambda: waited.append(capture_gate.wait(poll=0.05)))
    t.start()
    time.sleep(0.3)
    assert t.is_alive()
    capture_gate.end()
    t.join(2)
    assert waited == [True] and not capture_gate.capturing()


def test_stale_flag_does_not_block(tmp_path, monkeypatch):
    flag = tmp_path / ".capturing"
    flag.write_text("1")
    old = time.time() - 60
    import os
    os.utime(flag, (old, old))
    monkeypatch.setattr(capture_gate, "FLAG", flag)
    assert capture_gate.wait() is False


def test_cancel_blocks_model_calls(tmp_path, monkeypatch):
    import pytest
    from core import usage
    monkeypatch.setattr(capture_gate, "FLAG", tmp_path / ".capturing")
    monkeypatch.setattr(capture_gate, "CANCEL", tmp_path / ".cancel")

    class Messages:
        calls = 0

        def create(self, **kwargs):
            Messages.calls += 1

    class Client:
        messages = Messages()

    tracked = usage.UsageTracker().wrap(Client())
    capture_gate.cancel_analysis(5)
    with pytest.raises(capture_gate.AnalysisCancelled):
        tracked.messages.create(model="m", max_tokens=1, messages=[])
    assert Messages.calls == 0
    capture_gate.clear_cancel()
    assert not capture_gate.cancelled()
