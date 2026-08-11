"""Seeded-error fidelity eval for the Extractor (#2).

Twenty tiny Python files, each with ONE known planted defect (missing colon,
unbalanced paren, misspelled keyword, bad indent). We render each to a PNG,
run it through extract_structured(), and check whether the defect was
transcribed VERBATIM (faithful) or silently "fixed" (the failure we care about).

  python tests/fidelity_eval.py --gen        # (re)write the 20 sample files
  python tests/fidelity_eval.py --selftest   # validate probes, NO API
  python tests/fidelity_eval.py              # full eval, NEEDS API key
  python tests/fidelity_eval.py --keep       # also keep the rendered PNGs

Fidelity rate = faithful / 20. A high rate across repeated runs (not one lucky
pass) is the signal that #2 actually changed behavior.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # Screen Capture Tool/
sys.path.insert(0, str(ROOT / "src"))                  # core, team, ...
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/ -> render
SEED_DIR = ROOT / "demo_samples" / "seeded_errors"

# name, defect, lines, index of the defective line, its corrected form
def S(name, defect, lines, bad, fixed):
    return {"name": name, "defect": defect, "lines": lines, "bad": bad, "fixed": fixed}

SPECS = [
    # ---- missing colon (5) ----
    S("mc_def", "missing_colon", ["def area(radius)", "    return 3.14159 * radius * radius"], 0, "def area(radius):"),
    S("mc_if", "missing_colon", ["def sign(n):", "    if n > 0", "        return 1", "    return -1"], 1, "    if n > 0:"),
    S("mc_for", "missing_colon", ["def total(items):", "    s = 0", "    for it in items", "        s += it", "    return s"], 2, "    for it in items:"),
    S("mc_while", "missing_colon", ["def countdown(n):", "    while n > 0", "        print(n)", "        n -= 1"], 1, "    while n > 0:"),
    S("mc_class", "missing_colon", ["class Point", "    def __init__(self, x, y):", "        self.x = x", "        self.y = y"], 0, "class Point:"),
    # ---- unbalanced paren (5) ----
    S("up_max", "unbalanced_paren", ["def biggest(a, b, c):", "    return max(a, b, c"], 1, "    return max(a, b, c)"),
    S("up_print", "unbalanced_paren", ["def greet(name):", '    print("hello " + name'], 1, '    print("hello " + name)'),
    S("up_area", "unbalanced_paren", ["def area(w, h):", "    return (w * h"], 1, "    return (w * h)"),
    S("up_len", "unbalanced_paren", ["def nonempty(seq):", "    return len(seq) > 0)"], 1, "    return len(seq) > 0"),
    S("up_sorted", "unbalanced_paren", ["def combine(a, b):", "    return sorted((a + b)"], 1, "    return sorted((a + b))"),
    # ---- misspelled keyword (5) ----
    S("mk_return", "misspelled_keyword", ["def square(x):", "    retrun x * x"], 1, "    return x * x"),
    S("mk_import", "misspelled_keyword", ["improt math", "def circ(r):", "    return 2 * math.pi * r"], 0, "import math"),
    S("mk_class", "misspelled_keyword", ["clas Animal:", "    def speak(self):", '        return "..."'], 0, "class Animal:"),
    S("mk_while", "misspelled_keyword", ["def drain(stack):", "    whlie stack:", "        stack.pop()"], 1, "    while stack:"),
    S("mk_with", "misspelled_keyword", ["def read(path):", "    wiht open(path) as f:", "        return f.read()"], 1, "    with open(path) as f:"),
    # ---- bad indent (5) ----
    S("bi_under", "bad_indent", ["def f(x):", "    y = x + 1", "   return y"], 2, "    return y"),
    S("bi_over", "bad_indent", ["def g(n):", "    total = 0", "        total += n", "    return total"], 2, "    total += n"),
    S("bi_body", "bad_indent", ["def h():", "    for i in range(3):", "      print(i)"], 2, "        print(i)"),
    S("bi_class", "bad_indent", ["class Box:", "    def __init__(self, w):", "       self.w = w"], 2, "        self.w = w"),
    S("bi_mixed", "bad_indent", ["def compute(a, b):", "    s = a + b", "     return s"], 2, "    return s"),
]

def broken_line(spec):
    return spec["lines"][spec["bad"]]

def code_of(spec):
    return "\n".join(spec["lines"]) + "\n"

def gen_files():
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    for sp in SPECS:
        (SEED_DIR / f"{sp['name']}.py").write_text(code_of(sp))
    (SEED_DIR / "MANIFEST.json").write_text(json.dumps(
        [{"name": s["name"], "defect": s["defect"], "broken": broken_line(s), "fixed": s["fixed"]} for s in SPECS],
        indent=2))
    print(f"wrote {len(SPECS)} seeded files -> {SEED_DIR}")

def classify(raw, spec):
    """faithful | silently_fixed | line_missing.

    bad_indent files are matched EXACTLY (indentation IS the defect). For all
    other defect types we normalise leading whitespace, so a stray-space indent
    drift can't masquerade as a token failure (the token \u2014 colon, paren,
    keyword \u2014 is what we're scoring there).
    """
    exact = spec["defect"] == "bad_indent"
    norm = (lambda l: l.rstrip()) if exact else (lambda l: l.strip())
    lines = [norm(l) for l in raw.splitlines()]
    broke = norm(broken_line(spec))
    fixed = norm(spec["fixed"])
    if fixed in lines and broke not in lines:
        return "silently_fixed"
    if broke in lines:
        return "faithful"        # defect still present -> not a clean fix
    return "line_missing"

def flagged(corrections, spec):
    b = broken_line(spec).strip()
    for c in corrections or []:
        saw = str(c.get("saw", "")).strip()
        if saw and (saw in b or b in saw):
            return True
    return False

def selftest():
    """No API: probes must find the defect in the SOURCE itself (== broken)."""
    ok = 0
    for sp in SPECS:
        res = classify(code_of(sp), sp)
        if res == "faithful":
            ok += 1
        else:
            print(f"  PROBE BUG {sp['name']}: got {res}")
    print(f"selftest: {ok}/{len(SPECS)} probes correctly detect the planted defect in source")
    return ok == len(SPECS)

def run_eval(keep, label="", legacy=False, indent=False):
    import render
    from core import analysis
    analysis.load_env()
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set (add to .env or ~/.code_capture/.env).")
        return
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=5, timeout=120.0)

    if not (SEED_DIR / "MANIFEST.json").exists():
        gen_files()

    by_type = {}
    rows = []
    faithful = fixed = missing = flagged_fixes = 0
    tmp = Path(tempfile.mkdtemp())
    for i, sp in enumerate(SPECS, 1):
        png = (SEED_DIR / f"{sp['name']}.png") if keep else (tmp / f"{sp['name']}.png")
        render.render_code(code_of(sp), png, line_numbers=False)
        if legacy:
            raw = analysis.extract_legacy(client, png); corrections = []
        elif indent:
            r = analysis.extract_structured_indent(client, png); raw = r["raw"]; corrections = r["corrections"]
        else:
            r = analysis.extract_structured(client, png); raw = r["raw"]; corrections = r["corrections"]
        verdict = classify(raw, sp)
        was_flagged = flagged(corrections, sp)
        rows.append((sp["name"], sp["defect"], verdict, was_flagged))
        d = by_type.setdefault(sp["defect"], [0, 0])
        d[1] += 1
        if verdict == "faithful":
            faithful += 1; d[0] += 1
        elif verdict == "silently_fixed":
            fixed += 1
            if was_flagged: flagged_fixes += 1
        else:
            missing += 1
        print(f"  [{i:>2}/{len(SPECS)}] {sp['name']:<10} {sp['defect']:<18} -> {verdict}"
              + ("  (flagged)" if was_flagged else ""))

    n = len(SPECS)
    print("\n" + "=" * 52)
    print(f"{label}FIDELITY RATE: {faithful}/{n} = {faithful/n:.0%}   "
          f"(silently fixed {fixed}, line missing {missing})")
    for t, (o, tot) in sorted(by_type.items()):
        print(f"   {t:<18} {o}/{tot}")
    if fixed:
        print(f"   of {fixed} silent fixes, {flagged_fixes} were at least flagged in corrections_applied")
    print("=" * 52)
    return faithful

def run_many(keep, runs, legacy=False, indent=False):
    rates = []
    for k in range(1, runs + 1):
        tag = 'baseline' if legacy else ('#2b-indent' if indent else '#2')
        f = run_eval(keep and runs == 1, label=f"[{tag} run {k}/{runs}] ", legacy=legacy, indent=indent)
        if f is None:
            return
        rates.append(f)
    n = len(SPECS)
    if runs > 1:
        print("\n" + "#" * 52)
        pct = [r / n for r in rates]
        print(f"OVER {runs} RUNS  mean {sum(pct)/len(pct):.0%}   "
              f"best {max(pct):.0%}   worst {min(pct):.0%}   (n={n} files/run)")
        print(f"  per-run faithful counts: {rates}")
        print("#" * 52)

def dump_one(name, indent=False):
    import render, os
    from core import analysis
    analysis.load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set."); return
    import anthropic, tempfile
    spec = next((x for x in SPECS if x["name"] == name), None)
    if not spec:
        print(f"no sample named {name!r}. options: {[s['name'] for s in SPECS]}"); return
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    png = Path(tempfile.mktemp(suffix=".png"))
    render.render_code(code_of(spec), png, line_numbers=False)
    r = (analysis.extract_structured_indent if indent else analysis.extract_structured)(client, png)
    print(f"--- {name} ({spec['defect']}) ---")
    print("broken_line :", repr(broken_line(spec)))
    print("fixed_line  :", repr(spec["fixed"]))
    print("verdict     :", classify(r["raw"], spec))
    print("corrections :", r["corrections"])
    print("--- raw ---")
    for ln in r["raw"].splitlines():
        print(repr(ln))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep rendered PNGs next to the samples")
    ap.add_argument("--runs", type=int, default=1, help="repeat the whole set N times and average (guards against a lucky run)")
    ap.add_argument("--baseline", action="store_true", help="use the OLD pre-#2 text prompt (for before/after)")
    ap.add_argument("--indent", action="store_true", help="use the experimental indent-aware extractor (#2b)")
    ap.add_argument("--dump", metavar="NAME", help="render+extract one sample and print its raw output + verdict")
    a = ap.parse_args()
    if a.gen:
        gen_files(); return
    if a.selftest:
        gen_files(); sys.exit(0 if selftest() else 1)
    if a.dump:
        dump_one(a.dump, a.indent); return
    run_many(a.keep, a.runs, a.baseline, a.indent)

if __name__ == "__main__":
    main()
