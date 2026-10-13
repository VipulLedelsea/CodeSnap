import re
from types import SimpleNamespace

from core import deepdive as DD
from test_deepdive import art, store  # noqa: F401  (fixtures)


def test_short_files_are_read_whole_and_long_ones_in_even_windows():
    assert DD.segments(700) == [(1, 700)] and DD.segments(750) == [(1, 750)]
    seg = DD.segments(2500)
    assert seg[0][0] == 1 and seg[-1][1] == 2500 and len(seg) == 5
    assert all(b + 1 == a2 for (_, b), (a2, _) in zip(seg, seg[1:]))


def test_windowed_listing_keeps_the_real_line_numbers():
    text = "\n".join(f"L{i}" for i in range(1, 201))
    out = DD.listing(text, start=150, end=152).split("\n")
    assert [x.split("|")[0].strip() for x in out] == ["150", "151", "152"]


def test_merge_joins_windows_and_drops_repeats():
    a = {"purpose": "Pays.", "file_role": "not shown", "run_mode": "batch", "facts": [{"x": 1}], "interfaces": [{"name": "T"}]}
    b = {"purpose": "Later.", "file_role": "business_logic", "run_mode": "interactive", "facts": [{"x": 2}], "interfaces": [{"name": "T"}, {"name": "U"}]}
    m = DD._merge_reads([a, b])
    assert m["purpose"] == "Pays." and m["file_role"] == "business_logic" and m["run_mode"] == "batch"
    assert len(m["facts"]) == 2 and [i["name"] for i in m["interfaces"]] == ["T", "U"]


class Windows:
    """Answers each window with one fact on its first line; the first whole-size window is cut off to force a split."""

    def __init__(self, text_lines, cut_over=10**9):
        self.n, self.cut_over, self.calls, self.messages = text_lines, cut_over, [], self

    def create(self, **kw):
        prompt = kw["messages"][0]["content"]
        self.calls.append((kw["tools"][0]["name"], prompt))
        if kw["tools"][0]["name"] == "record_review":
            ids = [int(i) for i in re.findall(r"^(\d+)\. \[", prompt, re.M)]
            return self._msg("record_review", {"verdicts": [{"id": i, "verdict": "supported"} for i in ids]})
        m = re.search(r"covers lines (\d+)-(\d+) of", prompt)
        a, b = (int(m.group(1)), int(m.group(2))) if m else (1, self.n)
        if b - a + 1 > self.cut_over:
            return SimpleNamespace(content=[], usage=SimpleNamespace(input_tokens=1, output_tokens=1), stop_reason="max_tokens")
        facts = [{"category": "calculation", "statement": f"Line {a} adds one.", "lines": [a, a], "quote": f"MOVE {a} TO X", "basis": "observed"},
                 {"category": "calculation", "statement": "Outside the window.", "lines": [b + 5, b + 5], "quote": f"MOVE {b + 5} TO X", "basis": "observed"}]
        return self._msg("record_analysis", {"purpose": "Moves.", "facts": facts, "interfaces": [{"name": f"T{a}"}]})

    @staticmethod
    def _msg(name, data):
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=name, input=data)],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=5), stop_reason="tool_use")


def _long(store, n):  # noqa: F811
    a = dict(art(store, "AidPaymentController.cs"))
    a["transcription"] = "\n".join(f"MOVE {i} TO X" for i in range(1, n + 1))
    return a


def test_a_long_file_is_read_in_windows_and_each_fact_is_kept_once(store):  # noqa: F811
    a = _long(store, 2500)
    c = Windows(2500)
    r = DD.analyse_file(store, c, a, model="m", review=False)
    reads = [p for t, p in c.calls if t == "record_analysis"]
    assert len(reads) >= 5 and all("covers lines" in p for p in reads[:5])
    firsts = [f["lines"][0] for f in r["facts"] if f["statement"].startswith("Line")]
    assert len(firsts) == len(set(firsts)) >= 5
    starts = {x for x, _ in DD.segments(2500)}
    assert {f["lines"][0] for f in r["facts"]} <= starts     # facts cited outside their window are left to the window they belong to
    assert len(r["interfaces"]) >= 5


def test_a_window_that_is_cut_off_is_read_again_as_two_halves(store):  # noqa: F811
    a = _long(store, 2500)
    c = Windows(2500, cut_over=300)
    r = DD.analyse_file(store, c, a, model="m", review=False)
    sizes = [int(m.group(2)) - int(m.group(1)) + 1 for m in (re.search(r"covers lines (\d+)-(\d+)", p) for t, p in c.calls if t == "record_analysis") if m]
    assert max(sizes) > 300 and min(sizes) <= 300
    assert any(f["statement"].startswith("Line") for f in r["facts"])


def test_the_independent_check_goes_in_batches(store):  # noqa: F811
    a = _long(store, 2500)
    c = Windows(2500)
    DD.analyse_file(store, c, a, model="m", review_model="m", review=True)
    reviews = [p for t, p in c.calls if t == "record_review"]
    assert len(reviews) >= 1 and all(len(re.findall(r"^\d+\. \[", p, re.M)) <= DD.REVIEW_BATCH for p in reviews)


class FailsOnce(Windows):
    """Fails every call for one window until told to stop, so the file cannot finish but the other windows are paid for."""
    broken = True

    def create(self, **kw):
        prompt = kw["messages"][0]["content"]
        if self.broken and kw["tools"][0]["name"] == "record_analysis" and "covers lines 1501-2000" in prompt:
            raise RuntimeError("service busy")
        return super().create(**kw)


def test_windows_already_paid_for_are_not_read_again_after_a_failure(store, monkeypatch):  # noqa: F811
    import pytest
    monkeypatch.setattr(DD.time, "sleep", lambda s: None)
    a = _long(store, 2500)
    c = FailsOnce(2500)
    with pytest.raises(RuntimeError):
        DD.analyse_file(store, c, a, model="m", review=False)
    reads = lambda: sum(1 for t, p in c.calls if t == "record_analysis" and "NO findings yet" not in p)
    first = reads()
    c.broken = False
    c.calls.clear()
    r = DD.analyse_file(store, c, a, model="m", review=False)
    assert first == 4 and reads() == 1           # only the window that failed is read again
    assert len([f for f in r["facts"] if f["statement"].startswith("Line")]) >= 5
    assert not (store.get_meta(f"deepdive_windows_{a['id']}") or {}).get("reads")     # cleared once the file is done
