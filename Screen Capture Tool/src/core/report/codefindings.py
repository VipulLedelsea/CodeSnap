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
    r"DISP=MOD|appends? to|rerun|re-run|idempot|duplicate (output|record)|return code 0|RC LE 8|continue|\bCOND\b|return.?code",
    r"redefine|overlay|override|expir|sunset|no end date|threshold.*differ|differ.*threshold",
    r"not provided|unhandled|no (check|test|validation|authorization)|without (any )?(check|validation|authorization)",
)]
THEMES = re.compile(r"waiver|DSPLY|job log|DISP=MOD|short receipt|12-character|redefine|CHAR\(12\)|return code 0|INTAKE\.RC|"
                    r"\bCOMMIT\b|foreign key|referential|BELOW-MINIMUM|\bABS\(|cents|whole.unit|omit(s|ted)? .*amount|"
                    r"not (written|output)|file status|AT END|DISP=\(MOD|no sunset|sunset check|no (expiry|end date)|never expires?|"
                    r"first \d+ characters|substr|multiple active rows|does not (include|show|write)[^.]*amount", re.I)
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
    if THEMES.search(f["statement"]) and f.get("category") in ("defect", "data_integrity", "error_handling", "control_flow", "calculation", "data_write"):
        return True     # a known defect pattern (waiver, truncation, a return code that does not stop the job) needs no severity
    return sum(1 for p in SIGNALS if p.search(f["statement"])) >= 2


IDENT = re.compile(r"\b\w*_\w*\b|\b[A-Za-z]*[a-z][A-Z][A-Za-z]*\b")


def _same(a, b):
    ta, tb = set(WORD.findall(a.lower())), set(WORD.findall(b.lower()))
    if not ta or not tb:
        return False
    ids = {w.lower() for w in IDENT.findall(a)} & {w.lower() for w in IDENT.findall(b)}
    return bool(ids) or len(ta & tb) / min(len(ta), len(tb)) >= 0.5


PER_FILE = 5
_RANK = {"high": 2, "medium": 1}      # within a file a medium finding is chosen before a low or unrated one of a higher score


def select(store, code_arts, review_facts, total=24, minimum=2):
    from core import deepdive as DDV
    cands = []
    for art in code_arts:
        seen = set()
        try:
            zones = DDV.gap_zones(store, art)
        except Exception:  # noqa: BLE001 - the tag is an extra; the finding stands without it
            zones = []
        for f in review_facts.get(art["id"], []):
            if f.get("category") not in CATEGORIES or (SUSPECT.search(f["statement"]) and not THEMES.search(f["statement"])) or not _defect_like(f):
                continue
            if f.get("review") not in (None, "supported", "partly_supported", "corrected"):
                continue
            key = f["statement"][:50]
            sc = _score(f)
            if sc >= minimum and key not in seen:
                seen.add(key)
                gap = DDV.in_gap(zones, f.get("lines")) if zones else None
                cands.append({"file": art["name"], "text": f["statement"] + (GAP_TAG if gap else ""), "gap": gap, "lines": f.get("lines"),
                              "severity": f.get("severity"), "category": f["category"], "score": sc})
    cands.sort(key=lambda r: (-_RANK.get(r["severity"], 0), bool(r.get("gap")), -r["score"]))
    picked = []
    # Every file with candidates gets its best PER_FILE first, so a file whose defects score lower than another's repeated
    # ones is still represented; the rest is filled by rank up to the total.
    per_file, guaranteed = {}, []
    for c in cands:
        if per_file.get(c["file"], 0) < PER_FILE and not any(g["file"] == c["file"] and _same(g["text"], c["text"]) for g in guaranteed):
            per_file[c["file"]] = per_file.get(c["file"], 0) + 1       # a near copy of one already chosen does not use a slot
            guaranteed.append(c)
    ordered = guaranteed + [c for c in cands if c not in guaranteed]
    for c in ordered:
        if any(p["file"] == c["file"] and _same(p["text"], c["text"]) for p in picked):
            continue
        if c["severity"] != "high" and c not in guaranteed and len(picked) >= total:
            continue
        picked.append(c)
    picked.sort(key=lambda r: (-(r["severity"] == "high"), bool(r.get("gap")), -r["score"]))
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


GAP_TAG = " (check against the source: the captured copy has a gap or cut-off here)"


