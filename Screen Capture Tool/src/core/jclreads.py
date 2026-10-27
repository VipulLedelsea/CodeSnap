"""JCL check: many steps that run the same program over the whole of the same input dataset. Each step reads every
record, so the work grows with the number of steps (one per district or route) instead of one pass that splits the data.
Read straight from the JCL text; no model call."""
import re

_STEP = re.compile(r"^//(\w+)\s+EXEC\s+(?:PGM=)?(\w+)", re.I)
_DD = re.compile(r"^//(\w+)\s+DD\s+(.*)", re.I)
_DSN = re.compile(r"DSN=([\w.&$#@()+-]+)", re.I)
_SHARED = re.compile(r"DISP=\(?(SHR|OLD)\b", re.I)
MIN_STEPS = 4


def _rereads(text):
    step = pgm = None
    seen = {}
    for n, line in enumerate((text or "").splitlines(), 1):
        m = _STEP.match(line)
        if m:
            step, pgm = m.group(1), m.group(2).upper()
            continue
        d = _DD.match(line)
        if d and step:
            dsn, shr = _DSN.search(d.group(2)), _SHARED.search(d.group(2))
            if dsn and shr:
                steps = seen.setdefault((dsn.group(1).upper(), pgm), {})
                steps.setdefault(step, n)
    return seen


def conflicts(store):
    out = []
    for a in store.artifacts():
        text = a.get("transcription") or ""
        if not re.search(r"^//\w+\s+EXEC\b", text, re.M | re.I):
            continue
        for (dsn, pgm), steps in sorted(_rereads(text).items()):
            if len(steps) < MIN_STEPS:
                continue
            names = list(steps)
            lines = sorted(steps.values())
            out.append({
                "title": f"{pgm} re-reads the whole of {dsn} in each of {len(steps)} steps",
                "statement": (f"{len(steps)} job steps ({names[0]} to {names[-1]}) each run {pgm} over the whole of {dsn}, so every step reads "
                              f"every record once: the work grows with the number of steps instead of the data being read once and split."),
                "facts": [], "basis": "observed", "files": [a["name"]],
                "cites": [f"{a['name']} lines {lines[0]}–{lines[0]}", f"{a['name']} lines {lines[-1]}–{lines[-1]}"],
                "source": "job steps"})
    return out
