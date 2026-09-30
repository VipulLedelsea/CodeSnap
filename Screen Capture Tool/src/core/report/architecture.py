"""Architectural analysis for the report: what the application is made of, how the parts connect, what that means for
any change, and an outline target architecture. Written for architects: technical names are kept, and each point
says in plain English why it matters."""

import re

PLATFORMS = [
    ("IBM mainframe (z/OS)", ("cobol", "jcl", "cics", "ims", "pl/i", "assembler", "assembly", "hlasm", "bms", "mfs", "rexx", "idms", "3270")),
    ("IBM i (AS/400)", ("rpg", "cl", "ibm i", "dds")),
    ("Windows desktop (VB6)", ("visual basic 6", "vb6", "visual basic", "vba")),
    ("Microsoft .NET (Windows server)", ("c#", ".net", "asp", "aspx", "vb.net")),
    ("Java", ("java", "jsp", "struts")),
    ("Web browser", ("html", "javascript", "jquery", "css")),
    ("Python runtime", ("python", ".py")),
    ("Node.js runtime", ("node", "typescript")),
    ("Oracle Database", ("pl/sql", "oracle")),
    ("Database server", ("sql", "db2", "t-sql")),
    ("Desktop", ("delphi", "pascal", "c++", "foxpro", "access")),
]


def _platform(lang: str, name: str, role: str = "") -> str:
    if role == "3270 terminal screen":
        return "IBM mainframe (z/OS)"
    if role in ("Web page", "Application screen") and name.lower().endswith((".screen", ".html", ".htm")):
        return "Web browser"
    key = f"{lang} {name}".lower()
    for p, keys in PLATFORMS:
        if any(k in key for k in keys):
            return p
    return "Other"


def _layer_role(art: dict, comp: dict, displays: list) -> tuple:
    t, lang, name = art.get("artifact_type") or "", (art.get("language") or ""), art["name"].lower()
    if t == "ui_screen" or name.endswith(".screen"):
        kind = "3270 terminal screen" if "3270" in name or "terminal" in (art.get("transcription") or "").lower()[:400] else "Application screen"
        return "Presentation", kind
    if comp.get("type") == "web" or name.endswith((".html", ".htm", ".asp", ".aspx", ".jsp")):
        return "Presentation", "Web page"
    if name.endswith((".dbd", ".psb", ".ddl", ".sql")) and "pl/sql" not in lang.lower() or re.search(
            r"\bDBD\s+NAME=|\bCREATE\s+TABLE\b", (art.get("transcription") or "")[:3000], re.I) and "pl/sql" not in lang.lower():
        return "Data", "Database definition"
    if lang.lower().startswith("pl/sql") or name.endswith((".pkb", ".pks")):
        return "Data", "Database procedures (business logic in the database)"
    if "jcl" in lang.lower() or name.endswith(".jcl"):
        return "Integration", "Batch job control (scheduling)"
    if displays:
        return "Application", "Interactive program (drives screens)"
    if "cobol" in lang.lower():
        return "Application", "Batch program"
    return "Application", "Program"


