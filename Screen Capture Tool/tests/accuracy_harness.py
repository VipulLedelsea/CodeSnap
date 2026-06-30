"""Accuracy harness for the Screen Capture Tool.

Two modes:

SYNTHETIC (default): render known source files to PNGs, extract, score.
  python tests/accuracy_harness.py                # needs API
  python tests/accuracy_harness.py --selftest     # no API (sanity check)
  python tests/accuracy_harness.py --line-numbers --classify

REAL (--real): run the FULL pipeline (multi-image stitch + classify) over real
  editor screenshots you captured, scored against the true source.
  python tests/accuracy_harness.py --real         # needs API

  Layout — one folder per sample under tests/real/ :
      tests/real/<name>/001.png 002.png ...   <- the screenshots (in order)
      tests/real/<name>/truth.py              <- the real source (any 1 non-png
                                                 file; its extension = language)

Metrics: char_sim (difflib), line_match (exact lines), compiles (validate),
         class_ok (is_code AND language matches the truth file's extension).
"""

import argparse
import difflib
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent

import render  # noqa: E402

SYNTH_SAMPLES = [
    {"file": "samples/sample.py", "language": "Python", "ext": "py"},
    {"file": "samples/sample.js", "language": "JavaScript", "ext": "js"},
    {"file": "samples/sample.c", "language": "C", "ext": "c"},
]

EXT_LANG = {
    "py": "Python", "js": "JavaScript", "ts": "TypeScript", "c": "C",
    "cpp": "C++", "cc": "C++", "cs": "C#", "java": "Java", "go": "Go",
    "rb": "Ruby", "rs": "Rust", "swift": "Swift", "kt": "Kotlin",
}


def score(gt: str, got: str):
    char_sim = difflib.SequenceMatcher(None, gt, got).ratio()
    g = [ln.rstrip() for ln in gt.splitlines()]
    o = [ln.rstrip() for ln in got.splitlines()]
    matches = sum(1 for a, b in zip(g, o) if a == b)
    return char_sim, matches / max(len(g), 1)


def compiles(code: str, ext: str) -> bool:
    from core import validate
    tmp = Path(tempfile.mktemp(suffix=f".{ext}"))
    tmp.write_text(code)
    try:
        res = validate.check_source(tmp)
        return bool(res["checked"] and res["ok"])
    finally:
        tmp.unlink(missing_ok=True)


def _print_table(rows):
    print(f"\n{'sample':22} {'char_sim':>9} {'line_match':>11} {'compiles':>9} {'class_ok':>9}")
    print("-" * 64)
    for name, cs, lm, comp, cls in rows:
        print(f"{name:22} {cs:9.3f} {lm:11.3f} {str(comp):>9} {str(cls):>9}")
    n = len(rows) or 1
    print("-" * 64)
    print(f"{'AVG':22} {sum(r[1] for r in rows)/n:9.3f} {sum(r[2] for r in rows)/n:11.3f} "
          f"{sum(1 for r in rows if r[3])}/{len(rows):<7} "
          f"{sum(1 for r in rows if r[4] is True)}/{sum(1 for r in rows if r[4] is not None) or '-'}")


def _make_client():
    import os
    from core.analysis import load_env
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set (add it to .env).", file=sys.stderr)
        return None
    try:
        import anthropic
    except ImportError:
        print("anthropic not installed. Run: pip install -r requirements.txt", file=sys.stderr)
        return None
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def run_real(client) -> int:
    from core.analysis import analyse_incremental
    real_dir = HERE / "real"
    sample_dirs = sorted(d for d in real_dir.iterdir() if d.is_dir()) if real_dir.exists() else []
    if not sample_dirs:
        print(f"No real samples found. Create folders under {real_dir}/ — see the docstring.", file=sys.stderr)
        return 1

    rows = []
    for d in sample_dirs:
        pngs = sorted(d.glob("*.png"))
        truths = [f for f in d.iterdir() if f.is_file() and f.suffix.lower() != ".png"]
        if not pngs or not truths:
            print(f"  skip {d.name}: need >=1 .png and exactly one truth file")
            continue
        truth = truths[0]
        ext = truth.suffix.lstrip(".").lower()
        gt = truth.read_text()
        print(f"[{d.name}] {len(pngs)} image(s) -> analysing...")
        result = analyse_incremental(client, pngs, cache_dir=d / ".cache")
        got = result.get("extracted_text", "")
        cs, lm = score(gt, got)
        comp = compiles(got, ext)
        exp_lang = EXT_LANG.get(ext, "").lower()
        class_ok = bool(result.get("is_code")) and exp_lang in (result.get("language") or "").lower()
        rows.append((d.name, cs, lm, comp, class_ok))
    _print_table(rows)
    return 0


