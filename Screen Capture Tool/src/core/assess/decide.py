DISPOSITIONS = {
    "retain": ("Retain", "good to go", "Keep as is; routine maintenance only."),
    "rehost": ("Rehost", "patch", "Move to supported infrastructure with minimal code change (e.g. mainframe to cloud-hosted COBOL runtime)."),
    "replatform": ("Replatform", "patch", "Upgrade runtime/framework to a supported version with targeted code changes."),
    "refactor": ("Refactor", "patch", "Keep the platform; fix security and restructure the worst code."),
    "rearchitect": ("Re-architect / rebuild", "rebuild", "Rewrite on a modern, supported stack; the current platform has no upgrade path."),
    "replace": ("Replace", "rebuild", "Retire the custom code in favour of an off-the-shelf or shared state solution."),
    "retire": ("Retire", "rebuild", "Decommission; function is no longer needed or is duplicated elsewhere."),
}
NO_PATH = ("ASP.NET Web Forms", "Pre-standard C++", "Adobe Flash", "Microsoft Silverlight", "ActiveX", "Java applets",
           "Apache Struts 1", "16-bit Windows", "Borland OWL", ".NET Remoting", "EJB 2", "AngularJS")
IMPACT_KINDS = {"student_data": 4, "writes": 4, "entry": 3}
LEVELS = [(20, "critical"), (12, "high"), (6, "medium"), (0, "low")]


def likelihood(scores: dict) -> tuple:
    worst = min(scores[d]["score"] for d in ("security", "supportability", "health"))
    debt = scores["tech_debt"]["score"]
    base = worst if worst < debt + 15 else (worst + debt) / 2
    value = 5 if base < 30 else 4 if base < 50 else 3 if base < 70 else 2 if base < 85 else 1
    return value, round(base)


def default_impact(c: dict) -> tuple:
    if c["student_data"]:
        return 4, "handles student data"
    if c["writes"]:
        return 4, "writes program data"
    if c["entry"]:
        return 3, "user- or job-facing entry point"
    return 2, "supporting component"


def risk_level(score: int) -> str:
    return next(label for floor, label in LEVELS if score >= floor)


def _no_path(c):
    return [f["title"] for f in c["findings"] if f["category"] == "eol" and any(n in f["title"] for n in NO_PATH)]


def disposition(scores: dict, facts: dict, inputs: dict) -> dict:
    S, P, H, D = (scores[k]["score"] for k in ("security", "supportability", "health", "tech_debt"))
    reasons = []

    def pick(code, *why):
        return {"code": code, "label": DISPOSITIONS[code][0], "bucket": DISPOSITIONS[code][1],
                "meaning": DISPOSITIONS[code][2], "reasons": [w for w in why if w] + reasons}

    if inputs.get("retire"):
        return pick("retire", "Marked by staff as no longer needed" + (f": {inputs['retire']}" if isinstance(inputs["retire"], str) else ""))
    no_path = facts.get("no_path") or []
    no_path_share = facts.get("no_path_share", 0)
    if inputs.get("cots"):
        return pick("replace", f"Staff decision — off-the-shelf / shared option: {inputs['cots']}" if isinstance(inputs["cots"], str)
                    else "Staff noted an off-the-shelf / shared option exists",
                    f"Scores at time of decision: tech debt {D}/100, supportability {P}/100, security {S}/100")
    if no_path and (no_path_share >= 0.5 or D < 45 or H < 50):
        return pick("rearchitect", "Built on technology with no supported upgrade path: " + "; ".join(sorted(set(no_path))[:4]),
                    f"{round(no_path_share * 100)}% of code lines are on that technology" if no_path_share else None,
                    f"Tech debt {D}/100" if D < 45 else None)
    if P < 40 and D < 40:
        return pick("rearchitect", f"Supportability {P}/100 and tech debt {D}/100 are both poor — upgrading in place "
                                   f"would touch most of the code")
    if facts.get("cobol_share", 0) >= 0.5 and P < 70 and D >= 55 and S >= 50:
        return pick("rehost", f"COBOL/CICS code is in reasonable shape (tech debt {D}/100) but the platform/skills "
                              f"are the constraint (supportability {P}/100)")
    if P < 60 and D >= 45:
        return pick("replatform", f"Supportability {P}/100: runtime or libraries past end of life but have an upgrade path",
                    f"Code is workable (tech debt {D}/100)")
    if S < 70 or D < 60 or H < 60:
        why = []
        if S < 70:
            why.append(f"Security {S}/100 ({facts.get('sec_high', 0)} critical/high finding(s))")
        if D < 60:
            why.append(f"Tech debt {D}/100")
        if H < 60:
            why.append(f"Health {H}/100")
        return pick("refactor", *why)
    return pick("retain", f"All scores fair or better (security {S}, supportability {P}, health {H}, tech debt {D})",
                "No critical or high security findings open" if not facts.get("sec_high") else None)


def confidence(coverage: dict, components: list, inputs: dict) -> dict:
    ratio = coverage.get("resolved_ratio")
    files = len(components)
    missing = (coverage.get("missing_counts") or {}).get("missing_code", 0)
    notes = []
    level = "high"
    if ratio is None or files < 5:
        level = "low"
        notes.append(f"only {files} file(s) captured")
    elif ratio < 0.6:
        level = "low"
    elif ratio < 0.85:
        level = "medium"
    if ratio is not None:
        notes.append(f"{round(ratio * 100)}% of referenced code captured ({missing} missing)")
    unconfirmed = sum(1 for c in components for f in c["findings"]
                      if f["category"] == "eol" and "not confirmed" in (f.get("detail") or ""))
    if unconfirmed:
        notes.append(f"{unconfirmed} technology version(s) unconfirmed")
        if level == "high":
            level = "medium"
    if not (inputs.get("components") or {}):
        notes.append("business criticality not entered — impact uses defaults")
    return {"level": level, "resolved_ratio": ratio, "notes": notes}
