"""Modernization options that agree with each other: a disposition per component, a program recommendation that
follows from them, option scores that reflect what each option actually removes, and an estimate built by skill set
with its basis and assumptions stated."""
import re

DISP = {"retain": "Retain", "rehost": "Re-host", "replatform": "Re-platform", "refactor": "Refactor",
        "rearchitect": "Re-architect", "rebuild": "Rebuild", "replace": "Replace", "consolidate": "Consolidate",
        "retire": "Retire", "covered": "Covered"}
NO_PATH = ("Visual Basic 6", "VB6", "VBScript", "Classic ASP", "ASP.NET Web Forms", "Silverlight", "Flash", "FoxPro",
           "PowerBuilder", "ActiveX")


def _posting(c):
    n = c["name"].lower()
    return bool(re.search(r"post|payrn|pay.?run|payment", n)) and "controller" not in n and c["layer"] in ("Application", "Data") and \
        (c["writes"] or "Batch" in c["role"] or "procedures" in c["role"])


def components(AM, techs, sec_f, texts=None, fin=False, legacy_ui=(), copies=False, cics=False, screen_copies=None):
    """One disposition per component, with the reason and the skill set the work needs."""
    cobol = "COBOL/CICS" if cics else "COBOL"
    no_path = {t.get("file") for t in techs if t.get("status") in ("eol", "legacy")
               and any(k.lower() in (t.get("name") or "").lower() for k in NO_PATH)}
    eol = {t.get("file") for t in techs if t.get("status") in ("eol", "extended", "ending")}
    posting = [c for c in AM["components"] if _posting(c)] if fin else []
    out = []
    for c in AM["components"]:
        n, role, plat, lang = c["name"], c["role"], c["platform"], (c["language"] or "")
        fs = [f for f in sec_f if _ev_file(f) == n]
        cobol = "COBOL/CICS" if re.search(r"\bEXEC\s+CICS\b", (texts or {}).get(n, ""), re.I) else "COBOL"
        if n in (screen_copies or {}):
            out.append({"name": n, "code": "covered", "label": "Covered", "why": f"a screen image of the page in "
                        f"{screen_copies[n]}; it is covered by that page's disposition", "skill": "–", "platform": plat,
                        "lines": 0, "findings": 0, "layer": c["layer"]})
            continue
        if n in no_path:
            d, why = "rearchitect", f"{lang or 'its technology'} has no supported upgrade path, so it must be rewritten; " \
                                    "its calculation logic moves into a service the new front end calls"
            skill = "VB6 to .NET rewrite" if "Visual Basic" in lang or "VB6" in plat else "Rewrite"
        elif role == 'BMS map source':
            d, why = 'retain', 'provisionally retain map source; assess user tasks, accessibility and supported channels before choosing interface replacement'
            skill = cobol
        elif role == "3270 terminal screen" or (role.startswith("Interactive") and "EXEC CICS" in (texts or {}).get(n, "")):
            d, why = "retain", "provisionally retain current behavior; characterize transaction boundaries and user tasks before deciding on service exposure or interface replacement"
            skill = cobol if role != "3270 terminal screen" else "Web front end"
        elif c["layer"] == "Presentation" and (n in legacy_ui or n in eol or fs):
            d, why = "rebuild", "screen or web page rebuilt in the new front end" + (
                f"; its {len(fs)} security finding{'s are' if len(fs) != 1 else ' is'} fixed now" if fs else "")
            skill = "Web front end"
        elif role == "Database definition":
            ims = "IMS" in lang or "Assembl" in lang or "DBD" in _text(c)
            d, why = ("retain", "keep until the system-of-record decision (5.5); then migrate the data to the chosen store"
                      + (" and evaluate IMS retirement" if ims else "")) if copies else ("retain", "provisionally retain; confirm constraints, data semantics and deployed usage")
            skill = "IMS / data migration" if ims else "Data migration"
        elif c in posting and len(posting) > 1 and plat not in ("IBM mainframe (z/OS)",):
            others = [p["name"] for p in posting if p is not c]
            d, why = "consolidate", f"one of {len(posting)} components that post or calculate payments (also {', '.join(others[:3])}); " \
                                    "keep one posting service and retire the " + ("other" if len(posting) == 2 else "others")
            skill = {"IBM i (AS/400)": "RPG / IBM i", "Oracle Database": "PL/SQL / Oracle",
                     "Microsoft .NET (host to confirm)": "C# / .NET"}.get(plat, "Application developer")
        elif n in eol or (plat == "Microsoft .NET (host to confirm)"
                         and re.search(r"\bSystem\.Web\b", (texts or {}).get(n, ""))):
            d, why = "replatform", f"move to a supported runtime (for .NET Framework MVC, current .NET) and become part " \
                                   f"of the API layer; fix the {len(fs)} security finding(s) first" if fs else \
                                   "move to a supported runtime and become part of the API layer"
            skill = "C# / .NET" if ".NET" in plat else "Application developer"
        else:
            d, why = "retain", ("the batch code is workable; keep it through the transition, fix its findings, and decide "
                                "whether to keep or rebuild it with the data consolidation") if "Batch" in role else \
                "keep with routine maintenance; fix its findings"
            skill = {"IBM mainframe (z/OS)": cobol, "IBM i (AS/400)": "RPG / IBM i",
                     "Oracle Database": "PL/SQL / Oracle"}.get(plat, "Application developer")
        out.append({"name": n, "code": d, "label": DISP[d], "why": why, "skill": skill, "platform": plat,
                    "lines": c.get("lines") or 0,
                    "findings": len([f for f in fs if f.get("rule") != "CVE"]) + (1 if any(f.get("rule") == "CVE" for f in fs) else 0), "layer": c["layer"]})
        if 'pl/i' in lang.lower():
            out[-1]['skill'] = 'PL/I'
        elif 'jcl' in lang.lower() or n.lower().endswith('.jcl'):
            out[-1]['skill'] = 'JCL / mainframe operations'
        elif 'rexx' in lang.lower():
            out[-1]['skill'] = 'REXX / TSO'
    return out


