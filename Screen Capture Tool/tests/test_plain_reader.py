import contextlib
from types import SimpleNamespace

import pytest
from PIL import Image

from core import analysis, spacing


class FakeClient:
    def __init__(self, text="A\nB", stop="end_turn"):
        self.calls = []
        self.messages = SimpleNamespace(create=self.create)
        self.text, self.stop = text, stop

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason=self.stop, content=[SimpleNamespace(text=self.text)])


@pytest.fixture
def shot(tmp_path):
    path = tmp_path / "shot.png"
    Image.new("RGB", (40, 20), "white").save(path)
    return path


def calibrated(monkeypatch, origin=5.0):
    @contextlib.contextmanager
    def frame(path, calibration=None):
        yield path, origin, {}
    monkeypatch.setattr(spacing, "frame", frame)


def measured(monkeypatch, status):
    def fake(client, path, raw, *, calibration=None):
        return raw, {"status": status, "spacing": {"calibrated": True}}, 0
    monkeypatch.setattr(analysis, "measured_frame", fake)


def test_json_reader_when_selected(monkeypatch, shot):
    monkeypatch.setattr(analysis, "READER", "json")
    monkeypatch.setattr(analysis, "extract_plain", lambda *a, **k: pytest.fail("plain reader must stay off"))
    monkeypatch.setattr(analysis, "extract_json", lambda *a, **k: {"raw": "x", "verify": {}})
    assert analysis.extract_structured(None, shot)["raw"] == "x"
    assert "reader_fallback" not in analysis.extract_structured(None, shot)["verify"]


def test_plain_result_skips_json_reader(monkeypatch, shot):
    monkeypatch.setattr(analysis, "READER", "plain")
    monkeypatch.setattr(analysis, "extract_plain", lambda *a, **k: ({"raw": "p", "verify": {}}, None))
    monkeypatch.setattr(analysis, "extract_json", lambda *a, **k: pytest.fail("fallback must not run"))
    assert analysis.extract_structured(None, shot)["raw"] == "p"


@pytest.mark.parametrize("reason", ["uncalibrated", "truncated", "empty", "unverified"])
def test_flagged_frame_falls_back_to_json_reader(monkeypatch, shot, reason):
    monkeypatch.setattr(analysis, "READER", "plain")
    monkeypatch.setattr(analysis, "extract_plain", lambda *a, **k: (None, reason))
    monkeypatch.setattr(analysis, "extract_json", lambda *a, **k: {"raw": "j", "verify": {}})
    out = analysis.extract_structured(None, shot)
    # the plain read is tried on more than one model before the JSON reader, so the reason is listed per model
    assert out["raw"] == "j" and reason in out["verify"]["reader_fallback"]


def test_plain_error_falls_back_to_json_reader(monkeypatch, shot):
    monkeypatch.setattr(analysis, "READER", "plain")

    def boom(*a, **k):
        raise RuntimeError("api down")
    monkeypatch.setattr(analysis, "extract_plain", boom)
    monkeypatch.setattr(analysis, "extract_json", lambda *a, **k: {"raw": "j"})
    assert "error:RuntimeError" in analysis.extract_structured(None, shot)["verify"]["reader_fallback"]


def test_uncalibrated_frame_makes_no_model_call(monkeypatch, shot):
    calibrated(monkeypatch, origin=None)
    client = FakeClient()
    assert analysis.extract_plain(client, shot) == (None, "uncalibrated")
    assert client.calls == []


def test_truncated_and_empty_replies_are_flagged(monkeypatch, shot):
    calibrated(monkeypatch)
    assert analysis.extract_plain(FakeClient(stop="max_tokens"), shot) == (None, "truncated")
    assert analysis.extract_plain(FakeClient(text="```\n```"), shot) == (None, "empty")


def test_good_frame_returns_plain_result(monkeypatch, shot):
    calibrated(monkeypatch)
    measured(monkeypatch, ["verified", "verified"])
    client = FakeClient(text="```\n  A\n    B\n```")
    out, reason = analysis.extract_plain(client, shot)
    assert reason is None
    assert out["raw"] == "  A\n    B" and out["observed_raw"] == "  A\n    B"
    assert out["verify"]["numbers_seen"] is False and out["verify"]["reader"] == analysis.PLAIN_MODEL
    call = client.calls[0]
    assert call["model"] == analysis.PLAIN_MODEL and call["max_tokens"] == 8192
    assert call["system"] == analysis.EXTRACT_PLAIN_SYSTEM_PROMPT


def test_mostly_unverified_frame_is_flagged(monkeypatch, shot):
    calibrated(monkeypatch)
    measured(monkeypatch, ["verified", "mismatch"])
    assert analysis.extract_plain(FakeClient(), shot) == (None, "unverified")


def test_few_unverified_lines_are_accepted(monkeypatch, shot):
    calibrated(monkeypatch)
    monkeypatch.setattr(analysis, "PLAIN_MAX_BAD", 0.5)
    measured(monkeypatch, ["verified", "mismatch"])
    out, reason = analysis.extract_plain(FakeClient(), shot)
    assert reason is None and out is not None


def test_plain_prompt_reuses_json_prompt_clauses():
    for clause in (analysis._FIXED_COLUMN_CLAUSE, analysis._PANE_CLAUSE):
        assert clause in analysis.EXTRACT_JSON_SYSTEM_PROMPT
        assert clause in analysis.EXTRACT_PLAIN_SYSTEM_PROMPT
    assert "JSON" in analysis.EXTRACT_PLAIN_SYSTEM_PROMPT and "line_numbers" not in analysis.EXTRACT_PLAIN_SYSTEM_PROMPT


def test_plain_reader_is_the_default(monkeypatch):
    monkeypatch.delenv("CODESNAP_READER", raising=False)
    import importlib
    module = importlib.reload(analysis)
    try:
        assert module.READER == "plain"
    finally:
        monkeypatch.setenv("CODESNAP_READER", "plain")
        importlib.reload(analysis)
