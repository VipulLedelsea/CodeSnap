"""Architectural analysis for the report: what the application is made of, how the parts connect, what that means for
any change, and an outline target architecture. Written for architects: technical names are kept, and each point
says in plain English why it matters."""

import re

PLATFORMS = [
    ("IBM mainframe (z/OS)", ("cobol", "jcl", "cics", "ims", "pl/i", "assembler", "assembly", "hlasm", "bms", "mfs", "rexx", "idms", "3270")),
    ("IBM i (AS/400)", ("rpg", "cl", "ibm i", "dds")),
    ("Windows desktop (VB6)", ("visual basic 6", "vb6", "visual basic", "vba")),
    ("Microsoft .NET (host to confirm)", ("c#", ".net", "asp", "aspx", "vb.net")),
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
        if any(re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", key) for k in keys):
            return p
    return "Other"


def _layer_role(art: dict, comp: dict, displays: list) -> tuple:
    t, lang, name = art.get("artifact_type") or "", (art.get("language") or ""), art["name"].lower()
    if name.endswith('.bms') and re.search(r'\bDFHM(?:SD|DI|DF)\b', art.get('transcription') or '', re.I):
        return 'Presentation', 'BMS map source'
    if t == "ui_screen" or name.endswith(".screen"):
        kind = "3270 terminal screen" if "3270" in name or "terminal" in (art.get("transcription") or "").lower()[:400] else "Application screen"
        return "Presentation", kind
    if comp.get("type") == "web" or name.endswith((".html", ".htm", ".asp", ".aspx", ".jsp")):
        return "Presentation", "Web page"
    if name.endswith((".dbd", ".psb", ".ddl", ".sql")) and "pl/sql" not in lang.lower() or re.search(
            r"\bDBD\s+NAME=|\bCREATE\s+TABLE\b", (art.get("transcription") or "")[:3000], re.I) and "pl/sql" not in lang.lower():
        return "Data", "Database definition"
    if lang.lower().startswith("pl/sql") or name.endswith((".pkb", ".pks")):
        return "Data", "Stored procedures"
    if "jcl" in lang.lower() or name.endswith(".jcl"):
        return "Integration", "Batch job control (scheduling)"
    if displays:
        return "Application", "Interactive program"
    if "cobol" in lang.lower():
        from core.cobol.detect import detect_kind
        source = art.get('transcription') or ''
        if detect_kind(source, extension=__import__('pathlib').Path(name).suffix) == 'copybook':
            return 'Data', 'Record layout copybook'
        if re.search(r'\bPROCEDURE\s+DIVISION\s+USING\b', source, re.I):
            return 'Application', 'Called subprogram'
        if re.search(r'\bSELECT\s+[\w-]+\s+ASSIGN\b|\bOPEN\s+(?:INPUT|OUTPUT|I-O)\b', source, re.I):
            return "Application", "Batch program"
        return 'Application', 'Program'
    return "Application", "Program"


def _defined_here(text):
    """Names this file itself defines as a subroutine (RPG BEGSR) or a numbered or bare paragraph header, found in one pass
    so a long file is not searched again for every name it calls."""
    names = {m.upper() for m in re.findall(r"(\S+)\s+BEGSR\b", text, re.I)}
    names |= {m.upper() for m in re.findall(r"\bBEGSR\s+(\S+)", text, re.I)}
    names |= {m.upper() for m in re.findall(r"(?m)^[ \t]*\d*[ \t]+(\S+?)\.[ \t]*$", text)}
    return names


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
        calls = [x.replace(' (not provided)', ' (standard system utility; availability to confirm)')
                 if x.split(' (')[0].upper() in ('IEFBR14', 'IEBGENER') else x for x in calls]
        own = art.get("transcription") or ""
        defined = _defined_here(own)
        calls = [x for x in calls if x.split(' (')[0].upper() not in defined]
        displays = names(("displays",), ("screen",))
        from .evidence import display_files, record_formats
        dfs = display_files([art])
        fmts = record_formats([art])
        reads = [x for x in reads if x.split(" (")[0].upper() not in dfs]
        displays = [x for x in displays if x.split(" (")[0].upper() not in fmts
                    and x.split(" (")[0].lower() != c["name"].rsplit(".", 1)[0].lower()]
        layer, role = _layer_role(art, c, displays)
        defines, define_dbs = [], []
        if role == "Database definition":
            mine_e = [e for eid, e in sorted(ents.items()) if c["name"] in src.get(eid, set())]
            define_dbs = [e["name"] for e in mine_e if e["kind"] == "data_store"
                          and "IMS" in ((e.get("attrs") or {}).get("store_type") or "")]
            defines = define_dbs + [e["name"] for e in mine_e if e["kind"] == "table"]
            reads = []
        ts = sorted({f"{t.get('name')} {t.get('version') or t.get('cycle') or ''}".strip() for t in techs
                     if t.get("file") == c["name"]})
        routines = [e["name"] for eid, e in ents.items() if c["name"] in src.get(eid, set())
                    and e["kind"] in ("paragraph", "function", "procedure", "method", "subroutine")]
        lang = art.get("language") or c.get("language") or ""
        if not lang and re.search(r'/\*\s*REXX\b', own, re.I) and re.search(r'^\s*ADDRESS\s+TSO\b', own, re.M | re.I):
            lang = 'REXX'
        if role == "Database definition" and ("dbd" in c["name"].lower() or re.search(r"\bDBD\s+NAME=", art.get("transcription") or "")):
            lang = "IMS DBD"
        if lang.lower() in ("ui screen", "screen", ""):
            lang = ("3270 terminal screen" if role == "3270 terminal screen" else "Web page (HTML)"
                    if layer == "Presentation" and re.search(r"https?:|www\.|<html|browser|\.gov|\.com", (art.get("transcription") or "")[:3000], re.I)
                    else "Graphical screen" if layer == "Presentation" else lang)
        comps.append({"name": c["name"], "layer": layer, "role": role, "language": lang,
                      "platform": _platform(lang, c["name"], role), "tech": ts, "reads": reads,
                      "writes": writes, "calls": [x for x in calls if x not in routines], "displays": displays,
                      "lines": c.get("lines", 0), "routines": routines, "defines": defines,
                      "define_dbs": define_dbs})
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
                    "Changes across these platforms may need different development and deployment skills. Confirm hosting, "
                    "release ownership and support arrangements before planning the transition."))
    files = [n for n in stores if "FILE" in n.upper() or n.upper().endswith(("-DAT", ".DAT"))]
    plat_of = {c["name"]: c["platform"] for c in comps}
    shared = [(n, s) for n, s in stores.items() if len(s["writers"] | s["readers"]) > 1
              and len({plat_of.get(x) for x in s["writers"] | s["readers"]}) == 1]
    apis = [e["name"] for e in store.entities("api_endpoint")]
    if shared:
        out.append(("Components exchange data through files and shared data stores" + (", alongside identified APIs" if apis else ""),
                    f"{len(shared)} data store{'s connect' if len(shared) > 1 else ' connects'} the components ("
                    + ", ".join(n for n, _ in shared[:4]) + ")." + (f" {len(apis)} web endpoint(s) were identified ({', '.join(apis[:3])})."
                                                                  if apis else " No service or API layer was found."),
                    "Programs using the same record layout or table depend on that structure. Review those dependencies before "
                    "changing it; the available code does not establish whether other interfaces exist."))
    elif stores and not apis:
        out.append(("No service or API layer was identified in the supplied code",
                    f"Each component works on its own files and tables: no data store is used by more than one "
                    f"component on the same platform" + (f", and {len(files)} file names ({', '.join(files[:4])}) suggest file-based integration; confirm whether they go to "
                    f"or come from systems outside the code provided" if files else "") + ". No service or API layer was found.",
                    "Confirm file producers, consumers and record layouts before changing these interfaces. Record expected "
                    "inputs and outputs in interface tests."))
    multi_w = [(n, s) for n, s in stores.items() if len(s["writers"]) > 1]
    if multi_w:
        out.append(("Some data has more than one writer",
                    "; ".join(f"{n} is written by {', '.join(sorted(s['writers']))}" for n, s in multi_w[:4]) + ".",
                    "Several writers can apply different validation rules. Confirm ownership and compare their update paths. "
                    "The target should give each data set one owning service."))
    elif shared:
        out.append(("Data is shared between components",
                    "; ".join(f"{n} is used by {', '.join(sorted(s['writers'] | s['readers']))}" for n, s in shared[:4]) + ".",
                    "Shared data creates a schema dependency. A layout change may require coordinated updates to its readers and writers."))
    io = ("READ", "WRITE", "OPEN", "CLOSE", "PRINT", "INIT", "FINAL")
    rules = [(c["name"], [r for r in c["routines"] if any(w in r.upper() for w in RULE_WORDS)
                          and not any(w in r.upper() for w in io)]) for c in comps]
    rules = [(n, r) for n, r in rules if r]
    if rules:
        out.append(("Routine names suggest business-rule responsibilities",
                    "Routine names suggest calculation or validation responsibilities: " + "; ".join(
                        f"{', '.join(r[:4])} in {n}" for n, r in rules[:3]) + ".",
                    "Review the routine bodies and compare them with business specifications. Before an option other "
                    "than retain changes these routines, establish expected inputs and outputs with characterization tests."))
    pres = [c for c in comps if c["layer"] == "Presentation"]
    if pres:
        kinds = sorted({c["role"] for c in pres})
        out.append(("The user interface is split across technologies" if len(kinds) > 1 else "The supplied user interface",
                    f"The {len(pres)} screen file(s) provided: " + "; ".join(f"{c['name']} ({c['role']}"
                    + (f", {', '.join(c['tech'])}" if c["tech"] else "") + ")" for c in pres) + ".",
                    ("Terminal interfaces need accessibility testing with the intended assistive tools. Review the web pages against the agreed "
                     "accessibility target. A web front end is one option; user needs and integration constraints remain to confirm."
                     if any("terminal" in k.lower() for k in kinds) else
                     "The screen files show the presentation structure. Confirm supported browsers, accessibility and security requirements before "
                     "choosing whether to retain or replace the interface.")))
    cov = store.coverage()
    from .evidence import display_files, record_formats
    fmts = record_formats(store.artifacts())
    missing = [m for m in cov.get("missing") or [] if m["category"] == "missing_code" and m["name"].upper() not in fmts
               and m.get("kind") in ("program", "copybook", "job", "screen", "transaction", "procedure", "module")]
    if missing:
        out.append(("Parts of the application were not provided",
                    f"{len(missing)} referenced component(s) are missing: " + ", ".join(
                        f"{m['name']} ({'display file' if m['name'].upper() in display_files(store.artifacts()) else m['kind']})"
                        for m in missing[:8]) + ".",
                    "The architecture and the risk ratings cover only what was provided; these parts could change the "
                    "picture, especially if they hold business rules or integrations."))
    from . import plain as P
    sec = [f for f in store.findings() if f.get("rule") in ("SEC-CRED", "UIS-PREFILL", "SEC-TLS", "UIS-MIXED", "SEC-AUTH", "SEC-AUTHZ")
           and f.get("status") not in ("dismissed", "fixed")]
    if sec and len({(f.get("evidence") or [{}])[0].get("file") for f in sec}) >= 2:
        kinds = []
        for f in sec:
            w = P.describe(f)[0]
            n = sum(1 for g in sec if g["rule"] == f["rule"])
            w = P.tagged(w, f"{n} place{'s' if n > 1 else ''}") if n > 1 else w
            if w not in kinds:
                kinds.append(w)
        out.append(("Security findings occur in several components",
                    f"{len(sec)} finding(s) were identified: {P.sentence(kinds)}. The findings do not establish whether a central identity service or secrets "
                    f"store is configured elsewhere; confirm the deployment settings.",
                    "Check each affected component and any shared security configuration. Where available, use the organisation's identity service, "
                    "a secrets store and TLS for relevant connections."))
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


