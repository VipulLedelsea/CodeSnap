import json

from .kinds import ENTITY_KINDS, RELATION_KINDS
from .store import entity_key

OPS = {
    "entity.rename": ("key", "name"),
    "entity.set_attrs": ("key", "attrs"),
    "entity.delete": ("key",),
    "entity.add": ("kind", "name"),
    "entity.merge": ("from_key", "to_key"),
    "relation.delete": ("kind", "from_key", "to_key"),
    "relation.add": ("kind", "from_key", "to_key"),
    "relation.set_attrs": ("kind", "from_key", "to_key", "attrs"),
    "finding.status": ("sig", "status"),
    "finding.severity": ("sig", "severity"),
    "finding.add": ("category", "severity", "title"),
}
STATUSES = {"open", "accepted", "dismissed", "fixed"}
SEVERITIES = {"critical", "high", "medium", "low", "info"}
FINDING_CATEGORIES = {"security", "eol", "vulnerability", "privacy", "accessibility", "usability", "ui_security", "website"}


class CorrectionError(ValueError):
    pass


def finding_sig(f) -> str:
    return f"{f.get('rule') or f['category']}|{f['title']}"


def _entity(store, key):
    if not key:
        return None
    e = store.entity_by_key(key)
    if e:
        return e
    row = store._one("SELECT * FROM entity WHERE attrs LIKE ?", (f'%"{key}"%',))
    if row and key in (row.get("attrs") or {}).get("aliases", []):
        return row
    return None


def _subtree(store, eid):
    ids, stack = {eid}, [eid]
    while stack:
        cur = stack.pop()
        for k in store._all("SELECT id FROM entity WHERE parent_id = ?", (cur,)):
            if k["id"] not in ids:
                ids.add(k["id"])
                stack.append(k["id"])
    return ids


def _rels(store, kind, a, b, deep=False):
    if not (a and b):
        return []
    sources = _subtree(store, a["id"]) if deep else {a["id"]}
    return [r for r in store.relations(kind, to_id=b["id"]) if r["from_id"] in sources]


def validate(op, payload):
    if op not in OPS:
        raise CorrectionError(f"unknown correction: {op}")
    missing = [k for k in OPS[op] if payload.get(k) in (None, "")]
    if missing:
        raise CorrectionError(f"{op} needs {', '.join(missing)}")
    if op == "entity.add" and payload["kind"] not in ENTITY_KINDS:
        raise CorrectionError(f"unknown entity kind {payload['kind']}")
    if op.startswith("relation.") and payload["kind"] not in RELATION_KINDS:
        raise CorrectionError(f"unknown relation kind {payload['kind']}")
    if op == "finding.status" and payload["status"] not in STATUSES:
        raise CorrectionError("status must be open, accepted, dismissed or fixed")
    if op in ("finding.severity", "finding.add") and payload["severity"] not in SEVERITIES:
        raise CorrectionError("severity must be critical, high, medium, low or info")
    if op == "finding.add" and payload["category"] not in FINDING_CATEGORIES:
        raise CorrectionError(f"unknown finding category {payload['category']}")
    for k in ("attrs",):
        if k in OPS[op] and not isinstance(payload.get(k), dict):
            raise CorrectionError("attrs must be an object")


def describe(c) -> str:
    p, op = c["payload"], c["op"]
    name = lambda k: (p.get(k) or "").split(":", 1)[-1]
    return {
        "entity.rename": lambda: f"Rename {name('key')} → {p.get('name')}",
        "entity.set_attrs": lambda: f"Set {', '.join(f'{k}={v}' for k, v in p.get('attrs', {}).items())} on {name('key')}",
        "entity.delete": lambda: f"Remove {name('key')} (not real)",
        "entity.add": lambda: f"Add {p.get('kind')} {p.get('name')}",
        "entity.merge": lambda: f"Merge {name('from_key')} into {name('to_key')}",
        "relation.delete": lambda: f"Remove: {name('from_key')} {p.get('kind')} {name('to_key')}",
        "relation.add": lambda: f"Add: {name('from_key')} {p.get('kind')} {name('to_key')}",
        "relation.set_attrs": lambda: f"Set {', '.join(f'{k}={v}' for k, v in p.get('attrs', {}).items())} on "
                                      f"{name('from_key')} {p.get('kind')} {name('to_key')}",
        "finding.status": lambda: f"Mark '{p.get('sig', '').split('|', 1)[-1]}' {p.get('status')}",
        "finding.severity": lambda: f"Set '{p.get('sig', '').split('|', 1)[-1]}' to {p.get('severity')}",
        "finding.add": lambda: f"Add {p.get('severity')} {p.get('category')} finding: {p.get('title')}",
    }.get(op, lambda: op)()


