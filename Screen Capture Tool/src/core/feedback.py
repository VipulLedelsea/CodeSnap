import json
import re

from core.model import corrections as C

INTERPRET_VERSION = "corrections-v1"
SYSTEM = """You turn an analyst's plain-English correction about a legacy program model into structured changes.
Only use the operations and keys listed. Only reference entity keys and finding signatures that appear in the context.
If the request is ambiguous or refers to something not in the context, return no changes and explain in `unclear`.
Operations:
- entity.rename {key, name}
- entity.set_attrs {key, attrs}  (e.g. {"no_pii": true} = holds no student data; {"pii": "student ID"} = does;
  {"hardcoded_secret": false} = not a secret; {"store_type": "database"})
- entity.delete {key}            (false entity that is not really in the program)
- entity.add {kind, name, parent_key?, attrs?}
- entity.merge {from_key, to_key} (duplicates)
- relation.delete {kind, from_key, to_key}
- relation.add {kind, from_key, to_key}
- relation.set_attrs {kind, from_key, to_key, attrs}
- finding.status {sig, status: open|accepted|dismissed|fixed}
- finding.severity {sig, severity: critical|high|medium|low|info}
- finding.add {category, severity, title, detail}
Relation kinds: calls, uses, reads, writes, includes, imports, displays, navigates_to, connects_to, depends_on,
inherits, implements, invokes_transaction."""
TOOL = {"name": "propose_corrections", "description": "Structured corrections for the program model.",
        "input_schema": {"type": "object", "properties": {
            "changes": {"type": "array", "items": {"type": "object", "properties": {
                "op": {"type": "string", "enum": sorted(C.OPS)}, "payload": {"type": "object"},
                "reason": {"type": "string"}}, "required": ["op", "payload"]}},
            "unclear": {"type": "string"}}, "required": ["changes"]}}


def snapshot(store) -> dict:
    a = store.get_meta("assessment")
    if not a:
        return {}
    return {"verdict": (a.get("verdict") or {}).get("label"), "overall": (a["scores"].get("overall") or {}).get("score"),
            "scores": {k: v.get("score") for k, v in a["scores"].items() if k != "overall" and isinstance(v, dict)},
            "risk": a["total_risk"]["level"], "findings": sum(1 for f in store.findings() if f.get("status") not in ("dismissed", "fixed")),
            "components": {c["name"]: ((c.get("disposition") or {}).get("label"), c["risk"]["level"]) for c in a["components"]},
            "component_scores": {c["name"]: {k: v["score"] for k, v in c["scores"].items()} for c in a["components"]},
            "confidence": a["confidence"]["level"]}


def diff(before, after, labels=None) -> list:
    labels = labels or {}
    if not before:
        return ["First assessment run."]
    out = []
    if before.get("verdict") != after.get("verdict"):
        out.append(f"Verdict: {before.get('verdict')} → {after.get('verdict')}")
    if before.get("overall") != after.get("overall"):
        out.append(f"Overall score: {before.get('overall')} → {after.get('overall')}")
    for k, v in (after.get("scores") or {}).items():
        b = (before.get("scores") or {}).get(k)
        if b != v:
            out.append(f"{labels.get(k, k)}: {b} → {v}")
    if before.get("risk") != after.get("risk"):
        out.append(f"Total risk: {before.get('risk')} → {after.get('risk')}")
    if before.get("findings") != after.get("findings"):
        out.append(f"Open findings: {before.get('findings')} → {after.get('findings')}")
    for name, (disp, lvl) in (after.get("components") or {}).items():
        old = (before.get("components") or {}).get(name)
        if old and tuple(old) != (disp, lvl):
            out.append(f"{name}: {old[0] or 'as program'} / {old[1]} → {disp or 'as program'} / {lvl}")
    moved = []
    for name, sc in (after.get("component_scores") or {}).items():
        old = (before.get("component_scores") or {}).get(name) or {}
        for k, v in sc.items():
            if k in old and old[k] != v:
                moved.append(f"{name} · {labels.get(k, k)}: {old[k]} → {v}")
    out += moved[:10]
    for name in set(before.get("components") or {}) - set(after.get("components") or {}):
        out.append(f"{name}: removed from the assessment")
    if before.get("confidence") != after.get("confidence"):
        out.append(f"Confidence: {before.get('confidence')} → {after.get('confidence')}")
    return out or ["No change to scores, verdict or findings."]


