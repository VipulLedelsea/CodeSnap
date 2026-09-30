"""Data architecture from the code: which business data lives where, who writes it, and whether a system of record
can be named. The point an architect needs is not the list of stores but the conclusion they point to: the same
business entity kept in several places on different platforms, with no visible owner or reconciliation."""
import re

STEMS = [
    ("DISTRICT", "District"), ("PAYMENT", "Payment"), ("ADJUSTMENT", "Adjustment"), ("ADJUST", "Adjustment"),
    ("ENTITLEMENT", "Entitlement"), ("ENTITLE", "Entitlement"), ("STUDENT", "Student"), ("SCHOOL", "School"),
    ("CUSTOMER", "Customer"), ("ACCOUNT", "Account"), ("INVOICE", "Invoice"), ("ORDER", "Order"), ("CLAIM", "Claim"),
    ("EMPLOYEE", "Employee"), ("VENDOR", "Vendor"), ("SUPPLIER", "Vendor"), ("PRODUCT", "Product"), ("POLICY", "Policy"),
    ("MEMBER", "Member"), ("PROVIDER", "Provider"), ("PERSON", "Person"), ("CONTRACT", "Contract"), ("GRANT", "Grant"),
    ("BUDGET", "Budget"), ("LEDGER", "Ledger"), ("TRANSACTION", "Transaction"), ("CASE", "Case"), ("LICENSE", "License"),
    ("PERMIT", "Permit"), ("ENROLL", "Enrollment"), ("COURSE", "Course"), ("STAFF", "Staff"), ("TEACHER", "Staff"),
    ("PAYROLL", "Payroll"), ("RATE", "Rate"),
    ("DIST", "District"), ("PAY", "Payment"), ("ADJ", "Adjustment"), ("CUST", "Customer"), ("ACCT", "Account"),
    ("INV", "Invoice"), ("EMP", "Employee"), ("STU", "Student"), ("VEND", "Vendor"), ("TXN", "Transaction"),
]
ROLE = [("STAGING", "staging"), ("STAGE", "staging"), ("HISTORY", "history"), ("HIST", "history"), ("BATCH", "batch"),
        ("RUN", "run control"), ("MST", "master"), ("MASTER", "master"), ("FILE", "file"), ("ADM", "membership")]
SKIP = re.compile(r"REPORT|RPT|AUDIT|\.LOG$|\bLOG\b|PRINT|SYSOUT", re.I)


def _norm(name):
    return re.sub(r"[^A-Z0-9]", "_", name.split(".")[-1].upper())


def _prefix(names):
    """A short application prefix shared by several names (AID in AIDPAY, AID_RUN, AIDDSP), to strip before matching."""
    counts = {}
    for n in names:
        n = _norm(n)
        for k in (3, 4):
            if len(n) > k + 2:
                counts[n[:k]] = counts.get(n[:k], 0) + 1
    best = max(counts.items(), key=lambda kv: (kv[1], len(kv[0])), default=(None, 0))
    return best[0] if best[1] >= 3 and not any(best[0] == s for s, _ in STEMS) else None


def entity_of(name, prefix=None):
    n = _norm(name)
    cands = [n]
    if prefix and n.startswith(prefix):
        cands.append(n[len(prefix):].lstrip("_"))
    for c in cands:
        for stem, ent in STEMS:
            if c.startswith(stem):
                return ent
    for c in cands:
        for tok in c.split("_"):
            for stem, ent in STEMS:
                if len(stem) >= 5 and tok.startswith(stem):
                    return ent
    return None


def role_of(name, prefix=None):
    n = _norm(name)
    for k, r in ROLE:
        if re.search(rf"(^|_|[A-Z]){k}(_|$)", n) or n.endswith(k):
            return r
    return ""


