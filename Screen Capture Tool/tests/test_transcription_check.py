import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "quality"))
import transcription_check as T  # noqa: E402

ORIG = "\n".join(["       IDENTIFICATION DIVISION.", "       PROCEDURE DIVISION.", "       5050-CHECK-05.",
                  "           MOVE 1 TO X.", "           MOVE 2 TO Y.", "       5060-CHECK-06.", "           MOVE 3 TO Z."]) + "\n"


def test_a_perfect_copy_meets_every_target():
    r = T.compare(ORIG, ORIG)
    assert (r["recovered"], r["extra"], r["dup_headers"], r["spacing_exact"]) == (1.0, 0, 0, 1.0)
    assert T.verdict(r) == []


def test_duplicate_paragraph_extra_lines_and_indentation_are_reported():
    lines = ORIG.strip().split("\n")
    dup = lines[:5] + lines[2:5] + lines[5:]                      # 5050-CHECK-05 and its body appear twice
    r = T.compare(ORIG, "\n".join(dup))
    assert r["extra"] == 3 and r["dup_headers"] == 1 and r["recovered"] == 1.0
    shifted = ORIG.replace("           MOVE 3 TO Z.", "          MOVE 3 TO Z.")
    r = T.compare(ORIG, shifted)
    assert r["indent_off"] == 1 and r["recovered"] == 1.0 and r["spacing_exact"] < 1.0


def test_a_lost_block_is_named():
    big = "\n".join(f"           MOVE {i} TO X." for i in range(12))
    r = T.compare(big, "\n".join(big.split("\n")[:3] + big.split("\n")[9:]))
    assert r["missing_blocks"][0]["lines"] == 6 and r["missing_blocks"][0]["original_line"] == 4
    assert any("missing block" in m for m in T.verdict(r))


def test_files_are_paired_by_name_ignoring_number_prefix_and_extension():
    pairs = T.pair({"03_MUNFEE.cbl": "a", "05_MUNEXPORT.rpgle": "b", "09_X.cpy": "c"},
                   {"02_MUNFEE.cbl": "A", "05_MUNEXPORT.rpgl": "B"})
    assert [(n, g) for n, _, g in pairs] == [("03_MUNFEE.cbl", "A"), ("05_MUNEXPORT.rpgle", "B"), ("09_X.cpy", None)]
