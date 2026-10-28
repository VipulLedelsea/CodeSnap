import re
from core.model.linker import trace_flows
from core.model.store import classify_placeholder

from .layout import columns, lanes, layered, sequence

CLASS_KINDS = ("class", "interface", "program", "copybook")
MEMBER_ATTR = ("field", "column")
MEMBER_OP = ("function", "paragraph", "section")
CODE_REL = ("calls", "uses", "includes", "imports", "invokes_transaction", "depends_on", "navigates_to")
DATA_REL = ("reads", "writes", "connects_to", "displays")
MAX_ATTR, MAX_OPS, MAX_MESSAGES = 10, 14, 40
MAX_TABLE_COLS, MAX_TABLES = 30, 60      # keeps the data model diagram drawable for very large schemas


def _short(s, n=48):
    s = str(s)
    return s if len(s) <= n else s[:n - 1] + "…"


class _Model:
    def __init__(self, store):
        self.store = store
        self.ents = {e["id"]: e for e in store.entities()}
        self.rels = store.relations()
        self._collapse_numbered_datasets()
        self.arts = {a["id"]: a for a in store.artifacts()}
        self.children = {}
        for e in self.ents.values():
            if e["parent_id"]:
                self.children.setdefault(e["parent_id"], []).append(e)
        self.owner_art = {e["id"]: e["artifact_id"] for e in self.ents.values() if e["artifact_id"] in self.arts}
        self.sources = {}
        for row in store._all("SELECT entity_id, artifact_id FROM entity_source"):
            if row["artifact_id"] in self.arts:
                self.sources.setdefault(row["entity_id"], set()).add(row["artifact_id"])
        for eid, aid in self.owner_art.items():
            self.sources.setdefault(eid, set()).add(aid)

    def _collapse_numbered_datasets(self, minimum=4):
        """A job that touches SYNTH.RESTART.P00.WORK ... P29.WORK has thirty look-alike datasets; drawing each one makes the
        context and architecture diagrams several times taller than they are informative. Show one node per family."""
        families = {}
        for e in self.ents.values():
            if e["kind"] == "data_store" and re.search(r"\d", e["name"] or ""):
                families.setdefault((re.sub(r"\d+", "nn", e["name"]), e["origin"] == "placeholder"), []).append(e)
        remap = {}
        for (pattern, _), members in families.items():
            if len(members) < minimum:
                continue
            members.sort(key=lambda e: e["id"])
            rep = members[0]
            self.ents[rep["id"]] = rep = {**rep, "name": f"{pattern} (x{len(members)})"}
            for e in members[1:]:
                remap[e["id"]] = rep["id"]
                del self.ents[e["id"]]
        # one dotted segment varies (SYNTH.ASHFORD.REVIEW, SYNTH.BRIARWOO.REVIEW ...): one node for the family
        seg = {}
        for e in self.ents.values():
            parts = (e["name"] or "").split(".")
            if e["kind"] == "data_store" and len(parts) >= 3:
                for i in range(len(parts)):
                    key = (".".join(parts[:i] + ["*"] + parts[i + 1:]), e["origin"] == "placeholder")
                    seg.setdefault(key, []).append(e)
        taken = set()
        for (pattern, _), members in sorted(seg.items(), key=lambda kv: -len(kv[1])):
            members = [e for e in members if e["id"] not in taken and e["id"] in self.ents]
            if len(members) < 6:
                continue
            members.sort(key=lambda e: e["id"])
            rep = members[0]
            self.ents[rep["id"]] = rep = {**rep, "name": f"{pattern} (x{len(members)})"}
            taken.add(rep["id"])
            for e in members[1:]:
                remap[e["id"]] = rep["id"]
                taken.add(e["id"])
                del self.ents[e["id"]]
        if not remap:
            return
        seen, rels = set(), []
        for r in self.rels:
            r = {**r, "from_id": remap.get(r["from_id"], r["from_id"]), "to_id": remap.get(r["to_id"], r["to_id"])}
            key = (r["from_id"], r["to_id"], r["kind"])
            if key not in seen:
                seen.add(key)
                rels.append(r)
        self.rels = rels

    def in_file(self, eid, aid):
        return aid in self.sources.get(eid, ())

    def top(self, eid, kinds=CLASS_KINDS):
        seen = set()
        while eid and eid not in seen:
            seen.add(eid)
            e = self.ents.get(eid)
            if e is None:
                return None
            if e["kind"] in kinds:
                return eid
            eid = e["parent_id"]
        return None


