"""The report states what the files do together once, for the program, instead of repeating single-file findings."""
from core.report import codefindings as CF

OBS = [
    {"title": "End-to-end nightly payment flow", "statement": "A is read by P, which writes B.", "files": ["10_N.jcl", "06_P.cbl"],
     "cites": ["10_N.jcl lines 1–7"], "basis": "inferred"},
    {"title": "REV reads PAY output with a different record layout", "statement": "REV expects the district first.",
     "files": ["06_P.cbl", "07_R.cbl"], "cites": ["06_P.cbl lines 17–18", "07_R.cbl lines 12–16"], "basis": "inferred"},
    {"title": "Receipt thresholds are the same in five programs", "statement": "All five hardcode the same HOLD thresholds.",
     "files": ["01_A.cbl", "02_B.cbl", "03_C.cbl"], "cites": ["01_A.cbl lines 5–30"], "basis": "observed"},
    {"title": "Amount precision is the same across programs", "statement": "All use 9.2 digits.",
     "files": ["01_A.cbl", "02_B.cbl", "03_C.cbl"], "cites": [], "basis": "observed"},
    {"title": "RECOV reads the audit files REV writes", "statement": "It parses them.", "files": ["11_X.rexx", "07_R.cbl"],
     "cites": [], "basis": "inferred"},
]


def test_observations_are_sorted_into_flow_risk_debt_and_nothing():
    out = CF.program_items(OBS)
    assert out["flow"]["title"].startswith("End-to-end")
    assert [r["title"] for r in out["risks"]] == ["REV reads PAY output with a different record layout"]
    assert [d["title"] for d in out["debt"]] == ["Receipt thresholds are the same in five programs"]
    assert out["risks"][0]["severity"] == "high"          # a different record layout between steps is serious


def test_single_file_findings_inside_a_program_finding_are_absorbed():
    out = CF.program_items(OBS)
    single = [{"file": "07_R.cbl", "lines": [13, 14], "text": "REV expects the district first in the record layout"},   # inside REV's lines, same point
              {"file": "07_R.cbl", "lines": [13, 14], "text": "The waiver is subtracted even when no fee applied"},       # same lines, a different defect
              {"file": "07_R.cbl", "lines": [200, 210], "text": "y"},      # elsewhere in the same file
              {"file": "06_P.cbl", "lines": [], "text": "z"}]
    assert [f["text"] for f in CF.absorb(single, out)] == ["The waiver is subtracted even when no fee applied", "y", "z"]


def test_program_rating_grows_with_files_and_severity():
    out = CF.program_items(OBS)
    L, I, why_l, why_i = CF.program_rating(out["risks"][0])
    assert (L, I) == (4, 4) and "2 files" in why_l


def test_no_observations_changes_nothing():
    assert CF.program_items(None) == {"flow": None, "risks": [], "debt": []}
    assert CF.absorb([{"file": "a", "lines": [1, 2], "text": "t"}], CF.program_items([])) == [{"file": "a", "lines": [1, 2], "text": "t"}]
