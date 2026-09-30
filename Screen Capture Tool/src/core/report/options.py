"""Modernization options that agree with each other: a disposition per component, a program recommendation that
follows from them, option scores that reflect what each option actually removes, and an estimate built by skill set
with its basis and assumptions stated."""
import re

DISP = {"retain": "Retain", "rehost": "Re-host", "replatform": "Re-platform", "refactor": "Refactor",
        "rearchitect": "Re-architect", "rebuild": "Rebuild", "replace": "Replace", "consolidate": "Consolidate",
        "retire": "Retire"}
NO_PATH = ("Visual Basic 6", "VB6", "VBScript", "Classic ASP", "ASP.NET Web Forms", "Silverlight", "Flash", "FoxPro",
           "PowerBuilder", "ActiveX")


def _posting(c):
    n = c["name"].lower()
    return bool(re.search(r"post|payrn|pay.?run|payment", n)) and c["layer"] in ("Application", "Data") and \
        (c["writes"] or "Batch" in c["role"] or "procedures" in c["role"])


def components(AM, techs, sec_f, texts=None, fin=False, legacy_ui=(), copies=False):
    """One disposition per component, with the reason and the skill set the work needs."""
    no_path = {t.get("file") for t in techs if t.get("status") in ("eol", "legacy")
               and any(k.lower() in (t.get("name") or "").lower() for k in NO_PATH)}
    eol = {t.get("file") for t in techs if t.get("status") in ("eol", "extended", "ending")}
    posting = [c for c in AM["components"] if _posting(c)] if fin else []
    out = []
    for c in AM["components"]:
        n, role, plat, lang = c["name"], c["role"], c["platform"], (c["language"] or "")
        fs = [f for f in sec_f if (f.get("title") or "").split(": ")[-1].startswith(n)]
        if n in no_path:
            d, why = "rearchitect", f"{lang or 'its technology'} has no supported upgrade path, so it must be rewritten; " \
                                    "its calculation logic moves into a service the new front end calls"
            skill = "VB6 to .NET rewrite" if "Visual Basic" in lang or "VB6" in plat else "Rewrite"
        elif role == "3270 terminal screen" or (role.startswith("Interactive") and "EXEC CICS" in (texts or {}).get(n, "")):
            d, why = "replace", "online inquiry on a terminal screen; replaced by the web front end over the new API, " \
                                "retiring the CICS transaction"
            skill = "COBOL/CICS" if role != "3270 terminal screen" else "Web front end"
        elif c["layer"] == "Presentation" and (n in legacy_ui or n in eol or fs):
            d, why = "rebuild", "screen or web page rebuilt in the new front end" + (
                f"; its {len(fs)} security finding(s) are fixed now" if fs else "")
            skill = "Web front end"
        elif role == "Database definition":
            ims = "IMS" in lang or "Assembl" in lang or "DBD" in _text(c)
            d, why = ("retain", "keep until the system-of-record decision (5.5); then migrate the data to the chosen store"
                      + (" and retire the IMS database" if ims else "")) if copies else ("retain", "keep; the data definition is sound")
            skill = "IMS / data migration" if ims else "Data migration"
        elif c in posting and len(posting) > 1 and plat not in ("IBM mainframe (z/OS)",):
            others = [p["name"] for p in posting if p is not c]
            d, why = "consolidate", f"one of {len(posting)} components that post or calculate payments (also {', '.join(others[:3])}); " \
                                    "keep one posting service and retire the others"
            skill = {"IBM i (AS/400)": "RPG / IBM i", "Oracle Database": "PL/SQL / Oracle",
                     "Microsoft .NET (Windows server)": "C# / .NET"}.get(plat, "Application developer")
        elif n in eol or plat == "Microsoft .NET (Windows server)":
            d, why = "replatform", f"move to a supported runtime (for .NET Framework MVC, current .NET) and become part " \
                                   f"of the API layer; fix the {len(fs)} security finding(s) first" if fs else \
                                   "move to a supported runtime and become part of the API layer"
            skill = "C# / .NET" if ".NET" in plat else "Application developer"
        else:
            d, why = "retain", ("the batch code is workable; keep it through the transition, fix its findings, and decide "
                                "re-host or rebuild with the data consolidation") if "Batch" in role else \
                "keep with routine maintenance; fix its findings"
            skill = {"IBM mainframe (z/OS)": "COBOL/CICS", "IBM i (AS/400)": "RPG / IBM i",
                     "Oracle Database": "PL/SQL / Oracle"}.get(plat, "Application developer")
        out.append({"name": n, "code": d, "label": DISP[d], "why": why, "skill": skill, "platform": plat,
                    "lines": c.get("lines") or 0, "findings": len(fs), "layer": c["layer"]})
    return out


