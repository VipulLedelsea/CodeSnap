from datetime import date

from core.assess import run_assessment
from core.assess.scores import DIMENSIONS, LABELS
from core.security.scan import technologies

SEV_ORDER = ["critical", "high", "medium", "low", "info"]
STATUS_TEXT = {"eol": "End of life", "extended": "Extended support only", "ending": "Ends within 12 months",
               "legacy": "Legacy — no upgrade path", "supported": "Supported", "unknown": "Version not confirmed"}
DIAGRAM_NOTES = {
    "architecture": "Every captured component by layer, with risk and end-of-life badges; platform, configuration, "
                    "security and coverage along the bottom.",
    "context": "The program as one system: who uses it, what triggers it, and every external system and data store it touches.",
    "component": "Every captured file, what it depends on, and the data it reads and writes. Dashed = referenced but not captured.",
    "class": "Classes and COBOL programs with their fields and routines; inheritance, calls and copybook includes.",
    "data": "Tables with columns and keys. Dashed tables are used by code but no DDL was captured.",
    "sequence": "Step-by-step flow from an entry point through the code to the data it touches (line numbers from the source).",
}


def _pct(v):
    return f"{round(v * 100)}%" if isinstance(v, (int, float)) else "n/a"


def _loc(ev):
    ev = (ev or [{}])[0] if isinstance(ev, list) else ev
    if not isinstance(ev, dict):
        return ""
    return f"{ev.get('file') or ''}{':' + str(ev['line']) if ev.get('line') else ''}"


def _refs(r):
    r = r or {}
    out = [r.get("cve"), r.get("cwe")] + [f"NIST {n}" for n in (r.get("nist") or [])[:2]]
    if r.get("ferpa"):
        out.append("FERPA")
    if r.get("mn_gdpa"):
        out.append("MN ch.13")
    return ", ".join(x for x in out if x)


def summary_text(a, sec, eol_count, name):
    v = a.get("verdict") or {}
    if not v:
        return f"No components have been captured for {name} yet, so no verdict can be given."
    top = [c for c in a["components"] if c["risk"]["level"] in ("critical", "high")]
    parts = [f"{name} is assessed as **{v['label']}** ({v['bucket']}), with {a['confidence']['level']} confidence."]
    parts.append(v.get("meaning", ""))
    if sec["by_severity"].get("critical") or sec["by_severity"].get("high"):
        parts.append(f"The scan found {sec['by_severity'].get('critical', 0)} critical and "
                     f"{sec['by_severity'].get('high', 0)} high-severity security issues"
                     + (", several in code that handles student data (FERPA scope)." if any(c["student_data"] for c in top)
                        else "."))
    if eol_count:
        parts.append(f"{eol_count} technolog{'y is' if eol_count == 1 else 'ies are'} past end of life or have no "
                     f"supported upgrade path.")
    if top:
        parts.append(f"{len(top)} of {len(a['components'])} components carry high or critical risk; "
                     f"the highest is {top[0]['name']}.")
    t = a["roadmap"]["total"]
    parts.append(f"The recommended roadmap is estimated at {t['low']}–{t['high']} person-weeks "
                 f"(about {t['months_one_dev'][0]}–{t['months_one_dev'][1]} months for one developer).")
    return " ".join(p for p in parts if p)