def _snap_entity(store, e):
    kids, stack, seen = [], [e["id"]], set()
    while stack:
        cur = stack.pop()
        for k in store._all("SELECT * FROM entity WHERE parent_id = ?", (cur,)):
            if k["id"] not in seen:
                seen.add(k["id"])
                kids.append(k)
                stack.append(k["id"])
    ids = {e["id"]} | seen
    key_of = {i: store.entity(i)["key"] for i in ids}
    rels = []
    for r in store._all(f"SELECT * FROM relation WHERE from_id IN ({','.join('?' * len(ids))}) OR to_id IN "
                        f"({','.join('?' * len(ids))})", (*ids, *ids)):
        fk = key_of.get(r["from_id"]) or (store.entity(r["from_id"]) or {}).get("key")
        tk = key_of.get(r["to_id"]) or (store.entity(r["to_id"]) or {}).get("key")
        rels.append({"kind": r["kind"], "from_key": fk, "to_key": tk, "attrs": r["attrs"], "artifact_id": r["artifact_id"],
                     "line": r["line"], "origin": r["origin"]})
    ent = lambda x: {"kind": x["kind"], "key": x["key"], "name": x["name"], "attrs": x["attrs"], "origin": x["origin"],
                     "artifact_id": x["artifact_id"], "line_start": x["line_start"], "line_end": x["line_end"],
                     "parent_key": (store.entity(x["parent_id"]) or {}).get("key") if x["parent_id"] else None}
    return {"entities": [ent(e)] + [ent(k) for k in kids], "relations": rels}


def _delete_entity(store, e):
    snap = _snap_entity(store, e)
    ids = [store.entity_by_key(x["key"])["id"] for x in snap["entities"] if store.entity_by_key(x["key"])]
    with store.transaction() as db:
        q = ",".join("?" * len(ids))
        db.execute(f"DELETE FROM relation WHERE from_id IN ({q}) OR to_id IN ({q})", (*ids, *ids))
        db.execute(f"DELETE FROM entity_source WHERE entity_id IN ({q})", ids)
        db.execute(f"DELETE FROM entity WHERE id IN ({q})", ids)
    return snap


def _set_entity(store, e, *, name=None, attrs=None):
    with store.transaction() as db:
        db.execute("UPDATE entity SET name = COALESCE(?, name), attrs = COALESCE(?, attrs), origin = 'corrected' WHERE id = ?",
                   (name, json.dumps(attrs) if attrs is not None else None, e["id"]))


