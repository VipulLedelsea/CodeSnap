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


def test_no_file_is_done_while_the_pipeline_is_still_building_the_report(tmp_path, monkeypatch):
    """After the last file is reviewed the pipeline still writes the summary and builds the report; files stay not-done until it ends."""
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "p"))
    import time
    from webapp import server
    from core import pipeline
    s = ProgramStore.create("Report gap")
    a = s.add_pending_capture(_frames(tmp_path, seed=2))
    complete_capture(s, None, a, _report())
    assert _state(server, s, a) == "done"
    pipeline._say(s, 6, "building the final report")
    assert _state(server, s, a) == "reviewing"
    assert server._artifact_summary(s, s.artifact(a))["step"] == "Step 6 of 7: building the final report"
    assert server._artifact_summary(s, s.artifact(a))["state"] != "done"
    stale = dict(s.get_meta("pipeline_job"), updated=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 13 * 3600)))
    s.set_meta("pipeline_job", stale)
    assert _state(server, s, a) == "done"          # a job that has not moved for 12 hours is dead
    pipeline._job(s, "done", stage=None)
    assert _state(server, s, a) == "done"
    s.close()
