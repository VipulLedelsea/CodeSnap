"""COBOL transcription fidelity (Phase 2 M2 2.6). Needs ANTHROPIC_API_KEY.

python tests/cobol_fidelity_eval.py [--runs N] [--keep]
"""
import argparse
import difflib
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from render import render_code
from core import analysis
from core.cobol.parser import parse
from core.cobol import detect_kind

SAMPLES = HERE / "samples" / "cobol"
RESULTS = HERE / "results"
CLEAN = ["AIDCALC.cbl", "AIDCALC_noseq.cbl", "AIDCALC_shifted.cbl", "AIDINQ.cbl", "AIDREC.cpy", "AIDMAP.bms",
         "AIDJOB.jcl"]


def _set(lines, idx, new):
    lines = list(lines)
    lines[idx] = new
    return lines


def seeds():
    calc = (SAMPLES / "AIDCALC.cbl").read_text().splitlines()
    inq = (SAMPLES / "AIDINQ.cbl").read_text().splitlines()

    def find(lines, needle):
        return next(i for i, l in enumerate(lines) if needle in l)

    specs = []

    def add(name, defect, base, idx, bad):
        specs.append({"name": name, "defect": defect, "base": base, "line": idx + 1,
                      "good": base[idx].rstrip(), "bad": bad.rstrip(), "lines": _set(base, idx, bad)})

    i = find(calc, "UNTIL END-OF-FILE"); add("kw_until", "misspelled keyword", calc, i, calc[i].replace("UNTIL", "UNTL"))
    i = find(calc, "GOBACK."); add("missing_period", "missing period", calc, i, calc[i].replace("GOBACK.", "GOBACK"))
    i = find(inq, "TO WS-COMMAREA"); add("ident_typo", "misspelled identifier", inq, i, inq[i].replace("WS-COMMAREA", "WS-COMAREA"))
    i = next(k for k, l in enumerate(calc) if l[7:].startswith("1000-READ-DISTRICT."))
    add("para_area_b", "paragraph name in Area B", calc, i, calc[i][:7] + "    " + calc[i][7:])
    i = find(calc, "ADD 1 TO WS-COUNT"); add("stmt_area_a", "statement in Area A", calc, i, calc[i][:7] + calc[i][7:].lstrip())
    i = find(calc, "BATCH GENERAL"); add("lost_indicator", "comment missing '*' in column 7", calc, i, calc[i][:6] + " " + calc[i][7:])
    i = find(inq, "PIC X(6)."); add("pic_paren", "unbalanced PIC parenthesis", inq, i, inq[i].replace("PIC X(6).", "PIC X(6."))
    i = find(calc, "000900"); add("seq_number", "out-of-order sequence number", calc, i, "000990" + calc[i][6:])
    i = find(inq, "LINK PROGRAM"); add("end_exec", "misspelled END-EXEC", inq, i + 2, inq[i + 2].replace("END-EXEC", "END-EXCE"))
    return specs


def transcribe(client, path):
    raw = analysis.extract_structured(client, path)["raw"]
    return analysis.merge_frames([raw])[0]


def layout(line, kind="cobol"):
    if kind in ("bms", "jcl"):
        return ("label" if line[:1].strip() else "blank", line[71] if len(line) > 71 else "")
    if len(line) > 7 and all(c.isdigit() or c == " " for c in line[:6]):
        rest = line[7:]
        return ("fixed", line[6], len(rest) - len(rest.lstrip()))
    return ("lead", len(line) - len(line.lstrip()), line[6] if len(line) > 6 else "")


def tokens(line):
    return " ".join(line.split())


def column_accuracy(truth, got, kind="cobol"):
    got_lines = [l.rstrip() for l in got.splitlines()]
    pool = {}
    for idx, l in enumerate(got_lines):
        pool.setdefault(tokens(l), []).append(idx)
    ok = total = 0
    for t in truth.splitlines():
        if not t.strip():
            continue
        total += 1
        cands = pool.get(tokens(t))
        if cands and layout(got_lines[cands.pop(0)], kind) == layout(t.rstrip(), kind):
            ok += 1
    return ok / total if total else 1.0


def line_exact(truth, got):
    t = [l.rstrip() for l in truth.splitlines() if l.strip()]
    g = [l.rstrip() for l in got.splitlines() if l.strip()]
    sm = difflib.SequenceMatcher(None, t, g, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks()) / len(t) if t else 1.0


def char_accuracy(truth, got):
    return difflib.SequenceMatcher(None, truth.rstrip("\n"), got.rstrip("\n"), autojunk=False).ratio()


def structure_scores(name, truth, got):
    a, b = parse(truth, name), parse(got, name)
    if a is None:
        return None
    ta = {(r["kind"], r["source"], r["target"]) for r in a["relations"]} | {("E", e["kind"], e["name"]) for e in a["entities"]}
    tb = {(r["kind"], r["source"], r["target"]) for r in (b or {"relations": []})["relations"]} | \
         {("E", e["kind"], e["name"]) for e in (b or {"entities": []})["entities"]}
    hit = len(ta & tb)
    return {"recall": hit / len(ta) if ta else 1.0, "precision": hit / len(tb) if tb else 1.0,
            "missed": sorted(map(str, ta - tb))[:10], "extra": sorted(map(str, tb - ta))[:10]}


def classify(spec, got):
    seen = {(layout(l.rstrip()), tokens(l)) for l in got.splitlines()}
    key = lambda l: (layout(l), tokens(l))
    if key(spec["bad"]) in seen:
        return "preserved"
    if key(spec["good"]) in seen:
        return "corrected"
    return "other"