def _engine(art, store_ent):
    """Where a component keeps this store: IMS, mainframe files or Db2, IBM i, Oracle, SQL Server or a local file."""
    at = store_ent.get("attrs") or {}
    lang = (art.get("language") or "").lower()
    text = art.get("transcription") or ""
    mainframe = any(k in lang for k in ("cobol", "assembl", "pl/i", "jcl", "ims"))
    if (at.get("ims_segment") or "IMS" in (at.get("store_type") or "")) and (mainframe or not sql_server(text)):
        return "IBM mainframe (IMS)"
    if at.get("store_type") == "file" or store_ent["kind"] == "file":
        if re.match(r"^[A-Za-z]:\\", store_ent["name"]):
            return "Windows desktop (local file)"
        if "cobol" in lang or "jcl" in lang:
            return "IBM mainframe (files)"
        return "File"
    if "cobol" in lang and re.search(r"EXEC\s+SQL", text, re.I):
        return "IBM mainframe (Db2)"
    if "rpg" in lang or lang in ("cl", "ibm i"):
        return "IBM i (Db2 for i)"
    if "pl/sql" in lang or "plsql" in lang or re.search(r"CREATE\s+OR\s+REPLACE\s+PACKAGE", text, re.I):
        return "Oracle Database"
    cat = catalog(text)
    if sql_server(text):
        return f"SQL Server ({cat})" if cat else "SQL Server"
    return "Database (engine not identified)"


def catalog(text):
    m = re.search(r"Initial\s+Catalog\s*=\s*([^;\"']+)", text or "", re.I)
    return m.group(1).strip() if m else ""


def host(text):
    m = re.search(r"(?:Data\s+Source|Server)\s*=\s*([^;\"']+)", text or "", re.I)
    return m.group(1).strip() if m else ""


def sql_server(text) -> bool:
    return bool(re.search(r"System\.Data\.SqlClient|Microsoft\.Data\.SqlClient|SqlConnection|SQLOLEDB|SQLNCLI|"
                          r"Driver=\{SQL Server|\bdbo\.", text or "", re.I))


def _display_file(store, e):
    for s in _sources(store, e["id"]):
        art = s
        if re.search(rf"^\s*F{re.escape(e['name'])}\s+.*\bWORKSTN\b", art.get("transcription") or "", re.I | re.M):
            return True
    return False


def _sources(store, eid):
    rows = store._all("SELECT a.* FROM entity_source es JOIN artifact a ON a.id = es.artifact_id "
                      "WHERE a.is_current = 1 AND es.entity_id = ?", (eid,))
    return [dict(r) for r in rows]


