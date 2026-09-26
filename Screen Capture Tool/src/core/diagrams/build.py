from core.model.linker import trace_flows
from core.model.store import classify_placeholder

from .layout import columns, layered, sequence

CLASS_KINDS = ("class", "interface", "program", "copybook")
MEMBER_ATTR = ("field", "column")
MEMBER_OP = ("function", "paragraph", "section")
CODE_REL = ("calls", "uses", "includes", "imports", "invokes_transaction", "depends_on", "navigates_to")
DATA_REL = ("reads", "writes", "connects_to", "displays")
MAX_ATTR, MAX_OPS, MAX_MESSAGES = 10, 14, 40


def _short(s, n=48):
    s = str(s)
    return s if len(s) <= n else s[:n - 1] + "…"


class _Model:
    def __init__(self, store):
        self.store = store
        self.ents = {e["id"]: e for e in store.entities()}
        self.rels = store.relations()
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
    m = _Model(store)
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
                detail.append("not captured")
            right.append({"id": f"e{e['id']}", "title": _short(e["name"]), "stereotype": stereo, "kind": kind,
                          "sections": [detail] if detail else [], "dashed": e["origin"] == "placeholder"})
            verbs = sorted(access.get(e["id"], {"connects_to"}))
            edges.append({"from": "program", "to": f"e{e['id']}", "label": "/".join(v.replace("connects_to", "connects")
                                                                                 for v in verbs), "style": "solid", "head": "arrow"})
    tables = [e for e in m.ents.values() if e["kind"] == "table"]
    if tables:
        names = sorted(tables, key=lambda t: t["name"])
        lines = [_short(t["name"], 40) + (" (no DDL)" if t["origin"] == "placeholder" else "") for t in names[:16]]
        if len(names) > 16:
            lines.append(f"+{len(names) - 16} more")
        right.append({"id": "tables", "title": f"Database tables ({len(tables)})", "stereotype": "data", "kind": "data_store",
                      "sections": [lines]})
        verbs = sorted({v for t in tables for v in access.get(t["id"], set())} or {"reads"})
        edges.append({"from": "program", "to": "tables", "label": "/".join(verbs), "style": "solid", "head": "arrow"})
    scene = columns([left, [program], right], edges)
    return {"id": "context", "kind": "context", "title": f"Context — {name}", **scene}


def components(store) -> dict:
    m = _Model(store)
    nodes, edges, agg = {}, [], {}
    for aid, a in m.arts.items():
        nodes[f"a{aid}"] = {"id": f"a{aid}", "title": a["name"], "stereotype": a.get("language") or a.get("artifact_type"),
                            "kind": "component"}
    for r in m.rels:
        if r["kind"] not in CODE_REL + DATA_REL:
            continue
        tt = m.ents.get(r["to_id"])
        if tt and tt["origin"] == "placeholder" and (tt["kind"] == "module" or classify_placeholder(tt) == "library"):
            continue
        src_art = r["artifact_id"] if r["artifact_id"] in m.arts else m.owner_art.get(r["from_id"])
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
    scene = layered(list(nodes.values()), edges, "LR", sinks=sinks, straight=True, per_row=12)
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
    stereo = {"interface": "interface", "program": "COBOL program", "copybook": "copybook"}.get(e["kind"])
    ph = e["origin"] == "placeholder"
    if ph:
        stereo = (stereo + " · " if stereo else "") + "not captured"
    sections = [x for x in (a_lines, o_lines) if x] if ph else [a_lines, o_lines]
    return {"id": f"c{e['id']}", "title": _short(e["name"].split(".")[-1], 40), "stereotype": stereo,
            "kind": "missing" if ph else "class", "sections": sections, "dashed": ph}


def classes(store, artifact_id=None) -> dict:
    m = _Model(store)
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
    scene = layered(nodes, edges, "TB", straight=len(edges) > 12)
    title = "Classes & programs" + (f" — {m.arts[artifact_id]['name']}" if artifact_id else f" — {store.info['name']}")
    return {"id": f"class-{artifact_id}" if artifact_id else "class", "kind": "class", "title": title, **scene}


def data_model(store) -> dict:
    m = _Model(store)
    tables = [e for e in m.ents.values() if e["kind"] == "table"]
    nodes, edges, seen = [], [], set()
    for t in sorted(tables, key=lambda t: t["name"]):
        cols = [k for k in m.children.get(t["id"], []) if k["kind"] == "column"]
        lines = []
        for c in sorted(cols, key=lambda c: (c["line_start"] or 0, c["name"])):
            at = c.get("attrs") or {}
            flag = " PK" if at.get("primary_key") else ""
            null = "" if at.get("nullable", True) else " NOT NULL"
            lines.append(_short(f"{c['name']}{': ' + str(at['type']) if at.get('type') else ''}{flag}{null}", 56))
        stereo = "table · no DDL captured" if t["origin"] == "placeholder" else ("view" if (t.get("attrs") or {}).get("view") else "table")
        nodes.append({"id": f"t{t['id']}", "title": _short(t["name"], 44), "stereotype": stereo, "kind": "table",
                      "sections": [lines] if lines else [], "dashed": t["origin"] == "placeholder"})
    ids = {t["id"] for t in tables}
    for r in m.rels:
        if r["kind"] == "depends_on" and r["from_id"] in ids and r["to_id"] in ids and r["from_id"] != r["to_id"]:
            key = (r["from_id"], r["to_id"])
            if key not in seen:
                seen.add(key)
                edges.append({"from": f"t{r['from_id']}", "to": f"t{r['to_id']}",
                              "label": "trigger" if (r.get("attrs") or {}).get("trigger_on") else "FK",
                              "style": "solid", "head": "open"})
    scene = layered(nodes, edges, "TB", straight=len(edges) > 12)
    return {"id": "data", "kind": "data", "title": f"Data model — {store.info['name']}", **scene}


def interactions(store, limit=40) -> list:
    flows = trace_flows(store)
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


def all_diagrams(store, per_file=True) -> list:
    out = [context(store), components(store), classes(store)]
    if any(e["kind"] == "table" for e in store.entities("table")):
        out.append(data_model(store))
    if per_file:
        m = _Model(store)
        for aid, a in m.arts.items():
            n = sum(1 for e in m.ents.values() if m.in_file(e["id"], aid) and (
                e["kind"] in CLASS_KINDS or (e["kind"] == "function" and m.top(e["id"]) is None)))
            if n >= 1:
                out.append(classes(store, aid))
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
