import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from core import analysis  # noqa: E402


def test_the_unverified_copy_of_a_line_read_twice_goes():
    good = '        if self.decision == "deny" and not self.denial_reason:'
    bad = '        if self decision == "deny" and not self denial reason:'
    text = "\n".join(["    def check(self):", bad, good, "            raise ValueError()"])
    out, dropped = analysis._drop_garbled_twins(text, {good: "verified", bad: "unchecked"})
    assert good in out.split("\n") and bad not in out.split("\n") and dropped == [2]


def test_two_verified_lines_that_differ_in_punctuation_are_both_kept():
    a, b = "    first_value = compute.alpha_beta(x)", "    first_value = compute_alpha_beta(x)"
    text = "\n".join([a, b])
    assert analysis._drop_garbled_twins(text, {a: "verified", b: "verified"}) == (text, [])
