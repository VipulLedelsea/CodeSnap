"""Two source checks the line-by-line review tends to miss because each needs two files or the whole file at once.

1. Threshold drift: a paragraph with the same name (ASHFORD, BRIARWOOD ...) exists in two COBOL programs and tests the
   same conditions against different numbers. One program then decides a payment one way and the other another way.
2. Calculated but never written: an amount field a program computes (sign flips, caps) that never reaches the record the
   program writes, so the result of the calculation is lost.
Both read the source text; no model call."""
import re

_PARA = re.compile(r"^ {7}(\d+)-([A-Z][A-Z0-9-]*)\.\s*$", re.M)
_CMP = re.compile(r"\b(IF|AND|OR)\s+[\w()-]+\s*(<=|>=|<|>|=)\s*(\d+(?:\.\d+)?)\b")
MIN_SHARED = 3


def _paragraphs(text):
    marks = [(m.start(), m.end(), m.group(2)) for m in _PARA.finditer(text)]
    out = {}
    for i, (s, e, name) in enumerate(marks):
        body = text[e:marks[i + 1][0] if i + 1 < len(marks) else len(text)]
        cmps = [(m.group(2), m.group(3)) for m in _CMP.finditer(body)]
        line = text.count("\n", 0, s) + 1
        if cmps:
            out.setdefault(name, (cmps, line))
    return out


def threshold_drift(store):
    arts = [a for a in store.artifacts() if re.search(r"PROCEDURE\s+DIVISION", a.get("transcription") or "", re.I)]
    paras = {a["name"]: _paragraphs(a.get("transcription") or "") for a in arts}
    out, names = [], sorted(paras)
    for i, x in enumerate(names):
        for y in names[i + 1:]:
            shared = [n for n in paras[x] if n in paras[y]]
            same_shape = [n for n in shared if [o for o, _ in paras[x][n][0]] == [o for o, _ in paras[y][n][0]]]
            differ = [n for n in same_shape if paras[x][n][0] != paras[y][n][0]]
            if len(differ) < MIN_SHARED or len(differ) < 0.5 * max(1, len(same_shape)):
                continue
            n0 = differ[0]
            fmt = lambda c: " and ".join(f"{'below' if o in '<<=' and o.startswith('<') else 'above' if o.startswith('>') else 'at'} {v}" for o, v in c)
            out.append({
                "title": f"Thresholds differ between {x} and {y}",
                "statement": (f"{len(differ)} of the {len(same_shape)} paragraphs that exist in both {x} and {y} test the same conditions against different numbers, "
                              f"for example {n0}: {fmt(paras[x][n0][0])} in {x}, {fmt(paras[y][n0][0])} in {y}. The two programs can decide the same payment differently."),
                "facts": [], "basis": "observed", "files": [x, y], "source": "rule drift", "severity": "high",
                "cites": [f"{x} lines {paras[x][n0][1]}–{paras[x][n0][1]}", f"{y} lines {paras[y][n0][1]}–{paras[y][n0][1]}"]})
    return out


_STRING = re.compile(r"STRING\s+(.*?)\s+INTO\s+([\w-]+)", re.S | re.I)
_AMOUNT = re.compile(r"\b[\w-]*(?:AMOUNT|AMT)[\w-]*\b", re.I)


def unwritten_amounts(store):
    found = {}
    for a in store.artifacts():
        text = a.get("transcription") or ""
        if not re.search(r"PROCEDURE\s+DIVISION", text, re.I):
            continue
        computed = {m.group(1).upper() for m in re.finditer(r"\b(?:COMPUTE|ADD\s+[\w-]+\s+TO|SUBTRACT\s+[\w-]+\s+FROM)\s+([\w-]*(?:AMOUNT|AMT)[\w-]*)", text, re.I)}
        computed |= {m.group(1).upper() for m in re.finditer(r"\bMOVE\s+[^\n]+\s+TO\s+([\w-]*(?:AMOUNT|AMT)[\w-]*)", text, re.I)}
        for m in _STRING.finditer(text):
            sources = {w.upper() for w in re.findall(r"[\w-]+", m.group(1))}
            out_rec = m.group(2).upper()
            if not re.search(rf"\bWRITE\s+{re.escape(out_rec)}\b", text, re.I):
                continue
            lost = sorted(c for c in computed if c not in sources and not re.search(rf"\bMOVE\s+{re.escape(c)}\s+TO\b", text, re.I)
                          and not re.search(rf"\b(?:WRITE|DISPLAY)\b[^\n]*\b{re.escape(c)}\b", text, re.I))
            if lost:
                line = text.count("\n", 0, m.start()) + 1
                found.setdefault((lost[0], out_rec, tuple(sorted(sources))), []).append((a["name"], line))
                break
    out = []
    for (field, out_rec, sources), where in found.items():
        names = [n for n, _ in where]
        out.append({
            "title": f"{field} is calculated but never written in {' and '.join(names)}",
            "statement": (f"{field} is calculated in {' and '.join(names)} (including its sign and limit checks), but the record written to {out_rec} is built from "
                          f"{', '.join(sources)} only, so the amount the checks used is not in the output."),
            "facts": [], "basis": "observed", "files": names, "source": "rule drift", "severity": "medium",
            "cites": [f"{n} lines {ln}\u2013{ln}" for n, ln in where]})
    return out


