CHAR_W, LINE_H, PAD = 7.0, 16, 10
NODE_GAP, RANK_GAP, MAX_PER_ROW, MARGIN = 36, 70, 7, 30


def text_w(s: str, bold=False) -> float:
    return len(str(s)) * (CHAR_W + (0.6 if bold else 0))


def size(node: dict) -> tuple:
    lines = [(node.get("stereotype") and f"«{node['stereotype']}»") or None, node["title"]]
    widths = [text_w(l) for l in lines if l] + [text_w(node["title"], True)]
    h = LINE_H * len([l for l in lines if l]) + 2 * PAD - 4
    for sec in node.get("sections") or []:
        widths += [text_w(l) for l in sec]
        h += LINE_H * max(1, len(sec)) + PAD
    w = max(110, min(360, max(widths) + 2 * PAD))
    return w, max(44, h + 6)


def _ranks(ids, edges):
    out = {i: [] for i in ids}
    for a, b in edges:
        if a in out and b in out and a != b:
            out[a].append(b)
    state, order, back = {}, [], set()

    def dfs(n):
        stack = [(n, iter(out[n]))]
        state[n] = 1
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[node] = 2
                order.append(node)
                stack.pop()
            elif state.get(nxt) == 1:
                back.add((node, nxt))
            elif nxt not in state:
                state[nxt] = 1
                stack.append((nxt, iter(out[nxt])))

    for i in ids:
        if i not in state:
            dfs(i)
    dag = [(a, b) for a, b in edges if a in out and b in out and a != b and (a, b) not in back]
    rank = {i: 0 for i in ids}
    for n in reversed(order):
        for a, b in dag:
            if a == n and rank[b] < rank[a] + 1:
                rank[b] = rank[a] + 1
    changed = True
    while changed:
        changed = False
        for a, b in dag:
            if rank[b] < rank[a] + 1:
                rank[b], changed = rank[a] + 1, True
    return rank, dag


def layered(nodes: list, edges: list, direction="TB", sinks=None, straight=False, per_row=None, max_ranks=None) -> dict:
    ids = [n["id"] for n in nodes]
    pairs = [(e["from"], e["to"]) for e in edges]
    rank, _ = _ranks(ids, pairs)
    if max_ranks:
        for i in ids:
            rank[i] = min(rank[i], max_ranks - 1)
    if sinks:
        top = max([rank[i] for i in ids if i not in sinks] or [0]) + 1
        for i in ids:
            if i in sinks:
                rank[i] = top
    for n in nodes:
        n["w"], n["h"] = size(n)
    layers = {}
    for i in ids:
        layers.setdefault(rank[i], []).append(i)
    rows = []
    for r in sorted(layers):
        members = layers[r]
        cap = per_row or MAX_PER_ROW
        for k in range(0, len(members), cap):
            rows.append(members[k:k + cap])
    nbrs = {i: set() for i in ids}
    for a, b in pairs:
        if a in nbrs and b in nbrs:
            nbrs[a].add(b)
            nbrs[b].add(a)
    pos = {}
    for sweep in range(6):
        seq = range(len(rows)) if sweep % 2 == 0 else range(len(rows) - 1, -1, -1)
        for ri in seq:
            row = rows[ri]
            for idx, i in enumerate(row):
                pos.setdefault(i, idx)
            ref = [ri - 1] if sweep % 2 == 0 else [ri + 1]

            def bary(i):
                vals = [pos[j] for j in nbrs[i] if any(j in rows[k] for k in ref if 0 <= k < len(rows))]
                return sum(vals) / len(vals) if vals else pos[i]
            row.sort(key=bary)
            for idx, i in enumerate(row):
                pos[i] = idx
    by_id = {n["id"]: n for n in nodes}
    horizontal = direction == "LR"
    extents = []
    for row in rows:
        span = sum((by_id[i]["h"] if horizontal else by_id[i]["w"]) for i in row) + NODE_GAP * (len(row) - 1)
        extents.append(span)
    widest = max(extents or [0])
    cursor = MARGIN + 30
    for row, span in zip(rows, extents):
        depth = max((by_id[i]["w"] if horizontal else by_id[i]["h"]) for i in row)
        offset = MARGIN + (widest - span) / 2
        for i in row:
            n = by_id[i]
            if horizontal:
                n["x"], n["y"] = cursor + (depth - n["w"]) / 2, offset
                offset += n["h"] + NODE_GAP
            else:
                n["x"], n["y"] = offset, cursor + (depth - n["h"]) / 2
                offset += n["w"] + NODE_GAP
        cursor += depth + RANK_GAP
    for e in edges:
        e["points"] = (direct if straight else route)(by_id[e["from"]], by_id[e["to"]], horizontal)
    if not straight:
        stagger(edges, horizontal)
    if horizontal:
        width, height = cursor - RANK_GAP + MARGIN, widest + 2 * MARGIN + 30
    else:
        width, height = widest + 2 * MARGIN, cursor - RANK_GAP + MARGIN
    return {"nodes": nodes, "edges": edges, "width": round(max(width, 300)), "height": round(max(height, 160))}


