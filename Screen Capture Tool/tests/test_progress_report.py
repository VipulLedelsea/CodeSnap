import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from core.model import ProgramStore, complete_capture  # noqa: E402
from core.report import cached_package, waiting  # noqa: E402
from test_capture_files import _frames, _report  # noqa: E402


def _program(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "p"))
    s = ProgramStore.create("Report once")
    a = s.add_pending_capture(_frames(tmp_path, seed=1))
    complete_capture(s, None, a, _report())
    return s, a


def test_report_built_once_and_reused_until_something_changes(tmp_path, monkeypatch):
    s, a = _program(tmp_path, monkeypatch)
    assert cached_package(s)["built"] is True
    assert cached_package(s)["built"] is False
    s.rename_artifact(a, "AIDCALC-v2.cbl")
    assert cached_package(s)["built"] is True
    s.close()


def test_report_waits_for_every_capture(tmp_path, monkeypatch):
    s, _ = _program(tmp_path, monkeypatch)
    s.add_pending_capture(_frames(tmp_path, seed=2))
    assert waiting(s) == 1
    from fastapi.testclient import TestClient
    from webapp import server
    slug = s.info["slug"]
    s.close()
    c = TestClient(server.app)
    r = c.get(f"/api/programs/{slug}/report.html")
    assert r.status_code == 409 and "still waiting" in r.text
    assert c.get(f"/api/programs/{slug}/report.docx").status_code == 409


def test_progress_counts_screenshots_read(tmp_path, monkeypatch):
    s, _ = _program(tmp_path, monkeypatch)
    aid = s.add_pending_capture(_frames(tmp_path, n=3, seed=3))
    ev = s.artifact_evidence(aid)
    (s.text_cache_dir / f"{ev[0]['sha256']}.md").write_text("x")
    s.claim_pending(aid, f"{__import__('os').getpid()}:1")
    p = s.capture_progress(aid)
    assert p == {"frames": 3, "read": 1, "stage": None, "analysing": True}
    s.close()


def test_program_mode_skips_per_file_bundle(tmp_path):
    import tools
    ctx = tools.ToolContext(client=None, out_dir=tmp_path, confirm_saves=False, program_mode=True)
    assert tools._t_save_output(ctx, {"format": "source", "content": "x = 1", "extension": "py"}) == "Added to the program."
    assert ctx.last_report["code"] == "x = 1" and not list(tmp_path.rglob("*.json"))


def test_screenshot_counter_updates_before_whole_file_cache_sync(tmp_path, monkeypatch):
    import hotkey_capture as hk
    from fastapi.testclient import TestClient
    from webapp import server
    s, _ = _program(tmp_path, monkeypatch)
    try:
        aid = s.add_pending_capture(_frames(tmp_path, n=3, seed=4))
        s.claim_pending(aid, f"{__import__('os').getpid()}:worker")
        local = tmp_path / 'session' / '.cache'
        local.mkdir(parents=True)
        app = hk.App.__new__(hk.App)
        app.program = s.info['slug']
        app._stage(aid, 'reading screenshots', cache_dir=local)
        frames = s.artifact_evidence(aid)
        client = TestClient(server.app)
        url = f'/api/programs/{s.info["slug"]}'
        def count():
            data = client.get(url).json()
            return next(a['pending']['read'] for a in data['artifacts'] if a['id'] == aid)
        assert count() == 0
        for expected, frame in enumerate(frames, 1):
            (local / f"{frame['sha256']}.md").write_text(f'frame {expected}')
            assert count() == expected
        assert not any((s.text_cache_dir / f"{f['sha256']}.md").exists() for f in frames)
        # The same screenshot in both caches counts once, and unrelated text does not count.
        (s.text_cache_dir / f"{frames[0]['sha256']}.md").write_text('synced')
        (local / 'unrelated.md').write_text('other capture')
        assert count() == 3
        app._stage(aid, 'checking source')
        assert count() == 3
    finally:
        s.close()
