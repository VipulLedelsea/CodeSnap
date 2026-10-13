#!/usr/bin/env python3
"""Re-stitch every structured file of a program COPY with the current code and compare with the transcription it stored,
when there are no original files to score against. Lists each file whose text changed and how (lines added, removed, changed).

    CODESNAP_PROGRAMS=<folder with a copy> python tests/quality/restitch_compare.py --program batch-test-10-09 [--only name]
"""
import argparse
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv=None):
    import restitch_harness as H
    from core.model import ProgramStore
    ap = argparse.ArgumentParser()
    ap.add_argument("--program", required=True)
    ap.add_argument("--only")
    ap.add_argument("--show", type=int, default=6, help="differences to print per file")
    args = ap.parse_args(argv)
    total_changed = 0
    with ProgramStore.open(args.program) as store:
        for art in store.artifacts():
            if args.only and args.only.lower() not in art["name"].lower():
                continue
            text = art.get("transcription") or ""
            if not text.strip() or art["status"] == "captured":
                continue
            frames = H.frames_of(store, art)
            if not frames:
                print(f"{art['name']}: no saved reads")
                continue
            code, notes = H.restitch(frames)
            a = [l for l in text.split("\n") if l.strip()]
            b = [l for l in code.split("\n") if l.strip()]
            sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
            ops = [o for o in sm.get_opcodes() if o[0] != "equal"]
            changed = sum(max(i2 - i1, j2 - j1) for _, i1, i2, j1, j2 in ops)
            total_changed += changed
            print(f"{art['name']:34} frames {len(frames):3} lines {len(a):5} -> {len(b):5}  changed {changed:3}", flush=True)
            for tag, i1, i2, j1, j2 in ops[:args.show]:
                print(f"    {tag} stored {i1 + 1}-{i2} new {j1 + 1}-{j2}")
                for x in a[i1:min(i2, i1 + 2)]:
                    print("      -", x[:100])
                for x in b[j1:min(j2, j1 + 2)]:
                    print("      +", x[:100])
    print(f"\nlines changed in total: {total_changed}")


if __name__ == "__main__":
    main()