def build(store, a: dict, techs: list) -> dict:
    """Components, data stores, flows, observations and a target outline, from the program model."""
    ents = {e["id"]: e for e in store.entities()}
    src = {}
    for r in store._all("SELECT es.entity_id, a.name FROM entity_source es JOIN artifact a ON a.id = es.artifact_id "
                        "WHERE a.is_current = 1"):
        src.setdefault(r["entity_id"], set()).add(r["name"])
    rel = [r for r in store.relations() if r["kind"] in ("reads", "writes", "uses", "calls", "displays")]
    comps = []
    for c in a["components"]:
        art = store.artifact(c["artifact_id"]) or {"name": c["name"], "language": c.get("language")}
        mine = [r for r in rel if c["name"] in src.get(r["from_id"], set())]

        def names(kinds, target_kinds):
            out = []
            for r in mine:
                e = ents.get(r["to_id"]) or {}
                if r["kind"] in kinds and e.get("kind") in target_kinds and e["name"] not in out:
                    out.append(e["name"] + (" (not provided)" if e.get("origin") == "placeholder" else ""))
            return out
        reads = names(("reads", "uses"), ("data_store", "table", "file"))
        writes = names(("writes",), ("data_store", "table", "file"))
        reads = [x for x in reads if x not in writes]
        calls = names(("calls",), ("program", "paragraph", "procedure", "transaction"))
        calls = [x for x in calls if "(not provided)" in x or x.upper() == x]
        own = art.get("transcription") or ""
        calls = [x for x in calls if not re.search(rf"\b{re.escape(x.split(' (')[0])}\s+BEGSR\b|\bBEGSR\s+{re.escape(x.split(' (')[0])}\b"
                                                   rf"|^\s*\d*\s+{re.escape(x.split(' (')[0])}\.\s*$", own, re.M | re.I)]
        displays = names(("displays",), ("screen",))
        layer, role = _layer_role(art, c, displays)
        ts = sorted({f"{t.get('name')} {t.get('version') or t.get('cycle') or ''}".strip() for t in techs
                     if t.get("file") == c["name"]})
        routines = [e["name"] for eid, e in ents.items() if c["name"] in src.get(eid, set())
                    and e["kind"] in ("paragraph", "function", "procedure", "method", "subroutine")]
        lang = art.get("language") or c.get("language") or ""
        if role == "Database definition" and "dbd" in c["name"].lower():
            lang = "IMS DBD"
        if lang.lower() in ("ui screen", "screen", ""):
            lang = ("3270 terminal screen" if role == "3270 terminal screen" else "Web page (HTML)"
                    if layer == "Presentation" and re.search(r"https?:|www\.|<html|browser|\.gov|\.com", (art.get("transcription") or "")[:3000], re.I)
                    else "Graphical screen" if layer == "Presentation" else lang)
        comps.append({"name": c["name"], "layer": layer, "role": role, "language": lang,
                      "platform": _platform(art.get("language") or "", c["name"], role), "tech": ts, "reads": reads,
                      "writes": writes, "calls": [x for x in calls if x not in routines], "displays": displays,
                      "lines": c.get("lines", 0), "routines": routines})
    stores = {}
    for c in comps:
        for n in c["reads"]:
            stores.setdefault(n, {"readers": set(), "writers": set()})["readers"].add(c["name"])
        for n in c["writes"]:
            stores.setdefault(n, {"readers": set(), "writers": set()})["writers"].add(c["name"])
    return {"components": comps, "stores": stores, "observations": observations(store, a, comps, stores),
            "platforms": sorted({c["platform"] for c in comps})}


RULE_WORDS = ("COMPUTE", "CALC", "APPLY", "HOLDBACK", "RATE", "ELIG", "VALID", "EDIT", "PRORAT", "ADJUST")


def observations(store, a, comps, stores) -> list:
    """(title, what we see, why it matters) for the target architecture."""
    out = []
    plats = sorted({c["platform"] for c in comps})
    if len(plats) > 1:
        out.append(("The application spans several platforms",
                    f"Its {len(comps)} components run on {len(plats)} platforms: " + "; ".join(
                        f"{p} ({', '.join(c['name'] for c in comps if c['platform'] == p)})" for p in plats) + ".",
                    "Each platform needs its own skills, hosting, release process and support contract, and modernizing "
                    "one leaves the others as they are. A target architecture should reduce the number of platforms."))
    files = [n for n in stores if "FILE" in n.upper() or n.upper().endswith(("-DAT", ".DAT"))]
    if files or stores:
        out.append(("Components exchange data through files and shared data stores, not APIs",
                    f"{len(stores)} data store(s) connect the components" + (f", including {len(files)} sequential file(s) "
                    f"({', '.join(files[:4])})" if files else "") + ". No service or API layer was found.",
                    "Every file layout and shared table is an unwritten contract between programs. A replacement must "
                    "reproduce each one, and there is no single interface a new front end or partner system could use."))
    shared = [(n, s) for n, s in stores.items() if len(s["writers"] | s["readers"]) > 1]
    multi_w = [(n, s) for n, s in stores.items() if len(s["writers"]) > 1]
    if multi_w:
        out.append(("Some data has more than one writer",
                    "; ".join(f"{n} is written by {', '.join(sorted(s['writers']))}" for n, s in multi_w[:4]) + ".",
                    "With several writers there is no single owner of the data's rules, so data errors are hard to trace. "
                    "The target should give each data set one owning service."))
    elif shared:
        out.append(("Data is shared between components",
                    "; ".join(f"{n} is used by {', '.join(sorted(s['writers'] | s['readers']))}" for n, s in shared[:4]) + ".",
                    "Shared data couples the components: a change to its layout needs every user changed at the same time."))
    io = ("READ", "WRITE", "OPEN", "CLOSE", "PRINT", "INIT", "FINAL")
    rules = [(c["name"], [r for r in c["routines"] if any(w in r.upper() for w in RULE_WORDS)
                          and not any(w in r.upper() for w in io)]) for c in comps]
    rules = [(n, r) for n, r in rules if r]
    if rules:
        out.append(("Business rules sit inside the programs",
                    "Calculation and validation routines were found in the code: " + "; ".join(
                        f"{', '.join(r[:4])} in {n}" for n, r in rules[:3]) + ".",
                    "These rules are the application's real value and are undocumented outside the code. Any option other "
                    "than retain must extract them first, and ideally move them into a tested, configurable rules layer."))
    pres = [c for c in comps if c["layer"] == "Presentation"]
    if pres:
        kinds = sorted({c["role"] for c in pres})
        out.append(("The user interface is split across technologies" if len(kinds) > 1 else "The user interface is legacy technology",
                    f"Users work through {len(pres)} screen(s): " + "; ".join(f"{c['name']} ({c['role']}"
                    + (f", {', '.join(c['tech'])}" if c["tech"] else "") + ")" for c in pres) + ".",
                    ("Terminal screens and old web pages can't meet current accessibility standards and need special "
                     "skills to change. A single web front end over an API would serve every user group."
                     if any("terminal" in k.lower() for k in kinds) else
                     "Screens built on older technology are harder to keep accessible and secure; a single web front end "
                     "over an API keeps the user interface on one supported stack.")))
    cov = store.coverage()
    missing = [m for m in cov.get("missing") or [] if m["category"] == "missing_code"
               and m.get("kind") in ("program", "copybook", "job", "screen", "transaction", "procedure", "module")]
    if missing:
        out.append(("Parts of the application were not provided",
                    f"{len(missing)} referenced component(s) are missing: " + ", ".join(f"{m['name']} ({m['kind']})" for m in missing[:8]) + ".",
                    "The architecture and the risk ratings cover only what was provided; these parts could change the "
                    "picture, especially if they hold business rules or integrations."))
    from . import plain as P
    sec = [f for f in store.findings() if f.get("rule") in ("SEC-CRED", "SEC-TLS", "UIS-MIXED", "SEC-AUTH", "SEC-AUTHZ")
           and f.get("status") not in ("dismissed", "fixed")]
    if sec:
        kinds = []
        for f in sec:
            w = P.what(f["rule"], f["title"])
            n = sum(1 for g in sec if g["rule"] == f["rule"])
            w = f"{w} ({n} place{'s' if n > 1 else ''})"
            if w not in kinds:
                kinds.append(w)
        out.append(("Security is built into each program rather than provided centrally",
                    f"{len(sec)} finding(s) show this: {P.sentence(kinds)}. No shared identity service or secrets "
                    f"store is used.",
                    "Each component must be fixed separately. The target should use the organisation's identity service, "
                    "a secrets store and TLS everywhere, so security is handled once."))
    return out


