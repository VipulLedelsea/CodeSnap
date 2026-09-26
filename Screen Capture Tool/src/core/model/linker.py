import re
from collections import deque

LINKER_VERSION = "linker-v1"
EXTERNAL_KINDS = {"table", "column", "data_store", "external_system", "transaction", "api_endpoint"}
CODE_KINDS = {"program", "module", "file", "class", "interface", "function", "paragraph", "section", "copybook",
              "screen", "job", "field", "ui_element", "config_item"}
LIBRARY_PREFIXES = ("java.", "javax.", "jakarta.", "system", "microsoft.", "org.apache.", "org.springframework",
                    "org.hibernate", "com.sun.", "sun.", "std", "windows", "afx", "atl", "newtonsoft", "log4j",
                    "junit", "org.junit", "mscorlib")
STD_HEADERS = {"iostream", "iostream.h", "fstream", "fstream.h", "string", "string.h", "stdio.h", "stdlib.h",
               "math.h", "time.h", "ctype.h", "vector", "map", "list", "set", "algorithm", "memory", "cstdio",
               "cstdlib", "cstring", "sstream", "iomanip", "iomanip.h", "windows.h", "afxwin.h", "stdafx.h",
               "conio.h", "dos.h", "malloc.h", "assert.h", "limits.h", "errno.h", "signal.h", "stddef.h",
               "strstream", "strstrea.h", "sql.h", "sqlext.h", "objbase.h", "atlbase.h"}
CONFIG_READ = [
    re.compile(r"ConnectionStrings\s*\[\s*\"([^\"]+)\"\s*\]"),
    re.compile(r"AppSettings\s*\[\s*\"([^\"]+)\"\s*\]"),
    re.compile(r"\.(?:getProperty|getInitParameter|getParameter|getString)\s*\(\s*\"([^\"]+)\""),
    re.compile(r"(?:Configuration|config|Config)\s*\[\s*\"([^\"]+)\"\s*\]"),
    re.compile(r"GetConnectionString\s*\(\s*\"([^\"]+)\"\s*\)"),
    re.compile(r"GetValue<[^>]*>\s*\(\s*\"([^\"]+)\"\s*\)"),
]
FLOW_EDGES = {"calls", "uses", "invokes_transaction", "depends_on", "same_as", "includes", "displays"}
TERMINAL_EDGES = {"reads", "writes", "connects_to"}
ENTRY_KINDS = ("screen", "api_endpoint", "transaction", "job")


def _is_library(name: str) -> bool:
    from core.langs.stdlib import is_library_type
    low = (name or "").lower()
    if low in STD_HEADERS or low.startswith(LIBRARY_PREFIXES):
        return True
    owner = name.split(".")[0] if "." in name else name
    return is_library_type(owner) or owner in ("HttpServlet", "Controller", "ApiController", "ControllerBase", "Page",
                                                "UserControl", "Form", "JFrame", "Applet", "Action", "ActionForm")


def classify(entity: dict, referrers=()) -> str:
    kind, name = entity["kind"], entity["name"]
    if kind in EXTERNAL_KINDS:
        return "external"
    if kind == "module":
        if any((r.get("relation") == "includes") for r in referrers or ()) and name.lower() not in STD_HEADERS \
                and not name.lower().startswith(LIBRARY_PREFIXES):
            return "missing_code"
        return "library" if _is_library(name) or "." in name else "missing_code"
    if kind in ("class", "interface", "function") and _is_library(name):
        return "library"
    return "missing_code"


def _short(name: str) -> str:
    return re.split(r"[.:]", name)[-1].upper()


