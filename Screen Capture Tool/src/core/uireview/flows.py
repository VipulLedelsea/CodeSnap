from collections import deque


def canonical_screens(store, ents=None, rels=None):
    ents = ents or {e["id"]: e for e in store.entities()}
    rels = rels if rels is not None else store.relations()
    canon = {}
    for r in rels:
        if r["kind"] == "same_as" and ents.get(r["from_id"], {}).get("kind") == "screen" \
                and ents.get(r["to_id"], {}).get("kind") == "screen":
            a, b = r["from_id"], r["to_id"]
            shot = a if (ents[a].get("attrs") or {}).get("technology") == "screenshot" else b
            canon[shot] = b if shot == a else a
    return canon


def journeys(store, max_depth=10, limit=40) -> dict:
    ents = {e["id"]: e for e in store.entities()}
    rels = store.relations()
    canon = canonical_screens(store, ents, rels)
    screens = {i for i, e in ents.items() if e["kind"] == "screen" and i not in canon}
    displays = {}
    for r in rels:
        if r["kind"] == "displays" and r["to_id"] in screens:
            displays.setdefault(r["from_id"], set()).add(r["to_id"])
    top = {}
    for i, e in ents.items():
        p, seen = i, set()
        while p and p not in seen:
            seen.add(p)
            if ents[p]["kind"] in ("program", "class"):
                top[i] = p
                break
            p = ents[p]["parent_id"]
    shown_by = {}
    for src, targets in displays.items():
        owner = top.get(src, src)
        shown_by.setdefault(owner, set()).update(targets)
    edges = {}

    def link(a, b, how):
        a, b = canon.get(a, a), canon.get(b, b)
        if a != b and a in screens and b in screens:
            edges.setdefault(a, {})[b] = how

    for r in rels:
        a, b = r["from_id"], r["to_id"]
        if r["kind"] == "navigates_to":
            link(a, b, "link")
        elif r["kind"] == "calls" and (r.get("attrs") or {}).get("cics") in ("XCTL", "LINK"):
            for s1 in shown_by.get(top.get(a, a), ()):
                for s2 in shown_by.get(top.get(b, b), ()):
                    link(s1, s2, f"CICS {(r.get('attrs') or {}).get('cics')}")
        elif r["kind"] == "calls" and a in screens and ents.get(b, {}).get("kind") == "api_endpoint":
            for r2 in rels:
                if r2["from_id"] == b and r2["kind"] in ("calls", "uses"):
                    for s2 in shown_by.get(top.get(r2["to_id"], r2["to_id"]), ()):
                        link(a, s2, "form submit")
    incoming = {b for a in edges for b in edges[a]}
    starts = [s for s in screens if s not in incoming and ents[s]["origin"] != "placeholder"] or \
             [s for s in screens if ents[s]["origin"] != "placeholder"][:1]
    out = []
    for s in sorted(starts, key=lambda i: ents[i]["name"]):
        queue = deque([[s]])
        while queue and len(out) < limit:
            path = queue.popleft()
            nxt = [n for n in edges.get(path[-1], {}) if n not in path]
            if not nxt or len(path) >= max_depth:
                if len(path) > 1:
                    out.append({"start": ents[s]["name"],
                                "steps": [{"screen": ents[p]["name"], "captured": ents[p]["origin"] != "placeholder",
                                           "via": edges.get(path[k - 1], {}).get(p) if k else None}
                                          for k, p in enumerate(path)]})
                continue
            for n in sorted(nxt, key=lambda i: ents[i]["name"]):
                queue.append(path + [n])
    dead = sorted({ents[b]["name"] for a in edges for b in edges[a] if ents[b]["origin"] == "placeholder"})
    orphans = sorted(ents[s]["name"] for s in screens if s not in incoming and s not in edges
                     and ents[s]["origin"] != "placeholder")
    return {"journeys": out, "edges": [(ents[a]["name"], ents[b]["name"], how) for a in edges for b, how in edges[a].items()],
            "dead_ends": dead, "orphans": orphans, "screens": len([s for s in screens if ents[s]["origin"] != "placeholder"])}
