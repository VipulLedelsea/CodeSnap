import pytest
from core.report.plainenglish import simplify

BANNED = ("is to check", "are to check", "to confirm", "supplied", "needs need", "need need", "unconfirmed", "provisional")


@pytest.mark.parametrize("text", [
    "PL/I support availability is to check.",
    "Available staff, vendor cover and training needs are to check.",
    "Ownership is to confirm; deployed version is not known.",
    "The supplied code writes it. The supplied components read it.",
    "To confirm (read only in the supplied code)",
    "Completeness is unconfirmed and the tier is provisional.",
    "Execution triggers, ordering and run frequency need checking.",
])
def test_known_awkward_phrases_are_gone(text):
    out = simplify(text, prose=False)
    assert not any(b in out.lower() for b in BANNED), out


def test_filler_sentences_are_dropped_and_nothing_else_is():
    out = simplify("Key entries shown. Full tables are in the supporting detail appendix. The fee is wrong on line 5.")
    assert out == "The fee is wrong on line 5."


def test_long_semicolon_chains_become_short_sentences():
    out = simplify("The batch job reads the input file and writes the output file for every district in the list; "
                   "the totals are never checked against the number of records that were read.")
    assert "; " not in out and out.count(". ") == 1


def test_identifier_lists_are_not_split():
    text = "Edit checks in the code: MUNIN.cbl (line 104); MUNPAY.cbl (line 112); report_20261001_104724.cbl (line 104)."
    assert simplify(text) == text


def test_numbers_and_file_names_survive():
    text = "MUNPAY.cbl has 1,002 lines and a risk score of 12 (line 112)."
    assert simplify(text) == text


def test_simplify_is_stable_when_applied_twice():
    text = "Ownership is to confirm; the supplied code does not establish who writes it, and the version is not confirmed."
    once = simplify(text)
    assert simplify(once) == once