def apply_one(store, c) -> str | None:
    op, p = c["op"], dict(c["payload"])
    changed = False
    if op == "entity.rename":
        e = _entity(store, p["key"])
        if not e:
            return "not found"
        if e["name"] != p["name"]:
            p.setdefault("_before", {"name": e["name"], "origin": e["origin"]})
            _set_entity(store, e, name=p["name"])
            changed = True
    elif op == "entity.set_attrs":
        e = _entity(store, p["key"])
        if not e:
            return "not found"
        cur = dict(e["attrs"])
        if any(cur.get(k) != v for k, v in p["attrs"].items()):
            p.setdefault("_before", {"attrs": {k: cur.get(k) for k in p["attrs"]}, "origin": e["origin"]})
            _set_entity(store, e, attrs={**cur, **p["attrs"]})
            changed = True
    elif op == "entity.delete":
        e = _entity(store, p["key"])
        if e:
            snap = _delete_entity(store, e)
            if "_snapshot" not in p:
                p["_snapshot"] = snap
                changed = True
    elif op == "entity.add":
        parent = _entity(store, p.get("parent_key")) if p.get("parent_key") else None
        key = entity_key(p["kind"], p["name"], parent["key"] if parent else None)
        if not store.entity_by_key(key):
            store.upsert_entity(p["kind"], p["name"], key=key, parent_id=parent["id"] if parent else None,
                                attrs=p.get("attrs") or None, origin="corrected")
            p["_key"] = key
            changed = True
    elif op == "entity.merge":
        a, b = _entity(store, p["from_key"]), _entity(store, p["to_key"])
        if a and b and a["id"] != b["id"]:
            store.merge_entities(a["id"], b["id"], rule="correction")
            changed = True
        elif not b:
            return "target not found"
    elif op in ("relation.delete", "relation.add", "relation.set_attrs"):
        a, b = _entity(store, p["from_key"]), _entity(store, p["to_key"])
        if not a or not b:
            if op != "relation.delete":
                return "endpoint not found"
            return None
        rels = _rels(store, p["kind"], a, b, deep=op == "relation.delete")
        if op == "relation.delete" and rels:
            snap = p.setdefault("_snapshot", [])
            seen = {(x.get("from_key"), x.get("artifact_id"), x.get("line")) for x in snap}
            for r in rels:
                fk = store.entity(r["from_id"])["key"]
                if (fk, r["artifact_id"], r["line"]) not in seen:
                    snap.append({"from_key": fk, "attrs": r["attrs"], "artifact_id": r["artifact_id"], "line": r["line"],
                                 "origin": r["origin"]})
            with store.transaction() as db:
                db.execute(f"DELETE FROM relation WHERE id IN ({','.join('?' * len(rels))})", [r["id"] for r in rels])
            changed = True
        elif op == "relation.add" and not rels:
            store.add_relation(p["kind"], a["id"], b["id"], attrs=p.get("attrs") or None, origin="corrected")
            changed = True
        elif op == "relation.set_attrs":
            for r in rels:
                if any(r["attrs"].get(k) != v for k, v in p["attrs"].items()):
                    p.setdefault("_before", {"attrs": {k: r["attrs"].get(k) for k in p["attrs"]}})
                    with store.transaction() as db:
                        db.execute("UPDATE relation SET attrs = ?, origin = 'corrected' WHERE id = ?",
                                   (json.dumps({**r["attrs"], **p["attrs"]}), r["id"]))
                    changed = True
    elif op in ("finding.status", "finding.severity"):
        hits = [f for f in store.findings() if finding_sig(f) == p["sig"] or f["title"] == p["sig"]]
        for f in hits:
            with store.transaction() as db:
                if op == "finding.status" and f["status"] != p["status"]:
                    db.execute("UPDATE finding SET status = ? WHERE id = ?", (p["status"], f["id"]))
                elif op == "finding.severity" and f["severity"] != p["severity"]:
                    db.execute("UPDATE finding SET severity = ? WHERE id = ?", (p["severity"], f["id"]))
        if not hits:
            return "finding not present (re-appears after next scan if still relevant)"
    elif op == "finding.add":
        if not any(f["title"] == p["title"] and f["origin"] == "user" for f in store.findings()):
            store.add_finding(p["category"], p["severity"], p["title"], detail=p.get("detail", ""),
                              source=f"analyst correction #{c['id']}", origin="user", rule=p.get("rule") or "USER",
                              evidence=[{"file": p.get("file"), "line": p.get("line"), "note": c.get("note")}] if p.get("file") else [])
    if changed and p != c["payload"]:
        store.update_correction(c["id"], payload=p)
    return None


def apply_corrections(store) -> dict:
    applied, skipped = 0, []
    for c in store.corrections():
        try:
            reason = apply_one(store, c)
        except Exception as exc:
            reason = f"error: {exc}"
        if reason:
            skipped.append({"id": c["id"], "reason": reason})
        else:
            applied += 1
    return {"applied": applied, "skipped": skipped}


def add(store, op, payload, note="") -> dict:
    payload = {k: v for k, v in (payload or {}).items() if not str(k).startswith("_")}
    validate(op, payload)
    cid = store.add_correction(op.split(".")[0], None, op, payload, note)
    c = store.correction(cid)
    reason = apply_one(store, c)
    return {"id": cid, "description": describe(store.correction(cid)), "warning": reason}


