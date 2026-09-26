from datetime import datetime, timezone

from core.model.linker import ENTRY_KINDS
from core.security import scan as security_scan

from .decide import confidence, default_impact, disposition, likelihood, risk_level, _no_path
from .roadmap import roadmap, solutions
from .scores import DIMENSIONS, LABELS, grade, program_scores, score_component, text_metrics

VERSION = "assess-v1"
UNIT_KINDS = ("function", "paragraph", "section")
DATA_KINDS = ("table", "data_store", "column")
EXTERNAL_KINDS = ("external_system", "data_store")


def _components(store):
    arts = {a["id"]: a for a in store.artifacts()}
    files = {e["artifact_id"]: e for e in store.entities("file") if e["artifact_id"] in arts}
    ents = {e["id"]: e for e in store.entities()}
    owner = {}
    for e in ents.values():
        if e["artifact_id"] in arts:
            owner[e["id"]] = e["artifact_id"]
    rels = store.relations()
    findings = store.findings()
    comps = {}
    for aid, a in arts.items():
        try:
            m = text_metrics(a.get("transcription") or "", a["name"], a.get("language") or "")
        except Exception:
            m = {"lines": len((a.get("transcription") or "").splitlines()), "decisions": 0, "gotos": 0, "family": "other"}
        comps[aid] = {"id": aid, "name": a["name"], "artifact": a, "file": files.get(aid), "metrics": m,
                      "units": [e for e in ents.values() if owner.get(e["id"]) == aid and e["kind"] in UNIT_KINDS],
                      "findings": [], "fan_out_set": set(), "fan_in_set": set(), "writes": False, "entry": False,
                      "student_data": False, "missing_code": 0, "external": set(), "write_targets": set()}
    for e in ents.values():
        if owner.get(e["id"]) in comps and e["kind"] in ENTRY_KINDS:
            comps[owner[e["id"]]]["entry"] = True
    writers = {}
    for r in rels:
        src_art = r["artifact_id"] if r["artifact_id"] in comps else owner.get(r["from_id"])
        if src_art not in comps:
            continue
        c = comps[src_art]
        target = ents.get(r["to_id"])
        if target is None or r["kind"] in ("contains", "same_as"):
            continue
        tgt_art = owner.get(target["id"])
        if tgt_art and tgt_art != src_art and tgt_art in comps:
            c["fan_out_set"].add(target["id"])
            comps[tgt_art]["fan_in_set"].add(src_art)
        if target["origin"] == "placeholder" and target["kind"] in ("program", "class", "function", "copybook",
                                                                     "paragraph", "module", "screen"):
            c["missing_code"] += 1
        if r["kind"] == "writes" and target["kind"] in DATA_KINDS:
            c["writes"] = True
            writers.setdefault(target["id"], set()).add(src_art)
            c["write_targets"].add(target["id"])
        if r["kind"] == "connects_to" and target["kind"] in EXTERNAL_KINDS:
            c["external"].add(target["name"])
    for c in comps.values():
        c["shared_writes"] = {ents[t]["name"] for t in c["write_targets"] if len(writers.get(t, ())) > 1}
    site = store.get_meta("site_scan") or {}
    for f in findings:
        if f.get("status") in ("dismissed", "fixed"):
            continue
        targets = {ev.get("artifact_id") for ev in f.get("evidence") or [] if isinstance(ev, dict)}
        if not (targets - {None}) and any(isinstance(ev, dict) and ev.get("url") for ev in f.get("evidence") or []):
            if 0 not in comps:
                host = (site.get("final_url") or site.get("start") or "live site").split("://")[-1].split("/")[0]
                art = {"id": 0, "name": f"Live site ({host})", "artifact_type": "web", "language": "Live website",
                       "status": "validated", "validation_ok": 1, "transcription": ""}
                comps[0] = {"id": 0, "name": art["name"], "artifact": art, "file": None,
                            "metrics": {"lines": 0, "decisions": 0, "gotos": 0, "family": "web"}, "units": [],
                            "findings": [], "fan_out_set": set(), "fan_in_set": set(), "writes": False, "entry": True,
                            "student_data": False, "missing_code": 0, "external": set(), "write_targets": set(),
                            "shared_writes": set()}
            targets = {0}
        if f.get("target_type") == "artifact":
            targets.add(f["target_id"])
        elif f.get("target_type") == "entity" and f.get("target_id") in owner:
            targets.add(owner[f["target_id"]])
        for t in targets:
            if t in comps and f not in comps[t]["findings"]:
                comps[t]["findings"].append(f)
                if f["category"] == "privacy":
                    comps[t]["student_data"] = True
        if f["category"] == "security" and "ferpa" in (f.get("refs") or {}):
            for t in targets:
                if t in comps:
                    comps[t]["student_data"] = True
    for c in comps.values():
        c["fan_out"], c["fan_in"] = len(c.pop("fan_out_set")), len(c.pop("fan_in_set"))
        c.pop("write_targets")
    return list(comps.values())


