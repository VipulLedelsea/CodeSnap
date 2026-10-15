#!/usr/bin/env python3
"""Score a second capture of a set of files against the originals, alone and combined with the first capture.

    CODESNAP_PROGRAMS=<folder holding COPIES of both programs> \
    python tests/quality/second_pass_eval.py --first batch-test-10-09 --second pass2-modern \
        --originals <folder of the original files> [--only auth,workflows] [--save out.json]

For every original file that both programs hold (matched by name without a number prefix or extension, case ignored) it
re-stitches each program's saved reads, combines the two (core/passes.combine) and prints how many lines are wrong in the
first capture, in the second, and in the combination, plus the two numbers that say whether the comparison can be trusted:
the share of confirmed lines (read alike by both) that are wrong, and the share of the combined text's wrong lines that sit
among the flagged conflicts. Run it on COPIES of the programs: the program database is opened normally.
"""
import argparse
import difflib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

ind = lambda l: len(l) - len(l.lstrip(" "))
key = lambda n: re.sub(r"^\d+[_-]", "", Path(n).stem).lower()


def wrong_lines(original, text):
    """(count of wrong lines, set of 0-based indexes in `text`): extra or different lines, lines with other indentation, and
    original lines that are missing."""
    o, t = [l.rstrip() for l in original.split("\n")], [l.rstrip() for l in text.split("\n")]
    sm = difflib.SequenceMatcher(None, [l.strip() for l in o], [l.strip() for l in t], autojunk=False)
    bad, missing = set(), 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            bad.update(b for a, b in zip(range(i1, i2), range(j1, j2)) if o[a].strip() and ind(o[a]) != ind(t[b]))
        else:
            bad.update(b for b in range(j1, j2) if t[b].strip())
            have, want = sum(1 for l in t[j1:j2] if l.strip()), sum(1 for l in o[i1:i2] if l.strip())
            missing += max(0, want - have)
    return len(bad) + missing, bad


def stitched(store, artifact):
    """(text, statuses) of one artifact, re-stitched from its saved screenshot reads."""
    import restitch_harness as H
    from core import passes
    from core.analysis import clean_source, measured_frame, source_mode
    frames = H.frames_of(store, artifact)
    if not frames:
        return None
    parts = [t for t, _, _ in frames]
    mode, metas = source_mode(parts), []
    for i, (text, meta, path) in enumerate(frames):
        cleaned, checked, _ = measured_frame(None, path, clean_source(text, mode))
        checked.update({k: meta[k] for k in ("numbers", "numbers_seen", "numbers_rejected") if k in meta})
        parts[i] = cleaned
        metas.append(checked)
    sessions = [f["session_id"] for f in store.artifact_evidence(artifact["id"])]
    code, _, notes, statuses = passes.stitch(parts, metas, sessions)
    return code, statuses, len(frames)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--first", required=True)
    ap.add_argument("--second", required=True)
    ap.add_argument("--originals", required=True)
    ap.add_argument("--only", help="comma-separated parts of file names")
    ap.add_argument("--save")
    args = ap.parse_args(argv)
    from core import analysis  # noqa: F401  (import order: core.analysis before core.model)
    from core import passes
    from core.model import ProgramStore
    originals = {key(p.name): p for p in Path(args.originals).iterdir() if p.is_file()}
    wanted = [w.strip().lower() for w in args.only.split(",")] if args.only else []
    results, rows = {}, []
    with ProgramStore.open(args.first) as one, ProgramStore.open(args.second) as two:
        a = {key(x["name"]): x for x in one.artifacts() if (x.get("transcription") or "").strip()}
        b = {key(x["name"]): x for x in two.artifacts() if (x.get("transcription") or "").strip()}
        for k in sorted(set(a) & set(b) & set(originals)):
            if wanted and not any(w in k for w in wanted):
                continue
            first, second = stitched(one, a[k]), stitched(two, b[k])
            if not first or not second:
                print(f"{k}: a program has no saved reads for this file")
                continue
            truth = originals[k].read_text()
            text, info = passes.combine(first[0], second[0], first[1], second[1])
            ea, _ = wrong_lines(truth, first[0])
            eb, _ = wrong_lines(truth, second[0])
            ec, bad = wrong_lines(truth, text)
            conf_wrong = sum(1 for n in info["confirmed"] if n - 1 in bad)
            flagged_wrong = sum(1 for n in info["conflicts"] if n - 1 in bad)
            results[k] = {"first": ea, "second": eb, "combined": ec, "confirmed": len(info["confirmed"]),
                          "confirmed_wrong": conf_wrong, "conflicts": len(info["conflicts"]),
                          "wrong_in_conflicts": flagged_wrong, "wrong_unflagged": len(bad) - flagged_wrong,
                          "frames": [first[2], second[2]], "lines": len(truth.split("\n"))}
            r = results[k]
            print(f"{k:24} lines {r['lines']:5}  wrong: first {ea:4} second {eb:4} combined {ec:4}   confirmed {r['confirmed']:5} "
                  f"(wrong {conf_wrong})  conflicts {r['conflicts']:4} (hold {flagged_wrong} wrong)  unflagged wrong {r['wrong_unflagged']}",
                  flush=True)
    if results:
        s = lambda f: sum(r[f] for r in results.values())
        lines = s("lines")
        print(f"\nTOTAL of {lines} lines: wrong first {s('first')} ({1 - s('first') / lines:.2%} right), second {s('second')} "
              f"({1 - s('second') / lines:.2%}), combined {s('combined')} ({1 - s('combined') / lines:.2%})")
        print(f"confirmed lines {s('confirmed')}, wrong among them {s('confirmed_wrong')}; flagged conflicts {s('conflicts')}, "
              f"holding {s('wrong_in_conflicts')} of the combined text's wrong lines; wrong and unflagged {s('wrong_unflagged')}")
    if args.save:
        Path(args.save).write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