def context(store) -> dict:
    m = _model(store)
    name = store.info["name"]
    kinds = {}
    for e in m.ents.values():
        if e["origin"] != "placeholder":
            kinds.setdefault(e["kind"], []).append(e)
    left, right, edges = [], [], []
    program = {"id": "program", "title": name, "stereotype": "system under assessment", "kind": "system",
               "sections": [[f"{len(m.arts)} captured files",
                             f"{len(kinds.get('screen', []))} screens · {len(kinds.get('api_endpoint', []))} endpoints",
                             f"{len(kinds.get('job', []))} jobs · {len(kinds.get('transaction', []))} transactions"]]}
    if kinds.get("screen") or kinds.get("api_endpoint") or kinds.get("transaction"):
        left.append({"id": "actor:users", "title": "Program users", "stereotype": "actor", "kind": "actor",
                     "sections": [[_short(s["name"], 36) for s in (kinds.get("screen") or [])[:6]]
                                  + ([f"+{len(kinds['screen']) - 6} more screens"] if len(kinds.get("screen") or []) > 6 else [])]})
        edges.append({"from": "actor:users", "to": "program", "label": "uses screens / endpoints", "style": "solid", "head": "arrow"})
    if kinds.get("job"):
        left.append({"id": "actor:scheduler", "title": "Batch scheduler", "stereotype": "actor", "kind": "actor",
                     "sections": [[_short(j["name"], 36) for j in kinds["job"][:6]]]})
        edges.append({"from": "actor:scheduler", "to": "program", "label": "runs jobs", "style": "solid", "head": "arrow"})
    access = {}
    for r in m.rels:
        t = m.ents.get(r["to_id"])
        if t and t["kind"] in ("external_system", "data_store", "table") and r["kind"] in DATA_REL + ("calls",):
            access.setdefault(t["id"], set()).add(r["kind"])
    for kind, stereo in (("external_system", "external system"), ("data_store", "data store")):
        for e in m.ents.values():
            if e["kind"] != kind:
                continue
            attrs = e.get("attrs") or {}
            detail = [v for v in (attrs.get("store_type"), attrs.get("protocol")) if v]
            if e["origin"] == "placeholder":
                detail.append("referenced only")
            right.append({"id": f"e{e['id']}", "title": _short(e["name"]), "stereotype": stereo, "kind": kind,
                          "sections": [detail] if detail else [], "dashed": e["origin"] == "placeholder"})
            verbs = sorted(access.get(e["id"], {"connects_to"}))
            edges.append({"from": "program", "to": f"e{e['id']}", "label": "/".join(v.replace("connects_to", "connects")
                                                                                 for v in verbs), "style": "solid", "head": "arrow"})
    every_table = [e for e in m.ents.values() if e["kind"] == "table"]
    views = [e for e in every_table if (e.get("attrs") or {}).get("view")]
    tables = [e for e in every_table if not (e.get("attrs") or {}).get("view")]       # a view is not a table; count them apart
    if tables or views:
        names = sorted(tables, key=lambda t: t["name"])
        lines = [_short(t["name"], 40) + (" (no DDL)" if t["origin"] == "placeholder" else "") for t in names[:16]]
        if len(names) > 16:
            lines.append(f"+{len(names) - 16} more")
        if views:
            lines.append(f"+ {len(views)} views")
        right.append({"id": "tables", "title": f"Database tables ({len(tables)})", "stereotype": "data", "kind": "data_store",
                      "sections": [lines]})
        verbs = sorted({v for t in tables for v in access.get(t["id"], set())} or {"reads"})
        edges.append({"from": "program", "to": "tables", "label": "/".join(verbs), "style": "solid", "head": "arrow"})
    scene = columns([left, [program], right], edges)
    return {"id": "context", "kind": "context", "title": f"Context — {name}", **scene}