def direct(a, b, horizontal=False):
    if a is b:
        return route(a, b, horizontal)
    if horizontal:
        if b["x"] >= a["x"] + a["w"] - 1:
            return [(a["x"] + a["w"], a["y"] + a["h"] / 2), (b["x"], b["y"] + b["h"] / 2)]
        if b["x"] + b["w"] <= a["x"] + 1:
            return [(a["x"], a["y"] + a["h"] / 2), (b["x"] + b["w"], b["y"] + b["h"] / 2)]
        up = b["y"] < a["y"]
        return [(a["x"] + a["w"] / 2, a["y"] if up else a["y"] + a["h"]),
                (b["x"] + b["w"] / 2, b["y"] + b["h"] if up else b["y"])]
    if b["y"] >= a["y"] + a["h"] - 1:
        return [(a["x"] + a["w"] / 2, a["y"] + a["h"]), (b["x"] + b["w"] / 2, b["y"])]
    if b["y"] + b["h"] <= a["y"] + 1:
        return [(a["x"] + a["w"] / 2, a["y"]), (b["x"] + b["w"] / 2, b["y"] + b["h"])]
    left = b["x"] < a["x"]
    return [(a["x"] if left else a["x"] + a["w"], a["y"] + a["h"] / 2),
            (b["x"] + b["w"] if left else b["x"], b["y"] + b["h"] / 2)]


def route(a, b, horizontal=False):
    if a is b:
        x, y = a["x"] + a["w"], a["y"] + a["h"] / 2
        return [(x, y - 8), (x + 24, y - 8), (x + 24, y + 8), (x, y + 8)]
    if horizontal:
        if b["x"] >= a["x"] + a["w"]:
            sx, sy = a["x"] + a["w"], a["y"] + a["h"] / 2
            tx, ty = b["x"], b["y"] + b["h"] / 2
        else:
            sx, sy = a["x"], a["y"] + a["h"] / 2
            tx, ty = b["x"] + b["w"], b["y"] + b["h"] / 2
        mx = (sx + tx) / 2
        return [(sx, sy), (mx, sy), (mx, ty), (tx, ty)]
    if b["y"] >= a["y"] + a["h"]:
        sx, sy = a["x"] + a["w"] / 2, a["y"] + a["h"]
        tx, ty = b["x"] + b["w"] / 2, b["y"]
    elif b["y"] + b["h"] <= a["y"]:
        sx, sy = a["x"] + a["w"] / 2, a["y"]
        tx, ty = b["x"] + b["w"] / 2, b["y"] + b["h"]
    else:
        if b["x"] > a["x"]:
            sx, tx = a["x"] + a["w"], b["x"]
        else:
            sx, tx = a["x"], b["x"] + b["w"]
        sy = ty = a["y"] + a["h"] / 2
        return [(sx, sy), (tx, ty)]
    my = (sy + ty) / 2
    return [(sx, sy), (sx, my), (tx, my), (tx, ty)]


