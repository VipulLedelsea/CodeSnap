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


_LIST = re.compile(r"[(\[]\s*((?:[\"'][A-Z][A-Z0-9_]+[\"']\s*,\s*)+[\"'][A-Z][A-Z0-9_]+[\"'])\s*,?\s*[)\]]")


def status_list_omits(store):
    """A hard-coded list that names all but one of the states a workflow defines: the one left out is almost always a mistake."""
    arts = _arts(store)
    out = []
    for a, t in arts:
        m = _TRANSITIONS.search(t)
        states = set(_STATE_KEY.findall(m.group(2))) if m else set()
        if len(states) < 4:
            continue
        for b, bt in arts:
            for lm in _LIST.finditer(bt):
                if b is a and m and m.start() <= lm.start() <= m.end():
                    continue
                items = set(re.findall(r"[\"']([A-Z][A-Z0-9_]+)[\"']", lm.group(1)))
                missing = states - items
                if items <= states and len(items) == len(states) - 1 and len(missing) == 1:
                    ln = _line(bt, lm.start())
                    out.append(_obs(f"A list of statuses in {b['name']} leaves out {next(iter(missing))}",
                                    f"{b['name']} line {ln} lists {len(items)} of the {len(states)} states that {a['name']} defines and leaves out {next(iter(missing))}, "
                                    f"so anything counted or handled by that list misses permits in that state.", [(b["name"], ln), (a["name"], _line(t, m.start()))],
                                    "status list", "medium"))
    return out


def rerun_unsafe_schema(store):
    """A deploy script that loads a SQL file each time it runs, where the file cannot be loaded twice."""
    arts = _arts(store)
    sqls = {a["name"].split("/")[-1].lower(): (a, t) for a, t in arts if a["name"].lower().endswith(".sql")}
    out = []
    for a, t in arts:
        if not a["name"].lower().endswith((".sh", ".bash", ".ksh")):
            continue
        if not re.search(r"git\s+(pull|fetch|checkout)|pkill|systemctl\s+restart|service\s+\w+\s+restart", t):
            continue          # not a script that is run again for each release
        for m in re.finditer(r"(?:sqlite3|psql|mysql|sqlcmd)\b[^\n]*?(?:<\s*|-f\s+|-i\s+)([\w./-]+\.sql)", t):
            name = m.group(1).split("/")[-1].lower()
            if name not in sqls:
                continue
            sa, st = sqls[name]
            creates = re.search(r"CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS)", st, re.I)
            seeds = re.search(r"INSERT\s+INTO\b(?![^;]*(?:ON\s+CONFLICT|OR\s+IGNORE|WHERE\s+NOT\s+EXISTS))", st, re.I)
            if creates or seeds:
                ln = _line(t, m.start())
                what = " and ".join(x for x, y in (("fails on tables that already exist", creates), ("inserts its seed rows again", seeds)) if y)
                out.append(_obs(f"{a['name']} loads {sa['name']} on every run, and it cannot be loaded twice",
                                f"{a['name']} line {ln} loads {sa['name']} each time the script runs (it also restarts the application), but that file {what}.",
                                [(a["name"], ln), (sa["name"], _line(st, (creates or seeds).start()))], "rerun unsafe", "medium"))
    return out


def _setting(name):
    return re.sub(r"_(days?|seconds?|secs?|ms|minutes?|hours?|count|limit|max|min|size|length)$", "", name.lower())


def settings_duplicated(store):
    """Numbers defined both in a settings file and in code under the same names: two sources for one value."""
    arts = _arts(store)
    out = []
    for a, t in arts:
        if not a["name"].lower().endswith((".yaml", ".yml", ".ini", ".toml", ".json")):
            continue
        conf = {(_setting(k), v) for k, v in re.findall(r"^\s*[\"']?(\w+)[\"']?\s*[:=]\s*(\d+)\s*,?\s*$", t, re.M)}
        if len(conf) < 3:
            continue
        for b, bt in arts:
            if b is a or b["name"].lower().endswith((".yaml", ".yml", ".ini", ".toml", ".json", ".md", ".txt")):
                continue
            code = {(_setting(k), v) for k, v in re.findall(r"[\"'](\w+)[\"']\s*:\s*(\d+)", bt)} | {(_setting(k), v) for k, v in re.findall(r"^\s*(\w+)\s*=\s*(\d+)\s*$", bt, re.M)}
            both = sorted(conf & code)
            if len(both) >= 3:
                names = ", ".join(k for k, _ in both[:4])
                out.append(_obs(f"{len(both)} settings are defined in both {a['name']} and {b['name']}",
                                f"{names} are set to the same numbers in {a['name']} and in {b['name']}: today they agree, but changing one does not change the other, so they can drift apart.",
                                [(a["name"], 1), (b["name"], 1)], "settings duplicated", "low"))
    return out


def conflicts(store):
    out = []
    for fn in (weekend_test, status_never_set, csv_formula, login_column_not_unique, status_list_omits, rerun_unsafe_schema, settings_duplicated):
        try:
            out += fn(store)
        except Exception:  # noqa: BLE001 - one check failing must not hide the others
            continue
    return out
