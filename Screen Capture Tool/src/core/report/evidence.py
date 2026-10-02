"""What the source actually shows, for the parts of the report that are not the line-by-line review.

A stock sentence in the report may only be used when the code shows what it claims: CICS only with CICS commands,
a shared database account only with a connection string, totals "on the report" only when the program writes them,
personal data only where a person-level field exists. Each check returns the evidence (file and line) or nothing."""
import re

from core.deepdive import review_facts, unreached

CICS = re.compile(r"\bEXEC\s+CICS\b|\bDFHCOMMAREA\b|\bEIBCALEN\b|\bDFHMSD\b|\bDFHEIENT\b", re.I)
IMS_DC = re.compile(r"\bCBLTDLI\b|\bPLITDLI\b|\bASMTDLI\b|\bEXEC\s+DLI\b|\bIO-?PCB\b|\bFMT\b\s+\w+.*\bMFS\b|\bTRANSACT\b", re.I)
CONNECTION = re.compile(r"User\s*ID\s*=|\bUID\s*=|Password\s*=|Data\s+Source\s*=|Initial\s+Catalog|connect\s*\(|"
                        r"IDENTIFIED\s+BY|SQLCA\.(DBPass|LogPass)|jdbc:|Provider\s*=|DSN\s*=", re.I)
CREDENTIAL_RULES = ("SEC-CRED", "UIS-PREFILL")
DISPROVABLE = ("SEC-XSS", "SEC-CMD", "SEC-SQLI", "SEC-SQLDYN", "SEC-PATH", "SEC-DESER", "SEC-MEM")
DOWN = {"critical": "high", "high": "medium", "medium": "low", "low": "low", "info": "info"}


def texts(arts):
    return {a["name"]: a.get("transcription") or "" for a in arts}


def cics(arts) -> list:
    return [(a["name"], n) for a in arts for n, l in enumerate((a.get("transcription") or "").splitlines(), 1) if CICS.search(l)]


def ims_dc(arts) -> list:
    return [(a["name"], n) for a in arts for n, l in enumerate((a.get("transcription") or "").splitlines(), 1) if IMS_DC.search(l)]


def _file(f):
    ev = (f.get("evidence") or [{}])[0] or {}
    return ev.get("file") or f["title"].split(": ")[-1].split(":")[0]


def _line(f):
    ev = (f.get("evidence") or [{}])[0] or {}
    return ev.get("line")


def credentials(sec_f) -> list:
    return [f for f in sec_f if f.get("rule") in CREDENTIAL_RULES]


def db_credentials(sec_f) -> list:
    """Credentials that sign in to a database: a connection string, a DB connect call or a config secret."""
    out = []
    for f in sec_f:
        if f.get("rule") != "SEC-CRED":
            continue
        snip = " ".join((e or {}).get("snippet") or "" for e in f.get("evidence") or [])
        if CONNECTION.search(snip) or re.search(r"connection string|config item", f.get("detail") or "", re.I):
            out.append(f)
    return out


# ── batch control totals ────────────────────────────────────────────────────────────────────────────────────────

_ACC = re.compile(r"\bADD\s+(?:1|[\w-]+)\s+TO\s+([\w-]+)", re.I)
_TALLY = re.compile(r"COUNT|CNT|TOTAL|\bTOT\b|-TOT-|SUM|ACCUM", re.I)


def batch_totals(arts) -> dict:
    """{component: {"counts": [...], "totals": [...], "unused": [...]}} for the counters and totals a COBOL program
    keeps. One "is output" when it appears in a DISPLAY, WRITE or MOVE ... TO; it is "unused" when nothing but its
    declaration, its reset and the ADD that builds it refers to it. A working subtotal used in a calculation is neither."""
    out = {}
    for a in arts:
        t = a.get("transcription") or ""
        if not re.search(r"\bPROCEDURE\s+DIVISION\b", t, re.I):
            continue
        lines = t.splitlines()
        accs = []
        for l in lines:
            for m in _ACC.finditer(l):
                if m.group(1) not in accs and _TALLY.search(m.group(1)):
                    accs.append(m.group(1))
        if not accs:
            continue
        rec = {"counts": [], "totals": [], "unused": []}
        for v in accs:
            word = rf"(?<![\w-]){re.escape(v)}(?![\w-])"
            refs = [l for l in lines if re.search(word, l, re.I)]
            other = [l for l in refs if not re.search(rf"\bPIC\b|\bTO\s+{re.escape(v)}(?![\w-])|INITIALIZE\s+{re.escape(v)}", l, re.I)]
            shown = [l for l in other if re.search(rf"\b(DISPLAY|WRITE|STRING)\b.*{word}|\bMOVE\s+{re.escape(v)}\s+TO\b", l, re.I)]
            kind = "counts" if re.search(r"COUNT|CNT", v, re.I) else "totals"
            if shown:
                rec[kind].append(v)
            elif not other:
                rec["unused"].append(v)
        out[a["name"]] = rec
    return out


