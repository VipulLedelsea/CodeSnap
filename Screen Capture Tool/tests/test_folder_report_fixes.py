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
    obs = [o for o in jclreads.conflicts(_Texts(**{"job.jcl": "//JOB1 JOB\n" + steps})) if "re-reads" in o["title"]]
    assert len(obs) == 1 and "6 steps" in obs[0]["title"] and "SYNTH.POST.OUT" in obs[0]["title"]
    few = "//JOB1 JOB\n" + "".join(f"//X{i} EXEC PGM=A\n//IN DD DSN=SAME,DISP=SHR\n" for i in range(3))
    assert [o for o in jclreads.conflicts(_Texts(**{"few.jcl": few})) if "re-reads" in o["title"]] == []


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


def test_sentence_split_does_not_break_after_an_abbreviation():
    from core.report import editorial
    text = "It writes to the same datasets (e.g. SYNTH.SOUTHGAT.REVIEW), showing one flow. A second sentence follows."
    assert editorial._sentences(text) == ["It writes to the same datasets (e.g. SYNTH.SOUTHGAT.REVIEW), showing one flow.", "A second sentence follows."]


def test_code_check_note_has_no_dangling_reference():
    from core.report_review import note_for
    out = note_for("INPUT-FILE is used in 06_MUNPAY.cbl (and similarly in 07_MUNREV.cbl per finding 170), but findings do not show them shared at runtime.")
    assert "per." not in out and out.count("(") == out.count(")") and "finding" not in out


def test_a_structural_check_can_set_its_own_severity():
    from core.report import codefindings as CFM
    o = {"title": "X is calculated but never written", "statement": "never written", "files": ["a"], "cites": [], "severity": "medium", "source": "rule drift"}
    assert CFM.program_items([o])["risks"][0]["severity"] == "medium"


def test_datasets_that_differ_in_one_name_segment_become_one_diagram_node():
    from core.diagrams import build
    names = [f"SYNTH.{d}.REVIEW" for d in ("ASHFORD", "BRIARWOO", "CEDARVAL", "DUNWICH", "ELMBRIDG", "FAIRHAVE", "GLENMOOR")] + ["SYNTH.POST.OUT", "SYNTH.BANK.INPUT"]
    model = build._Model.__new__(build._Model)
    model.ents = {i: {"id": i, "name": n, "kind": "data_store", "origin": "placeholder", "parent_id": None, "artifact_id": None, "attrs": {}}
                  for i, n in enumerate(names, 1)}
    model.rels = [{"from_id": 100, "to_id": i, "kind": "writes"} for i in model.ents]
    model._collapse_numbered_datasets()
    titles = sorted(e["name"] for e in model.ents.values())
    assert "SYNTH.*.REVIEW (x7)" in titles and "SYNTH.POST.OUT" in titles and len(titles) == 3
    assert len(model.rels) == 3


def test_family_labels_collapse_numbered_and_one_segment_families():
    from core.diagrams.build import _family_labels
    names = [f"SYNTH.{d}.REVIEW" for d in ("A1X", "BRI", "CED", "DUN", "ELM", "FAI")] + [f"SYNTH.RESTART.P{n:02d}.WORK" for n in range(5)] + ["SYNTH.POST.OUT"]
    out = _family_labels(names)
    assert out["SYNTH.BRI.REVIEW"] == "SYNTH.*.REVIEW (x6)" and out["SYNTH.RESTART.P03.WORK"] == "SYNTH.RESTART.Pnn.WORK (x5)"
    assert "SYNTH.POST.OUT" not in out


def test_views_are_not_counted_as_database_tables_in_the_context_diagram(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "p"))
    from core.diagrams import build
    s = ProgramStore.create("Views")
    for n, v in (("T1", False), ("T2", False), ("V1", True)):
        s.upsert_entity("table", n, attrs={"view": True} if v else {}, origin="extracted")
    box = next(n for n in build.context(s)["nodes"] if n["id"] == "tables")
    assert "(2)" in box["title"] and any("1 views" in line for line in box["sections"][0])
    s.close()


