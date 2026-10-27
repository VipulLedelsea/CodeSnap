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


def test_every_file_with_a_defect_gets_one_in_the_code_findings():
    from core.report import codefindings as CFM
    arts = [{"id": i, "name": f"F{i}.cbl"} for i in range(1, 7)]
    noisy = {"statement": "Waiver subtracts the fee even when the threshold prevented it; unconditional.", "category": "defect", "severity": "medium", "basis": "observed"}
    quiet = {"statement": "None of the steps carry a COND= parameter or return-code test, so INTAKE.RC LE 8 lets the job continue.", "category": "error_handling"}
    facts = {i: [dict(noisy, statement=noisy["statement"] + f" Variant {i}-{k} in paragraph P{k}.") for k in range(6)] for i in range(1, 6)}
    facts[6] = [quiet]
    picked = CFM.select(None, arts, facts, total=6)
    assert {c["file"] for c in picked} == {a["name"] for a in arts}


def test_numbered_dataset_families_become_one_diagram_node(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "p"))
    from core.diagrams import build
    s = ProgramStore.create("Datasets")
    a = s.add_pending_capture([]) if False else None
    names = [f"SYNTH.RESTART.P{n:02d}.WORK" for n in range(8)]
    model = build._Model.__new__(build._Model)
    model.ents = {i: {"id": i, "name": n, "kind": "data_store", "origin": "placeholder", "parent_id": None, "artifact_id": None, "attrs": {}}
                  for i, n in enumerate(names, 1)}
    model.rels = [{"from_id": 100, "to_id": i, "kind": "writes"} for i in model.ents]
    model._collapse_numbered_datasets()
    assert len(model.ents) == 1 and "x8" in next(iter(model.ents.values()))["name"]
    assert len(model.rels) == 1
    s.close()
