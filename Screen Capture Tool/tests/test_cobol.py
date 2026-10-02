from pathlib import Path

import pytest

from core import validate
from core.analysis import clean_source, merge_frames
from core.cobol import (check_cobol, detect_format, detect_kind, is_column_sensitive, stub_exec_blocks,
                        to_fixed_layout)
from core.cobol.compile import _cobc

SAMPLES = Path(__file__).resolve().parent / "samples" / "cobol"
needs_cobc = pytest.mark.skipif(_cobc() is None, reason="GnuCOBOL not installed (brew install gnucobol)")


def sample(name):
    return (SAMPLES / name).read_text()


@pytest.mark.parametrize("name,kind,fmt", [
    ("AIDCALC.cbl", "cobol", "fixed"),
    ("AIDCALC_noseq.cbl", "cobol", "fixed"),
    ("AIDCALC_shifted.cbl", "cobol", "shifted"),
    ("AIDINQ.cbl", "cobol", "fixed"),
    ("AIDREC.cpy", "copybook", "fixed"),
])
def test_detect_kind_and_format(name, kind, fmt):
    assert detect_kind(sample(name)) == kind
    assert detect_format(sample(name)) == fmt


def test_detect_bms_jcl_and_non_cobol():
    assert detect_kind(sample("AIDMAP.bms")) == "bms"
    assert detect_kind(sample("AIDJOB.jcl")) == "jcl"
    assert detect_kind("def main():\n    print('hi')\n") is None
    assert detect_kind("int main() { return 0; }") is None
    assert detect_kind("x", extension="cpy") == "copybook"
    assert detect_kind("", language="COBOL") is None
    assert detect_kind("MOVE A TO B.", language="COBOL") == "cobol"
    assert detect_format(">>SOURCE FORMAT IS FREE\nIDENTIFICATION DIVISION.") == "free"


@pytest.mark.parametrize("name", ["AIDCALC.cbl", "AIDCALC_noseq.cbl", "AIDINQ.cbl", "AIDREC.cpy", "AIDJOB.jcl",
                                  "AIDMAP.bms"])
def test_cleanup_keeps_columns(name):
    text = sample(name).rstrip("\n")
    assert clean_source(text) == text
    assert clean_source(f"```cobol\n{text}\n```") == text
    assert merge_frames([text])[0] == text


def test_cleanup_still_strips_gutters_for_other_languages():
    assert clean_source("1  def f():\n2      return 1\n3  x = f()") == "def f():\n    return 1\nx = f()"


def test_shifted_layout_restored():
    restored = to_fixed_layout(sample("AIDCALC_shifted.cbl"))
    noseq = sample("AIDCALC_noseq.cbl").rstrip("\n")
    assert [l.rstrip() for l in restored.splitlines()] == [l.rstrip() for l in noseq.splitlines()]
    assert to_fixed_layout(sample("AIDCALC.cbl")) == sample("AIDCALC.cbl")


def test_stub_preserves_lines_and_columns():
    text = sample("AIDINQ.cbl")
    out, blocks, includes = stub_exec_blocks(text)
    assert len(out.splitlines()) == len(text.splitlines())
    assert all(len(a) == len(b) for a, b in zip(out.splitlines(), text.splitlines()))
    assert "EXEC" not in out and "DFHRESP" not in out
    assert includes == ["SQLCA"]
    assert [b["kind"] for b in blocks] == ["SQL", "CICS", "CICS", "CICS", "CICS", "CICS", "SQL", "CICS"]
    link = next(b for b in blocks if "LINK" in b["body"])
    assert "PROGRAM('AIDAUDIT')" in link["body"] and link["end"] == link["start"] + 2
    receive = out.splitlines()[blocks[1]["start"] - 1]
    assert receive[11:19] == "CONTINUE"


def test_stub_ignores_comment_lines():
    text = "000100* EXEC CICS RETURN END-EXEC\n000200 PROCEDURE DIVISION.\n"
    out, blocks, _ = stub_exec_blocks(text)
    assert out == text and blocks == []


