import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from core.analysis import merge_frames  # noqa: E402
from core.colfix import respace  # noqa: E402
from core.model import ProgramStore  # noqa: E402
from render import render_code  # noqa: E402
from test_capture_files import _frames  # noqa: E402

DBD = (HERE / "samples" / "langpacks" / "AIDDBD.dbd").read_text().rstrip("\n")


def test_claim_of_exited_worker_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "p"))
    with ProgramStore.create("Claims") as s:
        aid = s.add_pending_capture(_frames(tmp_path))
        assert s.claim_pending(aid, "999999:1")
        assert s.claim_pending(aid, "123:2")


def test_cut_lines_replaced_when_a_later_screenshot_shows_them_whole():
    cut = "\n".join(l[:24] + " [CUT OFF]" if 1 <= i <= 9 else l for i, l in enumerate(DBD.splitlines()))
    out = merge_frames([cut, DBD])[0]
    assert "[CUT OFF]" not in out and out.splitlines() == [l.rstrip() for l in DBD.splitlines()]


def test_separator_length_measured(tmp_path):
    truth = ["000400*" + "-" * 64, "000500* MONTHLY RUN", "000600" + " " * 5 + "MOVE A TO B", "000700*" + "-" * 64]
    png = render_code("\n".join(truth), tmp_path / "s.png", font_size=24)
    wrong = [truth[0] + "-", truth[1], truth[2], truth[3][:-1]]
    assert respace(png, "\n".join(wrong))[0].split("\n") == truth


def test_large_retina_font(tmp_path):
    truth = [l.rstrip() for l in (HERE / "samples/cobol/AIDINQ.cbl").read_text().splitlines()][:30]
    png = render_code("\n".join(truth), tmp_path / "r.png", font_size=30, line_numbers=True)
    shifted = [("  " + l[6:]).join([l[:6], ""]) if i % 3 == 0 and len(l) > 7 else l for i, l in enumerate(truth)]
    shifted = [l[:6] + l[7:] if i % 3 == 0 and len(l) > 7 and l[6:8] == "  " else l for i, l in enumerate(truth)]
    assert respace(png, "\n".join(shifted))[0].split("\n") == truth


def test_worker_skips_frames_while_codesnap_is_in_front(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import hotkey_capture as hk
    app = hk.App(None)
    calls = {"n": 0}

    def front():
        calls["n"] += 1
        if calls["n"] > 3:
            app.running = False
        return True

    monkeypatch.setattr(app, "_own_window_in_front", front)
    monkeypatch.setattr(hk, "BURST_INTERVAL", 0)
    monkeypatch.setattr(app, "_register_capture", lambda d: None)
    monkeypatch.setattr(app, "_analyse_burst", lambda *a, **k: None)
    d = tmp_path / "captures" / "s"
    d.mkdir(parents=True)
    app.running = True
    app._burst_loop(d)
    assert not list(d.glob("*.png"))


def test_mode_switch_is_read_at_next_capture(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import hotkey_capture as hk
    (tmp_path / "captures").mkdir()
    (tmp_path / "captures" / ".capture_kind").write_text("screen")
    app = hk.App(None)
    monkeypatch.setattr(app, "_ensure_client", lambda: None)
    monkeypatch.setattr(hk.threading, "Thread", lambda *a, **k: type("T", (), {"start": lambda self: None})())
    app.project_mode = True
    app._begin_burst_session()
    assert app.capture_kind == "screen"
