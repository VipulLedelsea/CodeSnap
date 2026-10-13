#!/usr/bin/env python3
"""How long does stitching take as a file grows? Builds a synthetic COBOL-like file, cuts it into overlapping 45-line screens
(35 new lines each, like a real capture) and times merge_verified. No API, no images.

    python tests/quality/scale_bench.py 1000 2000 4000 [--profile]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def make_file(lines):
    out = ["       IDENTIFICATION DIVISION.", "       PROGRAM-ID. BENCH.", "       PROCEDURE DIVISION."]
    n = 0
    while len(out) < lines:
        n += 1
        out += [f"       {n:04d}-CHECK-{n % 97:02d}.", f"      * CHG-{1990 + n % 30}-{n:03d}: route {n % 17}.",
                f'           IF REQ-RECEIPT(1:2) = "{n % 90:02d}"', f"               IF WS-AMOUNT > {10000 + n % 977}",
                '                   MOVE "HOLD" TO WS-RESULT', "               END-IF", "               IF WS-AMOUNT < ZERO",
                '                   MOVE "REVERSE" TO WS-RESULT', "               END-IF", "           END-IF."]
    return out[:lines]


def screens(lines, height=45, step=35):
    return ["\n".join(lines[i:i + height]) for i in range(0, max(1, len(lines) - height + step), step)]


def main():
    from core.analysis import merge_verified
    sizes = [int(a) for a in sys.argv[1:] if a.isdigit()] or [1000, 2000, 4000]
    for size in sizes:
        lines = make_file(size)
        parts = screens(lines)
        began = time.time()
        if "--profile" in sys.argv:
            import cProfile
            import pstats
            pr = cProfile.Profile()
            pr.enable()
            code, _, notes, _ = merge_verified(parts, [{}] * len(parts))
            pr.disable()
            pstats.Stats(pr).strip_dirs().sort_stats("tottime").print_stats(14)
        else:
            code, _, notes, _ = merge_verified(parts, [{}] * len(parts))
        took = time.time() - began
        got = [l for l in code.split("\n") if l.strip()]
        want = [l for l in lines if l.strip()]
        print(f"{size:6} lines {len(parts):4} screens  {took:7.1f}s  exact={got == want}  lines out {len(got)}", flush=True)


if __name__ == "__main__":
    main()
