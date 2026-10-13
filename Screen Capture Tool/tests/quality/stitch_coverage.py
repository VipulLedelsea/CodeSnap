#!/usr/bin/env python3
"""Check a stitched file against the screenshots it was built from, when there is no original to score against.
missing: distinct lines some screenshot shows that the stitched text lacks (content lost).
extra: how many more times a line occurs in the stitched text than on any single screenshot, summed over lines
       that are not repeated in the source by nature (a block copied twice shows up here).

    CODESNAP_PROGRAMS=<copy> python stitch_coverage.py --program batch-test-10-09 --text <folder from restitch_dump.py> [--only name]
"""
import argparse
import collections
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))


def collapse(line):
    return " ".join(line.replace("[CUT OFF]", "").split())


def main():
    import restitch_harness as H
    from core.model import ProgramStore
    ap = argparse.ArgumentParser()
    ap.add_argument("--program", required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--only")
    args = ap.parse_args()
    tot_missing = tot_extra = 0
    with ProgramStore.open(args.program) as store:
        for art in store.artifacts():
            f = Path(args.text) / art["name"]
            if not f.exists() or (args.only and args.only.lower() not in art["name"].lower()):
                continue
            frames = H.frames_of(store, art)
            if not frames:
                continue
            result = collections.Counter(collapse(l) for l in f.read_text().split("\n") if collapse(l))
            per_frame = collections.Counter()
            seen = set()
            for text, _, _ in frames:
                c = collections.Counter(collapse(l) for l in text.split("\n") if collapse(l))
                seen |= set(c)
                for line, n in c.items():
                    per_frame[line] = max(per_frame[line], n)
            missing = [l for l in seen if l not in result and len(l) >= 6]
            extra = sum(max(0, n - per_frame.get(l, 1)) for l, n in result.items())
            tot_missing += len(missing)
            tot_extra += extra
            print(f"{art['name']:34} lines {sum(result.values()):5}  missing {len(missing):4}  extra {extra:4}")
    print(f"\\ntotal missing {tot_missing}  extra {tot_extra}")


if __name__ == "__main__":
    main()