def _merge_placeholders(store) -> int:
    real = [e for e in store.entities() if e["origin"] != "placeholder"]
    by_key = {e["key"].lower(): e for e in real}
    by_kind_short = {}
    for e in real:
        by_kind_short.setdefault((e["kind"], _short(e["name"])), []).append(e)
    type_group = {"class": ("class", "interface"), "interface": ("interface", "class"), "program": ("program",),
                  "table": ("table",), "copybook": ("copybook",), "screen": ("screen",), "file": ("file",),
                  "function": ("function",), "data_store": ("data_store",), "job": ("job",)}
    merged = 0
    for p in store.entities(origin="placeholder"):
        target = by_key.get(p["key"].lower())
        if target is None and p["kind"] == "unknown":
            cands = [e for e in real if e["name"].lower() == p["name"].lower()]
            target = cands[0] if len(cands) == 1 else None
        if target is None:
            for kind in type_group.get(p["kind"], ()):
                cands = by_kind_short.get((kind, _short(p["name"])), [])
                if p["kind"] == "function":
                    owner = p["name"].rsplit(".", 1)[0].split(".")[-1].upper() if "." in p["name"] else None
                    cands = [c for c in cands if owner is None or (c["parent_id"] and _short(
                        (store.entity(c["parent_id"]) or {}).get("name", "")) == owner)]
                if len(cands) == 1:
                    target = cands[0]
                    break
        if target is not None:
            store.merge_entities(p["id"], target["id"], rule="name")
            merged += 1
    return merged


def _artifact_program(store, artifact_id):
    rows = store._all("SELECT e.* FROM entity e JOIN entity_source s ON s.entity_id = e.id "
                      "WHERE s.artifact_id = ? AND e.kind = 'program'", (artifact_id,))
    return rows[0] if rows else None


def _link_jcl(store) -> int:
    created = 0
    for r in store.relations():
        attrs = r["attrs"]
        if r["kind"] not in ("reads", "writes") or not attrs.get("ddname") or not attrs.get("program"):
            continue
        program = store.entity_by_key(f"program:{attrs['program']}")
        if program is None or program["origin"] == "placeholder" or not program["artifact_id"]:
            continue
        files = store._all("SELECT e.* FROM entity e JOIN entity_source s ON s.entity_id = e.id "
                           "WHERE s.artifact_id = ? AND e.kind = 'data_store'", (program["artifact_id"],))
        for f in files:
            if str(f["attrs"].get("assign", "")).upper() == attrs["ddname"].upper():
                store.add_relation("connects_to", f["id"], r["to_id"], origin="inferred",
                                   attrs={"rule": "jcl_dd", "ddname": attrs["ddname"], "step": attrs.get("step")})
                created += 1
    return created


def _innermost(store, artifact_id, line):
    rows = store._all(
        "SELECT e.* FROM entity e JOIN entity_source s ON s.entity_id = e.id WHERE s.artifact_id = ? "
        "AND e.kind IN ('function', 'paragraph', 'section', 'class', 'program') AND s.line_start <= ? "
        "AND (s.line_end IS NULL OR s.line_end >= ?) ORDER BY (COALESCE(s.line_end, 1e9) - s.line_start) ASC LIMIT 1",
        (artifact_id, line, line))
    return rows[0] if rows else None


def _link_config(store) -> int:
    items = {}
    for e in store.entities(kind="config_item"):
        items.setdefault(e["name"].lower(), e)
        items.setdefault(e["name"].split(":")[-1].lower(), e)
    if not items:
        return 0
    created = 0
    for a in store.artifacts():
        if a["artifact_type"] != "code" or not a["transcription"]:
            continue
        for n, line in enumerate(a["transcription"].splitlines(), 1):
            for rx in CONFIG_READ:
                for key in rx.findall(line):
                    item = items.get(key.lower())
                    if item is None:
                        continue
                    owner = _innermost(store, a["id"], n)
                    if owner is None:
                        continue
                    store.add_relation("reads", owner["id"], item["id"], artifact_id=a["id"], line=n,
                                       origin="inferred", attrs={"rule": "config_key", "key": key})
                    created += 1
    return created


def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 1}


