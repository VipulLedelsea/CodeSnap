from pathlib import Path

import pytest

from core.cobol.parser import logical_lines, parse, parse_bms, parse_cobol, parse_jcl
from core.model import ProgramStore, ingest_capture

SAMPLES = Path(__file__).resolve().parent / "samples" / "cobol"


def sample(name):
    return (SAMPLES / name).read_text()


def ents(result, kind=None):
    return {(e["kind"], e["name"], e["parent"]) for e in result["entities"] if kind in (None, e["kind"])}


def rels(result, kind=None):
    return {(r["kind"], r["source"], r["target"]) for r in result["relations"] if kind in (None, r["kind"])}


def test_logical_lines_skip_comments_and_join_continuations():
    text = ("000100 PROCEDURE DIVISION.\n000200* COMMENT\n000300     DISPLAY 'HELLO\n"
            "000400-    ' WORLD'.\n")
    out = logical_lines(text)
    assert [n for n, _, _ in out] == [1, 3]
    assert "HELLO WORLD" in out[1][1]
    assert out[0][2] is True and out[1][2] is False


def test_batch_program_structure():
    r = parse_cobol(sample("AIDCALC.cbl"), "AIDCALC.cbl")
    assert ("program", "AIDCALC", None) in ents(r)
    assert ents(r, "section") == {("section", "0000-MAIN", "AIDCALC")}
    assert ents(r, "paragraph") == {("paragraph", "0000-START", "0000-MAIN"),
                                    ("paragraph", "1000-READ-DISTRICT", "0000-MAIN"),
                                    ("paragraph", "2000-CALC-AID", "0000-MAIN")}
    assert {e[1] for e in ents(r, "data_store")} == {"DISTRICT-FILE", "PAYMENT-FILE"}
    assert rels(r) == {
        ("includes", "AIDCALC", "copybook:AIDREC"),
        ("reads", "0000-START", "data_store:DISTRICT-FILE"),
        ("writes", "0000-START", "data_store:PAYMENT-FILE"),
        ("calls", "0000-START", "1000-READ-DISTRICT"),
        ("calls", "0000-START", "2000-CALC-AID"),
        ("calls", "0000-START", "program:AIDAUDIT"),
        ("reads", "1000-READ-DISTRICT", "data_store:DISTRICT-FILE"),
        ("writes", "2000-CALC-AID", "data_store:PAYMENT-FILE"),
        ("calls", "2000-CALC-AID", "1000-READ-DISTRICT"),
    }
    section = next(e for e in r["entities"] if e["kind"] == "section")
    assert (section["line_start"], section["line_end"]) == (23, 42)
    eof = next(e for e in r["entities"] if e["name"] == "END-OF-FILE")
    assert eof["parent"] == "WS-EOF" and eof["attrs"]["level"] == 88


def test_cics_program_structure():
    r = parse_cobol(sample("AIDINQ.cbl"), "AIDINQ.cbl")
    assert rels(r) == {
        ("reads", "MAIN-PARA", "screen:AIDMAP1"),
        ("displays", "MAIN-PARA", "screen:AIDMAP1"),
        ("calls", "MAIN-PARA", "program:AIDERR"),
        ("calls", "MAIN-PARA", "LOOKUP-AID"),
        ("calls", "MAIN-PARA", "program:AIDAUDIT"),
        ("invokes_transaction", "MAIN-PARA", "transaction:AIDQ"),
        ("reads", "LOOKUP-AID", "table:MDE.DISTRICT_AID"),
        ("calls", "LOOKUP-AID", "program:AIDERR"),
    }
    link = next(x for x in r["relations"] if x["target"] == "program:AIDAUDIT")
    assert link["attrs"]["verb"] == "CICS LINK" and link["line"] == 25
    send = next(x for x in r["relations"] if x["kind"] == "displays")
    assert send["attrs"]["mapset"] == "AIDMAP"


def test_sequence_area_variants_parse_the_same():
    base = parse_cobol(sample("AIDCALC.cbl"), "AIDCALC.cbl")
    for name in ("AIDCALC_noseq.cbl", "AIDCALC_shifted.cbl"):
        other = parse_cobol(sample(name), name)
        assert ents(other) == ents(base) and rels(other) == rels(base)