def totals_sentence(bt, component) -> str:
    r = bt.get(component)
    if not r:
        return ""
    bits = []
    if r["counts"]:
        bits.append("record counts are displayed at the end of the run")
    if r["totals"]:
        bits.append("control totals are written out")
    if r["unused"]:
        bits.append(f"{', '.join(r['unused'][:3])} {'is' if len(r['unused']) == 1 else 'are'} accumulated but never output")
    return "; ".join(bits)


# ── screens ─────────────────────────────────────────────────────────────────────────────────────────────────────

def display_files(arts) -> set:
    """IBM i display files (WORKSTN) declared in RPG: screens, not data."""
    out = set()
    for a in arts:
        for m in re.finditer(r"^\s*\S{0,5}F([A-Z0-9#@$_]{1,10})\s+\S+\s+\S+.*\bWORKSTN\b", a.get("transcription") or "", re.M | re.I):
            out.add(m.group(1).upper())
        for m in re.finditer(r"\bdcl-f\s+(\w+)\s+workstn\b", a.get("transcription") or "", re.I):
            out.add(m.group(1).upper())
    return out


def record_formats(arts) -> dict:
    """{record format: display file} for formats shown with EXFMT in a program that declares one display file."""
    out = {}
    for a in arts:
        t = a.get("transcription") or ""
        dfs = display_files([a])
        if len(dfs) != 1:
            continue
        df = next(iter(dfs))
        for m in re.finditer(r"\bEXFMT\s+(\w+)", t, re.I):
            if m.group(1).upper() != df:
                out[m.group(1).upper()] = df
    return out


def _words(s):
    return {w for w in re.findall(r"[a-z]{3,}", (s or "").lower())}


def screen_copies(arts) -> dict:
    """{screen image: web page file} when a screen image shows the same form as a page whose source was provided:
    at least three of its field labels, and its notices, appear in that page."""
    import json
    pages = [a for a in arts if re.search(r"<(form|input|table)\b", a.get("transcription") or "", re.I)]
    out = {}
    for s in arts:
        if s.get("artifact_type") != "ui_screen":
            continue
        try:
            data = json.loads(s.get("transcription") or "{}")
        except ValueError:
            continue
        labels = [f.get("label") for f in data.get("fields") or [] if f.get("label") and f.get("kind") not in ("table", "display")]
        if len(labels) < 3:
            continue
        for p in pages:
            low = (p.get("transcription") or "").lower()
            found = sum(1 for lb in labels if lb.lower() in low)
            if found >= 3 and found >= 0.75 * len(labels):
                out[s["name"]] = p["name"]
                break
    return out


def screens(store, arts) -> list:
    """Screen entities counted once: a record format belongs to its display file, and a screen image of a page whose
    source was provided is that page."""
    fmts = record_formats(arts)
    copies = screen_copies(arts)
    copy_ids = {a["id"] for a in arts if a["name"] in copies}
    out = []
    for e in store.entities("screen"):
        if e["name"].upper() in fmts:
            continue
        if e.get("artifact_id") in copy_ids:
            continue
        out.append(e)
    return out


# ── personal data ───────────────────────────────────────────────────────────────────────────────────────────────

def personal_entities(store, findings) -> set:
    """Names of tables, stores and screens that hold a person-level field (from the privacy findings)."""
    out = set()
    for f in findings:
        if f.get("rule") == "SEC-PII" or f["category"] == "privacy":
            if f.get("target_type") == "entity" and f.get("target_id"):
                e = store.entity(f["target_id"])
                if e:
                    out.add(e["name"])
    return out


