import base64
import io
import sys
import types
from pathlib import Path

import pytest
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from core import capture  # noqa: E402
from core.analysis import merge_frames  # noqa: E402
from core.model import ProgramStore, complete_capture  # noqa: E402
from test_capture_files import _frames, _report  # noqa: E402

COBOL = (HERE / "samples" / "cobol" / "AIDCALC.cbl").read_text()


class _FakeMss:
    monitors = [{"left": 0, "top": 0, "width": 4000, "height": 1200},
                {"left": 0, "top": 0, "width": 1470, "height": 956},
                {"left": 1470, "top": 0, "width": 2560, "height": 1440}]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_display_choice(monkeypatch):
    monkeypatch.setitem(sys.modules, "mss", types.SimpleNamespace(mss=_FakeMss))
    monkeypatch.delenv("CODESNAP_DISPLAY", raising=False)
    assert capture.pick_display("2") == 2
    assert capture.pick_display("9") == 1
    monkeypatch.setattr(capture, "_cursor_display", lambda mons: 2)
    assert capture.pick_display(None) == 2
    monkeypatch.setenv("CODESNAP_DISPLAY", "1")
    assert capture.pick_display("auto") == 1


def _png(w, h):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_large_screen_warns_small_region_does_not():
    out = capture._downscale_png(_png(5120, 2880))
    assert Image.open(io.BytesIO(out)).size[0] == capture.MAX_CAPTURE_PX
    assert "Pick code area" in capture.clarity_warning()
    capture._downscale_png(_png(1556, 972))
    assert capture.clarity_warning() is None


def test_added_earlier_screenshot_goes_first():
    lines = COBOL.splitlines()
    early, late = "\n".join(lines[:24]), "\n".join(lines[20:])
    assert merge_frames([late, early])[0].splitlines() == [l.rstrip() for l in lines if l.strip()]


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "progs"))
    with ProgramStore.create("Append test") as s:
        yield s


def test_added_screenshots_make_a_version_with_all_frames(store, tmp_path):
    first = store.add_pending_capture(_frames(tmp_path, n=2, seed=1))
    complete_capture(store, None, first, _report())
    more = store.add_pending_capture(_frames(tmp_path, n=3, seed=2), recapture_of="AIDCALC.cbl", keep_frames_of=first)
    assert len(store.artifact_evidence(more)) == 5
    new_id = complete_capture(store, None, more, _report())
    cur = store.current_artifact("AIDCALC.cbl")
    assert cur["id"] == new_id and cur["version"] == 2 and len(store.artifact_evidence(new_id)) == 5


def test_worker_append_reads_old_and_new_frames_and_reuses_old_text(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "progs"))
    monkeypatch.chdir(tmp_path)
    import hotkey_capture as hk
    from core.analysis import cache_path_for
    with ProgramStore.create("Worker append") as s:
        slug = s.info["slug"]
        first = s.add_pending_capture(_frames(tmp_path, n=2, seed=1))
        complete_capture(s, None, first, _report())
        for e in s.artifact_evidence(first):
            p = Path(s.evidence(e["id"])["abs_path"])
            (s.text_cache_dir / cache_path_for(p, s.text_cache_dir).name).write_text("cached text")
        s.set_meta("recapture_target", {"name": "AIDCALC.cbl", "artifact_id": first, "version": 1, "mode": "append"})
    seen = {}

    def fake(client, ctx, **k):
        seen["images"] = len(ctx.images)
        seen["cached"] = sum(1 for p in ctx.images if cache_path_for(p, ctx.cache_dir).exists())
        for p in ctx.images:
            cf = cache_path_for(p, ctx.cache_dir)
            if not cf.exists():
                cf.write_text("new text")
        ctx.last_report = _report()
        return "", None

    monkeypatch.setattr(hk, "run_team_fast", fake)
    app = hk.App(None)
    app.program, app.project_mode, app.team_mode = slug, True, True
    d = tmp_path / "captures" / "s_add"
    d.mkdir(parents=True)
    for p in _frames(tmp_path, n=2, seed=9):
        (d / p.name).write_bytes(p.read_bytes())
    aid = app._register_capture(d)
    app._analyse_burst(d, artifact_id=aid)
    assert seen == {"images": 4, "cached": 2}
    with ProgramStore.open(slug) as s:
        cur = s.current_artifact("AIDCALC.cbl")
        assert cur["version"] == 2 and len(s.artifact_evidence(cur["id"])) == 4
        assert len([p for p in s.text_cache_dir.glob("*.md") if not p.name.endswith('.ocr.md')]) == 4


def test_upload_screenshots_api(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "progs"))
    from fastapi.testclient import TestClient
    from webapp import server
    monkeypatch.setattr(server._session, "process_pending", lambda slug: True)
    with ProgramStore.create("Upload test") as s:
        slug = s.info["slug"]
        first = s.add_pending_capture(_frames(tmp_path, n=2, seed=1))
        complete_capture(s, None, first, _report())
    c = TestClient(server.app)
    img = "data:image/png;base64," + base64.b64encode(_png(30, 20)).decode()
    r = c.post(f"/api/programs/{slug}/artifacts/{first}/screenshots", json={"images": [img]})
    assert r.status_code == 200 and r.json()["frames"] == 3 and r.json()["added"] == 1
    assert c.post(f"/api/programs/{slug}/artifacts/{first}/screenshots", json={"images": ["nope"]}).status_code == 400
    d = c.get(f"/api/programs/{slug}").json()
    assert d["waiting"] == 1
    r = c.post(f"/api/programs/{slug}/recapture", json={"artifact_id": first, "mode": "append"})
    assert r.json()["recapture_target"]["mode"] == "append"
