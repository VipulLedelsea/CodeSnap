"""M11 bars on the deterministic eval suite (tests/evals). Numbers are written up by tests/evals/run_evals.py."""
import pytest

pytest.importorskip("tree_sitter")


@pytest.fixture(scope="module")
def results():
    from evals.run_evals import run
    return run(scale=False)


def test_structure_bars(results):
    dev, held = results["structure_dev"], results["structure_heldout"]
    assert dev["entities"]["recall"] >= 0.95 and dev["relations"]["recall"] >= 0.9 and dev["relations"]["precision"] >= 0.85
    assert held["entities"]["recall"] >= 0.9 and held["relations"]["recall"] >= 0.8 and held["relations"]["precision"] >= 0.8


def test_security_rule_bars(results):
    f = results["findings"]
    assert f["cases"] >= 40 and f["detection_rate"] >= 0.95 and f["safe_variant_fp_rate"] <= 0.05


def test_diagram_bars(results):
    for d in results["diagrams"]:
        assert not d["invalid"] and d["coverage"] >= 0.99 and d["identical_rerun"] and d["order_independent"], d


def test_verdict_bars(results):
    v = results["verdict"]
    assert all(x["stable_across_orders"] for x in v["stability"])
    assert all(x["pass"] for x in v["scenarios"] + v["monotonic"]), [x for x in v["scenarios"] + v["monotonic"] if not x["pass"]]
    e = v["explainability"]
    assert e["deductions_with_rule_and_reason"] == e["score_deductions"] and e["findings_with_source_and_evidence"] == e["findings"]


def test_robustness_bars(results):
    assert results["partial"]["complete_flagged"] == 0 and results["partial"]["detection_rate"] >= 0.6
    assert results["fuzz"]["crashes"] == 0 and results["fuzz"]["slowest_s"] < 5


def test_api_fidelity_harness_selftest(tmp_path):
    import legacy_fidelity_eval as lf
    js = lf.jobs()
    assert len(js) > 100 and any(j["kind"] == "seed" for j in js)
    rows = [lf.score(j, j["text"], None, 0) for j in js[:30]]
    s = lf.summarize(rows)
    assert s["char_accuracy"] == 1.0 and s["errors"] == 0
    long_text = "\n".join(f"line {i}" for i in range(100))
    fr = lf.frames(long_text)
    assert len(fr) == 3 and fr[1].splitlines()[0] == "line 32"
    est = lf.estimate(js[:3], tmp_path)
    assert est["calls"] >= 3 and est["est_cost"] > 0