def stagger(edges, horizontal):
    groups = {}
    for e in edges:
        pts = e["points"]
        if len(pts) != 4:
            continue
        key = (round(pts[0][0]), round(pts[3][0])) if horizontal else (round(pts[0][1]), round(pts[3][1]))
        band = (min(key), max(key))
        groups.setdefault(band, []).append(e)
    for (lo, hi), group in groups.items():
        group.sort(key=lambda e: (e["points"][3][1], e["points"][0][1]) if horizontal else (e["points"][3][0], e["points"][0][0]))
        n = len(group)
        for k, e in enumerate(group):
            frac = 0.5 if n == 1 else 0.2 + 0.6 * k / (n - 1)
            (sx, sy), _, _, (tx, ty) = e["points"]
            if horizontal:
                m = sx + (tx - sx) * frac
                e["points"] = [(sx, sy), (m, sy), (m, ty), (tx, ty)]
            else:
                m = sy + (ty - sy) * frac
                e["points"] = [(sx, sy), (sx, m), (tx, m), (tx, ty)]


def columns(cols: list, edges: list, gap=140) -> dict:
    x = MARGIN
    heights = []
    for col in cols:
        for n in col:
            n["w"], n["h"] = size(n)
        w = max((n["w"] for n in col), default=0)
        y = MARGIN + 30
        for n in col:
            n["x"], n["y"] = x + (w - n["w"]) / 2, y
            y += n["h"] + NODE_GAP
        heights.append(y)
        x += w + gap
    total_h = max(heights or [100])
    for col, h in zip(cols, heights):
        shift = (total_h - h) / 2
        for n in col:
            n["y"] += shift
    by_id = {n["id"]: n for col in cols for n in col}
    for e in edges:
        e["points"] = route(by_id[e["from"]], by_id[e["to"]], True)
    stagger(edges, True)
    return {"nodes": [n for col in cols for n in col], "edges": edges, "width": round(x - gap + MARGIN),
            "height": round(total_h + MARGIN)}


def sequence(participants: list, messages: list) -> dict:
    x = MARGIN
    nodes, centers = [], {}
    for p in participants:
        n = {"id": p["id"], "title": p["title"], "stereotype": p.get("stereotype"), "kind": p.get("kind", "participant")}
        n["w"], n["h"] = size(n)
        n["w"] = max(n["w"], 120)
        n["x"], n["y"] = x, MARGIN + 30
        centers[p["id"]] = x + n["w"] / 2
        x += n["w"] + 40
        nodes.append(n)
    top = MARGIN + 30 + max((n["h"] for n in nodes), default=44)
    y = top + 30
    edges = []
    for m in messages:
        a, b = centers[m["from"]], centers[m["to"]]
        if m["from"] == m["to"]:
            pts = [(a, y), (a + 30, y), (a + 30, y + 14), (a, y + 14)]
            y += 14
        else:
            pts = [(a, y), (b, y)]
        edges.append({"from": m["from"], "to": m["to"], "label": m.get("label", ""), "style": m.get("style", "solid"),
                      "head": "arrow", "points": pts, "message": True})
        y += 34
    bottom = y + 10
    for n in nodes:
        cx = n["x"] + n["w"] / 2
        edges.insert(0, {"from": n["id"], "to": n["id"], "label": "", "style": "dashed", "head": "none",
                         "points": [(cx, n["y"] + n["h"]), (cx, bottom)], "lifeline": True})
    width = max(x - 40 + MARGIN, max((max(p[0] for p in e["points"]) + 40 + len(e["label"]) * 3.5)
                                     for e in edges if e.get("message")) if messages else 300)
    return {"nodes": nodes, "edges": edges, "width": round(max(width, 300)), "height": round(bottom + MARGIN)}


LANE_GAP, GROUP_GAP, CELL_GAP, GPAD, GTITLE = 70, 16, 10, 12, 24


def compact_size(n):
    w = 40 + max(text_w(n["title"], True), text_w(n.get("sub") or "") * 0.85) + (46 if n.get("badge") else 0)
    return max(130, min(250, w)), (44 if n.get("sub") else 34)


