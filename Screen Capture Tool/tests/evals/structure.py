import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLES = HERE.parent / "samples"
TYPES = {"sql": "sql", "ddl": "sql", "aspx": "web", "jsp": "web", "html": "web", "config": "config", "xml": "config"}
ENTITY_KINDS = {"program", "class", "interface", "function", "paragraph", "section", "copybook", "screen", "table", "data_store",
                "job", "transaction", "api_endpoint", "external_system", "module"}
PREFIXES = ENTITY_KINDS | {"field", "column", "ui_element", "file"}


def _target(t):
    t = str(t)
    head = t.split(":", 1)[0]
    return (t.split(":", 1)[1] if ":" in t and head in PREFIXES else t).strip().lower()


def parse_file(rel):
    from core.model.ingest import _parse_deterministic
    path = SAMPLES / rel if (SAMPLES / rel).exists() else HERE / "heldout" / rel
    text = path.read_text()
    atype = TYPES.get(path.suffix[1:].lower(), "code")
    out = _parse_deterministic(text, {"name": path.name, "language": "", "artifact_type": atype})
    return (out or {}).get("structure") or {"entities": [], "relations": []}


def _sets(s):
    ents = {f'{e["kind"]} {e["name"]}'.lower() for e in s["entities"] if e["kind"] in ENTITY_KINDS}
    rels = {f'{r["kind"]} {_target(r["target"])}' for r in s["relations"]}
    return ents, rels


def _base(x):
    kind, _, target = x.partition(" ")
    stem = target.rsplit(".", 1)[0] if target.endswith((".jsp", ".asp", ".aspx", ".cfm", ".php", ".cbl", ".cpy", ".inc")) else target
    return kind, stem


def _matches(g, x):
    if g == x:
        return True
    (gk, gt), (xk, xt) = _base(g), _base(x)
    if gk == "uses" and (xt == gt or xt.startswith(gt + ".") or gt.endswith("." + xt)):
        return True
    return gk == xk and (gt == xt or xt.endswith("." + gt) or xt.endswith("::" + gt) or gt.endswith("." + xt))


def _pr(gold, got):
    matched = {g for g in gold if any(_matches(g, x) for x in got)}
    used = {x for x in got if any(_matches(g, x) for g in gold)}
    hit = len(matched)
    return {"tp": hit, "gold": len(gold), "got": len(got), "recall": hit / len(gold) if gold else 1.0,
            "precision": len(used) / len(got) if got else (1.0 if not gold else 0.0), "used": len(used)}


def _pr_unused(gold, got):
    hit = len(gold & got)
    return {"tp": hit, "gold": len(gold), "got": len(got), "recall": hit / len(gold) if gold else 1.0,
            "precision": hit / len(got) if got else (1.0 if not gold else 0.0)}


def family(rel):
    ext = rel.rsplit(".", 1)[-1].lower()
    if rel.endswith(".aspx.cs"):
        return "C#"
    return {"cbl": "COBOL / JCL", "jcl": "COBOL / JCL", "cpp": "C / C++", "cs": "C#", "java": "Java", "sql": "SQL",
            "jsp": "Web pages", "aspx": "Web pages"}.get(ext, "Legacy language packs") if not rel.startswith("langpacks/AIDIDMS") \
        else "COBOL / JCL"


def run(gold_file="gold_structure.json"):
    gold = {k: v for k, v in json.loads((HERE / gold_file).read_text()).items() if not k.startswith("_")}
    files, fam = [], {}
    for rel, g in gold.items():
        ents, rels = _sets(parse_file(rel))
        ge = {x.lower() for x in g["entities"]}
        gr = {x.lower() for x in g["relations"]}
        loose_g = {"any " + x.split(" ", 1)[1] for x in gr}
        loose_r = {"any " + x.split(" ", 1)[1] for x in rels}
        row = {"file": rel, "family": family(rel), "entities": _pr(ge, ents), "relations": _pr(gr, rels),
               "relations_target_only": _pr(loose_g, loose_r),
               "missed": sorted(g for g in ge | gr if not any(_matches(g, x) for x in ents | rels))[:10],
               "extra": sorted(x for x in ents | rels if not any(_matches(g, x) for g in ge | gr))[:10]}
        files.append(row)
        agg = fam.setdefault(row["family"], {"entities": [0, 0, 0], "relations": [0, 0, 0]})
        for k in ("entities", "relations"):
            agg[k][0] += row[k]["tp"]
            agg[k][1] += row[k]["gold"]
            agg[k][2] += row[k]["got"]
            agg[k].append(row[k]["used"]) if len(agg[k]) < 4 else agg[k].__setitem__(3, agg[k][3] + row[k]["used"])

    def micro(key):
        tp = sum(r[key]["tp"] for r in files)
        g = sum(r[key]["gold"] for r in files)
        o = sum(r[key]["got"] for r in files)
        u = sum(r[key]["used"] for r in files)
        return {"recall": round(tp / g, 3), "precision": round(u / o, 3), "gold": g}
    by_family = {f: {k: {"recall": round(v[k][0] / v[k][1], 3) if v[k][1] else None,
                         "precision": round(v[k][3] / v[k][2], 3) if v[k][2] else None} for k in v} for f, v in fam.items()}
    return {"files": files, "entities": micro("entities"), "relations": micro("relations"),
            "relations_target_only": micro("relations_target_only"), "by_family": by_family}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(HERE.parent.parent / "src"))
    r = run(sys.argv[1] if len(sys.argv) > 1 else "gold_structure.json")
    print(json.dumps({k: r[k] for k in ("entities", "relations", "relations_target_only", "by_family")}, indent=1))
    for f in r["files"]:
        if f["entities"]["recall"] < 1 or f["relations"]["recall"] < 1 or f["relations"]["precision"] < 0.8:
            print(f["file"], round(f["entities"]["recall"], 2), round(f["relations"]["recall"], 2), round(f["relations"]["precision"], 2),
                  "MISSED", f["missed"], "EXTRA", f["extra"])