def run_once(client, workdir, keep):
    jobs = []
    for name in CLEAN:
        text = (SAMPLES / name).read_text()
        jobs.append(("clean", name, text, None))
    for spec in seeds():
        jobs.append(("seed", spec["name"], "\n".join(spec["lines"]) + "\n", spec))

    def work(job):
        kind, name, text, spec = job
        png = render_code(text, Path(workdir) / f"{name}.png")
        began = time.monotonic()
        try:
            got = transcribe(client, png)
            err = None
        except Exception as exc:
            got, err = "", f"{type(exc).__name__}: {exc}"
        return kind, name, text, spec, got, err, time.monotonic() - began

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(work, jobs))

    clean, seeded = [], []
    for kind, name, text, spec, got, err, secs in results:
        if keep:
            (Path(workdir) / f"{name}.got.txt").write_text(got)
        if kind == "clean":
            row = {"file": name, "char": round(char_accuracy(text, got), 4), "lines": round(line_exact(text, got), 4),
                   "columns": round(column_accuracy(text, got, detect_kind(text)), 4), "secs": round(secs, 1), "error": err}
            st = structure_scores(name, text, got)
            if st:
                row["structure_recall"] = round(st["recall"], 4)
                row["structure_precision"] = round(st["precision"], 4)
                row["structure_missed"] = st["missed"]
            clean.append(row)
        else:
            seeded.append({"seed": name, "defect": spec["defect"], "line": spec["line"],
                           "outcome": classify(spec, got) if not err else "error",
                           "column_ok": round(column_accuracy(text, got), 4), "error": err})
    return clean, seeded


def summarize(runs):
    clean = [r for c, _ in runs for r in c if not r["error"]]
    seeded = [s for _, s in runs for s in s]
    avg = lambda key, rows: round(sum(r[key] for r in rows) / len(rows), 4) if rows else None
    struct = [r for r in clean if "structure_recall" in r]
    preserved = sum(1 for s in seeded if s["outcome"] == "preserved")
    return {
        "char_accuracy": avg("char", clean), "line_exact": avg("lines", clean), "column_accuracy": avg("columns", clean),
        "structure_recall": avg("structure_recall", struct), "structure_precision": avg("structure_precision", struct),
        "seeded_preserved": f"{preserved}/{len(seeded)}",
        "seeded_rate": round(preserved / len(seeded), 4) if seeded else None,
        "bar": {"char_accuracy": 0.98, "column_accuracy": 0.95, "seeded_rate": 0.85},
    }


def to_markdown(summary, runs, model):
    s = summary
    ok = lambda v, bar: "PASS" if v is not None and v >= bar else "FAIL"
    out = [f"# COBOL fidelity — {datetime.now():%Y-%m-%d %H:%M}", "", f"Model: `{model}` · runs: {len(runs)}", "",
           "| Metric | Result | Bar | |", "|---|---|---|---|",
           f"| Character accuracy | {s['char_accuracy']} | 0.98 | {ok(s['char_accuracy'], 0.98)} |",
           f"| Column accuracy (indent + col 7 + tokens) | {s['column_accuracy']} | 0.95 | {ok(s['column_accuracy'], 0.95)} |",
           f"| Seeded errors preserved | {s['seeded_preserved']} ({s['seeded_rate']}) | 0.85 | {ok(s['seeded_rate'], 0.85)} |",
           f"| Exact lines incl. spacing inside lines | {s['line_exact']} | — | |",
           f"| Structure recall / precision (parser on transcription) | {s['structure_recall']} / {s['structure_precision']} | — | |",
           f"| API cost (est., list prices) | ${s.get('usage', {}).get('cost', 0):.3f} for {s.get('usage', {}).get('calls', 0)} calls, "
           f"{s.get('usage', {}).get('input_tokens', 0):,} in / {s.get('usage', {}).get('output_tokens', 0):,} out tokens | — | |",
           "", "## Clean samples", "", "| File | Char | Lines | Columns | Structure R/P |", "|---|---|---|---|---|"]
    for clean, _ in runs:
        for r in clean:
            sr = f"{r.get('structure_recall', '—')} / {r.get('structure_precision', '—')}"
            out.append(f"| {r['file']} | {r['char']} | {r['lines']} | {r['columns']} | {sr} |" + (f" error: {r['error']}" if r["error"] else ""))
    out += ["", "## Seeded errors", "", "| Seed | Defect | Outcome |", "|---|---|---|"]
    for _, seeded in runs:
        for x in seeded:
            out.append(f"| {x['seed']} | {x['defect']} | {x['outcome']} |")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    os.chdir(HERE.parent)
    analysis.load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1
    import anthropic
    from core.usage import UsageTracker, summarize as summarize_usage
    tracker = UsageTracker()
    client = tracker.wrap(anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5, timeout=120.0))
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    workdir = RESULTS / f"cobol_{stamp}" if args.keep else Path(tempfile.mkdtemp())
    workdir.mkdir(parents=True, exist_ok=True)
    runs = [run_once(client, workdir, args.keep) for _ in range(args.runs)]
    summary = summarize(runs)
    usage = summarize_usage(tracker.take(everything=True))
    summary["usage"] = usage
    (RESULTS / f"cobol_fidelity_{stamp}.json").write_text(json.dumps({"summary": summary, "runs": runs}, indent=2))
    md = to_markdown(summary, runs, analysis.EXTRACT_MODEL)
    (RESULTS / f"cobol_fidelity_{stamp}.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
