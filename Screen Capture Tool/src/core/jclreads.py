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


_IF_RC = re.compile(r"^//\w*\s+IF\s*\(?\s*(\w+)\.RC\s*(LE|<=|LT|<)\s*(\d+)\s*\)?\s*THEN", re.I)
_OUT_MOD = re.compile(r"DISP=\(?\s*MOD\b(?![^)]*DELETE)", re.I)


def _rc_gates(a, text):
    gates = {}
    for n, line in enumerate(text.splitlines(), 1):
        m = _IF_RC.match(line)
        if m:
            limit = int(m.group(3)) - (1 if m.group(2).upper() in ("LT", "<") else 0)
            if limit >= 8:      # return code 8 is an error; a gate that still runs at 8 does not stop on it
                gates.setdefault((m.group(1).upper(), limit), []).append(n)
    out = []
    for (step, limit), lines in gates.items():
        if len(lines) >= MIN_STEPS:
            out.append({
                "title": f"A failed {step} (return code {limit}) never stops the {len(lines)} steps after it",
                "statement": (f"{len(lines)} blocks in {a['name']} run only if {step}.RC is {limit} or lower, so {step} can end with return code {limit} (an error, "
                              f"not just a warning) and every one of those steps still runs on whatever it left behind."),
                "facts": [], "basis": "observed", "files": [a["name"]], "source": "job steps", "severity": "medium",
                "cites": [f"{a['name']} lines {lines[0]}\u2013{lines[0]}", f"{a['name']} lines {lines[-1]}\u2013{lines[-1]}"]})
    return out


def _mod_outputs(a, text):
    step = pgm = None
    steps = {}
    for n, line in enumerate(text.splitlines(), 1):
        m = _STEP.match(line)
        if m:
            step, pgm = m.group(1), m.group(2).upper()
            continue
        d = _DD.match(line) or (re.match(r"^//\s+(.*)", line) if step else None)
        if d and step and _OUT_MOD.search(d.group(d.lastindex or 1)) and pgm not in ("IEFBR14",):
            steps.setdefault(step, n)
    if len(steps) >= MIN_STEPS:
        names, lines = list(steps), sorted(steps.values())
        return [{
            "title": f"Output datasets are never emptied: {len(steps)} steps write with DISP=MOD",
            "statement": (f"{len(steps)} steps in {a['name']} ({names[0]} to {names[-1]}) write their output with DISP=MOD, which appends to what is already there, "
                          f"so running the job again adds a second copy of every record instead of replacing the first."),
            "facts": [], "basis": "observed", "files": [a["name"]], "source": "job steps", "severity": "medium",
            "cites": [f"{a['name']} lines {lines[0]}\u2013{lines[0]}", f"{a['name']} lines {lines[-1]}\u2013{lines[-1]}"]}]
    return []


def conflicts(store):
    out = []
    for a in store.artifacts():
        text = a.get("transcription") or ""
        if not re.search(r"^//\w+\s+EXEC\b", text, re.M | re.I):
            continue
        out += _rc_gates(a, text) + _mod_outputs(a, text)
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
                "source": "job steps", "severity": "medium"})
    return out
