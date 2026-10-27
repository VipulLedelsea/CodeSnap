import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from core.model import ProgramStore  # noqa: E402
from core.model.folder_import import add_folder_files  # noqa: E402
from core.report import quality  # noqa: E402


def test_folder_files_are_not_blocked_for_missing_original_benchmark(tmp_path, monkeypatch):
    """Files read straight from a folder are the original; no 'source completeness unconfirmed' blocker is raised."""
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "p"))
    folder = tmp_path / "src"
    folder.mkdir()
    (folder / "A.cbl").write_text("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. A.\n       PROCEDURE DIVISION.\n           STOP RUN.\n")
    s = ProgramStore.create("Folder fixes")
    add_folder_files(s, str(folder))
    assert not any("original-file benchmark" in b for b in quality.summary(s)["blockers"])
    assert any("read directly from the supplied folder" in (x.get("text") or "") for x in quality.blocks(s))
    s.close()
