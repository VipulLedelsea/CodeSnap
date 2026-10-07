from core.report import codefindings as CF


def fact(text, severity="medium", category="defect"):
    return {"statement": text, "severity": severity, "category": category, "review": "supported", "lines": "1-2", "basis": "observed"}


def test_short_never_ends_in_an_ellipsis_or_open_bracket():
    text = ("A comment documents a known defect (INC-1997-117) that the export_queue's exported flag update and the ledger "
            "(payments) update are committed separately, risking inconsistent state if one commit succeeds and the other fails")
    for limit in (60, 120, 230):
        out = CF.short(text, limit)
        assert "…" not in out
        assert out.count("(") == out.count(")")


def test_short_keeps_identifier_case():
    assert CF.short("SQLCODE is declared but never checked").startswith("SQLCODE")


def test_every_high_severity_finding_is_kept_and_duplicates_merge():
    facts = {1: [fact(f"q{i}aaa q{i}bbb q{i}ccc q{i}ddd changes payment", "high")
                 for i in range(25)]
                + [fact("The current_policy view ignores fiscal_year", "high"),
                   fact("A comment confirms the current_policy view defect: it ignores fiscal year", "high"),
                   fact("INPUT-FILE is assigned to PAYIN and has file status monitoring via WS-STATUS", "low")]}
    out = CF.select(None, [{"id": 1, "name": "A.cbl"}], facts)
    assert len([r for r in out if "current_policy" in r["text"]]) == 1
    assert not [r for r in out if "file status monitoring" in r["text"]]
    assert len([r for r in out if r["severity"] == "high"]) == 26


def test_high_severity_unconditional_defects_are_rated_high():
    cf = {"text": "In every district subroutine a priority unconditionally overrides a decision", "severity": "high"}
    likelihood, impact, why_l, why_i = CF.rate(cf)
    assert likelihood * impact >= 15 and "every run" in why_l
    medium = {"text": "A variable is declared STATIC and persists across calls", "severity": "medium"}
    likelihood, impact, *_ = CF.rate(medium)
    assert likelihood * impact < 15
