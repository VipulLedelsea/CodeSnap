"""A capture set to Detect is read as code or as an app screen from what its first frame shows."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.analysis import detect_kind

SHOT = next((Path(__file__).resolve().parent / "real" / "2026-09-29-run2" / "aidpayrn_cobol").glob("01.png"))


class Answer:
    def __init__(self, word=None, fail=False):
        self.word, self.fail, self.calls = word, fail, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise RuntimeError("down")
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.word)])


@pytest.mark.parametrize("word,kind", [("screen", "screen"), ("Screen.", "screen"), ("code", "code"), ("unsure", "code")])
def test_the_first_frame_decides(word, kind):
    c = Answer(word)
    assert detect_kind(c, SHOT) == kind
    call = c.calls[0]
    assert call["max_tokens"] <= 10 and call["messages"][0]["content"][0]["type"] == "image"


def test_a_failed_guess_reads_it_as_code():
    assert detect_kind(Answer(fail=True), SHOT) == "code"


def test_the_worker_resolves_auto_once_and_keeps_explicit_choices(monkeypatch):
    import hotkey_capture as hk
    import core.analysis as an
    seen = []
    monkeypatch.setattr(an, "detect_kind", lambda client, p: seen.append(p) or "screen")
    app = SimpleNamespace(client=None, program=None, _kind_guess={})
    resolve = hk.App._resolve_kind
    assert resolve(app, "code", [SHOT]) == "code" and resolve(app, "screen", [SHOT]) == "screen"
    assert resolve(app, "auto", [SHOT]) == "screen" and seen == [SHOT]
    assert resolve(app, "auto", []) == "code"


def test_the_app_accepts_detect(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from webapp import server
    monkeypatch.setattr(server, "PROJECT", tmp_path)
    r = TestClient(server.app).post("/api/session/kind?kind=auto").json()
    assert r["ok"] and (tmp_path / "captures" / ".capture_kind").read_text() == "auto"
