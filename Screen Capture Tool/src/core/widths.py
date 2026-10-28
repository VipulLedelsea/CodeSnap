"""Cross-file field width check: the same business value (a receipt, an account) declared with different widths in
different files. A narrower copy cuts the value off wherever it is used. This reads the structure already extracted
for each file, so it needs no model call and works the same for screenshots and folders."""
import json
import re

_PIC = re.compile(r"^\s*(?:X|A)\((\d+)\)\s*$", re.I)
_CHAR = re.compile(r"^\s*(?:VAR)?CHAR(?:ACTER)?(?:\s+VARYING)?\s*\((\d+)\)", re.I)
_SKIP = {"FILLER", "TYPE", "CODE", "NAME", "TEXT", "DATE", "TIME", "FLAG", "KEY", "LINE", "ITEM", "DATA", "AREA", "FIELD", "VALUE"}


def _attrs(e):
    a = e.get("attrs")
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except ValueError:
            return {}
    return a or {}


def _concept(name):
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", name or "") if p and not p.isdigit()]
    word = parts[-1].upper() if parts else ""
    return word if len(word) >= 4 and word not in _SKIP and not re.fullmatch(r"[A-Z]\d+", word) else ""


def _width(e):
    at = _attrs(e)
    if e["kind"] == "field":
        m = _PIC.match(str(at.get("picture") or "")) or _CHAR.match(str(at.get("type") or ""))
    elif e["kind"] == "column":
        m = _CHAR.match(str(at.get("type") or ""))
    else:
        return None
    return int(m.group(1)) if m else None


def declarations(store):
    """[(concept, width, file, name, line)] for character fields and columns, and for screen fields next to their label."""
    arts = {a["id"]: a["name"] for a in store.artifacts()}
    out = []
    labels = []
    for e in store.entities():
        if e.get("artifact_id") not in arts or e.get("origin") == "placeholder":
            continue
        w, c = _width(e), _concept(e["name"])
        if w and c:
            out.append((c, w, arts[e["artifact_id"]], e["name"], e.get("line_start")))
        elif e["kind"] == "ui_element":
            at = _attrs(e)
            pos = re.match(r"(\d+),(\d+)", str(at.get("pos") or ""))
            if pos:
                labels.append((e["artifact_id"], int(pos.group(1)), int(pos.group(2)), at, e))
    by_row = {}
    for art, row, col, at, e in labels:
        by_row.setdefault((art, row), []).append((col, at, e))
    for (art, row), items in by_row.items():
        items.sort(key=lambda x: x[0])
        for i, (col, at, e) in enumerate(items):
            text = str(at.get("text") or "")
            c = _concept(text)
            nxt = next((x for x in items[i + 1:] if x[1].get("input")), None)
            if c and not at.get("input") and nxt and nxt[1].get("length"):
                out.append((c, int(nxt[1]["length"]), arts[art], f"screen field '{text.strip()}'", nxt[2].get("line_start")))
    return out


def conflicts(store, minimum_files=2):
    """One observation per concept whose character width differs between files, shaped like the program observations."""
    groups = {}
    for c, w, f, name, line in declarations(store):
        groups.setdefault(c, {}).setdefault(w, []).append((f, name, line))
    obs = []
    for c, by_w in sorted(groups.items()):
        if len(by_w) < 2:
            continue
        files = {f for items in by_w.values() for f, _, _ in items}
        if len(files) < minimum_files:
            continue
        widest = max(by_w)
        narrow = [w for w in by_w if w < widest]
        if not narrow:
            continue

        def where(w):
            items = by_w[w]
            fs = sorted({f for f, _, _ in items})
            return f"{w} characters in {', '.join(fs[:3])}" + (f" and {len(fs) - 3} more" if len(fs) > 3 else "")
        stmt = (f"{c.title()} is cut to {min(narrow)} characters in {', '.join(where(w).split(' characters in ')[1] for w in sorted(narrow))}, "
                f"but is {where(widest)}. A {widest}-character {c.lower()} loses its last {widest - min(narrow)} characters wherever the narrower "
                f"copy is used, so two different {c.lower()}s can look identical or fail to match.")
        cites = [f"{f} lines {line}\u2013{line}" if line else f for w in sorted(narrow) for f, _, line in by_w[w][:2]]
        narrow_files = sorted({f for w in narrow for f, _, _ in by_w[w]})
        obs.append({"title": f"{c.title()} width differs between files", "statement": stmt, "facts": [], "basis": "observed",
                    "cites": cites, "files": narrow_files + [f for f in sorted(files) if f not in narrow_files], "source": "field widths", "severity": "medium"})
    return obs
