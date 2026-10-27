import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from core.model import ProgramStore, complete_capture  # noqa: E402
from test_capture_files import _frames, _report  # noqa: E402


def _state(server, store, art):
    return server._artifact_summary(store, store.artifact(art))["state"]


def test_file_is_not_done_while_the_program_analysis_is_still_running(tmp_path, monkeypatch):
    """Between model calls no file is marked active; a running job must still keep unreviewed files out of 'done'."""
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "p"))
    from webapp import server
    s = ProgramStore.create("Status gap")
    a = s.add_pending_capture(_frames(tmp_path, seed=1))
    complete_capture(s, None, a, _report())
    slug = s.info["slug"]
    assert _state(server, s, a) == "done"
    server._DEEP[slug] = {"running": True}
    try:
        assert _state(server, s, a) == "reviewing"          # not yet through the review
        server._DEEP[slug] = {"running": False}
        assert _state(server, s, a) == "done"
        server._FOLDER_JOBS[slug] = {"running": True}       # folder still being added
        assert _state(server, s, a) == "reviewing"
    finally:
        server._DEEP.pop(slug, None)
        server._FOLDER_JOBS.pop(slug, None)
        s.close()
