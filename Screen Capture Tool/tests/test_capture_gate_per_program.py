import pytest

from core import capture_gate


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(capture_gate, "FLAG", tmp_path / ".capturing")
    monkeypatch.setattr(capture_gate, "CANCEL", tmp_path / ".cancel_analysis")
    monkeypatch.delenv("CODESNAP_PROGRAM", raising=False)
    yield
    capture_gate.end()


def test_capturing_one_program_does_not_hold_back_another():
    capture_gate.begin("alpha")
    assert capture_gate.capturing("alpha")
    assert not capture_gate.capturing("beta") and not capture_gate.capturing()
    assert capture_gate.wait(program="beta") is False      # beta's analysis is not held
    capture_gate.end()
    assert not capture_gate.capturing("alpha")


def test_stop_analysis_cancels_only_that_program():
    capture_gate.cancel_analysis(30, "alpha")
    with pytest.raises(capture_gate.AnalysisCancelled):
        capture_gate.check("alpha")
    capture_gate.check("beta")
    capture_gate.check()
    capture_gate.clear_cancel("alpha")
    capture_gate.check("alpha")


def test_program_comes_from_environment_and_thread_binding(monkeypatch):
    monkeypatch.setenv("CODESNAP_PROGRAM", "alpha")
    capture_gate.cancel_analysis(30)                        # no argument: this process's program
    assert capture_gate.cancelled("alpha") and not capture_gate.cancelled("beta")
    monkeypatch.delenv("CODESNAP_PROGRAM")
    assert not capture_gate.cancelled()
    with capture_gate.bound("alpha"):
        assert capture_gate.cancelled()
    assert not capture_gate.cancelled()
