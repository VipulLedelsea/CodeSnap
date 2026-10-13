"""A file of 20,000 lines must not make any step quadratic or push a call over its limit."""
import time

from core import deepdive as DD
from core import exec_summary as ES
from core.limits import fit_text
from test_deepdive import art, store  # noqa: F401  (fixtures)

N = 20000
TEXT = "\n".join(f"       MOVE WS-A{i} TO WS-B{i}." if i % 7 else f"       COMPUTE WS-T{i} = WS-A{i} * 1.{i % 90:02d}." for i in range(1, N + 1))


def _facts(n):
    return [{"category": "calculation", "statement": f"Line {i} moves a value.", "lines": [i * 9, i * 9],
             "quote": f"MOVE WS-A{i * 9} TO WS-B{i * 9}", "basis": "observed", "severity": "low"} for i in range(1, n + 1)]


def test_checking_two_thousand_findings_in_a_20000_line_file_is_fast():
    t = time.time()
    kept, corrected, rejected, unverifiable = DD.check_facts([f for f in _facts(2000) if f["lines"][0] % 7], TEXT)
    gaps = DD.uncovered(TEXT, kept)
    assert time.time() - t < 30
    assert len(kept) > 1000 and isinstance(gaps, list)


def test_segments_and_batches_cover_a_20000_line_file_in_small_pieces():
    seg = DD.segments(N)
    assert len(seg) == 34 and seg[0][0] == 1 and seg[-1][1] == N and max(b - a + 1 for a, b in seg) <= 620
    facts = [{"lines": [i * 9, i * 9]} for i in range(1, 2001)]
    batches = DD.fact_batches(facts)
    assert sum(len(b) for b in batches) == 2000
    assert all(len(b) <= DD.REVIEW_BATCH and b[-1]["lines"][-1] - b[0]["lines"][0] <= 1200 for b in batches)


def test_a_check_call_shows_only_the_lines_around_its_findings():
    shown = DD.listing(TEXT, start=5000 - DD.SEGMENT_CONTEXT, end=5200 + DD.SEGMENT_CONTEXT).split("\n")
    assert len(shown) == 261 and len("\n".join(shown)) < 20000


def test_a_whole_file_sent_for_a_summary_is_cut_to_its_start_and_end():
    out = fit_text(TEXT)
    assert len(out) <= 150100 and "left out of the middle" in out and out.startswith("       MOVE WS-A1 ")


def test_the_summary_input_stays_valid_and_small_for_fifteen_large_files(store):  # noqa: F811
    import json
    from unittest import mock
    reviews = {}
    for k in range(15):
        a = dict(art(store, "AidPaymentController.cs"), id=1000 + k, name=f"FILE{k}.cbl")
        reviews[str(a["id"])] = {"name": a["name"], "purpose": "Pays.", "file_role": "business_logic", "run_mode": "batch",
                                 "facts": [{"id": i, "fact_id": f"F{i}", "category": "calculation", "severity": ["high", "low", "info"][i % 3],
                                            "statement": "x" * 150, "basis": "observed", "lines": [i, i]} for i in range(1, 2001)],
                                 **{r: [{"name": "n" * 20, "description": "d" * 60}] * 400 for r in DD.ROLLUPS}, "unknowns": []}
        reviews[str(a["id"])]["_art"] = a
    arts = [r.pop("_art") for r in reviews.values()]
    with mock.patch.object(DD, "current_reviews", return_value=reviews), mock.patch.object(store, "artifacts", return_value=arts), \
            mock.patch.object(DD, "current_concerns", return_value=[]), mock.patch.object(ES, "_lifecycle", return_value=[]):
        text = ES._payload(store)
    doc = json.loads(text)                      # never cut mid-way
    assert len(text) <= ES.MAX_INPUT_CHARS and len(doc["A_per_file_findings"]) == 15
    assert all(f["findings_total"] == 2000 and f["findings_shown"] > 0 for f in doc["A_per_file_findings"])


def test_a_window_that_fails_once_is_tried_again_but_an_unusable_answer_is_not():
    import pytest
    calls = {"n": 0}

    def flaky(x):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("busy")
        return x * 2
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(DD.time, "sleep", lambda s: None)
        assert DD.parallel(flaky, [1]) == [2] and calls["n"] == 2

    def cut(x):
        calls["n"] += 1
        raise ValueError("truncated")
    calls["n"] = 0
    with pytest.raises(ValueError):
        DD.parallel(cut, [1])
    assert calls["n"] == 1        # an unusable answer is not repeated
