"""Logic checks read straight from the source text, no model call: a weekend test that misses Saturday, a status that no code ever sets, a
CSV export that writes free text unescaped, a login or email column with no unique constraint. Each is stated only when the text proves it."""
import re

_WEEKDAY = re.compile(r"\.weekday\(\)\s*(?:>\s*5\b|>=\s*6\b)")
_TRANSITIONS = re.compile(r"^(\w*TRANSITIONS?\w*)\s*=\s*\{(.*?)^\}", re.M | re.S)
_STATE_KEY = re.compile(r"^\s*[\"'](\w+)[\"']\s*:\s*\[", re.M)


def _arts(store):
    return [(a, a.get("transcription") or "") for a in store.artifacts() if (a.get("transcription") or "").strip()]


def _line(text, pos):
    return text.count("\n", 0, pos) + 1


def _obs(title, statement, hits, source, severity="medium"):
    return {"title": title, "statement": statement, "facts": [], "basis": "observed", "files": sorted({n for n, _ in hits}),
            "cites": [f"{n} lines {l}–{l}" for n, l in hits[:4]], "source": source, "severity": severity}


def weekend_test(store):
    out = []
    for a, t in _arts(store):
        for m in _WEEKDAY.finditer(t):
            ln = _line(t, m.start())
            out.append(_obs(f"{a['name']} skips only Sunday when it means to skip the weekend",
                            f"{a['name']} line {ln} tests weekday() against 5, but weekday() is 5 for Saturday and 6 for Sunday, so Saturdays are treated as working days "
                            f"(use weekday() >= 5).", [(a["name"], ln)], "weekend test"))
            break
    return out


def status_never_set(store):
    arts = _arts(store)
    out = []
    for a, t in arts:
        m = _TRANSITIONS.search(t)
        if not m:
            continue
        states = _STATE_KEY.findall(m.group(2))
        if len(states) < 3:
            continue
        initial = states[0]
        body_start, body_end = m.start(), m.end()
        for st in states[1:]:
            set_rx = re.compile(r"\w+\([^)\n]*,\s*[\"']" + st + r"[\"']|SET\s+\w+\s*=\s*[\"']" + st + r"[\"']", re.I)
            hit = False
            for b, bt in arts:
                if not b["name"].lower().endswith(a["name"].lower().rsplit(".", 1)[-1]):
                    continue            # code of the same language only: a page's <option value="X"> sets nothing
                for line in bt.splitlines():
                    low = line.lower()
                    if set_rx.search(line) and " in " not in low and "==" not in line and " where " not in low:
                        hit = True
                        break
                if hit:
                    break
            if not hit:
                ln = _line(t, m.start() + m.group(2).find(f'"{st}"'))
                out.append(_obs(f"The status {st} is never set by any code",
                                f"{a['name']} lists {st} as a state that {initial} and other states move to, but no call or UPDATE in the files given sets it, "
                                f"so every action that needs a permit in {st} fails (for example approve fails from {initial}).", [(a["name"], ln)], "status never set", "high"))
    return out


def csv_formula(store):
    out = []
    for a, t in _arts(store):
        if not re.search(r"csv\.(writer|DictWriter)", t) or not re.search(r"\.writerows?\(", t):
            continue
        if re.search(r"startswith\(\s*\(\s*[\"']=|[\"']='\s*\+|lstrip\(|escape_formula|\[\s*[\"']=[\"']\s*,\s*[\"']\+", t):
            continue
        m = re.search(r"\.writerows?\(", t)
        out.append(_obs(f"{a['name']} writes free text into a CSV file without escaping",
                        f"{a['name']} line {_line(t, m.start())} writes database values into a CSV file as they are; a cell that starts with =, +, - or @ "
                        f"(a description someone typed) opens as a formula in a spreadsheet (CSV injection).", [(a["name"], _line(t, m.start()))], "csv formula"))
    return out


def login_column_not_unique(store):
    out = []
    for a, t in _arts(store):
        if not a["name"].lower().endswith(".sql"):
            continue
        for tm in re.finditer(r"CREATE\s+TABLE\s+(?:\w+\.)?(\w+)\s*\((.*?)\n\)\s*;", t, re.I | re.S):
            table, body = tm.group(1), tm.group(2)
            for cm in re.finditer(r"^\s*(email|username|login|user_name)\s+\w+[^,\n]*", body, re.I | re.M):
                col = cm.group(1)
                if re.search(r"UNIQUE|PRIMARY\s+KEY", cm.group(0), re.I) or re.search(rf"UNIQUE\s*\([^)]*\b{col}\b|CREATE\s+UNIQUE\s+INDEX[^;]*\b{col}\b", t, re.I):
                    continue
                ln = _line(t, tm.start(2) + cm.start())
                out.append(_obs(f"{table}.{col} has no unique constraint",
                                f"{a['name']} line {ln}: {table}.{col} is the sign-in name but nothing stops two rows holding the same value, so two accounts can share it "
                                f"and a sign-in can match the wrong one.", [(a["name"], ln)], "login not unique"))
    return out


def conflicts(store):
    out = []
    for fn in (weekend_test, status_never_set, csv_formula, login_column_not_unique):
        try:
            out += fn(store)
        except Exception:  # noqa: BLE001 - one check failing must not hide the others
            continue
    return out
