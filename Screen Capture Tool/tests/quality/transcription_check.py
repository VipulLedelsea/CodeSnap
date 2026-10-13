#!/usr/bin/env python3
"""Line-level accuracy of a transcribed program against the original source files. Run it after every test program.

    python tests/quality/transcription_check.py --program 10-08-test --originals "<folder of the original files>"
    python tests/quality/transcription_check.py --transcriptions <folder of .txt files named like the originals> ...

Reads a copy of the program database (the live file is never opened), so it is safe on a program that is still running.
Standard library only. Exit code 1 when any file misses its target. Use --save <dir> to keep the result as JSON.

Per file:
  recovered       original lines found in the transcription, spacing ignored (ordered match)
  spacing_exact   of those, the share whose leading spaces also match the original
  precision       transcription lines that are real original lines
  extra / missing lines that exist only in the transcription / only in the original
  missing_blocks  runs of MIN_BLOCK or more original lines that are absent together (a lost screen, header or comment)
  dup_headers     COBOL paragraph names that appear more often than in the original (a stitching artifact)
  indent_off      lines found but indented differently (the spacing gap)
"""
import argparse
import collections
import difflib
import json
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

# Per file: at most about one line in a thousand wrong. For the whole program: 99.99%, at most one line in ten thousand.
TARGETS = {"recovered": 0.999, "extra_share": 0.001, "spacing_exact": 0.999, "dup_headers": 0, "missing_block_lines": 0}
PROGRAM_TARGET = 0.9999
MIN_BLOCK = 5
_HEADER = re.compile(r"^([A-Za-z0-9][A-Za-z0-9-]*)\s*\.\s*$")
_NOT_PARA = {"EXIT", "GOBACK", "CONTINUE", "STOP", "ELSE"}


def _headers(lines):
    names = []
    for line in lines:
        m = _HEADER.match(line.strip())
        indent = len(line) - len(line.lstrip())
        if m and not m.group(1).isdigit() and m.group(1).upper() not in _NOT_PARA and not m.group(1).upper().startswith("END-") \
                and ((7 <= indent <= 10 and line[6:7] == " ") or indent <= 3):
            names.append(m.group(1).upper())
    return names


def _dups(lines):
    return sum(n - 1 for n in collections.Counter(_headers(lines)).values() if n > 1)


def compare(original: str, transcription: str) -> dict:
    # blank lines are not compared: a trailing newline or a blank row between screens says nothing about the code
    o = [x for x in original.split("\n") if x.strip()]
    t = [x for x in transcription.split("\n") if x.strip()]
    ol, tl = [x.strip() for x in o], [x.strip() for x in t]
    blocks = difflib.SequenceMatcher(None, ol, tl, autojunk=False).get_matching_blocks()
    matched = sum(b.size for b in blocks)
    pairs = [(b.a + k, b.b + k) for b in blocks for k in range(b.size)]
    exact = sum(1 for i, j in pairs if o[i].rstrip() == t[j].rstrip())
    found = {i for i, _ in pairs}
    runs, start = [], None
    for i in range(len(o) + 1):
        gone = i < len(o) and i not in found and o[i].strip()
        if gone and start is None:
            start = i
        elif not gone and start is not None:
            if i - start >= MIN_BLOCK:
                runs.append({"original_line": start + 1, "lines": i - start, "first": o[start].strip()[:70]})
            start = None
    off = [{"original_line": i + 1, "original_indent": len(o[i]) - len(o[i].lstrip()), "got_indent": len(t[j]) - len(t[j].lstrip())}
           for i, j in pairs if o[i].strip() and o[i].rstrip() != t[j].rstrip()]
    n_o, n_t = len(o), len(t)
    return {"original_lines": n_o, "transcribed_lines": n_t, "recovered": matched / n_o if n_o else 1.0,
            "spacing_exact": exact / matched if matched else 1.0, "precision": matched / n_t if n_t else 1.0,
            "extra": n_t - matched, "extra_share": (n_t - matched) / n_o if n_o else 0.0, "missing": n_o - matched,
            "missing_blocks": runs, "missing_block_lines": sum(r["lines"] for r in runs),
            "dup_headers": max(_dups(t) - _dups(o), 0), "indent_off": len(off), "indent_samples": off[:5]}


def verdict(r: dict) -> list:
    """The targets this file misses, as readable strings; [] when it meets all of them."""
    out = []
    if r["recovered"] < TARGETS["recovered"]:
        out.append(f"recovered {r['recovered']:.1%} < {TARGETS['recovered']:.1%}")
    if r["extra_share"] > TARGETS["extra_share"]:
        out.append(f"extra lines {r['extra']} ({r['extra_share']:.1%}) > {TARGETS['extra_share']:.1%}")
    if r["spacing_exact"] < TARGETS["spacing_exact"]:
        out.append(f"spacing exact {r['spacing_exact']:.1%} < {TARGETS['spacing_exact']:.1%}")
    if r["dup_headers"] > TARGETS["dup_headers"]:
        out.append(f"{r['dup_headers']} duplicate paragraph header(s) the original does not have")
    if r["missing_block_lines"]:
        out.append(f"missing block(s): " + ", ".join(f"{b['lines']} lines at {b['original_line']}" for b in r["missing_blocks"]))
    return out