def build(store, *, rescan=True, client="Minnesota Department of Education — School Finance", prepared_by="Ledelsea",
          today=None) -> dict:
    a = store.get_meta("assessment")
    if rescan or not a:
        a = run_assessment(store, scan=True, today=today)
    from core.security.eol import load_data
    eol_snapshot = load_data()["snapshot"]
    name = store.info["name"]
    sec = a["security"]
    findings = [f for f in store.findings() if f.get("status") not in ("dismissed", "fixed")]
    techs, seen = [], set()
    for t in technologies(store, today):
        key = (t.get("name"), t.get("cycle") or t.get("label"))
        if key in seen:
            continue
        seen.add(key)
        techs.append(t)
    eol_count = sum(1 for t in techs if t.get("status") in ("eol", "legacy"))
    cov = store.coverage()
    arts = store.artifacts()
    v = a.get("verdict") or {}
    sections = []

    top_risks = a["components"][:6]
    actions = [i for p in a["roadmap"]["phases"] for i in p["items"] if p["phase"] in ("assess", "stabilize")][:7]
    sections.append({"id": "summary", "title": "Executive summary", "blocks": [
        {"type": "verdict", "verdict": v, "confidence": a["confidence"], "total_risk": a["total_risk"],
         "overall": (a["scores"].get("overall") or {}).get("score")},
        {"type": "p", "text": summary_text(a, sec, eol_count, name)},
        {"type": "kv", "items": [
            ("Overall score", f"{(a['scores'].get('overall') or {}).get('score', 'n/a')}/100"),
            ("Total risk", a["total_risk"]["level"].title()),
            ("Critical / high findings", f"{sec['by_severity'].get('critical', 0)} / {sec['by_severity'].get('high', 0)}"),
            ("Unsupported technologies", str(eol_count)),
            ("Roadmap effort", f"{a['roadmap']['total']['low']}–{a['roadmap']['total']['high']} person-weeks"),
            ("Captured", f"{len(arts)} files · {_pct(cov.get('resolved_ratio'))} of referenced code"),
        ]},
        {"type": "h", "text": "Why this verdict"},
        {"type": "bullets", "items": v.get("reasons") or ["No components captured."]},
        {"type": "h", "text": "Highest-risk components"},
        {"type": "table", "head": ["Component", "Risk", "Score", "Disposition", "Student data"],
         "rows": [[c["name"], f"{c['risk']['level'].title()} ({c['risk']['likelihood']}×{c['risk']['impact']})",
                   str(c["overall"]), (c["disposition"] or {}).get("label", "as program"),
                   "yes" if c["student_data"] else ""] for c in top_risks], "sev_col": 1},
        {"type": "h", "text": "Recommended first actions"},
        {"type": "table", "head": ["Action", "Effort (person-weeks)", "Where"],
         "rows": [[i["title"], f"{i['low']}–{i['high']}", ", ".join(i["components"][:3]) or "program-wide"] for i in actions]},
        {"type": "diagram", "id": "architecture", "caption": "Architecture overview"},
    ]})

    by_type = {}
    for art in arts:
        by_type.setdefault(art.get("language") or art.get("artifact_type") or "other", []).append(art["name"])
    kinds = cov.get("entities_by_kind") or {}
    sections.append({"id": "current", "title": "Current state", "blocks": [
        {"type": "p", "text": f"{len(arts)} files were captured from screenshots and turned into a model of "
                              f"{cov.get('entities', 0)} program elements. Every fact in this report links back to the "
                              f"screenshot it came from."},
        {"type": "table", "head": ["Language / type", "Files", "Examples"],
         "rows": [[k, str(len(v_)), ", ".join(sorted(v_)[:4]) + (" …" if len(v_) > 4 else "")]
                  for k, v_ in sorted(by_type.items(), key=lambda kv: -len(kv[1]))]},
        {"type": "kv", "items": [(k.replace("_", " ").title(), str(kinds.get(k, 0))) for k in
                                 ("program", "class", "function", "paragraph", "screen", "api_endpoint", "job",
                                  "transaction", "table", "data_store", "external_system") if kinds.get(k)]},
        {"type": "diagram", "id": "context", "caption": "Context"},
    ]})

    dim_rows = []
    for d in DIMENSIONS:
        s = a["scores"].get(d) or {}
        worst = s.get("worst") or {}
        dim_rows.append([LABELS[d], f"{s.get('score', 'n/a')}", (s.get("grade") or "").title(),
                         f"{worst.get('component', '')} ({worst.get('score', '')})" if worst else ""])
    comp_rows = [[c["name"], c.get("language") or c.get("type") or "", str(c["lines"])]
                 + [str(c["scores"][d]["score"]) for d in DIMENSIONS] for c in sorted(a["components"], key=lambda c: c["name"])]
    factor_rows = []
    for c in a["components"]:
        for d in DIMENSIONS:
            for f in c["scores"][d]["factors"]:
                if f["points"] <= -10:
                    factor_rows.append([c["name"], LABELS[d], str(f["points"]), f["text"]])
    factor_rows.sort(key=lambda r: float(r[2]))
    sections.append({"id": "technical", "title": "Technical state & health", "blocks": [
        {"type": "p", "text": "Each component is scored 0–100 on six dimensions (100 = best). Every point deducted is "
                              "listed below with the rule and finding that caused it. " + a["grade_scale"] + "."},
        {"type": "table", "head": ["Dimension", "Score", "Grade", "Weakest component"], "rows": dim_rows, "score_col": 1},
        {"type": "h", "text": "Scores by component"},
        {"type": "table", "head": ["Component", "Language", "Lines"] + [LABELS[d] for d in DIMENSIONS], "rows": comp_rows,
         "score_cols": list(range(3, 3 + len(DIMENSIONS))), "small": True},
        {"type": "h", "text": "Largest deductions"},
        {"type": "table", "head": ["Component", "Dimension", "Points", "Reason"], "rows": factor_rows[:30], "small": True},
        {"type": "diagram", "id": "components", "caption": "Components & data"},
    ]})

    sections.append({"id": "risk", "title": "Total risk & risk-impact matrix", "blocks": [
        {"type": "p", "text": f"Total risk is **{a['total_risk']['level']}**. Likelihood comes from each component's weakest "
                              f"security, supportability and health scores; impact comes from MDE's criticality rating, "
                              f"or a default where none has been entered yet."},
        {"type": "matrix", "cells": a["matrix"]["cells"]},
        {"type": "table", "head": ["Component", "Likelihood", "Impact", "Level", "Impact source"],
         "rows": [[c["name"], str(c["risk"]["likelihood"]), str(c["risk"]["impact"]), c["risk"]["level"].title(),
                   c["risk"]["impact_source"]] for c in a["components"]], "sev_col": 3, "small": True},
    ]})

    sec_rows = []
    for f in sorted([f for f in findings if f["category"] in ("security", "vulnerability")],
                    key=lambda f: (SEV_ORDER.index(f["severity"]), f["title"])):
        ev = (f.get("evidence") or [{}])[0] if f.get("evidence") else {}
        sec_rows.append([f["severity"].title(), f["title"].split(":")[0] if f["category"] == "security" else f["title"],
                         _loc(f.get("evidence")), (ev.get("snippet") or "")[:90], _refs(f.get("refs"))])
    pii = [f for f in findings if f["category"] == "privacy"]
    sections.append({"id": "security", "title": "Security analysis & vulnerabilities", "blocks": [
        {"type": "kv", "items": [(k.title(), str(sec["by_severity"].get(k, 0))) for k in SEV_ORDER]},
        {"type": "p", "text": "Findings come from deterministic rules over the transcribed code and configuration, a CVE "
                              "check of versioned libraries, and a student-data classifier. Issues in code or connections "
                              "that handle student data are raised one level and tagged FERPA / Minn. Stat. ch. 13. "
                              "Secrets are masked."},
        {"type": "table", "head": ["Severity", "Finding", "Location", "Evidence", "Standards"], "rows": sec_rows,
         "sev_col": 0, "small": True},
        {"type": "h", "text": "Student and personal data"},
        {"type": "bullets", "items": [f"{f['title']} — {f['detail'].split('. Treat')[0]}" for f in pii]
         or ["No student data fields were identified in the captured files."]},
    ]})

    sections.append({"id": "eol", "title": "End-of-life & supportability", "blocks": [
        {"type": "p", "text": "Support dates come from a bundled endoflife.date snapshot plus vendor notices for "
                              "technologies it does not track. Versions marked unconfirmed need a build or server "
                              "configuration capture to confirm."},
        {"type": "table", "head": ["Technology", "Version", "Status", "End of life", "Basis", "Files"],
         "rows": [[t.get("name") or "", t.get("version") or t.get("cycle") or "", STATUS_TEXT.get(t.get("status"), t.get("status") or ""),
                   t.get("eol") or "", t.get("basis") or "", t.get("file") or ""] for t in techs], "status_col": 2, "small": True},
    ]})

    debt_rows = []
    for c in a["components"]:
        for f in c["scores"]["tech_debt"]["factors"]:
            debt_rows.append([c["name"], str(f["points"]), f["text"]])
    sections.append({"id": "debt", "title": "Technical debt", "blocks": [
        {"type": "p", "text": "Legacy constructs, machine-translated COBOL, GO TO usage, oversized files and routines. "
                              "These drive the refactor items in the roadmap."},
        {"type": "table", "head": ["Component", "Points", "Debt item"], "rows": debt_rows or [["—", "", "No debt items found."]],
         "small": True},
    ]})

    road_blocks = [{"type": "p", "text": f"Estimated total: **{a['roadmap']['total']['low']}–{a['roadmap']['total']['high']} "
                                         f"person-weeks**. Ranges come from rules per fix type and file size; MDE and "
                                         f"Ledelsea should adjust them with local rates and staffing."}]
    for p in a["roadmap"]["phases"]:
        road_blocks.append({"type": "h", "text": f"{p['title']}  ·  {p['window']}  ·  {p['low']}–{p['high']} person-weeks"})
        road_blocks.append({"type": "table", "head": ["Item", "What to do", "Effort", "Components"],
                            "rows": [[i["title"], i["action"], f"{i['low']}–{i['high']}",
                                      ", ".join(i["components"][:4]) + (" …" if len(i["components"]) > 4 else "")]
                                     for i in p["items"]], "small": True})
    disp = [c for c in a["components"] if c.get("disposition")]
    if disp:
        road_blocks.append({"type": "h", "text": "Component dispositions"})
        road_blocks.append({"type": "table", "head": ["Component", "Disposition", "Why"],
                            "rows": [[c["name"], c["disposition"]["label"], "; ".join(c["disposition"]["reasons"][:2])]
                                     for c in disp], "small": True})
    sections.append({"id": "roadmap", "title": "Potential solutions & modernization roadmap", "blocks": road_blocks})

    sections.append({"id": "diagrams", "title": "Diagrams", "blocks": [
        {"type": "p", "text": "All diagrams are generated from the program model, not drawn by hand or by AI. The full set, "
                              "including one class diagram per file, is in the accompanying Visio (.vsdx) and draw.io files."},
        {"type": "diagram", "id": "class", "caption": "Classes & programs"},
        {"type": "diagram", "id": "data", "caption": "Data model"},
        {"type": "diagrams", "kind": "sequence", "limit": 4, "caption": "Interaction"},
    ]})

    missing = [m for m in cov.get("missing") or [] if m["category"] == "missing_code"]
    sections.append({"id": "coverage", "title": "Coverage, confidence & method", "blocks": [
        {"type": "kv", "items": [("Confidence", a["confidence"]["level"].title()),
                                 ("Referenced code captured", _pct(cov.get("resolved_ratio"))),
                                 ("Missing code references", str(len(missing))),
                                 ("External resources", str((cov.get("missing_counts") or {}).get("external", 0)))]},
        {"type": "bullets", "items": a["confidence"]["notes"]},
        {"type": "h", "text": "Referenced but not captured"},
        {"type": "bullets", "items": [f"{m['kind']} {m['name']} — used by "
                                      + ", ".join(sorted({r.get('artifact') or r['name'] for r in m['referenced_by']})[:3])
                                      for m in missing[:40]] or ["Nothing missing."]},
        {"type": "h", "text": "Method"},
        {"type": "bullets", "items": [
            "Code, screens, schemas and configuration were captured as screenshots and transcribed with a vision model; "
            "transcriptions were syntax-checked with real compilers/parsers (GnuCOBOL, tree-sitter).",
            "Program structure, security rules, end-of-life matching, scoring, verdict and diagrams are deterministic "
            "code — the same inputs always give the same report.",
            f"End-of-life data: endoflife.date snapshot {eol_snapshot} plus vendor notices; CVEs: OSV (when online) or a "
            f"curated list.",
            "Nothing was executed against MDE systems; findings should be confirmed with MNIT before remediation.",
        ]},
    ]})
    return {"program": name, "slug": store.info["slug"], "client": client, "prepared_by": prepared_by,
            "date": (today or date.today()).strftime("%B %d, %Y"), "verdict": v, "assessment": a, "sections": sections}
