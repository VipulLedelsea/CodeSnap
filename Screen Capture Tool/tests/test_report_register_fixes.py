from core.report import codefindings as CFM
from core.report.template_docx import _id_runs


def test_id_runs_do_not_claim_a_range_across_other_findings():
    assert _id_runs(["VUL-1-01", "VUL-1-02", "VUL-1-05"]) == "VUL-1-01, VUL-1-02 and VUL-1-05"
    assert _id_runs(["VUL-1-01", "VUL-1-02", "VUL-1-03"]) == "VUL-1-01 to VUL-1-03"
    assert _id_runs(["VUL-1-04"]) == "VUL-1-04"


def test_ratings_differ_by_what_the_finding_says():
    sqli = {"text": "search_permits concatenates the query parameter q into SQL: SQL injection", "severity": "high"}
    local = {"text": "The database password is exported as an environment variable", "severity": "high"}
    minor = {"text": "The page parameter is not validated", "severity": "medium"}
    assert CFM.rate(sqli)[:2] == (5, 5)
    assert CFM.rate(local)[0] == 4
    assert CFM.rate(minor)[0] * CFM.rate(minor)[1] < 16


def test_high_configuration_fact_is_kept():
    import re
    assert "configuration" not in CFM.CATEGORIES      # kept by the severity rule in select, not by widening the list


def test_vendor_does_not_read_javascript_as_java():
    from core.report.template_docx import _vendor
    assert _vendor({"name": "JavaScript"}) != "Oracle"
    assert _vendor({"name": "Java"}) == "Oracle"


def test_id_runs_list_pairs_individually():
    assert _id_runs(["A-1", "A-2", "A-4", "A-5", "A-6"]) == "A-1, A-2 and A-4 to A-6"


def test_first_pass_medium_defects_are_not_cut_by_the_per_file_slots():
    from core.report import codefindings as CF
    W = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima", "mike", "november",
         "oscar", "papa", "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whiskey", "xray", "yankee", "zulu", "amber", "birch", "cedar", "dune"]

    def f(i, src=None):
        w = W[i]
        d = {"statement": f"{w}_load() never checks the {w}_result before {w}_commit runs on bad {w}_input", "severity": "medium",
             "category": "defect", "lines": [i, i], "review": "supported"}
        if src:
            d["source"] = src
        return d
    facts = {1: [f(i) for i in range(14)] + [f(i, "hunt") for i in range(20, 30)]}
    out = CF.select(None, [{"id": 1, "name": "A.py"}], facts, total=3)
    kept = [r["text"] for r in out]
    assert all(any(f"{W[i]}_load" in t for t in kept) for i in range(14))
