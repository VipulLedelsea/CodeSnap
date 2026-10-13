"""A screenshot is read by Haiku (plain) first, then by Sonnet (plain, larger limit); the JSON reader is the last resort."""
from pathlib import Path

from core import analysis


def _chain(monkeypatch, outcomes):
    calls = []

    def plain(client, path, *, calibration=None, model=None, max_tokens=8192):
        calls.append(("plain", model, max_tokens))
        r = outcomes[len([c for c in calls if c[0] == "plain"]) - 1]
        if isinstance(r, Exception):
            raise r
        return r

    def json_reader(client, path, *, calibration=None):
        calls.append(("json", analysis.EXTRACT_MODEL, None))
        return {"raw": "json read", "verify": {}}

    monkeypatch.setattr(analysis, "READER", "plain")
    monkeypatch.setattr(analysis, "extract_plain", plain)
    monkeypatch.setattr(analysis, "extract_json", json_reader)
    return calls


def test_haiku_read_that_is_trusted_stops_there(monkeypatch):
    calls = _chain(monkeypatch, [({"raw": "ok", "verify": {}}, None)])
    assert analysis.extract_structured(None, Path("x.png"))["raw"] == "ok"
    assert calls == [("plain", analysis.PLAIN_MODEL, 8192)]


def test_failed_haiku_read_goes_to_sonnet_plain_with_a_larger_limit(monkeypatch):
    calls = _chain(monkeypatch, [(None, "truncated"), ({"raw": "sonnet", "verify": {}}, None)])
    out = analysis.extract_structured(None, Path("x.png"))
    assert out["raw"] == "sonnet"
    assert [c[:2] for c in calls] == [("plain", analysis.PLAIN_MODEL), ("plain", analysis.READ_MODEL)]
    assert calls[1][2] == analysis.FALLBACK_MAX_TOKENS > 8192
    assert "truncated" in out["verify"]["reader_fallback"]


def test_haiku_error_also_goes_to_sonnet_plain(monkeypatch):
    calls = _chain(monkeypatch, [RuntimeError("boom"), ({"raw": "sonnet", "verify": {}}, None)])
    assert analysis.extract_structured(None, Path("x.png"))["raw"] == "sonnet"
    assert [c[1] for c in calls] == [analysis.PLAIN_MODEL, analysis.READ_MODEL]


def test_json_reader_only_when_both_plain_reads_fail(monkeypatch):
    calls = _chain(monkeypatch, [(None, "unverified"), (None, "unverified")])
    out = analysis.extract_structured(None, Path("x.png"))
    assert out["raw"] == "json read" and [c[0] for c in calls] == ["plain", "plain", "json"]
    assert out["verify"]["reader_fallback"].count("unverified") == 2


def test_uncalibrated_frame_skips_the_second_plain_read(monkeypatch):
    calls = _chain(monkeypatch, [(None, "uncalibrated")])
    assert analysis.extract_structured(None, Path("x.png"))["raw"] == "json read"
    assert [c[0] for c in calls] == ["plain", "json"]
