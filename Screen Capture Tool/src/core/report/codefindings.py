import re

CATEGORIES = {"defect", "data_integrity", "error_handling", "business_rule", "control_flow", "calculation", "interface", "security", "data_write", "data_read"}
SUSPECT = re.compile(r"duplicated verbatim|defined twice|identical paragraph name|repeated verbatim|blocks of duplicated|\btruncated\b|not created until|naming pattern|instead of the X|"
                     r"dangling|syntactically incomplete|corrupted or incompletely|begins mid|two fields both named|"
                     r"identical screen position|compile error|label not found", re.I)
SIGNALS = [re.compile(p, re.I) for p in (
    r"overwritten|unmodified input|before .*(sign|correct)|\bABS\b|negative",
    r"cancels?|fully cancel|subtracts? exactly|even (if|when)|regardless|unconditional|always (sets|returns|exits)",
    r"bypass|skips?|not changed|does not (reject|stop|block|reflect)|never (checks|enforced|output|written)",
    r"\bCOMMIT\b|not atomic|committed separately|rollback|referential integrity|foreign key",
    r"truncat|first 12|CHAR\(12\)|short receipt|12-character|cents|whole.unit|precision",
    r"DSPLY|job log|spool|account number|sensitive",
    r"DISP=MOD|appends? to|rerun|re-run|idempot|duplicate (output|record)|return code 0|RC LE 8|continue",
    r"redefine|overlay|override|expir|sunset|no end date|threshold.*differ|differ.*threshold",
    r"not provided|unhandled|no (check|test|validation|authorization)|without (any )?(check|validation|authorization)",
)]
THEMES = re.compile(r"waiver|DSPLY|job log|DISP=MOD|short receipt|12-character|redefine|CHAR\(12\)|return code 0|INTAKE\.RC|"
                    r"\bCOMMIT\b|foreign key|referential|BELOW-MINIMUM|\bABS\(|cents|whole.unit|omit(s|ted)? .*amount|"
                    r"not (written|output)|file status|AT END", re.I)
POSITIVE = re.compile(r"has file status monitoring|standard EXEC SQL host-variable binding|not dynamic SQL|so no (sql )?injection|"
                      r"is assigned to \w+ and has|properly (handled|checked)|correctly (handled|checked)", re.I)
UNCONDITIONAL = re.compile(r"\bevery\b|unconditional|\balways\b|\ball \d+\b|never (checks|checked|enforced)|silently ignor|"
                           r"syntax error|duplicated|no expiry|cannot (ever|actually)|can never", re.I)
WORD = re.compile(r"[a-z0-9_]{4,}")
GENERIC = re.compile(r"identical structure|^(the )?(file|program|copybook|jcl|rexx)\b.*\b(defines|is a|is an|contains|declares)\b|synthetic", re.I)


def _score(f):
    s = {"high": 3, "medium": 2}.get(f.get("severity"), 0)
    s += sum(2 for p in SIGNALS if p.search(f["statement"]))
    if f.get("basis") == "observed":
        s += 1
    if THEMES.search(f["statement"]):
        s += 3
    if GENERIC.search(f["statement"]):
        s -= 4
    return s


def _defect_like(f):
    if POSITIVE.search(f["statement"]):
        return False
    if f.get("severity") in ("high", "medium"):
        return True
    return sum(1 for p in SIGNALS if p.search(f["statement"])) >= 2


IDENT = re.compile(r"\b\w*_\w*\b|\b[A-Za-z]*[a-z][A-Z][A-Za-z]*\b")


def _same(a, b):
    ta, tb = set(WORD.findall(a.lower())), set(WORD.findall(b.lower()))
    if not ta or not tb:
        return False
    ids = {w.lower() for w in IDENT.findall(a)} & {w.lower() for w in IDENT.findall(b)}
    return bool(ids) or len(ta & tb) / min(len(ta), len(tb)) >= 0.5


def select(store, code_arts, review_facts, total=20, minimum=2):
    cands = []
    for art in code_arts:
        seen = set()
        for f in review_facts.get(art["id"], []):
            if f.get("category") not in CATEGORIES or SUSPECT.search(f["statement"]) or not _defect_like(f):
                continue
            if f.get("review") not in (None, "supported", "partly_supported", "corrected"):
                continue
            key = f["statement"][:50]
            sc = _score(f)
            if sc >= minimum and key not in seen:
                seen.add(key)
                cands.append({"file": art["name"], "text": f["statement"], "lines": f.get("lines"),
                              "severity": f.get("severity"), "category": f["category"], "score": sc})
    cands.sort(key=lambda r: (-(r["severity"] == "high"), -r["score"]))
    picked = []
    for c in cands:
        if any(p["file"] == c["file"] and _same(p["text"], c["text"]) for p in picked):
            continue
        if c["severity"] != "high" and len(picked) >= total:
            continue
        picked.append(c)
    picked.sort(key=lambda r: (-(r["severity"] == "high"), -r["score"]))
    return picked


def rate(cf):
    """Likelihood and impact (1 to 5) for a line-by-line finding, with the reason for each."""
    high = cf["severity"] == "high"
    every = bool(UNCONDITIONAL.search(cf["text"]))
    likelihood = 4 if (high or every) else 3
    impact = 4 if high else 3
    why_l = (f"{likelihood}: the line-by-line review found this in the source and it applies "
             + ("on every run of the path" if every else "whenever the path runs")
             + "; whether production uses the path is to confirm")
    why_i = (f"{impact}: " + ("it can change payments, ledger entries or the audit trail" if high
                              else "the effect on payments depends on how the business uses this path")
             + "; to confirm with the business owner")
    return likelihood, impact, why_l, why_i


def short(text, limit=230):
    first = re.split(r"(?<!e\.g\.)(?<!i\.e\.)(?<=[.!?])\s+(?=[A-Z])", text.strip())[0].rstrip(".")
    if re.match(r"(because|since|if|when|although)\b", first, re.I):
        limit = int(limit * 1.8)
    if len(first) <= limit:
        return first
    bound = re.compile(r",\s|;\s|\s\u2014\s|\s-\s|\s(?:so|meaning|which|because|where)\s")
    window = first[:limit]
    cut = max((m.start() for m in bound.finditer(window)), default=-1)
    if cut <= limit * 0.5:
        later = next((m.start() for m in bound.finditer(first) if limit < m.start() <= limit * 1.6), None)
        cut = later if later else cut
    base = first[:cut] if cut > limit * 0.5 else window.rsplit(" ", 1)[0]
    out = base.rstrip(",;:- ")
    if out.count("(") > out.count(")"):
        close = first.find(")", len(out))
        out = first[:close + 1] if 0 <= close <= len(out) + 80 else out[:out.rfind("(")].rstrip(",;:- ")
    return out