def _ev_file(f):
    ev = (f.get("evidence") or [{}])[0] or {}
    return ev.get("file") or (f.get("title") or "").split(": ")[-1].split(":")[0]


def P_sentence(items):
    from .plain import sentence
    return sentence(items)


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
                   f", {top['why']}")
    else:
        code, label, meaning = "retain", "Retain", "keep the application and fix its findings in place"
    return {"code": code, "label": label, "meaning": meaning,
            "counts": {DISP[k]: codes.count(k) for k in dict.fromkeys(codes)}}


CRITERIA = ["Risk reduction", "Business value", "Technical debt retired", "Implementation complexity",
            "Reduction in IT dependency", "Alignment with client enterprise", "Alignment with industry"]


OPTION = {"rearchitect": "Re-architect (phased)", "replatform": "Re-platform", "consolidate": "Consolidate",
          "refactor": "Refactor (keep all platforms)", "replace": "Replace (commercial or shared solution)",
          "retain": "Retain"}


def scores(facts) -> list:
    """(name, [7 scores], reason). 5 is always the most favourable; for implementation complexity 5 = least complex.
    The first option is always the one recommended in 12.3, so the recommendation is one of the scored options."""
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
        "Consolidate": ([4, 3, 3, 4, 3, 3, 3],
                        f"keeps the application, removes the duplicate posting implementation and fixes the findings in "
                        f"place; the {plats} platform{'s stay' if plats != 1 else ' stays'} and the data copies still need a "
                        f"system of record."),
        "Refactor (keep all platforms)": ([2 if np_ else 3, 2, 3, 4, 1, 2, 2],
                                          ("fixes security and code issues in place, but leaves " + ", ".join(np_) +
                                           f" unsupported and {'both' if plats == 2 else 'all ' + str(plats)} platforms and skill sets in place.")
                                          if np_ else "fixes issues in place; keeps " + ("both platforms." if plats == 2 else
                                                                                      f"all {plats} platforms." if plats > 2 else "the platform.")),
        "Retain": ([1, 1, 1, 5, 1, 1, 1], "no disruption, but every finding and end-of-life exposure stays open."),
    }
    first = OPTION.get(facts["program_code"], "Re-platform")
    order = [first] + [k for k in ("Replace (commercial or shared solution)", "Refactor (keep all platforms)", "Re-platform")
                       if k != first][:2]
    return [(k, opts[k][0], opts[k][1]) for k in order]


