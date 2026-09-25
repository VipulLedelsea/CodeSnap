import re

MAX_NODES = 150
HIDDEN_KINDS = {"field", "column", "ui_element"}
SHAPES = {
    "file": ('["', '"]'), "module": ('["', '"]'), "program": ('["', '"]'),
    "class": ('["', '"]'), "interface": ('["', '"]'),
    "function": ('("', '")'), "paragraph": ('("', '")'), "section": ('("', '")'),
    "table": ('[("', '")]'), "data_store": ('[("', '")]'),
    "screen": ('[/"', '"/]'), "api_endpoint": ('{{"', '"}}'), "external_system": ('{{"', '"}}'),
    "transaction": ('(["', '"])'), "job": ('(["', '"])'),
}


def _label(text: str) -> str:
    return re.sub(r'["\[\]{}<>|]', "", str(text))[:60]


def dependency_mermaid(graph: dict, max_nodes: int = MAX_NODES) -> str:
    nodes = {n["id"]: n for n in graph["nodes"] if n["kind"] not in HIDDEN_KINDS}
    edges = [e for e in graph["edges"] if e["kind"] != "contains" and e["from"] in nodes and e["to"] in nodes]
    degree = {}
    for e in edges:
        degree[e["from"]] = degree.get(e["from"], 0) + 1
        degree[e["to"]] = degree.get(e["to"], 0) + 1
    keep = sorted(degree, key=lambda i: -degree[i])[:max_nodes]
    if not keep:
        keep = [n for n in nodes if nodes[n]["kind"] == "file"][:max_nodes]
    keep = set(keep)
    lines = ["flowchart LR"]
    for node_id in sorted(keep):
        node = nodes[node_id]
        left, right = SHAPES.get(node["kind"], ('["', '"]'))
        lines.append(f"  n{node_id}{left}{_label(node['name'])}<br/><small>{node['kind']}</small>{right}")
    for e in edges:
        if e["from"] in keep and e["to"] in keep:
            lines.append(f"  n{e['from']} -->|{e['kind']}| n{e['to']}")
    missing = [f"n{i}" for i in keep if nodes[i]["origin"] == "placeholder"]
    if missing:
        lines.append("  classDef missing stroke-dasharray: 5 5,opacity:0.7")
        lines.append(f"  class {','.join(missing)} missing")
    hidden = len(nodes) - len(keep)
    if hidden > 0:
        lines.append(f"  %% {hidden} more entities not shown")
    return "\n".join(lines)