def _link_screens(store) -> int:
    screens = store.entities(kind="screen")
    shots = [s for s in screens if s["attrs"].get("technology") == "screenshot" and s["origin"] != "placeholder"]
    others = [s for s in screens if s["attrs"].get("technology") != "screenshot" and s["origin"] != "placeholder"]
    created = 0
    for shot in shots:
        shot_labels = _tokens(" ".join(e["attrs"].get("label", e["name"]) for e in store.entities(kind="ui_element")
                                       if e["parent_id"] == shot["id"]))
        title = _tokens(shot["attrs"].get("title") or shot["name"])
        best, score = None, 0.0
        for other in others:
            labels = _tokens(" ".join((e["attrs"].get("label") or e["attrs"].get("text") or e["name"])
                                      for e in store.entities(kind="ui_element") if e["parent_id"] == other["id"]))
            name_tokens = _tokens(other["name"]) | _tokens(other["attrs"].get("title") or "") | \
                _tokens(other["attrs"].get("mapset") or "")
            overlap = len(shot_labels & labels) / max(1, len(shot_labels | labels)) if shot_labels and labels else 0
            s = overlap + (0.5 if len(title & (name_tokens | labels)) >= 2 or (title & name_tokens) else 0)
            if s > score:
                best, score = other, s
        if best is not None and score >= 0.4:
            store.add_relation("same_as", shot["id"], best["id"], origin="inferred",
                               attrs={"rule": "screen_match", "score": round(score, 2)})
            created += 1
    return created


def _link_translated(store) -> int:
    created = 0
    for p in store.entities(kind="program", origin="placeholder"):
        cls = store.entity_by_key(f"class:{p['name']}")
        if cls is None or cls["origin"] == "placeholder":
            continue
        file = store._all("SELECT e.* FROM entity e JOIN entity_source s ON s.entity_id = e.id "
                          "WHERE e.kind = 'file' AND s.artifact_id = ?", (cls["artifact_id"],))
        profile = (file[0]["attrs"].get("profile") if file else {}) or {}
        if profile.get("cobol_translated"):
            store.add_relation("same_as", p["id"], cls["id"], origin="inferred", attrs={"rule": "cobol_translated"})
            created += 1
    return created


def link_program(store) -> dict:
    with store.transaction() as db:
        db.execute("DELETE FROM relation WHERE origin = 'inferred' AND artifact_id IS NULL")
    return {"merged": _merge_placeholders(store), "jcl": _link_jcl(store), "config": _link_config(store),
            "screens": _link_screens(store), "translated": _link_translated(store), "version": LINKER_VERSION}


def trace_flows(store, max_depth: int = 12, per_entry: int = 40) -> list:
    entities = {e["id"]: e for e in store.entities()}
    out_edges = {}
    for r in store.relations():
        out_edges.setdefault(r["from_id"], []).append(r)
    children = {}
    for e in entities.values():
        if e["parent_id"]:
            children.setdefault(e["parent_id"], []).append(e)
    flows = []
    entries = [e for e in entities.values() if e["kind"] in ENTRY_KINDS and e["origin"] != "placeholder"
               and not (e["kind"] == "job" and e["attrs"].get("tool") == "SQL script")]
    for entry in sorted(entries, key=lambda e: (ENTRY_KINDS.index(e["kind"]), e["name"])):
        seen = {entry["id"]}
        queue = deque([(entry["id"], [])])
        found = []
        while queue and len(found) < per_entry:
            node, path = queue.popleft()
            if len(path) >= max_depth:
                continue
            for r in out_edges.get(node, []):
                if r["kind"] in TERMINAL_EDGES:
                    target = entities.get(r["to_id"])
                    if target is not None:
                        found.append({"target": target, "path": path + [r]})
            nxt = [r for r in out_edges.get(node, []) if r["kind"] in FLOW_EDGES]
            node_kind = entities[node]["kind"] if node in entities else None
            if node_kind in ("program", "section", "class", "copybook"):
                nxt += [{"kind": "contains", "from_id": node, "to_id": c["id"], "line": c["line_start"], "attrs": {}}
                        for c in children.get(node, []) if c["kind"] in ("section", "paragraph", "function")]
            for r in nxt:
                if r["to_id"] not in seen:
                    seen.add(r["to_id"])
                    queue.append((r["to_id"], path + [r]))
        for f in found:
            steps = [{"from": entities[s["from_id"]]["name"] if s["from_id"] in entities else "?",
                      "kind": s["kind"], "to": entities[s["to_id"]]["name"] if s["to_id"] in entities else "?",
                      "line": s.get("line")} for s in f["path"]]
            flows.append({"entry": entry["name"], "entry_kind": entry["kind"], "target": f["target"]["name"],
                          "target_kind": f["target"]["kind"], "access": steps[-1]["kind"] if steps else None,
                          "steps": steps, "length": len(steps)})
    return flows