def dormant_personal_data(store, arts) -> list:
    """(file, first line, last line) where a personal-data field appears only in code that is never called."""
    from core.deepdive import dead_lines
    from core.security.rules import code_lines, family, student_data_lines
    from core.security.scan import uncalled_lines
    facts = review_facts(store)
    out = []
    for a in arts:
        t = a.get("transcription") or ""
        if not t.strip():
            continue
        pii = student_data_lines(code_lines(t, family(a["name"], a.get("language") or "", t)))
        dead = dead_lines(facts.get(a["id"])) | uncalled_lines(t)
        hit = sorted(pii & dead)
        if hit and not (pii - dead):
            out.append((a["name"], hit[0], hit[-1]))
    return out


# ── the line-by-line review overrides rule matches ──────────────────────────────────────────────────────────────

def apply_review(store, sec_f) -> list:
    """Rule findings checked against the line-by-line review. Where the review found that the matched code never
    runs, or cannot do what it appears to, the finding is lowered one level and says so, with the review's lines."""
    facts = review_facts(store)
    by_name = {a["name"]: a["id"] for a in store.artifacts()}
    out = []
    from .plain import lower_first
    order = ["info", "low", "medium", "high", "critical"]
    for f in sec_f:
        g = dict(f)
        fs = facts.get(by_name.get(_file(f)))
        fact = unreached(fs, _line(f)) if f.get("rule") in DISPROVABLE else None
        if f.get("rule") == "CVE" and fs:
            lib = (re.search(r" in ([A-Za-z][\w.-]*)", f.get("title") or "") or [None, ""])[1]
            unused = next((x for x in fs if lib and lib.lower() in x["statement"].lower() and re.search(
                r"\bno [\w.-]+ calls? appears?\b|\bnever (used|called)\b|\bis not used\b", x["statement"], re.I)), None)
            if unused:
                new = DOWN.get(f["severity"], f["severity"])
                g["severity"] = new
                if new != f["severity"]:
                    g["lowered_from"] = f["severity"]
                g["reviewed"] = (f"the line-by-line review found that {lower_first(unused['statement'].rstrip('.'))} "
                                 f"({cite(unused['lines'])}), so the page loads the library without using it; removing "
                                 f"the include closes these weaknesses")
                out.append(g)
                continue
        if fact:
            new = DOWN.get(f["severity"], f["severity"])
            g["severity"] = new
            g["reviewed"] = (f"the line-by-line review found that {lower_first(fact['statement'].rstrip('.'))} "
                             f"({cite(fact['lines'])}), so this cannot be triggered as the code stands")
            if new != f["severity"]:
                g["lowered_from"] = f["severity"]
        elif _line(f) and fs:
            conf = [x for x in fs if x["category"] == "security" and x.get("severity") in order and
                    x["lines"][0] <= _line(f) <= x["lines"][1] and order.index(x["severity"]) > order.index(f["severity"])]
            if conf and f.get("rule") in DISPROVABLE:
                x = conf[0]
                g["severity"] = x["severity"]
                g["raised_from"] = f["severity"]
                g["reviewed"] = (f"the line-by-line review confirmed it: {lower_first(x['statement'].rstrip('.'))} "
                                 f"({cite(x['lines'])})")
        out.append(g)
    return out


def review_statements(store, arts, names, cats=("error_handling", "defect"), rx=None, sev=("high", "medium")) -> list:
    """(component, statement, lines) from the line-by-line review for these components."""
    facts = review_facts(store)
    by_id = {a["id"]: a["name"] for a in arts}
    out = []
    for aid, fs in facts.items():
        n = by_id.get(aid)
        if n not in names:
            continue
        for f in fs:
            if f["category"] in cats and (sev is None or f.get("severity") in sev) and (
                    rx is None or re.search(rx, f["statement"], re.I)):
                out.append((n, f["statement"].rstrip("."), tuple(f["lines"])))
    return out


def cite(lines) -> str:
    a, b = lines
    return f"line {a}" if a == b else f"lines {a}–{b}"


def data_stores(store, arts):
    """Current, non-placeholder data stores, excluding display files."""
    current = {a["id"] for a in arts}
    displays = display_files(arts)
    return [e for e in store.entities("data_store")
            if e.get("origin") != "placeholder" and e["name"].upper() not in displays
            and any(s["artifact_id"] in current for s in store.entity_sources(e["id"]))]