def _text(c):
    return " ".join(c.get("routines") or []) + " " + (c.get("role") or "")


def program(cds, platforms) -> dict:
    codes = [c["code"] for c in cds]
    changing = [c for c in cds if c["code"] in ("rearchitect", "replace", "rebuild", "consolidate", "replatform")]
    if any(c in ("rearchitect", "replace") for c in codes) and (platforms >= 3 or len(changing) >= 3):
        code, label = "rearchitect", "Re-architect (phased, by component)"
        meaning = ("move to a service-based architecture in stages: keep what is sound while the front ends, business "
                   "logic and data are rebuilt or consolidated component by component")
    elif changing:
        rank = ["rearchitect", "replace", "replatform", "consolidate", "rebuild"]
        top = min(changing, key=lambda c: rank.index(c["code"]))
        code, label = ("refactor", "Retain and modernize selected components") if top["code"] == "rebuild" else (top["code"], DISP[top["code"]])
        meaning = (f"keep the application and {DISP[top['code']].lower()} {', '.join(c['name'] for c in changing if c['code'] == top['code'])}"
                   f": {top['why']}")
    else:
        code, label, meaning = "retain", "Retain", "keep the application and fix its findings in place"
    return {"code": code, "label": label, "meaning": meaning,
            "counts": {DISP[k]: codes.count(k) for k in dict.fromkeys(codes)}}


CRITERIA = ["Risk reduction", "Business value", "Technical debt retired", "Implementation complexity",
            "Reduction in IT dependency", "Alignment with client enterprise", "Alignment with industry"]


def scores(facts) -> list:
    """(name, [7 scores], reason). 5 is always the most favourable; for implementation complexity 5 = least complex."""
    np_ = facts["no_path"]
    plats = facts["platforms"]
    opts = {
        "Re-architect (phased)": ([5, 4, 5, 2, 4, 5, 4],
                                  "removes the end-of-life components"
                                  + (f", consolidates the {facts['posting']} posting implementations" if facts["posting"] > 1 else "")
                                  + " and names a system of record; the most change, done in stages."),
        "Replace (commercial or shared solution)": ([5, 4, 5, 2, 5, 4, 4],
                                                    "could retire all custom code, but depends on a market fit that has "
                                                    "not been assessed and on migrating every data copy."),
        "Re-platform": ([3 if np_ else 4, 3, 2, 3, 2, 3, 3],
                        ("moves runtimes to supported versions, but " + ", ".join(np_) + " has no upgrade path, so its "
                         "end-of-life exposure stays; platform count is unchanged.") if np_ else
                        "moves runtimes to supported versions with targeted change; platform count is unchanged."),
        "Refactor (keep all platforms)": ([2 if np_ else 3, 2, 3, 4, 1, 2, 2],
                                          ("fixes security and code issues in place, but leaves " + ", ".join(np_) +
                                           f" unsupported and all {plats} platforms and skill sets in place.")
                                          if np_ else f"fixes issues in place; keeps all {plats} platforms."),
        "Retain": ([1, 1, 1, 5, 1, 1, 1], "no disruption, but every finding and end-of-life exposure stays open."),
    }
    first = "Re-architect (phased)" if facts["program_code"] == "rearchitect" else "Re-platform"
    order = [first] + [k for k in ("Replace (commercial or shared solution)", "Refactor (keep all platforms)", "Re-platform")
                       if k != first][:2]
    return [(k, opts[k][0], opts[k][1]) for k in order]


WEIGHTS = [25, 20, 15, 15, 10, 10, 5]

# person-weeks (low, high) for the work each disposition needs on one component of the size provided
EFFORT = {"retain": (0.5, 1.5), "replatform": (3, 6), "rearchitect": (6, 12), "rebuild": (3, 6), "replace": (2, 4),
          "consolidate": (3, 6), "retire": (0.5, 1)}