def _facts(components):
    total = sum(max(1, c["metrics"]["lines"]) for c in components) or 1
    no_path_lines = sum(max(1, c["metrics"]["lines"]) for c in components if _no_path(c))
    cobol_lines = sum(max(1, c["metrics"]["lines"]) for c in components if c["metrics"]["family"] == "cobol")
    hard = lambda c: [f["title"] for f in c["findings"] if f["category"] == "eol" and f["severity"] == "high"
                      and (f.get("refs") or {}).get("eol_status") == "eol" and f.get("status") != "dismissed"]
    eol_lines = sum(max(1, c["metrics"]["lines"]) for c in components if hard(c))
    return {"no_path": [t for c in components for t in _no_path(c)], "no_path_share": no_path_lines / total,
            "eol_hard": [t for c in components for t in hard(c)], "eol_share": eol_lines / total,
            "cobol_share": cobol_lines / total,
            "sec_high": sum(1 for c in components for f in c["findings"]
                            if f["category"] in ("security", "vulnerability") and f["severity"] in ("critical", "high"))}


def run_assessment(store, *, scan: bool = True, online: bool = False, today=None) -> dict:
    if scan:
        from core.uireview import run_ui_review
        security_scan.run_scan(store, online=online, today=today)
        run_ui_review(store, today=today)
    from core.model.corrections import apply_corrections
    apply_corrections(store)
    inputs = store.get_meta("assessment_inputs", {}) or {}
    comp_inputs = inputs.get("components") or {}
    components = _components(store)
    for c in components:
        c["scores"] = score_component(c)
    prog = program_scores(components)
    coverage = store.coverage()
    from core.model.health import pipeline_health
    health = pipeline_health(store)
    facts = _facts(components)
    facts["components"] = len(components)
    facts["high_risk"] = 0
    for c in components:
        ci = comp_inputs.get(c["name"]) or {}
        imp = max(1, min(5, int(ci.get("impact") or ci.get("criticality") or default_impact(c)[0])))
        facts["high_risk"] += risk_level(likelihood(c["scores"])[0] * imp) in ("high", "critical")
    verdict = disposition(prog, facts, inputs.get("program") or {}) if components else None
    matrix = [[[] for _ in range(5)] for _ in range(5)]
    comp_out = []
    for c in components:
        like, basis = likelihood(c["scores"])
        ci = comp_inputs.get(c["name"]) or {}
        d_imp, why = default_impact(c)
        impact = int(ci.get("impact") or ci.get("criticality") or d_imp)
        impact = max(1, min(5, impact))
        score = like * impact
        level = risk_level(score)
        own = disposition(c["scores"], _facts([c]), ci)
        c["disposition"] = own
        c["own_disposition"] = level in ("high", "critical") or own["code"] != verdict["code"] or bool(
            ci.get("retire") or ci.get("cots"))
        matrix[5 - like][impact - 1].append(c["name"])
        comp_out.append({
            "name": c["name"], "artifact_id": c["id"], "type": c["artifact"].get("artifact_type"),
            "language": c["artifact"].get("language"), "lines": c["metrics"]["lines"],
            "scores": c["scores"], "overall": round(sum(c["scores"][d]["score"] for d in DIMENSIONS) / len(DIMENSIONS)),
            "risk": {"likelihood": like, "likelihood_basis": basis, "impact": impact,
                     "impact_source": "staff" if ci.get("impact") or ci.get("criticality") else f"default ({why})",
                     "score": score, "level": level},
            "disposition": own if c["own_disposition"] else None, "student_data": c["student_data"],
            "findings": {sev: sum(1 for f in c["findings"] if f["severity"] == sev and f["category"] != "privacy")
                         for sev in ("critical", "high", "medium", "low")},
        })
    comp_out.sort(key=lambda x: (-x["risk"]["score"], x["overall"]))
    program = {"disposition": verdict, "coverage": coverage, "inputs": inputs}
    items = solutions(components, program) if components else []
    plan = roadmap(items)
    levels = [c["risk"]["level"] for c in comp_out]
    total_risk = next((lvl for lvl in ("critical", "high", "medium", "low") if lvl in levels), "low")
    result = {
        "version": VERSION, "assessed": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "program": store.info["name"], "verdict": verdict, "scores": prog,
        "labels": LABELS, "grade_scale": "good ≥80 · fair ≥60 · poor ≥40 · critical <40",
        "total_risk": {"level": total_risk, "counts": {lvl: levels.count(lvl) for lvl in ("critical", "high", "medium", "low")}},
        "matrix": {"rows": "likelihood 5→1", "cols": "impact 1→5", "cells": matrix},
        "components": comp_out, "solutions": items, "roadmap": plan,
        "confidence": confidence(coverage, components, inputs, health), "health": health, "security": security_scan.summary(store),
        "facts": {k: v for k, v in facts.items() if k != "no_path"} | {"no_path": sorted(set(facts["no_path"]))},
    }
    store.set_meta("assessment", result)
    store.log_run("assessment", prompt_version=VERSION, ok=True)
    return result


def set_inputs(store, payload: dict) -> dict:
    current = store.get_meta("assessment_inputs", {}) or {}
    if "program" in payload:
        current["program"] = {k: v for k, v in (payload["program"] or {}).items() if v not in (None, "", False)}
    for name, vals in (payload.get("components") or {}).items():
        clean = {}
        for k, v in (vals or {}).items():
            if k in ("impact", "criticality") and v not in (None, ""):
                clean[k] = max(1, min(5, int(v)))
            elif k in ("retire", "cots", "note") and v not in (None, "", False):
                clean[k] = v
        comps = current.setdefault("components", {})
        if clean:
            comps[name] = clean
        else:
            comps.pop(name, None)
    store.set_meta("assessment_inputs", current)
    return current