def model(store, AM=None) -> dict:
    arts = {a["id"]: a for a in store.artifacts()}
    ents = [e for e in store.entities() if e["kind"] in ("table", "data_store", "file")]
    prefix = _prefix([e["name"] for e in ents])
    occ, containers, displays = [], [], []
    for e in ents:
        at = e.get("attrs") or {}
        if e["kind"] == "file":
            continue
        if e["kind"] == "data_store" and _display_file(store, e):
            displays.append(e["name"])
            continue
        if e["kind"] == "data_store" and at.get("store_type") in ("database", "IMS database") or (
                e["kind"] == "data_store" and at.get("dbd") is None and "IMS" in (at.get("store_type") or "")):
            containers.append(e)
            continue
        if e["kind"] == "data_store" and e["origin"] == "placeholder" and not store.relations(to_id=e["id"]):
            continue
        rels = [r for r in store.relations(to_id=e["id"]) if r["kind"] in ("reads", "writes", "uses", "contains", "defines")]
        by_art = {}
        for r in rels:
            aid = r.get("artifact_id")
            if aid not in arts:
                continue
            k = r["kind"]
            acc = by_art.setdefault(aid, set())
            acc.add("W" if k == "writes" else "R" if k in ("reads", "uses") else "D")
        for aid, acc in by_art.items():
            if acc == {"D"} and e["kind"] != "table":
                continue
            art = arts[aid]
            occ.append({"entity_id": e["id"], "store": e["name"], "component": art["name"], "engine": _engine(art, e),
                        "access": "".join(x for x in "DRW" if x in acc), "placeholder": e["origin"] == "placeholder",
                        "business": entity_of(e["name"], prefix), "role": role_of(e["name"], prefix),
                        "skip": bool(SKIP.search(e["name"]))})
    by_comp_writes = {}
    for o in occ:
        if o["business"] and "W" in o["access"]:
            by_comp_writes.setdefault(o["component"], set()).add(o["business"])
    for o in occ:
        if not o["business"] and not o["skip"]:
            w = by_comp_writes.get(o["component"]) or set()
            if len(w) == 1:
                o["business"], o["inferred"] = next(iter(w)), True
    groups = {}
    for o in occ:
        if o["skip"] or not o["business"]:
            continue
        g = groups.setdefault(o["business"], {"name": o["business"], "occ": [], "copies": []})
        g["occ"].append(o)
        key = (o["store"].split(".")[-1].upper(), o["engine"])
        if key not in [(c["store"].split(".")[-1].upper(), c["engine"]) for c in g["copies"]]:
            g["copies"].append(o)
    entities = sorted(groups.values(), key=lambda g: -len(g["copies"]))
    for g in entities:
        g["platforms"] = sorted({_plat(o["engine"]) for o in g["copies"]})
        g["engines"] = sorted({o["engine"] for o in g["copies"]})
        g["writers"] = sorted({o["component"] for o in g["occ"] if "W" in o["access"]})
        g["definers"] = sorted({o["component"] for o in g["occ"] if "D" in o["access"]})
        g["readers"] = sorted({o["component"] for o in g["occ"] if "R" in o["access"]} - set(g["writers"]))
    dup = []
    names = [c["name"] for c in containers]
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            na, nb = _norm(a), _norm(b)
            if na != nb and (na.startswith(nb) or nb.startswith(na)) and min(len(na), len(nb)) >= 5:
                dup.append((a, b))
    comps_text = " ".join((a.get("transcription") or "") for a in arts.values())
    sqls = sorted({f"{catalog(a.get('transcription'))} on {host(a.get('transcription'))}".strip(" on")
                   for a in arts.values() if sql_server(a.get("transcription")) and catalog(a.get("transcription"))})
    return {"entities": entities, "occurrences": occ, "containers": containers, "duplicates": dup,
            "displays": displays, "prefix": prefix, "sql_server": sqls if sql_server(comps_text) else [],
            "db2": any("cobol" in (a.get("language") or "").lower() and re.search(r"EXEC\s+SQL", a.get("transcription") or "", re.I)
                       for a in arts.values()),
            "lineage": lineage(occ), "reconciliation": reconciliation(arts.values())}


def _plat(engine):
    return engine.split(" (")[0] if not engine.startswith("SQL Server") else "SQL Server"


def lineage(occ) -> list:
    """Paths from inputs through components to outputs: 'ENTITLE-FILE, ADJUST-FILE → AIDPAYRN.cbl → PAYMENT-FILE'."""
    comps = {}
    for o in occ:
        if not o["business"] and not o["skip"] and o["engine"].startswith("Database (engine"):
            continue
        c = comps.setdefault(o["component"], {"in": [], "out": []})
        if "W" in o["access"]:
            c["out"].append(o["store"])
        elif "R" in o["access"]:
            c["in"].append(o["store"])
    writers = {}
    for name, c in comps.items():
        for s in c["out"]:
            writers.setdefault(s, set()).add(name)
    out = []
    for name, c in sorted(comps.items(), key=lambda kv: -len(kv[1]["in"]) - len(kv[1]["out"])):
        if not (c["in"] or c["out"]):
            continue
        ins = [s + ("" if writers.get(s) else "") for s in sorted(set(c["in"]))]
        outs = sorted(set(c["out"]))
        readers = {s: sorted({n for n, cc in comps.items() if s in cc["in"] and n != name}) for s in outs}
        out.append({"component": name, "in": ins, "out": outs,
                    "in_from": {s: sorted(writers.get(s, set()) - {name}) for s in ins},
                    "out_to": readers})
    return out


