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


class _Stub:
    def __init__(self, ents):
        self._e = ents

    def artifacts(self):
        return [{"id": 1, "name": "A.cbl"}, {"id": 2, "name": "B.pli"}, {"id": 3, "name": "SCR.bms"}]

    def entities(self):
        return self._e


def test_receipt_width_differing_between_files_is_reported():
    from core import widths
    ents = [
        {"id": 1, "kind": "field", "name": "REQ-RECEIPT", "attrs": {"picture": "X(16)"}, "artifact_id": 1, "origin": "extracted", "line_start": 5},
        {"id": 2, "kind": "field", "name": "SAVED_RECEIPT", "attrs": {"type": "CHAR(12) STATIC"}, "artifact_id": 2, "origin": "extracted", "line_start": 14},
        {"id": 3, "kind": "ui_element", "name": "LABEL@3,2", "attrs": {"pos": "3,2", "length": 7, "text": "RECEIPT", "input": False}, "artifact_id": 3, "origin": "extracted", "line_start": 7},
        {"id": 4, "kind": "ui_element", "name": "R00", "attrs": {"pos": "3,12", "length": 12, "input": True}, "artifact_id": 3, "origin": "extracted", "line_start": 9},
        {"id": 5, "kind": "field", "name": "WS-AMOUNT", "attrs": {"picture": "9(7)V99"}, "artifact_id": 1, "origin": "extracted", "line_start": 6},
    ]
    obs = widths.conflicts(_Stub(ents))
    assert len(obs) == 1 and obs[0]["title"].startswith("Receipt")
    assert obs[0]["files"][:2] == ["B.pli", "SCR.bms"] and "16 characters" in obs[0]["statement"]
    same = [dict(e) for e in ents if e["id"] in (1,)] + [dict(ents[0], id=9, artifact_id=2, name="IN-RECEIPT")]
    assert widths.conflicts(_Stub(same)) == []


class _Texts:
    def __init__(self, **files):
        self._f = files

    def artifacts(self):
        return [{"id": i, "name": n, "transcription": t} for i, (n, t) in enumerate(self._f.items(), 1)]


def test_many_steps_rereading_the_same_input_are_reported():
    from core import jclreads
    steps = "".join(f"//X{i:02d} EXEC PGM=MUNREV\n//PAYIN DD DSN=SYNTH.POST.OUT,DISP=SHR\n//PAYOUT DD DSN=SYNTH.D{i}.REVIEW,DISP=(MOD,CATLG)\n" for i in range(6))
    obs = jclreads.conflicts(_Texts(**{"job.jcl": "//JOB1 JOB\n" + steps}))
    assert len(obs) == 1 and "6 steps" in obs[0]["title"] and "SYNTH.POST.OUT" in obs[0]["title"]
    few = "//JOB1 JOB\n" + "".join(f"//X{i} EXEC PGM=A\n//IN DD DSN=SAME,DISP=SHR\n" for i in range(3))
    assert jclreads.conflicts(_Texts(**{"few.jcl": few})) == []


def test_commit_inside_a_called_routine_is_reported():
    from core import commitscope
    src = "SVC: PROC(REQUEST, RESULT);\n  EXEC SQL INSERT INTO AUD VALUES (1);\n  EXEC SQL COMMIT;\n  RETURN;\n"
    obs = commitscope.conflicts(_Texts(**{"svc.pli": src}))
    assert len(obs) == 1 and "caller" in obs[0]["title"] and "line 3" in obs[0]["statement"]
    top = "MAIN: PROC;\n  EXEC SQL COMMIT;\n"
    assert commitscope.conflicts(_Texts(**{"main.pli": top})) == []


def test_a_long_aside_does_not_hide_the_defect_when_a_finding_is_shortened():
    from core.report import codefindings as CFM
    from core.report import editorial
    text = ("Comment at line 135 (and repeated identically before every relief IF, e.g. 152, 169, 186, 203, 220, 237...) states "
            "'EMERGENCY OVERRIDE HAS NO SUNSET CHECK', confirming that the emergency override relief has no expiry date check in the code.")
    assert "SUNSET" in CFM.short(text, 120)
    assert "SUNSET" in editorial._short(text, 22)
    assert "(and repeated" in editorial._short(text, 60)            # nothing is dropped when the whole text fits


def _cobol(limits):
    paras = "".join(f"       {2000 + i * 10}-{n}.\n           IF WS-AMOUNT < {lo}\n               MOVE \"REVIEW\" TO WS-RESULT\n           END-IF\n           IF WS-AMOUNT > {hi}\n               MOVE \"HOLD\" TO WS-RESULT\n           END-IF.\n"
                    for i, (n, lo, hi) in enumerate(limits))
    return ("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. X.\n       PROCEDURE DIVISION.\n       1000-MAIN.\n"
            "           COMPUTE WS-AMOUNT = WS-AMOUNT * -1\n           STRING IN-RECEIPT WS-RESULT INTO OUTPUT-RECORD\n           END-STRING\n           WRITE OUTPUT-RECORD.\n" + paras)


def test_same_named_paragraphs_with_different_thresholds_are_reported():
    from core import ruledrift
    names = ["ASHFORD", "BRIARWOOD", "CEDARVALE", "DUNWICH"]
    a = _cobol([(n, 100 + 25 * i, 10000 + 2500 * i) for i, n in enumerate(names)])
    b = _cobol([(n, 125 + 25 * i, 12500 + 2500 * i) for i, n in enumerate(names)])
    obs = [o for o in ruledrift.threshold_drift(_Texts(**{"A.cbl": a, "B.cbl": b}))]
    assert len(obs) == 1 and "A.cbl" in obs[0]["title"] and "ASHFORD: below 100 and above 10000 in A.cbl" in obs[0]["statement"]
    same = ruledrift.threshold_drift(_Texts(**{"A.cbl": a, "C.cbl": a}))
    assert same == []


def test_an_amount_calculated_but_not_in_the_written_record_is_reported():
    from core import ruledrift
    obs = ruledrift.unwritten_amounts(_Texts(**{"A.cbl": _cobol([("ASHFORD", 1, 2)])}))
    assert len(obs) == 1 and "WS-AMOUNT" in obs[0]["title"] and "IN-RECEIPT" in obs[0]["statement"]
    kept = _cobol([("ASHFORD", 1, 2)]).replace("IN-RECEIPT WS-RESULT", "IN-RECEIPT WS-RESULT WS-AMOUNT")
    assert ruledrift.unwritten_amounts(_Texts(**{"A.cbl": kept})) == []