def short(text, limit=230):
    if text.endswith(GAP_TAG):                      # the tag always survives shortening
        return short(text[:-len(GAP_TAG)], limit) + GAP_TAG
    first = re.split(r"(?<!e\.g\.)(?<!i\.e\.)(?<=[.!?])\s+(?=[A-Z])", text.strip())[0].rstrip(".")
    if len(first) > limit:      # a long aside in brackets pushes the defect past the limit; the point matters more than the aside
        first = re.sub(r"\s*\((?:e\.g\.|i\.e\.|and |such as|including|for example|repeated)[^()]*\)", "", first, flags=re.I)
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


# ── program level: what the files do together ────────────────────────────────────────────────────────────────
# The whole-program review records what holds the files together: the order they run in, the data one hands to the
# next, rules copied between them and places where they disagree. The report states those once, for the program,
# and drops the single-file findings they already cover.

FLOW = re.compile(r"end[- ]to[- ]end|overall flow|how the (program|application|system) runs", re.I)
AGREE = re.compile(r"\b(agree|agrees|are the same|is the same|same (values?|thresholds?|precision|baselines?)|match(es)?)\b", re.I)
CONFLICT = re.compile(r"\b(differ|differs|different|differently|shifted|mismatch|misaligned|disagree|would read|never|bypass|"
                      r"ignores?|not (managed|defined|tested|checked|handled|applied)|undefined|truncat\w*|only the first|"
                      r"first \d+ characters|although|no way|would be triggered|re-?reads?|caller'?s work)\b", re.I)
SERIOUS = re.compile(r"different record layout|would read|bypass|never|no way|ignores|would be triggered|first \d+ characters|"
                     r"differ\w* from file to file", re.I)
_CITE_LINES = re.compile(r"^(?P<file>.+?) lines (?P<a>\d+)\D+(?P<b>\d+)$")


def _spans(cites):
    out = {}
    for c in cites or []:
        m = _CITE_LINES.match(c.strip())
        if m:
            out.setdefault(m.group("file"), []).append((int(m.group("a")), int(m.group("b"))))
    return out


def program_items(observations):
    """Split the whole-program observations into the end-to-end flow, risks (files that disagree or break each other),
    debt (the same rule copied into several files) and agreements (nothing to report)."""
    flow, risks, debt = None, [], []
    for o in observations or []:
        text = f"{o.get('title', '')}. {o.get('statement', '')}"
        files = list(o.get("files") or _spans(o.get("cites")))
        item = {"title": o.get("title", "").rstrip("."), "text": o.get("statement", ""), "files": files,
                "spans": {} if o.get("source") else _spans(o.get("cites")),     # a structural check names its own lines and covers no other finding
                "basis": o.get("basis"),
                "severity": o.get("severity") or ("high" if SERIOUS.search(text) else "medium"), "weight": len(files), "cites": o.get("cites") or []}
        if FLOW.search(o.get("title", "")):
            flow = item
        elif CONFLICT.search(o.get("title", "")) and len(files) >= 1:      # the headline says files disagree or break each other
            risks.append(item)
        elif AGREE.search(o.get("title", "")) and len(files) >= 3 and re.search(r"hard.?code", text, re.I):
            debt.append(item)
    return {"flow": flow, "risks": risks, "debt": debt}


def absorb(single, program):
    """Single-file findings whose lines fall inside a program-level observation that also says the same thing are covered by
    it; the rest remain. Overlapping lines alone are not enough: an observation about one rule must not hide a different
    defect that happens to sit in the same stretch of code."""
    items = program["risks"] + program["debt"]

    def covered(f):
        lines = f.get("lines") or []
        if not lines:
            return False
        a, b = lines[0], lines[-1]
        return any(a <= hi and b >= lo and _same(it["title"] + " " + it["text"], f["text"])
                   for it in items for lo, hi in it["spans"].get(f["file"], []))
    return [f for f in single if not covered(f)]


def program_rating(item):
    high = item["severity"] == "high"
    n = len(item["files"])
    likelihood = 4 if high or n >= 3 else 3
    impact = 4 if high else 3
    return (likelihood, impact,
            f"{likelihood}: the whole-program review found this where {n} file{'s' if n != 1 else ''} meet; whether production runs this path is to confirm",
            f"{impact}: " + ("it can change payments, ledger entries or the audit trail" if high
                             else "the effect depends on how the business uses these files") + "; to confirm with the business owner")
