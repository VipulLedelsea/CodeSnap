"""Transcription fidelity across legacy languages (M11). Needs ANTHROPIC_API_KEY unless --dry-run / --selftest.

python tests/legacy_fidelity_eval.py --dry-run          # estimate cost, no API
python tests/legacy_fidelity_eval.py --selftest         # score truth vs truth, no API
python tests/legacy_fidelity_eval.py --budget 3         # run, stop at $3
python tests/legacy_fidelity_eval.py --only rpgle,nsp --runs 2
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

from render import render_code  # noqa: E402

RESULTS = HERE / "results"
FRAME_LINES, OVERLAP = 36, 4
FILES = sorted([p for d in ("langpacks", "legacy", "cobol") for p in (HERE / "samples" / d).iterdir()
                if p.is_file() and p.suffix not in (".png", ".md") and "broken" not in p.name and p.name != "make_samples.py"]
               + list((HERE / "evals" / "heldout").iterdir()))
SEEDS = [("End Sub", "End Sbu"), ("ENDSR", "ENDRS"), ("END-IF", "END-FI"), ("END-DEFINE", "END-DEFNE"), ("END;", "EDN;"),
         ("RETURN", "RETRUN"), ("function", "fucntion"), ("SELECT", "SELCET"), ("PROCEDURE", "PROCEDRUE"), ("END-EXEC", "END-EXCE")]
IMG_MAX = 1568


def frames(text):
    lines = text.splitlines()
    if len(lines) <= FRAME_LINES:
        return [text]
    out, i = [], 0
    while i < len(lines):
        out.append("\n".join(lines[i:i + FRAME_LINES]))
        if i + FRAME_LINES >= len(lines):
            break
        i += FRAME_LINES - OVERLAP
    return out


def seeded(text):
    for good, bad in SEEDS:
        idx = next((k for k, l in enumerate(text.splitlines()) if good in l), None)
        if idx is not None:
            lines = text.splitlines()
            orig = lines[idx]
            lines[idx] = orig.replace(good, bad, 1)
            return "\n".join(lines) + "\n", {"line": idx + 1, "good": orig.rstrip(), "bad": lines[idx].rstrip()}
    return None, None


def jobs():
    out = []
    for p in FILES:
        text = p.read_text(errors="replace")
        out.append({"file": p.name, "kind": "clean", "text": text})
        s, spec = seeded(text)
        if s:
            out.append({"file": p.name, "kind": "seed", "text": s, "seed": spec})
    return out


def _img_tokens(png):
    from PIL import Image
    with Image.open(png) as im:
        w, h = im.size
    scale = min(1.0, IMG_MAX / max(w, h))
    return int((w * scale) * (h * scale) / 750)


def estimate(js, workdir):
    from core import analysis
    from core.usage import cost
    sys_tokens = len(analysis.EXTRACT_JSON_SYSTEM_PROMPT) // 4
    tin = tout = n = 0
    for j in js:
        for k, fr in enumerate(frames(j["text"])):
            png = render_code(fr, Path(workdir) / f"{j['file']}.{j['kind']}.{k}.png")
            tin += _img_tokens(png) + sys_tokens + 30
            tout += int(len(fr) / 3.2) + 250
            n += 1
    return {"calls": n, "input_tokens": tin, "output_tokens": tout, "est_cost": cost(analysis.EXTRACT_MODEL, tin, tout)}


def char_acc(a, b):
    return difflib.SequenceMatcher(None, a.rstrip("\n"), b.rstrip("\n"), autojunk=False).ratio()


def line_exact(a, b):
    t = [l.rstrip() for l in a.splitlines() if l.strip()]
    g = [l.rstrip() for l in b.splitlines() if l.strip()]
    sm = difflib.SequenceMatcher(None, t, g, autojunk=False)
    return sum(x.size for x in sm.get_matching_blocks()) / len(t) if t else 1.0


def column_acc(a, b):
    got = {}
    for l in b.splitlines():
        got.setdefault(" ".join(l.split()), []).append(l.rstrip())
    ok = total = 0
    for l in a.splitlines():
        if not l.strip():
            continue
        total += 1
        c = got.get(" ".join(l.split()))
        if c and c.pop(0) == l.rstrip():
            ok += 1
    return ok / total if total else 1.0


def structure_pr(name, truth, got):
    from evals.structure import _pr, _sets
    from core.model.ingest import _parse_deterministic
    art = {"name": name, "language": "", "artifact_type": "code"}
    a = (_parse_deterministic(truth, art) or {}).get("structure")
    b = (_parse_deterministic(got, art) or {}).get("structure") or {"entities": [], "relations": []}
    if not a:
        return None
    ea, ra = _sets(a)
    eb, rb = _sets(b)
    p = _pr(ea | ra, eb | rb)
    return {"recall": p["recall"], "precision": p["precision"]}


def transcribe(client, text, workdir, tag):
    from core import analysis
    raws = []
    for k, fr in enumerate(frames(text)):
        png = render_code(fr, Path(workdir) / f"{tag}.{k}.png")
        raws.append(analysis.extract_structured(client, png)["raw"])
    return analysis.merge_frames(raws)[0]


def score(j, got, err, secs):
    from core.langpacks.formats import detect_format
    fixed = bool(detect_format(j["text"], "", j["file"].rsplit(".", 1)[-1])) or j["file"].lower().endswith((".cbl", ".cpy", ".jcl", ".bms"))
    row = {"file": j["file"], "kind": j["kind"], "secs": round(secs, 1), "error": err}
    if j["kind"] == "clean":
        row.update({"char": round(char_acc(j["text"], got), 4), "lines": round(line_exact(j["text"], got), 4),
                    "columns": round(column_acc(j["text"], got), 4), "fixed_format": fixed})
        st = structure_pr(j["file"], j["text"], got)
        if st:
            row.update({"structure_recall": round(st["recall"], 4), "structure_precision": round(st["precision"], 4)})
    else:
        seen = {l.rstrip() for l in got.splitlines()}
        row["outcome"] = "preserved" if j["seed"]["bad"] in seen else ("corrected" if j["seed"]["good"] in seen else "other")
    return row


def summarize(rows):
    clean = [r for r in rows if r["kind"] == "clean" and not r["error"]]
    seeds = [r for r in rows if r["kind"] == "seed" and not r["error"]]
    avg = lambda k, rs: round(sum(r[k] for r in rs) / len(rs), 4) if rs else None
    fixed = [r for r in clean if r["fixed_format"]]
    st = [r for r in clean if "structure_recall" in r]
    return {"files": len(clean), "errors": sum(1 for r in rows if r["error"]), "char_accuracy": avg("char", clean),
            "line_exact": avg("lines", clean), "column_accuracy_fixed_formats": avg("columns", fixed),
            "structure_recall": avg("structure_recall", st), "structure_precision": avg("structure_precision", st),
            "seeded_preserved": f"{sum(r['outcome'] == 'preserved' for r in seeds)}/{len(seeds)}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--budget", type=float, default=5.0, help="stop when this many USD have been spent (default 5)")
    ap.add_argument("--only", default="", help="comma-separated extensions, e.g. rpgle,nsp,frm")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    os.chdir(HERE.parent)
    js = jobs()
    if args.only:
        exts = {e.strip().lower().lstrip(".") for e in args.only.split(",")}
        js = [j for j in js if j["file"].rsplit(".", 1)[-1].lower() in exts]
    workdir = Path(tempfile.mkdtemp())
    est = estimate(js, workdir)
    print(f"{len(js)} jobs ({sum(j['kind'] == 'seed' for j in js)} seeded) · {est['calls']} API calls · "
          f"~{est['input_tokens']:,} in / ~{est['output_tokens']:,} out tokens · est. ${est['est_cost'] * args.runs:.2f} for {args.runs} run(s)")
    if args.dry_run:
        return 0
    if args.selftest:
        rows = [score(j, j["text"], None, 0) for j in js]
        print(json.dumps(summarize(rows), indent=1))
        return 0
    from core import analysis
    analysis.load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 1
    import anthropic
    from core.usage import Budget, BudgetExceeded, UsageTracker, summarize as usage_summary
    tracker = UsageTracker()
    tracker.budget = Budget(args.budget, on_warn=lambda t, l: print(f"  ! spent ${t:.2f} of ${l:.2f} budget", file=sys.stderr))
    client = tracker.wrap(anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5, timeout=120.0))

    def work(j):
        began = time.monotonic()
        try:
            got, err = transcribe(client, j["text"], workdir, f"{j['file']}.{j['kind']}"), None
        except BudgetExceeded as exc:
            got, err = "", f"budget: {exc}"
        except Exception as exc:
            got, err = "", f"{type(exc).__name__}: {exc}"
        return score(j, got, err, time.monotonic() - began)

    rows = []
    for _ in range(args.runs):
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            rows += list(pool.map(work, js))
    summary = summarize(rows)
    summary["usage"] = usage_summary(tracker.take(everything=True))
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (RESULTS / f"legacy_fidelity_{stamp}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    md = [f"# Legacy transcription fidelity — {datetime.now():%Y-%m-%d %H:%M}", "", f"Model `{analysis.EXTRACT_MODEL}` · {args.runs} run(s)", "",
          "| Metric | Result |", "|---|---|"] + [f"| {k} | {v} |" for k, v in summary.items() if k != "usage"] + \
         [f"| API cost | ${summary['usage']['cost']:.2f} ({summary['usage']['calls']} calls) |", "",
          "| File | Char | Lines | Columns | Structure R/P | Error |", "|---|---|---|---|---|---|"]
    for r in rows:
        if r["kind"] == "clean":
            md.append(f"| {r['file']} | {r.get('char', '')} | {r.get('lines', '')} | {r.get('columns', '')} | "
                      f"{r.get('structure_recall', '—')} / {r.get('structure_precision', '—')} | {r['error'] or ''} |")
    md += ["", "| Seeded file | Outcome |", "|---|---|"] + [f"| {r['file']} | {r.get('outcome', r['error'])} |" for r in rows if r["kind"] == "seed"]
    (RESULTS / f"legacy_fidelity_{stamp}.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