def reconciliation(arts) -> list:
    """Code that compares or totals records between stores: control totals, record counts, hash totals."""
    hits = []
    for a in arts:
        t = a.get("transcription") or ""
        if re.search(r"RECONCIL|CONTROL[-_ ]?TOTAL|HASH[-_ ]?TOTAL|TRAILER|WS-TOTAL-|TOTAL-(GROSS|NET|AMOUNT)|RECORD[-_ ]COUNT|READ-COUNT|PAID-COUNT", t, re.I):
            kinds = sorted({k for k, rx in (("reconciliation", r"RECONCIL"), ("control totals", r"CONTROL[-_ ]?TOTAL|WS-TOTAL-|TOTAL-(GROSS|NET|AMOUNT)"),
                                             ("hash totals", r"HASH[-_ ]?TOTAL"), ("trailer record", r"TRAILER"),
                                             ("record counts", r"RECORD[-_ ]COUNT|READ-COUNT|PAID-COUNT"))
                            if re.search(rx, t, re.I)})
            hits.append((a["name"], kinds))
    return hits


def matrix(m, top=3) -> tuple:
    """(header, rows) with one row per platform and one column per business entity, like an ownership grid."""
    ents = [g for g in m["entities"] if len(g["copies"]) >= 1][:top]
    plats = []
    for g in ents:
        for o in g["copies"]:
            if o["engine"] not in plats:
                plats.append(o["engine"])
    head = ["Platform"] + [f"{g['name']} data" for g in ents] + ["Component"]
    rows = []
    for p in plats:
        cells, comps = [], set()
        for g in ents:
            here = [o for o in g["occ"] if o["engine"] == p]
            names = []
            for o in here:
                lab = o["store"] + (f" ({o['role']})" if o["role"] and o["role"] not in ("file", "membership") else "")
                lab += {"W": ", written", "R": ", read", "D": ", defined", "DR": ", defined and read",
                        "RW": ", read and written", "DW": ", defined and written"}.get(o["access"], "")
                if lab not in names:
                    names.append(lab)
                comps.add(o["component"])
            cells.append("; ".join(names) or "–")
        rows.append([p] + cells + [", ".join(sorted(comps))])
    return head, rows


def sor_rows(m) -> list:
    rec = m["reconciliation"]
    out = []
    for g in m["entities"]:
        n = len(g["copies"])
        writers = g["writers"]
        plats = len(g["platforms"])
        if n <= 1:
            sor = f"{g['copies'][0]['store']} ({g['copies'][0]['engine']}) is the only copy found; confirm it is authoritative"
        elif len(writers) == 1 and plats == 1:
            sor = f"Candidate: the copy written by {writers[0]}; not confirmed"
        elif writers:
            sor = (f"Not established: written by {len(writers)} components on {plats} platform(s); the IT and business "
                   f"owners must name one")
        else:
            sor = (f"Not established: no component provided writes it, so the master copy is maintained elsewhere; "
                   f"{n} copies are read on {plats} platform(s)")
        recon = "; ".join(f"{a} ({', '.join(k)})" for a, k in rec if a in {o["component"] for o in g["occ"]}) or \
            "None visible in the code"
        out.append([g["name"], str(n), ", ".join(g["platforms"]), ", ".join(writers) or "None in the code provided", sor, recon])
    return out


def hosting_platforms(AM, m) -> list:
    """Platforms that host code or data (browsers are clients, so they are not counted)."""
    out = {p for p in AM["platforms"] if p != "Web browser"}
    if m.get("sql_server"):
        out.add("Microsoft SQL Server")
    return sorted(out)


def fragmentation_sentence(m) -> str:
    big = [g for g in m["entities"] if len(g["copies"]) >= 3]
    if not big:
        return ""
    parts = [f"{g['name'].lower()} data is held in {len(g['copies'])} places across {len(g['platforms'])} platforms "
             f"({', '.join(g['platforms'])})" for g in big[:2]]
    return (_cap("; ".join(parts)) + ", and no system of record is named for "
            + ("either" if len(big[:2]) == 2 else "it") + ".")


def _cap(t):
    return t[:1].upper() + t[1:] if t else t