def lanes(lane_specs: list, edges: list, bars: list, title_h=30) -> dict:
    groups, nodes, lane_boxes = [], [], []
    x = MARGIN
    top = MARGIN + title_h + 26
    for lane in lane_specs:
        y = top + 28
        lane_w = 160
        placed = []
        for g in lane["groups"]:
            items = g["nodes"]
            for n in items:
                n["w"], n["h"] = compact_size(n)
                n["compact"] = True
            nw = max([n["w"] for n in items] or [140])
            nh = max([n["h"] for n in items] or [34])
            cols = 1 if len(items) <= 8 else 2 if len(items) <= 20 else 3
            rows = max(1, -(-len(items) // cols))
            gw = cols * nw + (cols - 1) * CELL_GAP + 2 * GPAD
            gh = GTITLE + rows * (nh + CELL_GAP) - CELL_GAP + GPAD + (0 if items else 10)
            placed.append((g, items, nw, nh, cols, gw, gh, y))
            y += gh + GROUP_GAP
            lane_w = max(lane_w, gw)
        for g, items, nw, nh, cols, gw, gh, gy in placed:
            gx = x + GPAD
            groups.append({"id": g["id"], "x": gx, "y": gy, "w": lane_w, "h": gh, "title": g["title"], "style": "group",
                           "dashed": g.get("dashed", True)})
            for i, n in enumerate(items):
                r, c = divmod(i, cols)
                n["w"], n["h"] = nw, nh
                n["x"] = gx + GPAD + c * (nw + CELL_GAP)
                n["y"] = gy + GTITLE + r * (nh + CELL_GAP)
                nodes.append(n)
        lane_boxes.append({"id": lane["id"], "x": x, "y": top, "w": lane_w + 2 * GPAD, "title": lane["title"],
                           "bottom": y})
        x += lane_w + 2 * GPAD + LANE_GAP
    total_w = max(x - LANE_GAP, 420)
    bottom = max([l["bottom"] for l in lane_boxes] or [top + 100])
    groups[:0] = [{"id": l["id"], "x": l["x"], "y": l["y"], "w": l["w"], "h": bottom - l["y"], "title": l["title"],
                   "style": "lane", "dashed": True} for l in lane_boxes]
    y = bottom + 20
    for b in bars:
        cx, cy, row_h = MARGIN + 150, y + 8, 0
        chips = []
        for chip in b["chips"]:
            chip["w"], chip["h"] = max(70, text_w(chip["title"]) * 0.9 + 26), 24
            chip["compact"] = True
            chip["chip"] = True
            if cx + chip["w"] > total_w - 8 and chips:
                cx, cy = MARGIN + 150, cy + 30
            chip["x"], chip["y"] = cx, cy
            cx += chip["w"] + 8
            chips.append(chip)
            nodes.append(chip)
        h = (cy - y) + 32
        groups.append({"id": b["id"], "x": MARGIN, "y": y, "w": total_w - MARGIN, "h": h, "title": b["title"],
                       "style": "bar", "dashed": False})
        y += h + 8
    by_id = {n["id"]: n for n in nodes} | {g["id"]: g for g in groups}
    lane_of = {}
    for li, lane in enumerate(lane_specs):
        for g in lane["groups"]:
            lane_of[g["id"]] = li
            for n in g["nodes"]:
                lane_of[n["id"]] = li
    gaps = {}
    kept = []
    for e in edges:
        a, b = by_id.get(e["from"]), by_id.get(e["to"])
        la, lb = lane_of.get(e["from"]), lane_of.get(e["to"])
        if a is None or b is None or la is None or lb is None or la == lb:
            continue
        forward = lb > la
        gap = la if forward else la - 1
        gaps.setdefault(gap, []).append(e)
        e["_ab"] = (a, b, forward, gap)
        kept.append(e)
    for gap, es in gaps.items():
        if gap < 0:
            continue
        lane = lane_boxes[gap]
        gx0 = lane["x"] + lane["w"]
        es.sort(key=lambda e: (e["_ab"][1]["y"], e["_ab"][0]["y"]))
        for k, e in enumerate(es):
            a, b, forward, _ = e.pop("_ab")
            mx = gx0 + LANE_GAP * (0.15 + 0.7 * (k + 1) / (len(es) + 1))
            ay = a["y"] + (a["h"] / 2 if a.get("compact") or a.get("style") != "lane" else 20)
            by = b["y"] + (b["h"] / 2 if b.get("style") not in ("group", "lane") else min(b["h"] - 10, GTITLE + 16))
            if forward:
                sx, tx = a["x"] + a["w"], b["x"]
            else:
                sx, tx = a["x"], b["x"] + b["w"]
            e["points"] = [(sx, ay), (mx, ay), (mx, by), (tx, by)]
    for e in kept:
        e.pop("_ab", None)
    return {"nodes": nodes, "groups": groups, "edges": [e for e in kept if "points" in e],
            "width": round(total_w + MARGIN), "height": round(y + MARGIN)}
