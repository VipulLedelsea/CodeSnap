"""Two figures an architect reads first: the current-state process as swimlanes (who does what, on which platform,
in order) and the integration context at system level (the systems at each end of every exchange, named or flagged
as not identified)."""
from core.diagrams.layout import lanes

PLATFORM_ORDER = ["IBM mainframe (z/OS)", "IBM i (AS/400)", "Oracle Database", "Database server",
                  "Microsoft .NET (host to confirm)", "Windows desktop (VB6)", "Java", "Desktop"]
DOWN_HINT = {"PAY": "to be named", "REPORT": "to be named"}


def _short(s, n=34):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _node(i, title, sub="", dashed=False, kind="component"):
    return {"id": i, "title": _short(title), "sub": _short(sub, 40), "dashed": dashed, "kind": kind}


def _step(c, DM):
    ins = [o["store"] for o in DM["occurrences"] if o["component"] == c["name"] and "R" in o["access"] and "W" not in o["access"]]
    outs = [o["store"] for o in DM["occurrences"] if o["component"] == c["name"] and "W" in o["access"]]
    approves = any("approv" in r.lower() for r in c.get("routines") or [])
    pay = "PAY" in " ".join(outs).upper()
    verb = ("approves and looks up payments" if approves else
            ("calculates and writes payments" if pay else "batch processing") if "Batch" in c["role"] else
            "serves web requests" if "Controller" in c["name"] or "api" in c["role"].lower() else
            "posts payments" if c["writes"] and pay else
            "calculates (desktop)" if "VB6" in c["platform"] else "screen entry and inquiry"
            if "Interactive" in c["role"] or c["layer"] == "Presentation"
            else "defines the database" if c["role"] == "Database definition" else c["role"].lower())
    return verb, ins, outs


STAGES = [("inputs", "1. Inputs arrive"), ("calc", "2. Calculate"), ("post", "3. Post"), ("approve", "4. Approve"),
          ("out", "5. Pay out and report"), ("inquire", "6. Look up")]


def _stage(c):
    n, role = c["name"].lower(), c["role"]
    if c["layer"] == "Presentation" or ("Interactive" in role and "IBM mainframe" in c["platform"]):
        return "inquire"
    if role == "Database definition":
        return "inputs"
    if "controller" in n or "approv" in " ".join(c.get("routines") or []).lower():
        return "approve"
    if "post" in n or ("procedures" in role and c["writes"]):
        return "post"
    return "calc"


def process(AM, DM, name):
    """Process flow by stage (columns), each step grouped by the platform it runs on, with the order of steps drawn."""
    by = {k: {} for k, _ in STAGES}
    for c in AM["components"]:
        by[_stage(c)].setdefault(c["platform"], []).append(c)
    readers, writers = {}, {}
    for o in DM["occurrences"]:
        (writers if "W" in o["access"] else readers).setdefault(o["store"], set()).add(o["component"])
    files_in = sorted(s for s in readers if s.endswith("-FILE") and not writers.get(s))
    files_out = sorted(s for s in writers if s.endswith("-FILE"))
    specs = []
    for key, title in STAGES:
        groups = []
        if key == "inputs":
            groups.append({"id": "g_in_files", "title": "Files from other systems", "nodes": [
                _node(f"in_{s}", s, "producer to name", True, "external_system") for s in files_in]})
        if key == "out":
            groups.append({"id": "g_out_files", "title": "Files to other systems", "nodes": [
                _node(f"out_{s}", s, "written by " + ", ".join(sorted(writers.get(s, ()))), True, "external_system")
                for s in files_out]})
            groups.append({"id": "g_out_dst", "title": "Receiving systems", "nodes": [
                _node(f"dst_{s}", "Consumer of " + s, next((v for k, v in DOWN_HINT.items() if k in s.upper()), "to name"),
                      True, "external_system") for s in files_out if "PAY" in s.upper()]})
        for plat, cs in by[key].items():
            groups.append({"id": f"g_{key}_{plat}", "title": plat, "dashed": False, "nodes": [
                _node(f"c_{c['name']}", c["name"], _step(c, DM)[0]) for c in cs]})
        if groups:
            specs.append({"id": f"lane_{key}", "title": title, "groups": groups})
    order = [spec["id"][5:] for spec in specs]
    edges = []
    ids = lambda k: [n["id"] for spec in specs if spec["id"] == f"lane_{k}" for g in spec["groups"] for n in g["nodes"]
                     if n["id"].startswith("c_")]
    for s_ in files_in:
        for c in sorted(readers.get(s_, ())):
            if f"c_{c}" in ids(order[1] if len(order) > 1 else ""):
                edges.append({"from": f"in_{s_}", "to": f"c_{c}", "style": "solid", "head": "arrow"})
    for a, b in zip(order, order[1:]):
        if a == "inputs" or b in ("inquire",):
            continue
        src = ids(a) if a != "out" else []
        dst = ids(b) if b != "out" else [f"out_{s_}" for s_ in files_out]
        for x in src[:3]:
            for y in dst[:3]:
                edges.append({"from": x, "to": y, "style": "dashed", "head": "arrow"})
    scene = lanes(specs, edges, [])
    return {"id": "process", "title": f"Current-state process — {name} (order of steps inferred from the code)", **scene}