def run_synthetic(client, selftest, line_numbers, classify) -> int:
    rows = []
    with tempfile.TemporaryDirectory() as td:
        for s in SYNTH_SAMPLES:
            gt = (HERE / s["file"]).read_text()
            png = render.render_code(gt, Path(td) / f"{Path(s['file']).stem}.png", line_numbers=line_numbers)
            if selftest:
                got, class_ok = gt, None
            else:
                from core.analysis import extract_one, synthesize_final
                got = extract_one(client, png)
                class_ok = None
                if classify:
                    meta = synthesize_final(client, got)
                    class_ok = bool(meta["is_code"]) and s["language"].lower() in (meta["language"] or "").lower()
            cs, lm = score(gt, got)
            rows.append((s["file"], cs, lm, compiles(got, s["ext"]), class_ok))
    _print_table(rows)
    return 0


def run_inbox(client) -> int:
    """Dead-simple: analyse whatever .png files are in tests/inbox/ as ONE
    document and print the result. Drop a same-stem source file (any non-png,
    non-md) in there too and it will also be scored."""
    from core.analysis import analyse_incremental
    inbox = HERE / "inbox"
    pngs = sorted(inbox.glob("*.png"))
    if not pngs:
        print(f"No screenshots in {inbox}/ — drop some .png files there and re-run.", file=sys.stderr)
        return 1

    print(f"Analysing {len(pngs)} screenshot(s) as one document...")
    result = analyse_incremental(client, pngs, cache_dir=inbox / ".cache")
    code = result.get("extracted_text", "")
    is_code = bool(result.get("is_code"))
    lang = result.get("language") or "-"
    ext = result.get("extension") or "txt"

    print(f"\nDetected: is_code={is_code}  language={lang}  ext=.{ext}")
    if is_code:
        print(f"Compiles:  {compiles(code, ext)}")

    truths = [f for f in inbox.iterdir()
              if f.is_file() and f.suffix.lower() not in (".png", ".md")]
    if truths:
        gt = truths[0].read_text()
        cs, lm = score(gt, code)
        print(f"Scored vs {truths[0].name}:  char_sim={cs:.3f}  line_match={lm:.3f}")

    label = "EXTRACTED CODE" if is_code else "EXTRACTED TEXT"
    print(f"\n----- {label} -----\n{code}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true", help="Use real screenshots from tests/real/.")
    ap.add_argument("--inbox", action="store_true", help="Analyse whatever .png files are in tests/inbox/.")
    ap.add_argument("--selftest", action="store_true", help="Synthetic only: no API, feed ground truth back.")
    ap.add_argument("--line-numbers", action="store_true", help="Synthetic only: render gutter line numbers.")
    ap.add_argument("--classify", action="store_true", help="Also score classification.")
    args = ap.parse_args()

    if args.inbox:
        client = _make_client()
        return 1 if client is None else run_inbox(client)

    if args.real:
        client = _make_client()
        return 1 if client is None else run_real(client)

    client = None if args.selftest else _make_client()
    if not args.selftest and client is None:
        return 1
    return run_synthetic(client, args.selftest, args.line_numbers, args.classify)


if __name__ == "__main__":
    raise SystemExit(main())