def components(store) -> dict:
    m = _model(store)
    nodes, edges, agg = {}, [], {}
    for aid, a in m.arts.items():
        nodes[f"a{aid}"] = {"id": f"a{aid}", "title": a["name"], "stereotype": a.get("language") or a.get("artifact_type"),
                            "kind": "component"}
    program_art = {}
    for e in m.ents.values():
        if e["kind"] in ("program", "class") and e["origin"] != "placeholder" and e["artifact_id"] in m.arts:
            program_art.setdefault((e["name"] or "").upper(), e["artifact_id"])
    for r in m.rels:
        if r["kind"] not in CODE_REL + DATA_REL:
            continue
        tt = m.ents.get(r["to_id"])
        if tt and tt["origin"] == "placeholder" and (tt["kind"] == "module" or classify_placeholder(tt) == "library"):
            continue
        src_art = r["artifact_id"] if r["artifact_id"] in m.arts else m.owner_art.get(r["from_id"])
        ff = m.ents.get(r["from_id"])
        if ff and tt and ff["kind"] == "data_store" and tt["kind"] == "data_store":
            continue        # a logical file (PAYIN) matched to a dataset: a mapping, not a component using it; shared names would be credited to one program
        step_pgm = program_art.get(str((r.get("attrs") or {}).get("program") or "").upper())
        if step_pgm and ff and ff["kind"] == "job" and tt and tt["kind"] in ("table", "data_store", "external_system"):
            # the JCL step names the program that runs against this dataset, so that program is the one that reads or writes it
            tid2 = f"e{tt['id']}"
            if tid2 not in nodes:
                nodes[tid2] = {"id": tid2, "title": _short(tt["name"]), "stereotype": tt["kind"].replace("_", " "),
                               "kind": tt["kind"], "dashed": tt["origin"] == "placeholder"}
            agg.setdefault((f"a{step_pgm}", tid2), set()).add(r["kind"])
        if src_art is None:
            continue
        t = m.ents.get(r["to_id"])
        if t is None:
            continue
        tgt_art = m.owner_art.get(t["id"])
        if t["kind"] in ("table", "data_store", "external_system"):
            tid = f"e{t['id']}"
            if tid not in nodes:
                nodes[tid] = {"id": tid, "title": _short(t["name"]), "stereotype": t["kind"].replace("_", " "),
                              "kind": t["kind"], "dashed": t["origin"] == "placeholder"}
        elif tgt_art and tgt_art != src_art:
            tid = f"a{tgt_art}"
        elif t["origin"] == "placeholder" and t["kind"] in ("program", "class", "copybook", "module", "screen"):
            tid = f"e{t['id']}"
            if tid not in nodes:
                nodes[tid] = {"id": tid, "title": _short(t["name"]), "stereotype": f"{t['kind']} · not captured",
                              "kind": "missing", "dashed": True}
        else:
            continue
        key = (f"a{src_art}", tid)
        if key[0] != key[1]:
            agg.setdefault(key, set()).add(r["kind"])
    for (a, b), kinds in agg.items():
        edges.append({"from": a, "to": b, "label": "/".join(sorted(k.replace("connects_to", "connects") for k in kinds)),
                      "style": "dashed" if kinds <= {"includes", "imports", "depends_on"} else "solid", "head": "arrow"})
    sinks = {i for i, n in nodes.items() if n["kind"] in ("table", "data_store", "external_system")}
    if len(edges) > 25:
        for e in edges:
            e["label"] = ""
    n = len(nodes)
    scene = layered(list(nodes.values()), edges, "LR", sinks=sinks, straight=True,
                    per_row=max(12, -(-n // 6)), max_ranks=5 if n > 30 else None)
    return {"id": "components", "kind": "component", "title": f"Components & data — {store.info['name']}", **scene}


def _descendants(m, eid, kinds, depth=0, stop=CLASS_KINDS):
    out = []
    for k in sorted(m.children.get(eid, []), key=lambda k: (k["line_start"] or 0, k["name"])):
        if k["kind"] in stop:
            continue
        if k["kind"] in kinds:
            out.append((depth, k))
        out += _descendants(m, k["id"], kinds, depth + 1, stop)
    return out


def _class_node(m, e, full=False):
    fields = _descendants(m, e["id"], MEMBER_ATTR)
    ops = [k for _, k in _descendants(m, e["id"], MEMBER_OP)]
    if not full:
        fields = [(d, k) for d, k in fields if d == 0]
    a_lines = []
    for depth, k in fields if full else fields[:MAX_ATTR]:
        at = k.get("attrs") or {}
        t = at.get("type") or at.get("pic")
        lvl = at.get("level")
        lvl = f"{int(lvl):02d}" if str(lvl).isdigit() else lvl
        a_lines.append(_short(f"{'  ' * depth}{str(lvl) + ' ' if lvl else ''}{k['name']}{': ' + str(t) if t else ''}", 52))
    if not full and len(fields) > MAX_ATTR:
        a_lines.append(f"+{len(fields) - MAX_ATTR} more")
    names = []
    for k in ops:
        label = k["name"].split(".")[-1] + ("()" if k["kind"] == "function" else "")
        label = ("§ " + label) if k["kind"] == "section" else label
        if label not in names:
            names.append(label)
    o_lines = [_short(n, 52) for n in (names if full else names[:MAX_OPS])]
    if not full and len(names) > MAX_OPS:
        o_lines.append(f"+{len(names) - MAX_OPS} more")
    ph = e["origin"] == "placeholder"
    lang = ((m.arts.get(e.get("artifact_id")) or {}).get("language") or "").strip()
    stereo = {"interface": "interface", "copybook": "copybook"}.get(e["kind"])
    if e["kind"] == "program":
        stereo = f"{lang} script" if lang.upper() == "REXX" else f"{lang} program" if lang else "program"
    if ph:
        stereo = "program or utility \u00b7 not in the supplied files" if e["kind"] == "program" else (stereo + " \u00b7 " if stereo else "") + "not captured"
    sections = [x for x in (a_lines, o_lines) if x] if ph else [a_lines, o_lines]
    return {"id": f"c{e['id']}", "title": _short(e["name"].split(".")[-1], 40), "stereotype": stereo,
            "kind": "missing" if ph else "class", "sections": sections, "dashed": ph}


def classes(store, artifact_id=None) -> dict:
    m = _model(store)
    chosen = {e["id"] for e in m.ents.values() if e["kind"] in CLASS_KINDS
              and (artifact_id is None or m.in_file(e["id"], artifact_id))}
    edges, agg = [], {}
    for r in m.rels:
        a = m.top(r["from_id"])
        b = m.top(r["to_id"])
        if not a or not b or a == b:
            continue
        if a not in chosen and b not in chosen:
            continue
        if artifact_id is not None and a not in chosen:
            continue
        tb = m.ents[b]
        if tb["origin"] == "placeholder" and r["kind"] not in ("inherits", "implements") and \
                classify_placeholder(tb) == "library":
            continue
        agg.setdefault((a, b), set()).add(r["kind"])
    extra = {x for pair in agg for x in pair} - chosen
    nodes = [_class_node(m, m.ents[i], full=artifact_id is not None and i in chosen)
             for i in sorted(chosen | extra, key=lambda i: m.ents[i]["name"])]
    for (a, b), kinds in agg.items():
        if "inherits" in kinds:
            style, head, label = "solid", "triangle", ""
        elif "implements" in kinds:
            style, head, label = "dashed", "triangle", ""
        elif kinds <= {"includes", "imports"}:
            style, head, label = "dashed", "open", "includes"
        else:
            style, head, label = "solid", "open", "/".join(sorted(kinds - {"inherits", "implements"}))
        edges.append({"from": f"c{a}", "to": f"c{b}", "label": label, "style": style, "head": head})
    if artifact_id is not None:
        free = [e for e in m.ents.values() if m.in_file(e["id"], artifact_id) and e["origin"] != "placeholder"
                and e["kind"] in ("function", "field") and m.top(e["id"]) is None]
        if free:
            fields = [_short(e["name"], 52) for e in free if e["kind"] == "field"]
            funcs = [_short(e["name"].split(".")[-1] + "()", 52) for e in free if e["kind"] == "function"]
            nodes.insert(0, {"id": f"f{artifact_id}", "title": m.arts[artifact_id]["name"], "stereotype": "file scope",
                             "kind": "component", "sections": [fields, funcs]})
    scene = layered(nodes, edges, "TB", straight=len(edges) > 12, per_row=max(7, -(-len(nodes) // 6)),
                    max_ranks=5 if len(nodes) > 30 else None)
    title = "Classes & programs" + (f" — {m.arts[artifact_id]['name']}" if artifact_id else f" — {store.info['name']}")
    return {"id": f"class-{artifact_id}" if artifact_id else "class", "kind": "class", "title": title, **scene}



def _data_relationship_label(attrs):
    if attrs.get("trigger_on"):
        return "trigger"
    if attrs.get("hierarchy"):
        return str(attrs["hierarchy"])
    if attrs.get("logical"):
        return "logical relationship"
    if attrs.get("foreign_key"):
        return "FK"
    return "dependency"


def _data_stereotype(table):
    attrs = table.get("attrs") or {}
    if attrs.get("ims_segment"):
        return "IMS segment"
    if table["origin"] == "placeholder":
        return "table · definition not provided"
    return "view" if attrs.get("view") else "table"

def data_model(store) -> dict:
    m = _model(store)
    every = [e for e in m.ents.values() if e["kind"] == "table"]
    views = [e for e in every if (e.get("attrs") or {}).get("view")]
    all_tables = [e for e in every if not (e.get("attrs") or {}).get("view")]      # a view has no columns of its own to draw
    tables = all_tables
    if len(all_tables) > MAX_TABLES:
        linked = {r[k] for r in m.rels if r["kind"] == "depends_on" for k in ("from_id", "to_id")}
        tables = sorted(all_tables, key=lambda t: (t["id"] not in linked, t["name"]))[:MAX_TABLES]
    nodes, edges, seen = [], [], set()
    for t in sorted(tables, key=lambda t: t["name"]):
        cols = [k for k in m.children.get(t["id"], []) if k["kind"] == "column"]
        lines = []
        for c in sorted(cols, key=lambda c: (c["line_start"] or 0, c["name"]))[:MAX_TABLE_COLS]:
            at = c.get("attrs") or {}
            flag = " PK" if at.get("primary_key") else ""
            null = "" if at.get("nullable", True) else " NOT NULL"
            lines.append(_short(f"{c['name']}{': ' + str(at['type']) if at.get('type') else ''}{flag}{null}", 56))
        if len(cols) > MAX_TABLE_COLS:
            lines.append(f"+{len(cols) - MAX_TABLE_COLS} more")
        stereo = _data_stereotype(t)
        nodes.append({"id": f"t{t['id']}", "title": _short(t["name"], 44), "stereotype": stereo, "kind": "table",
                      "sections": [lines] if lines else [], "dashed": t["origin"] == "placeholder"})
    ids = {t["id"] for t in tables}
    for r in m.rels:
        if r["kind"] == "depends_on" and r["from_id"] in ids and r["to_id"] in ids and r["from_id"] != r["to_id"]:
            key = (r["from_id"], r["to_id"])
            if key not in seen:
                seen.add(key)
                edges.append({"from": f"t{r['from_id']}", "to": f"t{r['to_id']}",
                              "label": _data_relationship_label(r.get("attrs") or {}),
                              "style": "solid", "head": "open"})
    scene = layered(nodes, edges, "TB", straight=len(edges) > 12)
    shown = f" (showing {len(tables)} of {len(all_tables)} tables)" if len(all_tables) > len(tables) else ""
    if views:
        shown += f" ({len(views)} views not drawn)" if shown else f" ({len(views)} views not drawn)"
    return {"id": "data", "kind": "data", "title": f"Data model — {store.info['name']}{shown}", **scene}


def _family_labels(names, minimum=4, segment_minimum=6) -> dict:
    """name -> 'pattern (xN)' for names that differ only by a number or by one dotted segment, so a family is drawn once."""
    names = sorted({n for n in names if n})
    out, fam = {}, {}
    for n in names:
        if re.search(r"\d", n):
            fam.setdefault(re.sub(r"\d+", "nn", n), []).append(n)
    for pat, mem in fam.items():
        if len(mem) >= minimum:
            out.update({n: f"{pat} (x{len(mem)})" for n in mem})
    seg = {}
    for n in names:
        parts = n.split(".")
        if n not in out and len(parts) >= 3:
            for i in range(len(parts)):
                seg.setdefault(".".join(parts[:i] + ["*"] + parts[i + 1:]), []).append(n)
    taken = set()
    for pat, mem in sorted(seg.items(), key=lambda kv: -len(kv[1])):
        mem = [n for n in mem if n not in taken]
        if len(mem) >= segment_minimum:
            out.update({n: f"{pat} (x{len(mem)})" for n in mem})
            taken.update(mem)
    return out


def interactions(store, limit=40) -> list:
    flows = trace_flows(store)
    labels = _family_labels([x for f in flows for st in f["steps"] for x in (st["from"], st["to"])])
    names = {e["id"]: e["name"] for e in store.entities()}
    step_program = {}          # (job, dataset, kind, line) -> the program the JCL step runs
    for r in store.relations():
        pgm = (r.get("attrs") or {}).get("program")
        if pgm and r["from_id"] in names and r["to_id"] in names:
            step_program[(names[r["from_id"]], names[r["to_id"]], r["kind"], r.get("line"))] = str(pgm)
    by_entry = {}
    for f in flows:
        by_entry.setdefault((f["entry_kind"], f["entry"]), []).append(f)
    out = []
    for idx, ((ekind, entry), fl) in enumerate(sorted(by_entry.items(), key=lambda kv: (-len(kv[1]), kv[0][1]))[:limit]):
        parts, msgs, seen = {}, [], set()
        actor = "Batch scheduler" if ekind == "job" else "User"
        parts[actor] = {"id": "p0", "title": actor, "stereotype": "actor", "kind": "actor"}
        parts[entry] = {"id": "p1", "title": _short(entry, 36), "stereotype": ekind.replace("_", " "), "kind": "participant"}
        msgs.append({"from": "p0", "to": "p1", "label": "runs" if ekind == "job" else "opens / submits"})
        for f in sorted(fl, key=lambda x: x["length"]):
            for s in f["steps"]:
                pgm = step_program.get((s["from"], s["to"], s["kind"], s.get("line"))) if ekind == "job" else None
                s = {**s, "from": labels.get(s["from"], s["from"]), "to": labels.get(s["to"], s["to"])}
                if pgm:        # the step runs a program, and the program is what reads or writes the dataset
                    run_key = (s["from"], "runs", pgm)
                    if run_key not in seen:
                        seen.add(run_key)
                        parts.setdefault(pgm, {"id": f"p{len(parts)}", "title": _short(pgm, 36), "kind": "participant"})
                        msgs.append({"from": parts[s["from"]]["id"], "to": parts[pgm]["id"], "label": "runs", "style": "solid"})
                    s = {**s, "from": pgm}
                key = (s["from"], s["kind"], s["to"])
                if key in seen:
                    continue
                seen.add(key)
                for nm in (s["from"], s["to"]):
                    if nm not in parts:
                        parts[nm] = {"id": f"p{len(parts)}", "title": _short(nm, 36), "kind": "participant"}
                verb = {"contains": "runs", "connects_to": "connects to", "invokes_transaction": "starts transaction"}.get(
                    s["kind"], s["kind"].replace("_", " "))
                label = verb + (f"  (L{s['line']})" if s.get("line") else "")
                msgs.append({"from": parts[s["from"]]["id"], "to": parts[s["to"]]["id"], "label": label,
                             "style": "dashed" if s["kind"] in ("reads", "displays") else "solid"})
                if len(msgs) >= MAX_MESSAGES:
                    break
            if len(msgs) >= MAX_MESSAGES:
                break
        scene = sequence(list(parts.values()), msgs)
        out.append({"id": f"seq-{idx}", "kind": "sequence", "title": f"Interaction — {entry}",
                    "entry": entry, "entry_kind": ekind, "truncated": len(msgs) >= MAX_MESSAGES, **scene})
    return out


def _model(store):
    return getattr(store, "_diagram_model", None) or _Model(store)


def all_diagrams(store, per_file=True) -> list:
    store._diagram_model = _Model(store)
    try:
        return _all_diagrams(store, per_file)
    finally:
        store._diagram_model = None


def _all_diagrams(store, per_file=True) -> list:
    out = [architecture(store), context(store), components(store), classes(store)]
    if any(e["kind"] == "table" for e in store.entities("table")):
        out.append(data_model(store))
    if per_file:
        m = _model(store)
        for aid, a in m.arts.items():
            n = sum(1 for e in m.ents.values() if m.in_file(e["id"], aid) and (
                e["kind"] in CLASS_KINDS or (e["kind"] == "function" and m.top(e["id"]) is None)))
            if n >= 1:
                try:
                    out.append(classes(store, aid))
                except Exception:
                    continue
    uf = user_flow(store)
    if uf and uf["nodes"] and uf["edges"]:      # screens with no navigation between them show nothing a list does not
        out.append(uf)
    out += interactions(store)
    return out


CHECK_KINDS = ("program", "class", "interface", "copybook", "function", "paragraph", "section", "field", "table",
               "column", "data_store", "external_system", "screen", "api_endpoint", "job", "transaction")


def diagram_coverage(store, diagrams) -> dict:
    text = set()
    for d in diagrams:
        for n in d["nodes"]:
            text.add(n["title"].strip())
            for sec in n.get("sections") or []:
                text.update(str(l).strip() for l in sec)
    blob = "\n".join(text)
    missing, total = [], 0
    for e in store.entities():
        if e["origin"] == "placeholder" or e["kind"] not in CHECK_KINDS:
            continue
        total += 1
        short = e["name"].split(".")[-1]
        if short not in blob and _short(e["name"], 36) not in blob and _short(short, 36) not in blob:
            missing.append({"kind": e["kind"], "name": e["name"]})
    return {"entities": total, "shown": total - len(missing), "missing": missing,
            "ratio": round((total - len(missing)) / total, 3) if total else 1.0}


ICONS = {"users": ("USR", "#2E7DB0"), "screen": ("UI", "#2E7DB0"), "cobol": ("CBL", "#BE6E4A"), "cs": ("C#", "#7B4FA0"),
         "java": ("JV", "#D9822B"), "cpp": ("C++", "#2A8C8C"), "web": ("WEB", "#2E7DB0"), "js": ("JS", "#B38F00"),
         "code": ("SRC", "#857A70"), "api": ("API", "#3F51B5"), "transaction": ("TX", "#B3261E"), "job": ("JOB", "#8A4A2C"),
         "database": ("DB", "#3B8F5E"), "table": ("TBL", "#3B8F5E"), "file": ("FILE", "#6E6E73"),
         "external": ("EXT", "#6E6E73"), "missing": ("?", "#A99C90"),
         "ibmi": ("RPG", "#1F6F8B"), "natural": ("NAT", "#6B5B95"), "vb": ("VB", "#5C4B9B"), "script": ("SH", "#4E6E58"),
         "4gl": ("4GL", "#8C6D1F"), "webscript": ("PHP", "#4F5B93"), "cfml": ("CFM", "#4F5B93"), "pli": ("PL/I", "#A0522D"), "asm": ("ASM", "#7A4A3A"),
         "report": ("RPT", "#6A7F2A"), "sqlproc": ("SQL", "#3B8F5E"), "etl": ("ETL", "#2F6E9E"), "fortran": ("F77", "#556B8E")}
PACK_GROUPS = {
    "ibmi": ("g-ibmi", "IBM i (RPG / CL)", "ibmi"), "natural": ("g-natural", "Natural / Adabas", "natural"),
    "vb": ("g-vb", "Visual Basic / VBA", "vb"), "vbscript": ("g-vbs", "VBScript / Classic ASP", "vb"),
    "script": ("g-scripts", "Scripts & job control", "script"), "4gl": ("g-4gl", "4GL / client-server", "4gl"),
    "webscript": ("g-webscript", "Web scripting (PHP / ColdFusion)", "webscript"), "pli": ("g-pli", "PL/I", "pli"),
    "asm": ("g-asm", "Assembler / IMS", "asm"), "report": ("g-report", "Reporting (SAS / Easytrieve)", "report"),
    "sql": ("g-sqlproc", "Stored procedures (PL/SQL / T-SQL)", "sqlproc"), "etl": ("g-etl", "ETL packages (SSIS)", "etl"),
    "fortran": ("g-fortran", "Fortran", "fortran"), "js": ("g-js", "JavaScript", "js"), "cs": ("g-cs", "C# / .NET", "cs"),
}
SCREEN_ONLY_PACKS = {"oracle_forms", "dfm", "xaml", "datawindow", "informix_form", "ispf_panel", "ims_mfs", "ims_dbd"}
TERMINAL_TECH = {"ISPF panel", "IMS MFS"}
STATUS_CHIP = {"eol": ("#FDE2E1", "#B3261E"), "extended": ("#FFF1D6", "#8A5A00"), "legacy": ("#FFF1D6", "#8A5A00"),
               "ending": ("#FFF1D6", "#8A5A00"), "supported": ("#E3F5E8", "#1F7A3A"), "unknown": ("#EFEFF2", "#6E6E73")}
SEV_CHIP = {"critical": ("#7A1020", "#7A1020"), "high": ("#FDE2E1", "#A4161A"), "medium": ("#FFF1D6", "#8A5A00"),
            "low": ("#E8F1FB", "#1D4F86"), "info": ("#EFEFF2", "#6E6E73")}


def _icon(key):
    t, c = ICONS[key]
    return {"text": t, "color": c}


def architecture(store) -> dict:
    from core.security.rules import family
    from core.security.scan import summary as sec_summary, technologies
    from core.model.folder_import import is_exact
    m = _model(store)
    from_folder = bool(m.arts) and all(is_exact(store, a) for a in m.arts.values())      # read from disk: nothing was captured
    not_there = "not in the folder" if from_folder else "not captured"
    name = store.info["name"]
    assessment = store.get_meta("assessment") or {}
    risk = {c["artifact_id"]: c["risk"]["level"] for c in assessment.get("components") or []}
    eol_arts = {f["target_id"] for f in store.findings("eol") if f["severity"] == "high" and f.get("status") != "dismissed"}

    def badge(aid):
        lvl = risk.get(aid)
        if lvl in ("critical", "high"):
            return {"text": "CRIT" if lvl == "critical" else "HIGH", "color": "#B3261E" if lvl == "critical" else "#E06A2C"}
        if aid in eol_arts:
            return {"text": "EOL", "color": "#B3261E"}
        return None

    node_of, lanes_ = {}, {k: {} for k in ("users", "presentation", "application", "integration", "data", "external")}

    def put(lane, gid, gtitle, node, dashed=True):
        lanes_[lane].setdefault(gid, {"id": gid, "title": gtitle, "nodes": [], "dashed": dashed})["nodes"].append(node)
        return node["id"]

    code_types = ("code",)
    for aid, a in sorted(m.arts.items(), key=lambda kv: kv[1]["name"]):
        fam = family(a["name"], a.get("language") or "")
        lang = (a.get("language") or "").lower()
        file_ent = next((e for e in m.ents.values() if e["kind"] == "file" and e["artifact_id"] == aid), None)
        prof = ((file_ent or {}).get("attrs") or {}).get("profile") or {}
        proc_sql = fam in ("plsql", "tsql") or (fam == "sql" and prof.get("pack") in ("plsql", "tsql"))
        if (a.get("artifact_type") not in code_types and not proc_sql) or fam in ("config", "props", "json", "web") or \
                (fam == "sql" and not proc_sql):
            continue
        if "bms" in lang or "jcl" in lang or a["name"].lower().endswith((".bms", ".jcl")):
            continue
        if prof.get("pack") in SCREEN_ONLY_PACKS:
            continue
        owned = [e for e in m.ents.values() if m.in_file(e["id"], aid)]
        cics = any(e["kind"] == "transaction" for e in owned) or "EXEC CICS" in (a.get("transcription") or "").upper()
        if fam == "cobol":
            gid, gt, ic = ("g-cics", "COBOL / CICS online", "cobol") if cics else ("g-cobol", "COBOL batch & copybooks", "cobol")
        elif fam == "cs":
            gid, gt, ic = ("g-cobnet", "COBOL-translated .NET", "cs") if prof.get("cobol_translated") else ("g-cs", "C# / .NET", "cs")
        elif fam == "java":
            gid, gt, ic = "g-java", "Java", "java"
        elif fam == "cpp":
            gid, gt, ic = "g-cpp", "C / C++", "cpp"
        elif fam == "js":
            gid, gt, ic = "g-js", "JavaScript", "js"
        elif proc_sql:
            gid, gt, ic = PACK_GROUPS["sql"]
        elif prof.get("family") in PACK_GROUPS:
            gid, gt, ic = PACK_GROUPS[prof["family"]]
            if fam == "coldfusion":
                ic = "cfml"
        else:
            gid, gt, ic = "g-code", "Other code", "code"
        units = sum(1 for e in owned if e["kind"] in ("class", "interface", "program"))
        lines = len([l for l in (a.get("transcription") or "").splitlines() if l.strip()])
        node_of[f"art:{aid}"] = put("application", gid, gt, {
            "id": f"a{aid}", "title": _short(a["name"], 30), "icon": _icon(ic), "badge": badge(aid),
            "sub": f"{lines} lines" + (f" · {units} unit{'s' if units != 1 else ''}" if units else "")})
    screen_family = {}
    for e in m.ents.values():
        if e["kind"] == "screen" and e["origin"] != "placeholder":
            screen_family.setdefault(re.sub(r"\d+", "nn", e["name"] or ""), []).append(e)
    screen_family = {k: sorted(v, key=lambda x: x["name"]) for k, v in screen_family.items() if len(v) >= 6}    # H00..H32 and M00..M35 are one node each
    screen_node = {}
    for e in sorted(m.ents.values(), key=lambda e: e["name"]):
        k, ph = e["kind"], e["origin"] == "placeholder"
        attrs = e.get("attrs") or {}
        nid = f"e{e['id']}"
        src_art = m.owner_art.get(e["id"])
        src = m.arts.get(src_art) or {}
        if k == "screen":
            fam = family(src.get("name", ""), src.get("language") or "")
            bms = src.get("name", "").lower().endswith(".bms") or "bms" in (src.get("language") or "").lower()
            if ph:
                gid, gt = "g-scr-miss", f"Screens referenced, {not_there}"
            elif bms:
                gid, gt = "g-scr-bms", "CICS / BMS screens"
            elif src.get("artifact_type") == "ui_screen":
                gid, gt = "g-scr-app", "Captured app screens"
            elif fam == "web" or attrs.get("technology") == "web" or fam in ("php", "coldfusion", "vbscript"):
                gid, gt = "g-scr-web", "Web pages"
            elif attrs.get("technology") in TERMINAL_TECH:
                gid, gt = "g-scr-term", "Terminal screens (ISPF / IMS)"
            elif attrs.get("technology"):
                gid, gt = "g-scr-client", "Desktop / client-server screens"
            else:
                gid, gt = "g-scr-bms", "CICS / BMS screens"
            fam_key = re.sub(r"\d+", "nn", e["name"] or "")
            if fam_key in screen_family:
                if fam_key not in screen_node:
                    members = screen_family[fam_key]
                    screen_node[fam_key] = put("presentation", gid, gt, {
                        "id": nid, "title": f"{members[0]['name']}\u2013{members[-1]['name']}", "icon": _icon("screen"),
                        "sub": f"{len(members)} screens", "dashed": False, "badge": badge(src_art)})
                node_of[e["id"]] = screen_node[fam_key]
                continue
            node_of[e["id"]] = put("presentation", gid, gt, {"id": nid, "title": _short(e["name"], 30), "icon": _icon("screen"),
                                                             "dashed": ph, "badge": badge(src_art)})
        elif k == "api_endpoint" and not ph:
            node_of[e["id"]] = put("integration", "g-api", "HTTP endpoints & services",
                                   {"id": nid, "title": _short(e["name"], 32), "icon": _icon("api")})
        elif k == "transaction":
            node_of[e["id"]] = put("integration", "g-tx", "CICS transactions",
                                   {"id": nid, "title": e["name"], "icon": _icon("transaction"), "dashed": ph})
        elif k == "job" and attrs.get("tool") != "SQL script" and not ph:
            node_of[e["id"]] = put("integration", "g-job", "Batch jobs", {"id": nid, "title": _short(e["name"], 30),
                                                                         "icon": _icon("job"), "sub": attrs.get("tool")})
        elif k == "data_store":
            st = attrs.get("store_type") or ""
            db = st == "database"
            node_of[e["id"]] = put("data", "g-db" if db else "g-files", "Databases" if db else "Files & datasets",
                                   {"id": nid, "title": _short(e["name"], 32), "icon": _icon("database" if db else "file"),
                                    "sub": ("referenced only" if ph else st) or None, "dashed": ph})
        elif k == "table" and attrs.get("view"):
            node_of[e["id"]] = put("data", "g-views", "Views", {"id": nid, "title": _short(e["name"], 32), "icon": _icon("table"),
                                                               "dashed": ph, "sub": "view"})
        elif k == "table":
            cols = sum(1 for c in m.children.get(e["id"], []) if c["kind"] == "column")
            node_of[e["id"]] = put("data", "g-tables", "Tables", {"id": nid, "title": _short(e["name"], 32),
                                                                 "icon": _icon("table"), "dashed": ph,
                                                                 "sub": "no DDL captured" if ph else f"{cols} columns"})
        elif k == "external_system":
            node_of[e["id"]] = put("external", "g-ext", "External systems", {"id": nid, "title": _short(e["name"], 32),
                                                                            "icon": _icon("external"), "dashed": ph,
                                                                            "sub": attrs.get("protocol")})
        elif ph and k in ("program", "class", "copybook") and classify_placeholder(e) == "missing_code":
            node_of[e["id"]] = put("application", "g-missing", f"Referenced, {not_there}",
                                   {"id": nid, "title": _short(e["name"], 30), "icon": _icon("missing"), "dashed": True,
                                    "sub": k})
    if lanes_["presentation"] or any(g for g in lanes_["integration"] if g in ("g-api", "g-tx")):
        put("users", "g-actors", "People & schedulers", {"id": "u-users", "title": "Program users", "icon": _icon("users"),
                                                          "sub": "Business users"}, dashed=False)
    if "g-job" in lanes_["integration"]:
        put("users", "g-actors", "People & schedulers", {"id": "u-sched", "title": "Batch scheduler", "icon": _icon("job"),
                                                          "sub": "JCL / job control"}, dashed=False)

    def target(eid):
        if eid in node_of:
            return node_of[eid]
        for aid in sorted(m.sources.get(eid, ())):
            if f"art:{aid}" in node_of:
                return node_of[f"art:{aid}"]
        top = m.top(eid)
        return node_of.get(top) if top else None

    agg = {}
    for r in m.rels:
        if r["kind"] in ("contains", "same_as"):
            continue
        a = node_of.get(f"art:{r['artifact_id']}") if r["artifact_id"] in m.arts and r["from_id"] not in node_of else None
        a = a or target(r["from_id"])
        b = target(r["to_id"])
        if a and b and a != b:
            agg.setdefault((a, b), set()).add(r["kind"])
    edges = [{"from": a, "to": b, "label": "", "style": "dashed" if kinds <= {"reads", "displays"} else "solid", "head": "arrow"}
             for (a, b), kinds in agg.items()]
    for gid in ("g-scr-bms", "g-scr-web", "g-scr-app"):
        if gid in lanes_["presentation"]:
            edges.append({"from": "u-users", "to": gid, "label": "", "style": "solid", "head": "arrow"})
    for gid in ("g-api", "g-tx"):
        if gid in lanes_["integration"] and "u-users" in {n["id"] for g in lanes_["users"].values() for n in g["nodes"]}:
            edges.append({"from": "u-users", "to": gid, "label": "", "style": "solid", "head": "arrow"})
    if "g-job" in lanes_["integration"]:
        edges.append({"from": "u-sched", "to": "g-job", "label": "", "style": "solid", "head": "arrow"})
    order = {"users": "Users & triggers", "presentation": "Presentation", "application": "Application",
             "integration": "Integration", "data": "Data", "external": "External"}
    group_order = ["g-actors", "g-scr-bms", "g-scr-web", "g-scr-app", "g-scr-miss", "g-cics", "g-cobol", "g-cobnet", "g-cs",
                   "g-java", "g-cpp", "g-js", "g-code", "g-missing", "g-tx", "g-api", "g-job", "g-db", "g-tables",
                   "g-files", "g-ext"]
    lane_specs = []
    for key, title in order.items():
        gs = sorted(lanes_[key].values(), key=lambda g: group_order.index(g["id"]) if g["id"] in group_order else 99)
        if gs:
            lane_specs.append({"id": f"lane-{key}", "title": title, "groups": gs})
    bars = []
    techs, seen = [], set()
    for t in technologies(store):
        base = t.get("name") or t.get("label")
        ver = t.get("version") or (t.get("cycle") if not t.get("curated") else None)
        label = f"{base} {ver}" if ver else base
        key = (base, ver)
        if key in seen:
            continue
        seen.add(key)
        fill, stroke = STATUS_CHIP.get(t.get("status"), STATUS_CHIP["unknown"])
        status = {"eol": "EOL", "extended": "ext. support", "legacy": "legacy", "ending": "EOL soon",
                  "supported": "supported", "unknown": "version ?"}.get(t.get("status"), "")
        techs.append({"id": f"t{len(techs)}", "title": f"{_short(label, 34)} · {status}", "fill": fill, "stroke": stroke,
                      "kind": "chip"})
    covered = " ".join(t["title"].lower() for t in techs)
    by_lang = {}
    for a in m.arts.values():
        lang = (a.get("language") or "").strip()
        if lang and a.get("artifact_type") not in ("ui_screen", "document"):
            by_lang[lang] = by_lang.get(lang, 0) + 1
    for lang, n in sorted(by_lang.items()):            # every language in the files, not only the ones with a support record
        if lang.lower() in covered or any(w in covered for w in re.findall(r"[a-z/]{3,}", lang.lower()) if w not in ("code", "the")):
            continue
        fill, stroke = STATUS_CHIP["unknown"]
        techs.append({"id": f"t{len(techs)}", "title": f"{_short(lang, 28)} \u00b7 {n} file{'s' if n != 1 else ''} \u00b7 version ?",
                      "fill": fill, "stroke": stroke, "kind": "chip"})
    if techs:
        bars.append({"id": "bar-platform", "title": "Platform & runtime", "chips": techs})
    cfg = [a for a in m.arts.values() if family(a["name"], a.get("language") or "") in ("config", "props", "json")
           and a.get("artifact_type") != "ui_screen"]
    if cfg:
        secrets = {}
        for e in m.ents.values():
            if e["kind"] == "config_item" and (e.get("attrs") or {}).get("hardcoded_secret"):
                secrets[e["artifact_id"]] = secrets.get(e["artifact_id"], 0) + 1
        bars.append({"id": "bar-config", "title": "Configuration", "chips": [
            {"id": f"cfg{a['id']}", "title": a["name"] + (f" · {secrets[a['id']]} secret(s)" if secrets.get(a["id"]) else ""),
             "kind": "chip", **({"fill": "#FDE2E1", "stroke": "#B3261E"} if secrets.get(a["id"]) else {})} for a in cfg]})
    sec = sec_summary(store)
    chips = [{"id": f"sev-{k}", "title": f"{v} {k}", "kind": "chip", "fill": SEV_CHIP[k][0], "stroke": SEV_CHIP[k][1],
              "ink": "#FFFFFF" if k == "critical" else None} for k, v in sec["by_severity"].items() if v] if sec["total"] else []
    try:        # the line-by-line review records security observations the rule-based scan does not
        from core import deepdive as _DD
        reviewed = {k: 0 for k in ("critical", "high", "medium", "low")}
        for facts in _DD.review_facts(store).values():
            for f in facts:
                if f.get("category") == "security" and f.get("severity") in reviewed:
                    reviewed[f["severity"]] += 1
    except Exception:  # noqa: BLE001 - the chip is an extra
        reviewed = {}
    chips += [{"id": f"rev-{k}", "title": f"{v} {k} (code review)", "kind": "chip", "fill": SEV_CHIP[k][0], "stroke": SEV_CHIP[k][1],
               "ink": "#FFFFFF" if k == "critical" else None} for k, v in reviewed.items() if v]
    if chips:
        bars.append({"id": "bar-security", "title": "Security findings", "chips": chips})
    cov = store.coverage()
    mc = cov.get("missing_counts") or {}
    word_files, word_missing, word_ratio = (("files read from the folder", "code references not in the folder", "of referenced code supplied")
                                            if from_folder else ("files captured", "code references not captured", "of referenced code captured"))
    bars.append({"id": "bar-coverage", "title": "Coverage", "chips": [
        {"id": "cov-files", "title": f"{len(m.arts)} {word_files}", "kind": "chip"},
        {"id": "cov-missing", "title": f"{mc.get('missing_code', 0)} {word_missing}", "kind": "chip"},
        {"id": "cov-ext", "title": f"{mc.get('external', 0)} external resources", "kind": "chip"},
        {"id": "cov-ratio", "title": f"{round((cov.get('resolved_ratio') or 0) * 100)}% {word_ratio}",
         "kind": "chip"}]})
    verdict = (assessment.get("verdict") or {}).get("label")
    scene = lanes(lane_specs, edges, bars)
    title = f"Architecture overview — {name}" + (f"  ·  verdict: {verdict}" if verdict else "")
    return {"id": "architecture", "kind": "architecture", "title": title, **scene}


def user_flow(store) -> dict | None:
    from core.uireview.flows import canonical_screens, journeys
    m = _model(store)
    canon = canonical_screens(store, m.ents, m.rels)
    fl = journeys(store)
    by_name = {}
    for e in m.ents.values():
        if e["kind"] == "screen" and e["id"] not in canon:
            by_name.setdefault(e["name"], e)
    if not by_name:
        return None
    nodes, edges = [], []
    for name, e in sorted(by_name.items()):
        attrs = e.get("attrs") or {}
        art = m.arts.get(e["artifact_id"]) or {}
        tech = "3270 / CICS" if art.get("name", "").lower().endswith(".bms") else attrs.get("screen_type") or \
            ("web page" if attrs.get("technology") == "web" else "screen")
        nodes.append({"id": f"s{e['id']}", "title": _short(name, 32), "stereotype": ("not captured" if e["origin"] == "placeholder"
                                                                                   else tech), "kind": "actor" if e["origin"] != "placeholder" else "missing",
                      "dashed": e["origin"] == "placeholder"})
    ids = {name: f"s{e['id']}" for name, e in by_name.items()}      # keyed by the full, unique name
    for a, b, how in fl["edges"]:
        if a in ids and b in ids:
            edges.append({"from": ids[a], "to": ids[b], "label": how, "style": "solid", "head": "arrow"})
    scene = layered(nodes, edges, "LR", straight=len(edges) > 12)
    return {"id": "userflow", "kind": "userflow", "title": f"User flow — {store.info['name']}", **scene}