def context(AM, DM, name):
    """System-level context: upstream systems, the application by platform, downstream systems, and user groups."""
    readers, writers = {}, {}
    for o in DM["occurrences"]:
        (writers if "W" in o["access"] else readers).setdefault(o["store"], set()).add(o["component"])
    src = sorted(s for s in readers if not writers.get(s) and s.endswith("-FILE"))
    ext_db = sorted({o["store"] for o in DM["occurrences"] if o["placeholder"] and o["business"] and "R" in o["access"]
                     and "W" not in o["access"]})
    users = [c for c in AM["components"] if c["layer"] == "Presentation"]
    specs = [{"id": "l_up", "title": "Upstream systems and users", "groups": [
        {"id": "g_u", "title": "User groups", "nodes": [
            _node(f"us_{i}", ("Staff (terminal)" if c["role"] == "3270 terminal screen" else "Public or district users (web)"),
                  c["name"].rsplit(".", 1)[0], False, "actor") for i, c in enumerate(users)]},
        {"id": "g_up_files", "title": "Send files (system to name)", "nodes": [
            _node(f"up_{i}", f"Producer of {s}", "APP ID to confirm", True, "external_system") for i, s in enumerate(src[:6])]},
        {"id": "g_up_db", "title": "Own shared tables", "nodes": [
            _node(f"db_{i}", f"Owner of {s}", "system of record?", True, "external_system") for i, s in enumerate(ext_db[:6])]}]}]
    supplied_platforms={c["platform"] for c in AM["components"]}
    plats = [p for p in PLATFORM_ORDER if p in supplied_platforms] + sorted(supplied_platforms-set(PLATFORM_ORDER))
    specs.append({"id": "l_app", "title": "This application", "groups": [
        {"id": f"ga_{p}", "title": p, "dashed": False, "nodes": [
            _node(f"a_{c['name']}", c["name"], c["role"]) for c in AM["components"]
            if c["platform"] == p and c["layer"] != "Presentation"]} for p in plats]})
    sinks = sorted(s for s in writers if s.endswith("-FILE"))
    specs.append({"id": "l_down", "title": "Downstream systems", "groups": [
        {"id": "g_down", "title": "Receive output (system to name)", "nodes": [
            _node(f"dn_{i}", f"Consumer of {s}", next((v for k, v in DOWN_HINT.items() if k in s.upper()), "to confirm"),
                  True, "external_system") for i, s in enumerate(sinks[:6])]}]})
    edges = []
    for i, s_ in enumerate(src[:6]):
        for c in sorted(readers.get(s_, ())):
            edges.append({"from": f"up_{i}", "to": f"a_{c}", "style": "solid", "head": "arrow"})
    for i, s_ in enumerate(ext_db[:6]):
        for c in sorted(readers.get(s_, ())):
            edges.append({"from": f"db_{i}", "to": f"a_{c}", "style": "dashed", "head": "arrow"})
    for i, s_ in enumerate(sinks[:6]):
        for c in sorted(writers.get(s_, ())):
            edges.append({"from": f"a_{c}", "to": f"dn_{i}", "style": "solid", "head": "arrow"})
    for i, c in enumerate(users):
        for o in AM["components"]:
            if o["layer"] != "Presentation" and ((c["role"] == "3270 terminal screen" and "Interactive" in o["role"]
                                                  and "IBM mainframe" in o["platform"])
                                                 or (c["role"] != "3270 terminal screen" and ".NET" in o["platform"])):
                edges.append({"from": f"us_{i}", "to": f"a_{o['name']}", "style": "dashed", "head": "arrow"})
    scene = lanes(specs, edges, [])
    return {"id": "context_sys", "title": f"System context — {name}", **scene}