def test_validate_routes_cobol_extensions(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr("core.cobol.check_cobol", lambda p: seen.append(Path(p).suffix) or {"checked": False})
    for ext in ("cbl", "cob", "cpy"):
        f = tmp_path / f"x.{ext}"
        f.write_text("x")
        validate.check_source(f)
    assert seen == [".cbl", ".cob", ".cpy"]


def test_check_without_cobc_is_unchecked(monkeypatch):
    monkeypatch.setattr("core.cobol.compile._cobc", lambda: None)
    res = check_cobol(SAMPLES / "AIDCALC.cbl")
    assert res["checked"] is False and "gnucobol" in res["note"].lower()


def test_bms_and_jcl_not_compiled():
    assert check_cobol(SAMPLES / "AIDMAP.bms")["checked"] is False
    assert check_cobol(SAMPLES / "AIDJOB.jcl")["checked"] is False


@needs_cobc
@pytest.mark.parametrize("name", ["AIDCALC.cbl", "AIDCALC_noseq.cbl", "AIDCALC_shifted.cbl", "AIDINQ.cbl", "AIDREC.cpy"])
def test_clean_samples_compile(name):
    res = check_cobol(SAMPLES / name, include_dirs=[SAMPLES])
    assert res["checked"] and res["ok"], res["errors"]


@needs_cobc
def test_broken_samples_report_real_line():
    res = check_cobol(SAMPLES / "AIDCALC_broken.cbl", include_dirs=[SAMPLES])
    assert res["checked"] and not res["ok"] and "AIDCALC_broken.cbl:28:" in res["errors"] and "UNTL" in res["errors"]
    res = check_cobol(SAMPLES / "AIDINQ_broken.cbl", include_dirs=[SAMPLES])
    assert not res["ok"] and "AIDINQ_broken.cbl:16:" in res["errors"] and "WS-COMAREA" in res["errors"]
    assert "stubbed" in res["note"]


@needs_cobc
def test_missing_copybook_is_a_gap_not_an_error():
    res = check_cobol(SAMPLES / "AIDCALC.cbl")
    assert res["checked"] is False and res["missing_copybooks"] == ["AIDREC"]
    assert "AIDREC" in res["note"]


@needs_cobc
def test_copybook_dirs_from_env(monkeypatch):
    monkeypatch.setenv("CODESNAP_COPYBOOK_DIRS", str(SAMPLES))
    assert check_cobol(SAMPLES / "AIDCALC.cbl")["ok"]


def test_legacy_kind_overrides_classifier():
    import team
    base = team._apply_legacy_kind({"is_code": False, "language": "", "extension": ""}, sample("AIDINQ.cbl"))
    assert (base["is_code"], base["language"], base["extension"]) == (True, "COBOL", "cbl")
    base = team._apply_legacy_kind({"is_code": True, "language": "Python", "extension": "py"}, "print(1)")
    assert base["language"] == "Python"


def test_column_sensitive_flag():
    assert is_column_sensitive(sample("AIDREC.cpy"))
    assert is_column_sensitive(extension="jcl")
    assert not is_column_sensitive("print('x')")


def test_ingest_types_for_bms_and_jcl():
    from core.model.ingest import artifact_type_for
    assert artifact_type_for({"extension": "bms"}, True) == "code"
    assert artifact_type_for({"extension": "jcl"}, True) == "job"
    assert artifact_type_for({"extension": "cbl"}, True) == "code"


def test_program_exports_copybooks(tmp_path):
    from core.model import ProgramStore
    with ProgramStore.create("Aid", root=tmp_path) as store:
        store.add_artifact("Aidrec.cpy", language="COBOL copybook", transcription=sample("AIDREC.cpy"))
        store.add_artifact("AIDCALC.cbl", language="COBOL", transcription=sample("AIDCALC.cbl"))
        out = store.export_copybooks()
        assert {p.name.upper() for p in out.iterdir()} == {"AIDREC.CPY"}


def test_normalize_ascii_and_bms_continuation():
    from core.cobol.normalize import normalize_transcription
    got = sample("AIDREC.cpy").replace("AIDREC - STUDENT", "AIDREC — STUDENT")
    assert normalize_transcription(got).rstrip("\n") == sample("AIDREC.cpy").rstrip("\n")
    bms = sample("AIDMAP.bms").splitlines()
    drifted = [bms[0][:71].rstrip() + "     X", " " + bms[1]] + bms[2:]
    assert normalize_transcription("\n".join(drifted)).rstrip("\n") == "\n".join(l.rstrip() for l in bms)
    assert normalize_transcription("x = 'a — b'") == "x = 'a — b'"

    noseq = sample("AIDCALC_noseq.cbl").splitlines()
    noseq[2] = noseq[2][1:]
    assert normalize_transcription("\n".join(noseq)).splitlines()[2] == sample("AIDCALC_noseq.cbl").splitlines()[2]


def test_copybook_with_program_extension_and_deep_fields():
    text = '       01 RECORD-A.\n          05 ITEMS OCCURS 10 TIMES.\n                 10 VALUE-A PIC X(8).\n                 10 VALUE-B PIC 9(4).'
    assert detect_kind(text, extension='.cbl', language='COBOL') == 'copybook'