def load_program(slug: str) -> dict:
    """{artifact name: transcription} from a copy of the program database."""
    home = Path.home() / "CodeSnap" / "programs" / slug
    if not (home / "program.db").exists():
        sys.exit(f"No program database at {home}")
    with tempfile.TemporaryDirectory() as tmp:
        for suffix in ("", "-wal", "-shm"):
            if (home / f"program.db{suffix}").exists():
                shutil.copy(home / f"program.db{suffix}", Path(tmp) / f"program.db{suffix}")
        db = sqlite3.connect(Path(tmp) / "program.db")
        try:
            return {n: t or "" for n, t in db.execute("SELECT name, transcription FROM artifact WHERE is_current = 1")}
        finally:
            db.close()


def load_folder(folder: Path, skip=(".md", ".json")) -> dict:
    """Every regular file in the folder except hidden files and notes (README, answer keys)."""
    return {p.name: p.read_text(errors="replace") for p in sorted(Path(folder).iterdir())
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() not in skip}


def pair(originals: dict, transcribed: dict) -> list:
    """(name, original text, transcription or None). Names match exactly, then ignoring case and a numeric prefix."""
    key = lambda n: Path(re.sub(r"^\d+[_-]", "", n)).stem.lower()
    by_key = {key(n): n for n in transcribed}
    out = []
    for name, text in originals.items():
        got = name if name in transcribed else by_key.get(key(name))
        out.append((name, text, transcribed.get(got) if got else None))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--program", help="program slug under ~/CodeSnap/programs")
    src.add_argument("--transcriptions", help="folder of transcribed files named like the originals")
    ap.add_argument("--originals", required=True, help="folder of the original source files")
    ap.add_argument("--save", help="folder to write <label>.json into")
    ap.add_argument("--label", help="name for the saved result (default: the program or folder name)")
    args = ap.parse_args(argv)
    transcribed = load_program(args.program) if args.program else load_folder(Path(args.transcriptions))
    originals = load_folder(Path(args.originals))
    rows, failing = {}, 0
    print(f"{'file':22}{'recov':>8}{'spacing':>9}{'prec':>8}{'extra':>7}{'miss':>6}{'dupH':>6}  result")
    for name, text, got in pair(originals, transcribed):
        if got is None:
            rows[name] = {"missing_file": True}
            failing += 1
            print(f"{name:22}{'':>44}  FAIL: not transcribed")
            continue
        r = compare(text, got)
        r["misses"] = verdict(r)
        rows[name] = r
        failing += bool(r["misses"])
        print(f"{name:22}{r['recovered']:>8.1%}{r['spacing_exact']:>9.1%}{r['precision']:>8.1%}{r['extra']:>7}{r['missing']:>6}"
              f"{r['dup_headers']:>6}  {'ok' if not r['misses'] else 'FAIL: ' + '; '.join(r['misses'])}")
    done = [r for r in rows.values() if "recovered" in r]
    total = lambda k: sum(r[k] for r in done)
    summary = {"files": len(rows), "files_meeting_targets": len(rows) - failing,
               "recovered": sum(r["recovered"] * r["original_lines"] for r in done) / max(total("original_lines"), 1),
               "spacing_exact": sum(r["spacing_exact"] * (r["recovered"] * r["original_lines"]) for r in done)
               / max(sum(r["recovered"] * r["original_lines"] for r in done), 1),
               "precision": sum(r["precision"] * r["transcribed_lines"] for r in done) / max(total("transcribed_lines"), 1),
               "extra_lines": total("extra"), "missing_lines": total("missing"), "dup_headers": total("dup_headers"),
               "files_at_100_percent": sum(1 for r in done if r["recovered"] == 1.0 and r["extra"] == 0)}
    summary["wrong_lines"] = summary["missing_lines"] + summary["extra_lines"]
    total_lines = max(total("original_lines"), 1)
    summary["program_accuracy"] = 1 - summary["wrong_lines"] / total_lines
    summary["program_target_met"] = (summary["program_accuracy"] >= PROGRAM_TARGET and summary["recovered"] >= PROGRAM_TARGET
                                     and summary["spacing_exact"] >= PROGRAM_TARGET and summary["dup_headers"] == 0)
    print(f"\n{summary['files_meeting_targets']} of {summary['files']} files meet the per-file targets {TARGETS}")
    print(f"PROGRAM {PROGRAM_TARGET:.2%} target: {'MET' if summary['program_target_met'] else 'NOT MET'}  "
          f"(accuracy {summary['program_accuracy']:.4%}: {summary['missing_lines']} lines missing + {summary['extra_lines']} extra "
          f"of {total_lines}; recovered {summary['recovered']:.4%}; spacing exact {summary['spacing_exact']:.4%})")
    print("totals:", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in summary.items()})
    if args.save:
        label = args.label or args.program or Path(args.transcriptions).name
        out = Path(args.save) / f"{label}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"label": label, "checked": time.strftime("%Y-%m-%d %H:%M"), "targets": TARGETS,
                                   "summary": summary, "files": rows}, indent=2))
        print("saved", out)
    return 1 if failing or not summary["program_target_met"] else 0


if __name__ == "__main__":
    sys.exit(main())