def test_coverage_chips_say_read_from_the_folder_for_a_folder_review(tmp_path, monkeypatch):
    monkeypatch.setenv("CODESNAP_PROGRAMS", str(tmp_path / "p"))
    from core.diagrams import build
    folder = tmp_path / "src"
    folder.mkdir()
    (folder / "A.cbl").write_text("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. A.\n       PROCEDURE DIVISION.\n           STOP RUN.\n")
    s = ProgramStore.create("Folder chips")
    add_folder_files(s, str(folder))
    titles = [n["title"] for n in build.architecture(s)["nodes"]]
    assert "1 files read from the folder" in titles and not any("captured" in t for t in titles)
    s.close()


def test_a_copybook_that_no_program_copies_is_reported():
    from core import ruledrift
    prog = "       IDENTIFICATION DIVISION.\n       PROCEDURE DIVISION.\n           STOP RUN.\n"
    used = prog.replace("PROCEDURE", "       COPY PAYREC.\n       PROCEDURE")
    files = {"09_PAYREC.cpy": "       01 PAY-RECORD.\n", "A.cbl": prog, "B.cbl": prog}
    obs = ruledrift.unused_copybooks(_Texts(**files))
    assert len(obs) == 1 and "09_PAYREC.cpy" in obs[0]["title"]
    files["A.cbl"] = used
    assert ruledrift.unused_copybooks(_Texts(**files)) == []


def test_a_value_stored_as_its_first_characters_counts_as_a_narrower_copy():
    from core import widths
    rexx = "route_00:\n  key = substr(receipt, 1, 12)\n  return 0\n"
    found = widths.truncations(_Texts(**{"r.rexx": rexx}))
    assert found and found[0][0] == "RECEIPT" and found[0][1] == 12


def test_a_gate_that_still_runs_at_return_code_8_is_reported():
    from core import jclreads
    blocks = "".join(f"//R{i:02d} IF (INTAKE.RC LE 8) THEN\n//X{i:02d} EXEC PGM=MUNREV\n//PAYIN DD DSN=SYNTH.POST.OUT,DISP=SHR\n// ENDIF\n" for i in range(5))
    obs = jclreads._rc_gates({"name": "job.jcl"}, blocks)
    assert len(obs) == 1 and "return code 8" in obs[0]["title"] and "5 blocks" in obs[0]["statement"]
    assert jclreads._rc_gates({"name": "job.jcl"}, blocks.replace("LE 8", "LE 4")) == []


def test_steps_that_append_with_disp_mod_are_reported():
    from core import jclreads
    steps = "".join(f"//X{i:02d} EXEC PGM=MUNREV\n//PAYOUT DD DSN=SYNTH.D{i}.REVIEW,\n// DISP=(MOD,CATLG,KEEP),SPACE=(TRK,(1,1))\n" for i in range(5))
    obs = jclreads._mod_outputs({"name": "job.jcl"}, steps)
    assert len(obs) == 1 and "5 steps" in obs[0]["title"]


def test_a_procedure_that_returns_zero_on_failure_is_reported_and_a_table_repeated_many_times():
    from core import ruledrift
    rexx = "".join(f"p{i}:\n  \"ALLOC FI(X) DA('A{i}')\"\n  open_rc = rc\n  if open_rc <> 0 then return 0\n" for i in range(4))
    obs = ruledrift.swallowed_failures(_Texts(**{"r.rexx": rexx}))
    assert len(obs) == 1 and "4 procedures" in obs[0]["statement"]
    cpy = "".join(f"          05 PA-{i:02d}-DETAIL OCCURS 12 TIMES.\n" for i in range(11))
    assert len(ruledrift.repeated_tables(_Texts(**{"c.cpy": cpy}))) == 1