def _resolve(store, payload):
    p = dict(payload)
    for key in ("key", "from_key", "to_key", "parent_key"):
        name = p.pop(key.replace("key", "name"), None) if key != "key" else p.pop("target", None)
        if p.get(key) or not name:
            continue
        hits = sorted(store.find(name), key=lambda e: (e["origin"] == "placeholder", e["kind"] in ("file",)))
        if not hits:
            raise C.CorrectionError(f"nothing named '{name}' in this program")
        p[key] = hits[0]["key"]
    return p


def apply(store, ops: list, note: str = "", today=None) -> dict:
    from core.assess import run_assessment
    from core.assess.scores import LABELS
    if not store.get_meta("assessment"):
        run_assessment(store, today=today)
    before = snapshot(store)
    done, warnings = [], []
    for item in ops:
        payload = _resolve(store, item.get("payload") or {})
        r = C.add(store, item["op"], payload, item.get("note") or note)
        done.append(r)
        if r.get("warning"):
            warnings.append(f"{r['description']}: {r['warning']}")
    run_assessment(store, today=today)
    after = snapshot(store)
    return {"applied": done, "warnings": warnings, "impact": diff(before, after, LABELS)}


def undo(store, correction_id: int, today=None) -> dict:
    from core.assess import run_assessment
    from core.assess.scores import LABELS
    before = snapshot(store)
    r = C.undo(store, correction_id)
    run_assessment(store, today=today)
    return {**r, "impact": diff(before, snapshot(store), LABELS)}


def _context(store, text, limit=40):
    words = {w.lower() for w in re.findall(r"[A-Za-z0-9_.\-]{3,}", text)}
    ents = []
    for e in store.entities():
        n = e["name"].lower()
        if any(w in n or n in w for w in words):
            ents.append({"key": e["key"], "kind": e["kind"], "name": e["name"], "origin": e["origin"]})
    ents = ents[:limit]
    ids = {store.entity_by_key(e["key"])["id"] for e in ents}
    rels = []
    for r in store.relations():
        if r["from_id"] in ids or r["to_id"] in ids:
            a, b = store.entity(r["from_id"]), store.entity(r["to_id"])
            rels.append({"kind": r["kind"], "from_key": a["key"], "to_key": b["key"]})
    finds = [{"sig": C.finding_sig(f), "severity": f["severity"], "detail": f["detail"][:120]} for f in store.findings()
             if any(w in f["title"].lower() or w in (f["detail"] or "").lower() for w in words)][:limit]
    return {"entities": ents, "relations": rels[:80], "findings": finds}


def interpret(store, text: str, client, model=None) -> dict:
    from core.analysis import TEXT_MODEL, _parse_json
    ctx = _context(store, text)
    msg = client.messages.create(
        model=model or TEXT_MODEL, max_tokens=2000, system=SYSTEM, tools=[TOOL], tool_choice={"type": "auto"},
        messages=[{"role": "user", "content": f"Context (JSON):\n{json.dumps(ctx)}\n\nAnalyst correction:\n{text}\n\n"
                                              f"Call propose_corrections once."}])
    data = None
    for block in getattr(msg, "content", []) or []:
        if getattr(block, "type", "") == "tool_use" and getattr(block, "name", "") == "propose_corrections":
            data = dict(block.input or {})
    if data is None:
        data = _parse_json("".join(getattr(b, "text", "") for b in msg.content)) or {"changes": []}
    usage = getattr(msg, "usage", None)
    if usage is not None:
        store.log_run("interpret_correction", model=model or TEXT_MODEL, prompt_version=INTERPRET_VERSION,
                      input_tokens=getattr(usage, "input_tokens", None), output_tokens=getattr(usage, "output_tokens", None))
    valid, rejected = [], []
    known = {e["key"] for e in ctx["entities"]} | {s for s in (f["sig"] for f in ctx["findings"])}
    for ch in data.get("changes") or []:
        try:
            C.validate(ch.get("op"), ch.get("payload") or {})
            refs = [v for k, v in (ch.get("payload") or {}).items() if k in ("key", "from_key", "to_key", "sig")]
            unknown = [v for v in refs if v not in known and not store.entity_by_key(v)]
            if unknown:
                raise C.CorrectionError(f"refers to unknown {', '.join(unknown)}")
            valid.append({**ch, "description": C.describe({"op": ch["op"], "payload": ch["payload"]})})
        except C.CorrectionError as exc:
            rejected.append({**ch, "error": str(exc)})
    return {"changes": valid, "rejected": rejected, "unclear": data.get("unclear")}
