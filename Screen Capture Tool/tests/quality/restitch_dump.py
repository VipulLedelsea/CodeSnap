#!/usr/bin/env python3
"""Re-stitch every file of a program COPY and write the text of each into a folder. Run it once with the old code and once with
the new, then diff the two folders to see only what the stitching change did.

    CODESNAP_PROGRAMS=<copy> python restitch_dump.py --program batch-test-10-09 --out <folder>
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--program", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--src", help="folder holding the src/ to test (default: this checkout)")
    args = ap.parse_args()
    sys.path.insert(0, str(Path(args.src) if args.src else HERE.parents[1] / "src"))
    import restitch_harness as H
    from core.model import ProgramStore
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with ProgramStore.open(args.program) as store:
        for art in store.artifacts():
            if not (art.get("transcription") or "").strip() or art["status"] == "captured":
                continue
            frames = H.frames_of(store, art)
            if frames:
                (out / art["name"]).write_text(H.restitch(frames)[0])
                print(art["name"], flush=True)


if __name__ == "__main__":
    main()