def undo(store, correction_id) -> dict:
    c = store.correction(correction_id)
    if not c or not c["active"]:
        raise CorrectionError("no such active correction")
    op, p = c["op"], c["payload"]
    if op == "entity.merge":
        raise CorrectionError("merges can't be undone automatically — re-extract the affected files")
    store.update_correction(correction_id, active=False)
    if op in ("entity.rename", "entity.set_attrs") and p.get("_before"):
        e = _entity(store, p["key"]) or (_entity(store, None))
        if e:
            before = p["_before"]
            attrs = dict(e["attrs"])
            for k, v in (before.get("attrs") or {}).items():
                if v is None:
                    attrs.pop(k, None)
                else:
                    attrs[k] = v
            with store.transaction() as db:
                db.execute("UPDATE entity SET name = COALESCE(?, name), attrs = ?, origin = ? WHERE id = ?",
                           (before.get("name"), json.dumps(attrs), before.get("origin") or "extracted", e["id"]))
    elif op == "entity.delete" and p.get("_snapshot"):
        snap = p["_snapshot"]
        for x in snap["entities"]:
            if store.entity_by_key(x["key"]):
                continue
            parent = store.entity_by_key(x["parent_key"]) if x.get("parent_key") else None
            store.upsert_entity(x["kind"], x["name"], key=x["key"], parent_id=parent["id"] if parent else None,
                                attrs=x["attrs"] or None, artifact_id=x["artifact_id"], line_start=x["line_start"],
                                line_end=x["line_end"], origin=x["origin"] if x["origin"] != "corrected" else "extracted")
        for r in snap["relations"]:
            a, b = store.entity_by_key(r["from_key"]), store.entity_by_key(r["to_key"])
            if a and b:
                store.add_relation(r["kind"], a["id"], b["id"], attrs=r["attrs"] or None, artifact_id=r["artifact_id"],
                                   line=r["line"], origin=r["origin"])
    elif op == "entity.add":
        e = store.entity_by_key(p.get("_key") or "")
        if e and e["origin"] == "corrected":
            _delete_entity(store, e)
    elif op == "relation.delete" and p.get("_snapshot"):
        b = _entity(store, p["to_key"])
        for r in p["_snapshot"]:
            a = _entity(store, r.get("from_key") or p["from_key"])
            if a and b:
                store.add_relation(p["kind"], a["id"], b["id"], attrs=r["attrs"] or None, artifact_id=r["artifact_id"],
                                   line=r["line"], origin=r["origin"])
    elif op == "relation.add":
        a, b = _entity(store, p["from_key"]), _entity(store, p["to_key"])
        with store.transaction() as db:
            for r in _rels(store, p["kind"], a, b):
                if r["origin"] == "corrected":
                    db.execute("DELETE FROM relation WHERE id = ?", (r["id"],))
    elif op == "relation.set_attrs" and p.get("_before"):
        a, b = _entity(store, p["from_key"]), _entity(store, p["to_key"])
        for r in _rels(store, p["kind"], a, b):
            attrs = dict(r["attrs"])
            for k, v in p["_before"]["attrs"].items():
                if v is None:
                    attrs.pop(k, None)
                else:
                    attrs[k] = v
            with store.transaction() as db:
                db.execute("UPDATE relation SET attrs = ? WHERE id = ?", (json.dumps(attrs), r["id"]))
    elif op == "finding.add":
        with store.transaction() as db:
            db.execute("DELETE FROM finding WHERE origin = 'user' AND title = ?", (p["title"],))
    elif op == "finding.status":
        with store.transaction() as db:
            db.execute("UPDATE finding SET status = 'open' WHERE (rule || '|' || title) = ? OR title = ?", (p["sig"], p["sig"]))
    return {"id": correction_id, "undone": describe(c)}


def history(store) -> list:
    return [{**{k: c[k] for k in ("id", "op", "note", "created", "active")}, "target": c["target_type"],
             "description": describe(c), "payload": {k: v for k, v in c["payload"].items() if not k.startswith("_")},
             "undoable": c["op"] != "entity.merge"} for c in store.corrections(active_only=False)]