def weighted(opt) -> float:
    return sum(s * w for s, w in zip(opt[1], WEIGHTS)) / 100


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
        if c["code"] == "covered":
            continue
        lo, hi = EFFORT[c["code"]]
        scale = max(1.0, c["lines"] / 150)
        add(c["skill"], f"{c['label']} {c['name']}", lo * scale, hi * scale,
            f"{c['label'].lower()}: {EFFORT[c['code']][0]:g}–{EFFORT[c['code']][1]:g} person-weeks per component of up to "
            f"150 lines, scaled by size")
        if c["findings"]:
            add("Security remediation", f"fix {c['findings']} security issue(s) in {c['name']}", 0.3 * c["findings"],
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
                                                 f"the {facts['copies']} copies of "
                                                 + (P_sentence(facts.get("copy_names") or []) or "the shared entities")
                                                 + " data", 1.5 * facts["copies"], 3 * facts["copies"],
            "1.5–3 person-weeks per data copy to map, reconcile and migrate")
    add("Architecture and delivery management", "target design, decisions, coordination across teams", 0, 0,
        "15% of the build effort")
    g = lines["Architecture and delivery management"]
    g["lo"] = sum(x["lo"] for x in lines.values()) * 0.15
    g["hi"] = sum(x["hi"] for x in lines.values()) * 0.15
    for x in lines.values():
        lo = max(1, int(x["lo"] + 0.5)) if x["lo"] > 0 else 0
        x["lo"], x["hi"] = float(lo), float(max(int(x["hi"] + 0.5), lo))
    total_lo = sum(x["lo"] for x in lines.values())
    total_hi = sum(x["hi"] for x in lines.values())
    skills = [k for k in lines if k not in ("Architecture and delivery management",)]
    team = max(3, min(8, len(skills)))
    months = (round(total_lo / team / 4.3 + 0.5), round(total_hi / team / 4.3 + 1.5))
    return {"lines": list(lines.values()), "low": round(total_lo), "high": round(total_hi), "team": team, "months": months,
            "skills": skills}


PHASES = [  # (start, end) as fractions of the elapsed time
    ("stabilize", 0.0, 0.2), ("settle", 0.05, 0.3), ("safety", 0.15, 0.4), ("services", 0.3, 0.7), ("front", 0.45, 1.0),
    ("platform", 0.65, 1.0)]


def _window(key, span):
    import math
    a, b = next((a, b) for k, a, b in PHASES if k == key)
    lo, hi = int(a * span), max(1, math.ceil(b * span))
    return f"months {lo}–{max(hi, lo + 1)}"


def sequence(facts) -> list:
    """Work ordered by dependency: fix exposure, settle the data, build the safety net, then change. The month
    windows are fractions of the elapsed time (facts["span"]), so the order of work and the estimate agree.
    facts: fin, fixes (list of plain fixes), copies, consolidate, front_end, platforms, phased, span."""
    cyc = "payment cycle" if facts["fin"] else "business peak"
    span = facts.get("span") or 12
    out = []
    fixes = facts.get("fixes") or []
    if fixes:
        out.append((f"0. Stabilize ({_window('stabilize', span)})", "Fix the security findings listed in 1.3 and 8.3 and the "
                    "control gaps in 8.6 in place, before any other change."))
    out.append((f"1. Settle the boundary and the data ({_window('settle', span)})",
                "Confirm the application boundary and provide any missing code"
                + ("; name the system of record for each entity (5.5) and reconcile the copies. Nothing is rebuilt before "
                   "this decision." if facts.get("copies") else ".")))
    if facts.get("changing"):
        out.append((f"2. Build the safety net ({_window('safety', span)})", "Characterization tests from current outputs"
                    + ("; control totals on every file exchange; the parallel-run approach agreed with finance." if facts["fin"] else ".")))
        out.append((f"3. Services first ({_window('services', span)})", "Expose the business logic through an API"
                    + ("; consolidate the posting implementations into one service on the chosen data store." if facts.get("consolidate") else ".")))
    if facts.get("front_end"):
        out.append((f"4. Front ends ({_window('front', span)})", "Replace the legacy screens with one accessible web front "
                    "end on the API, screen by screen."))
    if facts.get("platforms", 1) >= 3 and facts.get("phased"):
        out.append((f"5. Data consolidation and platform exit ({_window('platform', span)})", "Migrate the remaining copies "
                    "to the system of record and retire the platforms no longer needed, one at a time."))
    out.append(("Constraint", f"No cutover during a {cyc} or year-end; each step keeps the old path available until the "
                "results agree."))
    return out


def months(facts, est) -> tuple:
    """(low, high) elapsed months."""
    if facts.get("phased") and facts.get("platforms", 1) >= 3:
        return 18, 30
    if facts.get("phased"):
        return 9, 18
    lo, hi = est["months"]
    if facts.get("fin"):
        lo, hi = max(lo, 3), max(hi, 4)
    return lo, max(hi, lo + 1)


def elapsed(facts, est) -> str:
    lo, hi = months(facts, est)
    return f"{lo}–{hi} months elapsed"
