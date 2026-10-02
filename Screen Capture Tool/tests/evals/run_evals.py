"""Deterministic eval suite (0 API tokens). python tests/evals/run_evals.py [--scale]"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "src"))
sys.path.insert(0, str(HERE.parent))

RESULTS = HERE.parent / "results"


def partial_eval():
    from test_robustness import ALL, _truncations
    from core.model.completeness import check
    fp = [p.name for p in ALL if check(p.read_text(errors="replace"), p.name)["partial"]]
    cases = list(_truncations())
    hits = sum(1 for n, t in cases if check(t, n)["partial"])
    return {"complete_files": len(ALL), "complete_flagged": len(fp), "truncated_cases": len(cases), "detected": hits,
            "detection_rate": round(hits / len(cases), 3)}


def fuzz_eval():
    from test_robustness import ALL, _variants
    from core.model.ingest import _parse_deterministic
    from core.security.rules import scan_text
    runs = crashes = 0
    worst = 0.0
    for p in ALL:
        for label, v in _variants(p.read_text(errors="replace")):
            runs += 1
            t = time.monotonic()
            try:
                _parse_deterministic(v, {"name": p.name, "language": "", "artifact_type": "code"})
                scan_text(v, p.name)
            except Exception:
                crashes += 1
            worst = max(worst, time.monotonic() - t)
    return {"inputs": runs, "crashes": crashes, "slowest_s": round(worst, 2)}


def scale_eval():
    import random
    import tempfile
    from test_robustness import ALL
    from core.assess import run_assessment
    from core.diagrams import all_diagrams, vsdx
    from core.model import ProgramStore, ingest_capture
    from core.report import package
    from test_linker import NoApi
    store = ProgramStore.create("Scale", root=Path(tempfile.mkdtemp()))
    t0 = time.monotonic()
    n = 0
    for k in range(4):
        for p in ALL:
            text = p.read_text(errors="replace")
            if k and random.Random(n).random() < 0.2:
                text = "\n".join(text.splitlines()[: max(3, len(text.splitlines()) // 2)])
            rep = {"is_code": True, "code": text, "extension": p.suffix[1:].lower(), "language": "", "errors": "None"}
            if p.suffix == ".screen":
                rep["artifact_type"] = "ui_screen"
            ingest_capture(store, NoApi(), [], rep, name=p.name if k == 0 else f"{p.stem}_{k}{p.suffix}")
            n += 1
    t1 = time.monotonic()
    a = run_assessment(store)
    t2 = time.monotonic()
    ds = all_diagrams(store)
    vsdx(ds)
    t3 = time.monotonic()
    package(store, rescan=False)
    t4 = time.monotonic()
    out = {"files": n, "entities": len(store.entities()), "relations": len(store.relations()), "findings": len(store.findings()),
           "diagrams": len(ds), "verdict": a["verdict"]["label"], "partial_flagged": len(a["health"]["partial"]),
           "seconds": {"ingest": round(t1 - t0, 1), "scan+assessment": round(t2 - t1, 1), "diagrams+visio": round(t3 - t2, 1),
                       "report package": round(t4 - t3, 1), "total": round(t4 - t0, 1)}}
    store.close()
    return out


def run(scale=False):
    from evals import findings, pipeline, structure
    t = time.monotonic()
    out = {"generated": datetime.now().isoformat(timespec="seconds"), "structure_dev": structure.run("gold_structure.json"),
           "structure_heldout": structure.run("gold_heldout.json"), "findings": findings.run(),
           "diagrams": pipeline.diagrams_eval(), "verdict": pipeline.verdict_eval(), "partial": partial_eval(),
           "fuzz": fuzz_eval()}
    if scale:
        out["scale"] = scale_eval()
    out["seconds"] = round(time.monotonic() - t, 1)
    return out


def _pct(x):
    return "—" if x is None else f"{x * 100:.1f}%"


def to_markdown(r):
    sd, sh, f, p = r["structure_dev"], r["structure_heldout"], r["findings"], r["partial"]
    L = [f"# CodeSnap deterministic eval — {r['generated'][:16].replace('T', ' ')}", "",
         "All numbers are from local, deterministic code (0 API tokens). Transcription accuracy is measured separately "
         "by the API evals (`tests/legacy_fidelity_eval.py`, `tests/cobol_fidelity_eval.py`).", "",
         "## Structure extraction vs hand-labelled gold", "",
         "| Set | Files | Entity recall | Entity precision | Relation recall | Relation precision |", "|---|---|---|---|---|---|",
         f"| Dev (used while building) | {len(sd['files'])} | {_pct(sd['entities']['recall'])} | {_pct(sd['entities']['precision'])} | "
         f"{_pct(sd['relations']['recall'])} | {_pct(sd['relations']['precision'])} |",
         f"| **Held-out** (labelled before running) | {len(sh['files'])} | {_pct(sh['entities']['recall'])} | "
         f"{_pct(sh['entities']['precision'])} | {_pct(sh['relations']['recall'])} | {_pct(sh['relations']['precision'])} |", "",
         "| Language family (dev) | Entity R / P | Relation R / P |", "|---|---|---|"]
    for fam, v in sd["by_family"].items():
        L.append(f"| {fam} | {_pct(v['entities']['recall'])} / {_pct(v['entities']['precision'])} | "
                 f"{_pct(v['relations']['recall'])} / {_pct(v['relations']['precision'])} |")
    L += ["", "Known misses (held-out): " + "; ".join(f"{x['file']}: {', '.join(x['missed'])}" for x in sh["files"] if x["missed"]) or "none", "",
          "## Security rules — seeded vulnerabilities", "",
          f"{f['cases']} vulnerable lines inserted into real sample files across 14 languages, each paired with a safe rewrite.", "",
          f"- Detection rate: **{_pct(f['detection_rate'])}** · false positives on the safe rewrites: **{_pct(f['safe_variant_fp_rate'])}**",
          "- By rule: " + ", ".join(f"{k} {v['detected']}" for k, v in f["by_rule"].items()),
          f"- Misses: {', '.join(f['misses']) or 'none'} · FPs: {', '.join(f['false_positives']) or 'none'}", "",
          "## Diagrams", "", "| Program | Diagrams | Coverage | Valid SVG/draw.io/Visio/PNG | Identical re-run | Ingest-order independent |",
          "|---|---|---|---|---|---|"]
    for d in r["diagrams"]:
        L.append(f"| {d['program']} | {d['diagrams']} | {_pct(d['coverage'])} | {'yes' if not d['invalid'] else 'NO: ' + '; '.join(d['invalid'])} | "
                 f"{'yes' if d['identical_rerun'] else 'NO'} | {'yes' if d['order_independent'] else 'NO'} |")
    v = r["verdict"]
    L += ["", "## Verdict", "", "No expert-labelled verdicts exist yet, so this checks stability, rule consistency and explainability.", "",
          "| Program | Verdict | Same under 3 shuffled ingest orders |", "|---|---|---|"]
    L += [f"| {x['program']} | {x['verdict']} | {'yes' if x['stable_across_orders'] else 'NO'} |" for x in v["stability"]]
    L += ["", "| Scenario | Result | |", "|---|---|---|"]
    L += [f"| {x['scenario']} | {x['verdict']} | {'PASS' if x['pass'] else 'FAIL'} |" for x in v["scenarios"]]
    L += [f"| {x['check']} | {x['before']} → {x['after']} | {'PASS' if x['pass'] else 'FAIL'} |" for x in v["monotonic"]]
    e = v["explainability"]
    L += ["", f"Explainability: {e['deductions_with_rule_and_reason']}/{e['score_deductions']} score deductions cite a rule and reason; "
              f"{e['findings_with_source_and_evidence']}/{e['findings']} findings cite a source and evidence; verdict reasons: "
              f"{'yes' if e['verdict_has_reasons'] else 'no'}.", "",
          "## Robustness", "",
          f"- Partial-capture detection: {p['detected']}/{p['truncated_cases']} truncated files flagged (**{_pct(p['detection_rate'])}**); "
          f"{p['complete_flagged']}/{p['complete_files']} complete files wrongly flagged.",
          f"- Hostile inputs (truncated, garbage, 50k-char lines, open quotes, NUL/CRLF, empty): {r['fuzz']['inputs']} runs, "
          f"**{r['fuzz']['crashes']} crashes**, slowest {r['fuzz']['slowest_s']} s."]
    if "scale" in r:
        s = r["scale"]
        L += [f"- Large program: {s['files']} files → {s['entities']:,} entities, {s['relations']:,} relations, {s['findings']} findings, "
              f"{s['diagrams']} diagrams, verdict {s['verdict']}, {s['partial_flagged']} partial files flagged; "
              + ", ".join(f"{k} {t}s" for k, t in s["seconds"].items()) + "."]
    L += ["", f"_Eval run time: {r['seconds']} s._", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", action="store_true", help="also run the large-program timing (≈1 min)")
    args = ap.parse_args()
    r = run(scale=args.scale)
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    (RESULTS / f"EVAL_{stamp}.json").write_text(json.dumps(r, indent=1, default=str))
    md = to_markdown(r)
    (RESULTS / f"EVAL_{stamp}.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