def _names(items, n):
    """A list of names with "(not provided)" said once when it applies to all of them."""
    items = list(dict.fromkeys(items))[:n]
    gone = [i for i in items if i.endswith(" (not provided)")]
    if len(gone) == len(items) and len(items) > 1:
        return ", ".join(i[:-len(" (not provided)")] for i in items) + " (none provided)"
    return ", ".join(items)


def flows(model: dict) -> list:
    """One plain sentence per component that moves data."""
    out = []
    for c in model["components"]:
        if not (c["reads"] or c["writes"] or c["displays"] or c["calls"] or c.get("defines")):
            continue
        bits = []
        if c["role"] == "Database definition":
            d = c.get("defines") or []
            dbs = c.get("define_dbs") or []
            segs = [x for x in d if x not in dbs]
            from .plain import sentence
            out.append(f"{c['name']} (database definition): defines "
                       + ((f"the IMS database {dbs[0]}" if "IMS" in (c["language"] or "") else f"database {dbs[0]}")
                          + (f" with segments {sentence(segs[:6])}" if segs else "") if dbs else
                          sentence(d[:6]) if d else "the database structure") + ".")
            continue
        for key, verb, n in (("reads", "reads", 5), ("writes", "writes", 5), ("displays", "shows screens", 4),
                             ("calls", "calls", 4)):
            if c[key]:
                bits.append(f"{verb} {_names(c[key][:n + 4], n)}")
        out.append(f"{c['name']} ({c['role'].lower()}): " + "; ".join(bits) + ".")
    return out
