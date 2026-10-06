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


def select(store, code_arts, review_facts, total=16, minimum=2):
    per = []
    for art in code_arts:
        cands, seen = [], set()
        for f in review_facts.get(art["id"], []):
            if f.get("category") not in CATEGORIES or SUSPECT.search(f["statement"]):
                continue
            if f.get("review") not in (None, "supported", "partly_supported", "corrected"):
                continue
            key = f["statement"][:50]
            sc = _score(f)
            if sc >= minimum and key not in seen:
                seen.add(key)
                cands.append({"file": art["name"], "text": f["statement"], "lines": f.get("lines"),
                              "severity": f.get("severity"), "category": f["category"], "score": sc})
        cands.sort(key=lambda r: -r["score"])
        per.append(cands)
    picked = [c[0] for c in per if c]
    rest = sorted((r for c in per for r in c[1:3]), key=lambda r: -r["score"])
    picked += rest[:max(0, total - len(picked))]
    picked.sort(key=lambda r: -r["score"])
    return picked[:total]


def short(text, limit=170):
    first = re.split(r"(?<!e\.g\.)(?<!i\.e\.)(?<=[.!?])\s+(?=[A-Z])", text.strip())[0].rstrip(".")
    if len(first) > limit:
        cut = first[:limit].rsplit(" ", 1)[0]
        first = cut.rstrip(",;:") + "…"
    return first
