#!/usr/bin/env python3
"""Offline self-check of a saved program, with no source files and no API call.

Real captures have no original to score against, so this checks what must hold for any capture. Each check is one the
failures found on real batches violated:

  collapse      the re-stitched file is far shorter than the stored one (a file collapsed to one screen)
  duplicates    a class or function header appears twice in the re-stitched text (an overlap appended twice)
  rows          a screenshot's pixel rows do not match its text lines (editor guides or squiggles fused or split the rows,
                so the pixel check could not run and the model's spacing was left unchecked)
  unmeasured    most of a file's screenshots could not be matched to their text by the pixel check at all
  coverage      a large share of lines could not be checked against the pixels (guides, squiggles or a margin the check
                could not place), so their spacing is whatever the model wrote
  flags         a large share of lines are flagged "screenshots disagree" (spacing the pixels should have settled)

    CODESNAP_PROGRAMS=<folder holding a COPY of the program> python tests/quality/selfcheck.py --program NAME [--fast] [--only FILE]

--fast checks only the per-screenshot rows (a few minutes for a big program); without it every file is also re-stitched
(about ten minutes for twelve 1,000-line files). Exits 1 when any check fails, so it can gate a release.
Always point CODESNAP_PROGRAMS at a copy: the program database is opened normally.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

ROWS_LOW, ROWS_HIGH = 0.8, 1.25      # pixel rows / non-blank text lines for one screenshot
BAD_FRAMES = 0.15                    # share of a file's screenshots allowed to be off before the file fails
COLLAPSE = 0.6                       # re-stitched lines / stored lines below this is a collapse
FLAG_SHARE = 0.05                    # share of lines flagged
UNCHECKED_SHARE = 0.02               # share of lines the pixel check could not verify (clean captures sit at 0.1-1.1%)


def frame_rows(path, text):
    """(pixel rows, non-blank text lines) for one screenshot, or None when it cannot be read."""
    from core import colfix
    try:
        rows = colfix._rows(colfix._ink(path))
    except Exception:  # noqa: BLE001
        return None
    lines = sum(1 for l in text.splitlines() if l.strip() and "[CUT OFF]" not in l)
    return len(rows), lines


def check_file(store, art, fast):
    import restitch_harness as H
    from core.analysis import _has_dup_headers
    frames = H.frames_of(store, art)
    if not frames:
        return None
    from core import colfix
    problems, info = [], {}
    off, unmeasured, total = 0, 0, 0
    unchecked = body = 0
    for text, meta, path in frames:
        try:
            sx = ((meta or {}).get("spacing") or {}).get("calibration", {}).get("source_x")
            status = colfix.check(path, text, source_x=sx).get("status") or []
            nonblank = [st for line, st in zip(text.splitlines(), status) if line.strip()]
            body += len(nonblank)
            unchecked += sum(1 for st in nonblank if st == "unchecked")
        except Exception:  # noqa: BLE001
            pass
        got = frame_rows(path, text)
        if got is None:
            continue
        rows, lines = got
        total += 1
        if lines >= 8 and not (ROWS_LOW <= rows / lines <= ROWS_HIGH):
            off += 1
        if lines >= 8 and rows < 0.4 * lines:
            unmeasured += 1
    info["frames"] = len(frames)
    info["off_rows"] = f"{off}/{total}"
    info["unchecked"] = f"{unchecked / body:.1%}" if body else "n/a"
    if body and unchecked > UNCHECKED_SHARE * body:
        problems.append(f"coverage: {unchecked} of {body} lines could not be checked against the pixels")
    if total and off > BAD_FRAMES * total:
        problems.append(f"rows: {off} of {total} screenshots have a pixel row count that does not match their text")
    if total and unmeasured > 0.5 * total:
        problems.append(f"unmeasured: {unmeasured} of {total} screenshots could not be matched by the pixel check")
    if not fast:
        code, notes = H.restitch(frames)
        stored = (art.get("transcription") or "").splitlines()
        new = code.splitlines()
        info["lines"] = f"{len(stored)}->{len(new)}"
        if stored and len(new) < COLLAPSE * len(stored):
            problems.append(f"collapse: re-stitched {len(new)} lines against {len(stored)} stored")
        if _has_dup_headers(code):
            problems.append("duplicates: a class or function header appears twice in the re-stitched text")
        flagged = len(notes.get("flagged_lines") or [])
        info["flagged"] = flagged
        if new and flagged > FLAG_SHARE * len(new):
            problems.append(f"flags: {flagged} of {len(new)} lines flagged for review")
    return problems, info


def main(argv=None):
    from core.model import ProgramStore
    ap = argparse.ArgumentParser()
    ap.add_argument("--program", required=True)
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--only", help="substring of a file name")
    args = ap.parse_args(argv)
    failing = checked = 0
    with ProgramStore.open(args.program) as store:
        for art in store.artifacts():
            if args.only and args.only.lower() not in art["name"].lower():
                continue
            got = check_file(store, art, args.fast)
            if got is None:
                continue
            problems, info = got
            checked += 1
            failing += bool(problems)
            detail = " ".join(f"{k}={v}" for k, v in info.items())
            print(f"{'FAIL' if problems else 'ok  '} {art['name']:34} {detail}", flush=True)
            for p in problems:
                print(f"       - {p}", flush=True)
    print(f"\n{checked} files checked, {failing} failing")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
