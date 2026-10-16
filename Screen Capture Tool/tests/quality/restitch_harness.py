#!/usr/bin/env python3
"""Re-stitch every file of a saved program from its stored per-screenshot reads, with no API call, and score the result
against the original files. This is the free way to measure and improve the stitcher: the reads are fixed, so any
difference comes from the stitching code.

    CODESNAP_PROGRAMS=<folder holding a COPY of the program> python tests/quality/restitch_harness.py \
        --program 10-08-test --originals "<folder of originals>" [--only 04_MUNRECON] [--save out.json]

Always point CODESNAP_PROGRAMS at a copy: the program database is opened normally.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def frames_of(store, artifact):
    """[(raw text, sidecar meta, image path)] of the artifact's screenshots, from the saved reads."""
    from core.analysis import _normalize_extract
    out = []
    for frame in store.artifact_evidence(artifact["id"]):
        cached = store.text_cache_dir / (frame["sha256"] + ".md")
        if not cached.exists():
            return None
        raw = cached.read_text()
        text = _normalize_extract(raw)["raw"] if '"raw_transcription"' in raw else raw
        sidecar = cached.with_suffix(".verify.json")
        meta = json.loads(sidecar.read_text()) if sidecar.exists() and text == raw else {}
        out.append((text, meta, store.evidence(frame["id"])["abs_path"]))
    return out


def restitch(frames, sessions=None):
    from core.analysis import clean_source, measured_frame, merge_verified, source_mode
    parts = [t for t, _, _ in frames]
    mode = source_mode(parts)
    metas = []
    for i, (text, meta, path) in enumerate(frames):
        cleaned, checked, _ = measured_frame(None, path, clean_source(text, mode))
        checked.update({k: meta[k] for k in ("numbers", "numbers_seen", "numbers_rejected") if k in meta})
        parts[i] = cleaned
        metas.append(checked)
    from core import passes
    code, _, notes, statuses = passes.stitch(parts, metas, sessions)
    from core.verify import summarize
    flagged = {f["line"] for f in summarize(code, statuses, notes, read_code=code).get("flags") or []}
    notes["flagged_lines"] = flagged
    return code, notes


def _flag_coverage(original, code, flagged):
    """How many of the stitched lines that differ from the original were flagged for review, and how many are silent."""
    import difflib
    o = [x.strip() for x in original.split("\n") if x.strip()]
    rows = [(i + 1, x) for i, x in enumerate(code.split("\n")) if x.strip()]
    sm = difflib.SequenceMatcher(None, o, [x.strip() for _, x in rows], autojunk=False)
    wrong = [rows[j][0] for tag, _, _, j1, j2 in sm.get_opcodes() if tag in ("replace", "insert") for j in range(j1, j2)]
    return {"wrong_got_lines": wrong, "wrong_flagged": [n for n in wrong if n in flagged],
            "wrong_silent": [n for n in wrong if n not in flagged]}


def main(argv=None):
    import transcription_check as T
    from core.model import ProgramStore
    ap = argparse.ArgumentParser()
    ap.add_argument("--program", required=True)
    ap.add_argument("--originals", required=True)
    ap.add_argument("--only", help="substring of the file name")
    ap.add_argument("--save")
    ap.add_argument("--dump", help="folder to write each re-stitched file into, to diff against the originals")
    args = ap.parse_args(argv)
    originals = T.load_folder(Path(args.originals))
    results, failing = {}, 0
    with ProgramStore.open(args.program) as store:
        arts = {a["name"]: a for a in store.artifacts() if (a.get("transcription") or "").strip()}
        key = lambda n: T.Path(T.re.sub(r"^\d+[_-]", "", n)).stem.lower()
        by_key = {key(n): n for n in arts}
        for name, text in originals.items():
            if args.only and args.only.lower() not in name.lower():
                continue
            stored = by_key.get(key(name))
            if stored is None:
                print(f"{name}: not in the program")
                continue
            frames = frames_of(store, arts[stored])
            if not frames:
                print(f"{name}: no saved reads")
                continue
            code, notes = restitch(frames, [f['session_id'] for f in store.artifact_evidence(arts[stored]['id'])])
            if args.dump:
                Path(args.dump).mkdir(parents=True, exist_ok=True)
                (Path(args.dump) / name).write_text(code)
            r = T.compare(text, code)
            r["misses"] = T.verdict(r)
            r.update(_flag_coverage(text, code, notes.get("flagged_lines") or set()))
            results[name] = r
            failing += bool(r["misses"])
            print(f"{name:22} frames {len(frames):3} recov {r['recovered']:.2%} spacing {r['spacing_exact']:.2%} "
                  f"extra {r['extra']:4} missing {r['missing']:3} dupH {r['dup_headers']}  wrong {len(r['wrong_got_lines'])} "
                  f"(silent {len(r['wrong_silent'])})  "
                  f"{'ok' if not r['misses'] else 'FAIL'}", flush=True)
    done = list(results.values())
    if done:
        n = sum(r["original_lines"] for r in done)
        print(f"\nTOTAL recovered {sum(r['recovered'] * r['original_lines'] for r in done) / n:.4%}  "
              f"extra {sum(r['extra'] for r in done)}  missing {sum(r['missing'] for r in done)}  "
              f"files failing {failing}/{len(done)}  wrong lines {sum(len(r['wrong_got_lines']) for r in done)}  "
              f"silent (not flagged) {sum(len(r['wrong_silent']) for r in done)}")
    if args.save:
        Path(args.save).write_text(json.dumps(results, indent=2))
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