def unused_copybooks(store):
    arts = list(store.artifacts())
    programs = [a for a in arts if re.search(r"PROCEDURE\s+DIVISION", a.get("transcription") or "", re.I)]
    out = []
    for a in arts:
        if not re.search(r"\.(cpy|copy|cbl\.inc)$", a["name"], re.I):
            continue
        stem = re.sub(r"^\d+[_-]", "", a["name"].rsplit(".", 1)[0])
        used = any(re.search(rf"\bCOPY\s+{re.escape(stem)}\b", b.get("transcription") or "", re.I) for b in arts if b["id"] != a["id"])
        if not used and len(programs) >= 2:
            out.append({
                "title": f"{a['name']} is never copied in by any program",
                "statement": (f"No program copies in {stem}: the {len(programs)} COBOL programs each define their own record layouts, so {a['name']} and the "
                              f"layouts the programs actually use can drift apart without anyone noticing."),
                "facts": [], "basis": "observed", "files": [a["name"]] + [b["name"] for b in programs][:4], "source": "rule drift", "severity": "medium",
                "cites": [f"{a['name']} lines 1\u20131"]})
    return out


_SWALLOW = re.compile(r"^\s*if\s+(\w*rc)\s*(?:<>|\\=|\^=|>)\s*0\s+then\s+(?:do\s*;?\s*)?return\s+0\b", re.I | re.M)


def swallowed_failures(store):
    """A procedure that gives up on an allocation, read or write failure and still returns 0 (success) to its caller."""
    out = []
    for a in store.artifacts():
        text = a.get("transcription") or ""
        found = [(text.count("\n", 0, m.start()) + 1, m.group(1)) for m in _SWALLOW.finditer(text)]
        if len(found) >= 3:
            out.append({
                "title": f"A failed allocation or write never reaches the caller in {a['name']}",
                "statement": (f"{len(found)} procedures in {a['name']} (for example line {found[0][0]}: if {found[0][1]} is not 0 then return 0) give up when the "
                              f"allocation, read or write fails and still return 0, so the caller sees success and the failure is lost."),
                "facts": [], "basis": "observed", "files": [a["name"]], "source": "rule drift", "severity": "medium",
                "cites": [f"{a['name']} lines {found[0][0]}\u2013{found[0][0]}", f"{a['name']} lines {found[-1][0]}\u2013{found[-1][0]}"]})
    return out


def repeated_tables(store):
    """The same OCCURS table declared many times: a change to its size has to be made in every copy."""
    out = []
    for a in store.artifacts():
        text = a.get("transcription") or ""
        counts = {}
        for m in re.finditer(r"OCCURS\s+(\d+)\s+TIMES", text, re.I):
            counts.setdefault(m.group(1), []).append(text.count("\n", 0, m.start()) + 1)
        for n, lines in counts.items():
            if len(lines) >= 10:
                out.append({
                    "title": f"The {n}-period table in {a['name']} is repeated {len(lines)} times, so a change never lands in one place",
                    "statement": (f"{a['name']} declares OCCURS {n} TIMES in {len(lines)} separate record areas (lines {lines[0]} to {lines[-1]}), so changing the "
                                  f"number of periods means editing every copy and any copy that is missed keeps the old layout."),
                    "facts": [], "basis": "observed", "files": [a["name"]], "source": "rule drift", "severity": "medium",
                    "cites": [f"{a['name']} lines {lines[0]}\u2013{lines[0]}", f"{a['name']} lines {lines[-1]}\u2013{lines[-1]}"]})
    return out


def conflicts(store):
    return (threshold_drift(store) + unwritten_amounts(store) + unused_copybooks(store) + swallowed_failures(store)
            + repeated_tables(store))