def test_sql_reads_writes_and_cursor():
    text = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. AIDUPD.
000300 PROCEDURE DIVISION.
000400 MAIN-PARA.
000500     EXEC SQL
000600         UPDATE MDE.DISTRICT_AID SET TOTAL_AMOUNT = :WS-TOTAL
000700         WHERE DISTRICT_ID IN
000710             (SELECT DISTRICT_ID FROM MDE.DISTRICT)
000800     END-EXEC
000900     EXEC SQL INSERT INTO MDE.AUDIT_LOG VALUES (:WS-ID) END-EXEC
001000     EXEC SQL DELETE FROM MDE.STAGING WHERE 1 = 1 END-EXEC
001100     GOBACK.
"""
    r = parse_cobol(text, "AIDUPD.cbl")
    assert rels(r) == {("writes", "MAIN-PARA", "table:MDE.DISTRICT_AID"), ("reads", "MAIN-PARA", "table:MDE.DISTRICT"),
                       ("writes", "MAIN-PARA", "table:MDE.AUDIT_LOG"), ("writes", "MAIN-PARA", "table:MDE.STAGING")}


def test_dynamic_call_and_vsam_and_perform_filters():
    text = """000100 IDENTIFICATION DIVISION.
000200 PROGRAM-ID. DYN.
000300 PROCEDURE DIVISION.
000400 MAIN-PARA.
000500     MOVE 'AIDSUB1' TO WS-PGM
000600     CALL WS-PGM USING WS-AREA
000700     CALL WS-OTHER
000800     PERFORM 3 TIMES
000900         DISPLAY 'X'
001000     END-PERFORM
001100     PERFORM UNTIL WS-DONE = 'Y'
001200         CONTINUE
001300     END-PERFORM
001400     PERFORM WS-COUNT TIMES
001500         CONTINUE
001600     END-PERFORM
001700     PERFORM 9000-IN-COPYBOOK
001800     EXEC CICS READ FILE('AIDVSAM') INTO(WS-REC)
001810         RIDFLD(WS-KEY) END-EXEC
001900     EXEC CICS WRITEQ TS QUEUE('AIDTSQ') FROM(WS-REC) END-EXEC
002000     EXEC CICS START TRANSID('AIDB') END-EXEC
002100     GOBACK.
"""
    r = parse_cobol(text, "DYN.cbl")
    assert rels(r) == {
        ("calls", "MAIN-PARA", "program:AIDSUB1"),
        ("calls", "MAIN-PARA", "paragraph:DYN.9000-IN-COPYBOOK"),
        ("reads", "MAIN-PARA", "data_store:AIDVSAM"),
        ("writes", "MAIN-PARA", "data_store:AIDTSQ"),
        ("invokes_transaction", "MAIN-PARA", "transaction:AIDB"),
    }
    program = next(e for e in r["entities"] if e["kind"] == "program")
    assert program["attrs"]["dynamic_calls"] == ["WS-OTHER"]


def test_text_past_column_72_is_ignored():
    text = ("000100 IDENTIFICATION DIVISION.\n000200 PROGRAM-ID. C.\n000300 PROCEDURE DIVISION.\n"
            "000400 P1.\n000500     CALL 'AIDSUB1'" + " " * 44 + "IGNORED\n000600     GOBACK.\n")
    r = parse_cobol(text, "C.cbl")
    assert rels(r) == {("calls", "P1", "program:AIDSUB1")}


def test_exec_in_comment_is_ignored():
    text = ("000100 IDENTIFICATION DIVISION.\n000200 PROGRAM-ID. C.\n000300 PROCEDURE DIVISION.\n"
            "000400 P1.\n000500*    EXEC CICS LINK PROGRAM('NOPE') END-EXEC\n000600     GOBACK.\n")
    assert rels(parse_cobol(text, "C.cbl")) == set()


def test_copybook_fields():
    r = parse(sample("AIDREC.cpy"), "AIDREC.cpy")
    assert ("copybook", "AIDREC", None) in ents(r)
    fields = {e[1]: e[2] for e in ents(r, "field")}
    assert fields["AID-RECORD"] == "AIDREC" and fields["AID-TOTAL-AMOUNT"] == "AID-RECORD"
    total = next(e for e in r["entities"] if e["name"] == "AID-TOTAL-AMOUNT")
    assert total["attrs"] == {"level": 5, "picture": "9(11)V99"}


def test_bms_map():
    r = parse_bms(sample("AIDMAP.bms"), "AIDMAP.bms")
    screen = next(e for e in r["entities"] if e["kind"] == "screen")
    assert screen["name"] == "AIDMAP1" and screen["attrs"] == {"map_name": "AIDMAP1", "mapset": "AIDMAP", "size": "24x80"}
    fields = {e["name"]: e["attrs"] for e in r["entities"] if e["kind"] == "ui_element"}
    assert fields["DISTID"]["input"] is True and fields["TOTAL"]["input"] is False
    assert fields["LABEL@1,20"]["text"] == "DISTRICT AID INQUIRY"


def test_jcl_job():
    r = parse_jcl(sample("AIDJOB.jcl"), "AIDJOB.jcl")
    assert ents(r) == {("job", "AIDJOB", None)}
    assert rels(r) == {
        ("calls", "AIDJOB", "program:AIDCALC"),
        ("calls", "AIDJOB", "program:AIDRPT"),
        ("reads", "AIDJOB", "data_store:MDE.FIN.DISTRICT.INPUT"),
        ("writes", "AIDJOB", "data_store:MDE.FIN.AID.PAYMENTS"),
        ("reads", "AIDJOB", "data_store:MDE.FIN.AID.PAYMENTS"),
    }
    out = next(x for x in r["relations"] if x["kind"] == "writes")
    assert out["attrs"]["ddname"] == "PAYOUT" and out["attrs"]["program"] == "AIDCALC" and out["attrs"]["step"] == "STEP010"


def test_parse_dispatch():
    assert parse("print('x')", "x.py") is None
    assert parse(sample("AIDJOB.jcl"), "AIDJOB.jcl")["entities"][0]["kind"] == "job"


class NoApi:
    @property
    def messages(self):
        raise AssertionError("COBOL should not call the API for structure")


def test_ingest_full_cobol_program(tmp_path):
    store = ProgramStore.create("MDE Aid", root=tmp_path)
    files = [("AIDCALC.cbl", "COBOL", "cbl"), ("AIDJOB.jcl", "JCL", "jcl"), ("AIDINQ.cbl", "COBOL", "cbl"),
             ("AIDMAP.bms", "CICS BMS map", "bms"), ("AIDREC.cpy", "COBOL copybook", "cpy")]
    for name, language, ext in files:
        ingest_capture(store, NoApi(), [], {"is_code": True, "code": sample(name), "extension": ext,
                                            "language": language, "errors": "None"}, name=name)
    assert {a["name"]: (a["artifact_type"], a["status"]) for a in store.artifacts()} == {
        "AIDCALC.cbl": ("code", "structured"), "AIDINQ.cbl": ("code", "structured"),
        "AIDJOB.jcl": ("job", "structured"), "AIDMAP.bms": ("code", "structured"),
        "AIDREC.cpy": ("code", "structured")}
    calc = store.entity_by_key("program:AIDCALC")
    assert {e["name"] for e in store.neighbors(calc["id"], "in", kind="calls")} == {"AIDJOB"}
    screen = store.entity_by_key("screen:AIDMAP1")
    assert screen["origin"] == "extracted"
    assert {e["name"] for e in store.neighbors(screen["id"], "in", kind="displays")} == {"MAIN-PARA"}
    assert store.entity_by_key("copybook:AIDREC")["origin"] == "extracted"
    missing = {(m["kind"], m["name"]) for m in store.coverage()["missing"]}
    assert ("program", "AIDAUDIT") in missing and ("program", "AIDCALC") not in missing
    assert ("copybook", "AIDREC") not in missing and ("screen", "AIDMAP1") not in missing
    para = store.entity_by_key("paragraph:AIDCALC.0000-MAIN.1000-READ-DISTRICT")
    assert para and para["line_start"] == 32
    link = next(r for r in store.relations(kind="calls") if r["attrs"].get("verb") == "CICS LINK")
    assert link["line"] == 25
    assert store.usage()["input_tokens"] == 0 and store.runs()[-1]["model"] == "cobol-parser-v1"
    store.close()