TARGET = {
    "Presentation": "Replace the terminal screens and legacy web pages with one accessible web front end (WCAG 2.1 AA) "
                    "that calls the application through an API; it can be built screen by screen while the old ones run.",
    "Application": "Keep the proven business logic, but move it to a supported runtime and expose it as services (for "
                   "example REST APIs); batch programs can stay batch, run by a modern scheduler.",
    "Data": "Keep each data store with a single owning service; document file layouts as data contracts, and plan the "
            "move from files and hierarchical databases to a relational or managed store where the vendor path requires it.",
    "Integration": "Replace file drops and direct program calls with the API layer or managed file transfer, with "
                   "monitoring and retry, so each interface is visible and supported.",
}


def target_outline(model: dict, disposition_code: str) -> list:
    layers = [l for l in ("Presentation", "Application", "Data", "Integration")
              if l == "Integration" or any(c["layer"] == l for c in model["components"])]
    if disposition_code == "retain":
        return ["Retain: the current architecture stays; fix the security findings in place and document the data "
                "contracts so a later change starts from a known baseline."]
    out = [f"{l}: {TARGET[l]}" for l in layers]
    if not any(c["role"] == "3270 terminal screen" for c in model["components"]):
        out = [o.replace("the terminal screens and legacy web pages", "the legacy screens") for o in out]
    if not any("IMS" in (c["language"] or "") or c["role"] == "Database definition" for c in model["components"]):
        out = [o.replace("from files and hierarchical databases", "off legacy stores") for o in out]
    out.append("Cross-cutting: use the organisation's identity service for sign-in, a secrets store for credentials, "
               "TLS on every connection, and central logging and monitoring.")
    return out


def flows(model: dict) -> list:
    """One plain sentence per component that moves data."""
    out = []
    for c in model["components"]:
        if not (c["reads"] or c["writes"] or c["displays"] or c["calls"]):
            continue
        bits = []
        if c["role"] == "Database definition":
            out.append(f"{c['name']} (database definition): defines {', '.join(c['reads'][:5]) or 'the database structure'}.")
            continue
        if c["reads"]:
            bits.append(f"reads {', '.join(c['reads'][:5])}")
        if c["writes"]:
            bits.append(f"writes {', '.join(c['writes'][:5])}")
        if c["displays"]:
            bits.append(f"shows screens {', '.join(c['displays'][:4])}")
        if c["calls"]:
            bits.append(f"calls {', '.join(c['calls'][:4])}")
        out.append(f"{c['name']} ({c['role'].lower()}): " + "; ".join(bits) + ".")
    return out