def estimate(cds, facts) -> dict:
    """Effort by skill set, with the basis for each line, plus the cross-cutting work the change needs."""
    lines = {}

    def add(skill, work, lo, hi, basis):
        g = lines.setdefault(skill, {"skill": skill, "work": [], "lo": 0.0, "hi": 0.0, "basis": []})
        g["work"].append(work)
        g["lo"] += lo
        g["hi"] += hi
        if basis not in g["basis"]:
            g["basis"].append(basis)
    for c in cds:
        lo, hi = EFFORT[c["code"]]
        scale = max(1.0, c["lines"] / 150)
        add(c["skill"], f"{c['label']} {c['name']}", lo * scale, hi * scale,
            f"{c['label'].lower()}: {EFFORT[c['code']][0]:g}–{EFFORT[c['code']][1]:g} person-weeks per component of up to "
            f"150 lines, scaled by size")
        if c["findings"]:
            add("Security remediation", f"fix {c['findings']} finding(s) in {c['name']}", 0.3 * c["findings"],
                0.8 * c["findings"], "0.3–0.8 person-weeks per finding, including retest")
    changing = [c for c in cds if c["code"] not in ("retain", "retire")]
    if changing:
        add("Test and QA", "characterization tests from current outputs for the logic that changes",
            2 + 0.5 * len(changing), 4 + len(changing), "a test harness is a prerequisite for changing business logic")
    if facts["fin"] and changing:
        add("Test and QA", "parallel runs over at least two payment cycles", 3, 6,
            "old and new results compared line by line before cutover")
    if facts["copies"]:
        add("Data migration and reconciliation", f"system-of-record decision, reconciliation and migration of "
                                                 f"{facts['copies']} entity copies", 1.5 * facts["copies"], 3 * facts["copies"],
            "1.5–3 person-weeks per data copy to map, reconcile and migrate")
    add("Architecture and delivery management", "target design, decisions, coordination across teams", 0, 0,
        "15% of the build effort")
    total_lo = sum(g["lo"] for g in lines.values())
    total_hi = sum(g["hi"] for g in lines.values())
    g = lines["Architecture and delivery management"]
    g["lo"], g["hi"] = total_lo * 0.15, total_hi * 0.15
    total_lo, total_hi = total_lo * 1.15, total_hi * 1.15
    skills = [k for k in lines if k not in ("Architecture and delivery management",)]
    team = max(3, min(8, len(skills)))
    months = (round(total_lo / team / 4.3 + 0.5), round(total_hi / team / 4.3 + 1.5))
    return {"lines": list(lines.values()), "low": round(total_lo), "high": round(total_hi), "team": team, "months": months,
            "skills": skills}


def sequence(facts) -> list:
    """Work ordered by dependency: fix exposure, settle the data, build the safety net, then change.
    facts: fin, fixes (list of plain fixes), copies, consolidate, front_end, platforms, phased."""
    cyc = "payment cycle" if facts["fin"] else "business peak"
    out, m = [], 0
    fixes = facts.get("fixes") or []
    if fixes:
        out.append(("0. Stabilize (months 0–3)", "Fix the security and control findings in place: " + "; ".join(fixes[:4]) + "."))
    out.append(("1. Settle the boundary and the data (months 1–4)",
                "Confirm the application boundary and provide any missing code"
                + ("; name the system of record for each entity (5.5) and reconcile the copies. Nothing is rebuilt before "
                   "this decision." if facts.get("copies") else ".")))
    if facts.get("changing"):
        out.append(("2. Build the safety net (months 2–5)", "Characterization tests from current outputs"
                    + ("; control totals on every file exchange; the parallel-run approach agreed with finance." if facts["fin"] else ".")))
        out.append(("3. Services first (months 4–12)", "Expose the business logic through an API"
                    + ("; consolidate the posting implementations into one service on the chosen data store." if facts.get("consolidate") else ".")))
    if facts.get("front_end"):
        out.append(("4. Front ends (months 8–18)", "Replace the legacy screens with one accessible web front end on the "
                    "API, screen by screen."))
    if facts.get("platforms", 1) >= 3 and facts.get("phased"):
        out.append(("5. Data consolidation and platform exit (months 12–30)", "Migrate the remaining copies to the system "
                    "of record and retire the platforms no longer needed, one at a time."))
    out.append(("Constraint", f"No cutover during a {cyc} or year-end; each step keeps the old path available until the "
                "results agree."))
    return out


def elapsed(facts, est) -> str:
    if facts.get("phased") and facts.get("platforms", 1) >= 3:
        return "18–30 months elapsed"
    if facts.get("phased"):
        return "9–18 months elapsed"
    return f"{est['months'][0]}–{est['months'][1]} months elapsed"
