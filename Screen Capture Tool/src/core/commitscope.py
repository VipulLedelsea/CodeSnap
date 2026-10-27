"""Commit scope check: a routine that is called with parameters (PL/I PROC(args), COBOL PROCEDURE DIVISION USING) and
runs COMMIT or ROLLBACK itself. The caller's own uncommitted work is committed or undone with it, and the caller can no
longer roll back after the call returns. Read from the source text; no model call."""
import re

_PLI_PROC = re.compile(r"^\s*(\w+):\s*PROC(?:EDURE)?\s*\(([^)]*)\)", re.I)
_COBOL_USING = re.compile(r"PROCEDURE\s+DIVISION\s+USING\b", re.I)
_END = re.compile(r"EXEC\s+SQL\s+(COMMIT|ROLLBACK)\b(?!\s+TO\b)", re.I)


def conflicts(store):
    out = []
    for a in store.artifacts():
        text = a.get("transcription") or ""
        lines = text.splitlines()
        called = None
        for n, line in enumerate(lines, 1):
            m = _PLI_PROC.match(line)
            if m and m.group(2).strip():
                called = (n, m.group(1), "takes " + " and ".join(x.strip() for x in m.group(2).split(",") if x.strip()) + " from its caller")
                break
            if _COBOL_USING.search(line):
                called = (n, a["name"].split(".")[0], "is called with parameters (PROCEDURE DIVISION USING)")
                break
        if not called:
            continue
        ends = [(n, _END.search(l).group(1).upper()) for n, l in enumerate(lines, 1) if _END.search(l) and not re.match(r"^\s*(/\*|\*)", l)]
        if not ends:
            continue
        n, what = ends[0]
        name = called[1]
        out.append({
            "title": f"{name} {what.lower()}s the caller's work",
            "statement": (f"{name} is a called routine ({name} {called[2]}) and runs EXEC SQL {what} at line {n}"
                          f"{f' (and {len(ends) - 1} more place(s))' if len(ends) > 1 else ''}. Work the caller has not yet committed is "
                          f"{'committed' if what == 'COMMIT' else 'undone'} with it, so the caller cannot decide the outcome of its own unit of work."),
            "facts": [], "basis": "observed", "files": [a["name"]],
            "cites": [f"{a['name']} lines {called[0]}–{called[0]}", f"{a['name']} lines {n}–{n}"], "source": "commit scope"})
    return out
