import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.cobol import lint_columns, merge_column_review, review_columns

SAMPLES = Path(__file__).resolve().parent / "samples" / "cobol"


def lines(name):
    return (SAMPLES / name).read_text().splitlines()


def text(ls):
    return "\n".join(ls) + "\n"


@pytest.mark.parametrize("name", ["AIDCALC.cbl", "AIDCALC_noseq.cbl", "AIDCALC_shifted.cbl", "AIDINQ.cbl",
                                  "AIDREC.cpy", "AIDCALC_broken.cbl"])
def test_clean_samples_have_no_column_issues(name):
    assert lint_columns(text(lines(name))) == []


def test_non_cobol_and_free_format_skipped():
    assert lint_columns("def f():\n  return 1\n") == []
    assert lint_columns(">>SOURCE FORMAT IS FREE\nIDENTIFICATION DIVISION.\n       MOVE A TO B.\n") == []
    assert lint_columns((SAMPLES / "AIDJOB.jcl").read_text()) == []


def test_paragraph_in_area_b():
    ls = lines("AIDCALC.cbl")
    ls[31] = ls[31][:7] + "    " + ls[31][7:]
    issues = lint_columns(text(ls))
    assert [(i["line"], i["problem"], i["line_text"]) for i in issues] == [(32, "Area A", "1000-READ-DISTRICT.")]
    assert "column 12" in issues[0]["note"]


def test_division_section_fd_and_01_need_area_a():
    ls = lines("AIDCALC.cbl")
    for idx in (3, 12, 17):
        ls[idx] = ls[idx][:7] + "    " + ls[idx][7:]
    got = {(i["line"], i["problem"]) for i in lint_columns(text(ls))}
    assert got == {(4, "Area A"), (13, "Area A"), (18, "Area A")}


def test_statement_in_area_a():
    ls = lines("AIDCALC.cbl")
    ls[26] = ls[26][:7] + ls[26][11:]
    assert [(i["line"], i["problem"]) for i in lint_columns(text(ls))] == [(27, "Area B")]


def test_bad_indicator_tab_and_column_72():
    ls = lines("AIDCALC.cbl")
    ls[2] = ls[2][:6] + "X" + ls[2][7:]
    ls[36] = ls[36].rstrip().ljust(72, "Z") + "OVERFLOW"
    ls[30] = ls[30].replace("    GOBACK.", "\tGOBACK.")
    got = {(i["line"], i["problem"]) for i in lint_columns(text(ls))}
    assert (3, "column 7") in got and (37, "column 72") in got and (31, "tab") in got


def test_unreferenced_single_word_in_area_b_not_flagged():
    ls = lines("AIDCALC.cbl")
    ls.insert(31, "003150     EXIT.")
    assert lint_columns(text(ls)) == []


def test_merge_grounds_and_dedupes():
    code = text(lines("AIDCALC.cbl"))
    lint = [{"line": 32, "line_text": "1000-READ-DISTRICT.", "problem": "Area A", "note": "starts in column 12"}]
    seen = [{"line_text": "1000-READ-DISTRICT.", "problem": "Area A", "note": "dup"},
            {"line_text": "ADD 1 TO WS-COUNT", "problem": "Area A", "note": "on screen"},
            {"line_text": "INVENTED LINE", "problem": "Area B"}]
    out = merge_column_review("None", lint, seen, code)
    assert out.startswith("Column layout issues") and "line 32 (Area A)" in out
    assert "ADD 1 TO WS-COUNT" in out and "INVENTED" not in out and out.count("1000-READ-DISTRICT") == 1
    assert merge_column_review("E1", [], [], code) == "E1"
    assert merge_column_review("E1", lint, [], code).startswith("E1\n\nColumn layout")


class FakeVision:
    def __init__(self, reply):
        self.reply, self.calls = reply, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.reply)])


def test_review_columns_sends_ruler_and_parses(tmp_path):
    shot = tmp_path / "s.png"
    shot.write_bytes(b"\x89PNGx")
    client = FakeVision(json.dumps({"issues": [{"line_text": "ADD 1 TO WS-COUNT", "problem": "Area A"}, "bad"]}))
    issues = review_columns(client, [shot], "000100     ADD 1 TO WS-COUNT")
    assert issues == [{"line_text": "ADD 1 TO WS-COUNT", "problem": "Area A"}]
    sent = client.calls[0]["messages"][0]["content"]
    assert sent[0]["type"] == "image" and "1234567890" in sent[-1]["text"]
    assert review_columns(client, [], "x") == []
    assert review_columns(FakeVision("not json"), [shot], "x") == []
