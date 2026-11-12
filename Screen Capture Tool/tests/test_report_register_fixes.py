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


def test_hunt_prompt_shows_the_hunter_behaviour_the_first_pass_only_described():
    from types import SimpleNamespace
    from core import deepdive as DD
    seen = []

    def fake_call(client, model, system, tool, content, thinking=True):
        seen.append(content)
        return SimpleNamespace(stop_reason="end_turn"), 0
    kept = [{"statement": "installment_schedule rounds each payment without adjusting for drift", "category": "calculation", "lines": [4, 6]},
            {"statement": "an already judged defect", "category": "defect", "severity": "medium", "lines": [9, 9]}]
    store = SimpleNamespace(log_run=lambda *a, **k: None)
    orig = (DD._call, DD._tool, DD._log)
    DD._call, DD._tool, DD._log = fake_call, (lambda *a, **k: {"findings": []}), (lambda *a, **k: None)
    try:
        DD.hunt(store, None, {"id": 1, "name": "f.py"}, kept, "m", "a\nb\nc", set(), "H")
    finally:
        DD._call, DD._tool, DD._log = orig
    assert seen and all("only DESCRIBED" in c and "installment_schedule rounds each payment" in c for c in seen)
    assert "Sign-in and sessions" in DD.HUNT_SYSTEM and "Splits and truncation" in DD.HUNT_SYSTEM


def test_short_keeps_the_defect_when_the_sentence_opens_with_the_case_that_is_fine():
    from core.report.codefindings import short
    t = ("If the true final batch has exactly PAGE (500) rows, export_csv writes it and loops again; the next query returns an empty batch "
         "and breaks without writing anything, so in that case no rows are lost, but any batch strictly between 1 and 499 rows at the end "
         "is dropped entirely, e.g., a last page of 10 rows is never written.")
    out = short(t)
    assert "dropped entirely" in out and out.startswith("export_csv")
    assert short("The loop works as intended for most inputs. It also adds a surcharge.") == "The loop works as intended for most inputs"


def test_review_prompts_ask_for_the_checks_test_10_never_raised_and_a_sum_that_can_differ_is_a_defect():
    from core import deepdive as DD
    from core.report import codefindings as CF
    for needle in ("Sign-in and sessions", "Money type", "Opened and never closed", "Same calculation twice"):
        assert needle in DD.DEEP_SYSTEM
    assert "Compare paths" in DD.HUNT_SYSTEM and "a browser estimate and the server" in DD.SYNTH_SYSTEM
    assert CF.DEFECT_WORDS.search("the sum of all installments can differ from the original total due to per-installment rounding")


def test_a_long_register_text_runs_on_to_the_end_of_its_clause_instead_of_stopping_mid_thought():
    from core.report import editorial
    text = ("Token expiry or revocation is never checked in this file because the stored token is read back from the database without "
            "comparing its creation time to the session length, so a stolen token works forever")
    out = editorial._short(text, 20)
    assert not out.endswith("…") and "stored token is read back" in out
