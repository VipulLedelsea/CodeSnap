from datetime import date

from . import cves, eol
from .rules import code_lines, family, pii_class, scan_text, text_has_student_data
from .standards import RULES, escalate, refs_for

CATEGORIES = ("eol", "vulnerability", "security", "privacy")
_ORDER = ["info", "low", "medium", "high", "critical"]
_SHORT = {"eol": "end of life", "extended": "extended support only", "ending": "end of life within 12 months",
          "legacy": "legacy, no upgrade path", "unknown": "version unconfirmed", "supported": "supported"}
_STATUS_TEXT = {"eol": "is past end of life", "extended": "is only on paid extended support",
                "ending": "reaches end of life within 12 months", "legacy": "is a legacy technology with no upgrade path",
                "unknown": "has an unconfirmed version", "supported": "is supported"}


def _max(a, b):
    return a if _ORDER.index(a) >= _ORDER.index(b) else b


class _Ctx:
    def __init__(self, store):
        self.store = store
        self.artifacts = {a["id"]: a for a in store.artifacts()}
        self.frames = {}

    def screenshots(self, artifact_id):
        if artifact_id not in self.frames:
            self.frames[artifact_id] = [e["id"] for e in self.store.artifact_evidence(artifact_id)] if artifact_id else []
        return self.frames[artifact_id]

    def ev(self, artifact_id, line=None, snippet=""):
        art = self.artifacts.get(artifact_id) or {}
        out = {"artifact_id": artifact_id, "file": art.get("name"), "line": line,
               "screenshots": self.screenshots(artifact_id)}
        if snippet:
            out["snippet"] = snippet
        return out


def _pii(store, ctx):
    groups, sensitive_entities, sensitive_artifacts = {}, set(), set()
    for ent in store.entities():
        if ent["kind"] not in ("column", "field", "ui_element", "config_item") or ent["origin"] == "placeholder":
            continue
        hit = pii_class(ent["name"])
        if not hit:
            continue
        label, sev = hit
        parent = store.entity(ent["parent_id"]) if ent["parent_id"] else None
        owner = parent or ent
        g = groups.setdefault(owner["id"], {"owner": owner, "labels": {}, "severity": "info", "evidence": []})
        g["labels"].setdefault(label, []).append(ent["name"])
        g["severity"] = _max(g["severity"], sev)
        g["evidence"].append(ctx.ev(ent["artifact_id"], ent["line_start"], ent["name"]))
        sensitive_entities.update({ent["id"], owner["id"]})
        if ent["artifact_id"]:
            sensitive_artifacts.add(ent["artifact_id"])
        for src in store.entity_sources(ent["id"]):
            sensitive_artifacts.add(src["artifact_id"])
    for rel in store.relations():
        if rel["to_id"] in sensitive_entities and rel["artifact_id"] and rel["kind"] in (
                "reads", "writes", "displays", "connects_to", "uses", "depends_on"):
            sensitive_artifacts.add(rel["artifact_id"])
    for g in groups.values():
        owner = g["owner"]
        kinds = ", ".join(f"{label} ({', '.join(sorted(set(names))[:4])})" for label, names in g["labels"].items())
        severity = "high" if g["severity"] == "critical" else ("medium" if g["severity"] == "high" else "low")
        store.add_finding(
            "privacy", severity, f"Student / personal data in {owner['kind']} {owner['name']}",
            detail=f"Holds {kinds}. Treat as education records: access control, encryption and disclosure logging "
                   f"apply.", source="rule SEC-PII", target_type="entity", target_id=owner["id"],
            evidence=g["evidence"][:20], rule="SEC-PII", refs=refs_for("SEC-PII"))
    return sensitive_artifacts, bool(groups)


def _eol(store, ctx, data, today, online, cache_dir):
    inventory, grouped = [], {}
    for ent in store.entities("file"):
        profile = (ent.get("attrs") or {}).get("profile")
        if not profile:
            continue
        for tech in eol.technologies(profile):
            result = eol.assess(tech, data, today)
            key = (result.get("product") or result.get("curated"), result.get("cycle") or result.get("label"))
            g = grouped.setdefault(key, {**result, "files": [], "evidence": []})
            g["evidence"].append(ctx.ev(ent["artifact_id"], (tech["lines"] or [None])[0], tech["label"]))
            g["files"].append(ent["name"])
            if tech["confidence"] == "confirmed":
                g["confidence"] = "confirmed"
    confirmed = {k[0] for k, g in grouped.items() if g.get("confidence") == "confirmed" and g.get("product")}
    for k in [k for k, g in grouped.items() if g.get("product") in confirmed and g.get("confidence") != "confirmed"]:
        del grouped[k]
    count = 0
    for g in grouped.values():
        inventory.append({k: g.get(k) for k in ("name", "label", "version", "cycle", "status", "eol", "extended_until",
                                                "active_support_ended", "confidence", "basis", "source", "url",
                                                "note", "files")})
        severity = eol.SEVERITY.get(g["status"])
        if severity:
            when = f" ({g['eol']})" if g.get("eol") else ""
            extra = f" Extended support until {g['extended_until']}." if g.get("extended_until") else ""
            detail = f"{g['label']} {_STATUS_TEXT[g['status']]}{when}.{extra} Basis: {g.get('basis')}."
            if g.get("note"):
                detail += f" {g['note']}"
            if g["confidence"] != "confirmed":
                detail += " Version not confirmed from captured files."
                severity = "info" if severity == "info" else "low"
            cycle = f" {g['cycle']}" if g.get("cycle") and not g.get("curated") else ""
            store.add_finding("eol", severity, f"{g['name']}{cycle}: {_SHORT[g['status']]}", detail=detail,
                              source=f"{g['source']} ({g['url']})", target_type="artifact",
                              target_id=g["evidence"][0]["artifact_id"], evidence=g["evidence"][:20], rule="EOL",
                              refs=refs_for("EOL", extra={"eol_status": g["status"], "eol_date": g.get("eol")}))
            count += 1
        product = g.get("product")
        if product and (g.get("version") or product in ("log4j", "apache-struts")) and (
                product in cves.CURATED or product in cves.ECOSYSTEM):
            version = g.get("version")
            found = cves.lookup(product, version, online=online, cache_dir=cache_dir)
            for v in found["vulns"]:
                note = "" if v.get("confirmed") else " Version not confirmed — verify."
                err = f" ({found['error']})" if found.get("error") else ""
                store.add_finding(
                    "vulnerability", v["severity"],
                    f"{v['id']} in {g['name']} {version or ('' if g.get('curated') else g.get('cycle') or '')}".strip(),
                    detail=f"{v['summary']}.{note}", source=f"{v['source']}{err} ({v['url']})", target_type="artifact",
                    target_id=g["evidence"][0]["artifact_id"], evidence=g["evidence"][:20], rule="CVE",
                    refs=refs_for("CVE", extra={"cve": v["id"], "aliases": v.get("aliases")}))
                count += 1
    return inventory, count


def _code(store, ctx, sensitive_artifacts, has_pii):
    hits = []
    for art in ctx.artifacts.values():
        text = art.get("transcription") or ""
        if not text.strip():
            continue
        if text_has_student_data(code_lines(text, family(art["name"], art.get("language") or ""))):
            sensitive_artifacts.add(art["id"])
        for h in scan_text(text, art["name"], art.get("language") or ""):
            hits.append({**h, "artifact_id": art["id"]})
    seen = {(h["artifact_id"], h["line"], h["rule"]) for h in hits}
    for ent in store.entities("config_item"):
        if (ent.get("attrs") or {}).get("hardcoded_secret") and ent["artifact_id"]:
            key = (ent["artifact_id"], ent["line_start"], "SEC-CRED")
            if key not in seen:
                seen.add(key)
                hits.append({"rule": "SEC-CRED", "severity": "high", "line": ent["line_start"],
                             "artifact_id": ent["artifact_id"], "connection": True,
                             "detail": f"secret stored in config item {ent['name']}",
                             "snippet": f"{ent['name']} = {(ent.get('attrs') or {}).get('value') or '****'}"})
    for rel in store.relations("connects_to"):
        attrs = rel.get("attrs") or {}
        if attrs.get("hardcoded_secret") and rel["artifact_id"]:
            key = (rel["artifact_id"], rel["line"], "SEC-CRED")
            if key not in seen:
                seen.add(key)
                hits.append({"rule": "SEC-CRED", "severity": "high", "line": rel["line"],
                             "artifact_id": rel["artifact_id"], "connection": True,
                             "detail": "password embedded in a connection string",
                             "snippet": attrs.get("connection", "")})
    for h in hits:
        rule = h["rule"]
        base = RULES[rule]
        student = base["data_risk"] and (h["artifact_id"] in sensitive_artifacts or (
            has_pii and (h.get("connection") or rule in ("SEC-TLS", "SEC-AUTH"))))
        severity = escalate(h["severity"]) if student else h["severity"]
        detail = h["detail"][0].upper() + h["detail"][1:] + "."
        if student:
            detail += " Raised one level: this file or connection handles student data (FERPA scope)."
        store.add_finding("security", severity, f"{base['title']}: {ctx.artifacts[h['artifact_id']]['name']}"
                          f"{':' + str(h['line']) if h.get('line') else ''}", detail=detail, source=f"rule {rule}",
                          target_type="artifact", target_id=h["artifact_id"],
                          evidence=[ctx.ev(h["artifact_id"], h.get("line"), h.get("snippet", ""))], rule=rule,
                          refs=refs_for(rule, student_data=student))
    return len(hits)


def run_scan(store, *, online: bool = False, today: date | None = None, cache_dir=None) -> dict:
    today = today or date.today()
    data = eol.load_data()
    kept = {(f["rule"], f["title"]): f["status"] for f in store.findings()
            if f["category"] in CATEGORIES and f.get("status", "open") != "open"}
    store.clear_findings(CATEGORIES)
    ctx = _Ctx(store)
    sensitive, has_pii = _pii(store, ctx)
    inventory, _ = _eol(store, ctx, data, today, online, cache_dir)
    _code(store, ctx, sensitive, has_pii)
    for f in store.findings():
        status = kept.get((f["rule"], f["title"]))
        if status and f["category"] in CATEGORIES:
            store.set_finding_status(f["id"], status)
    store.log_run("security_scan", model=None, prompt_version="security-v1", ok=True)
    return {"snapshot": data["snapshot"], "technologies": inventory, "summary": summary(store)}


def summary(store) -> dict:
    out = {"total": 0, "by_severity": {s: 0 for s in reversed(_ORDER)}, "by_category": {c: 0 for c in CATEGORIES}}
    for f in store.findings():
        if f["category"] not in CATEGORIES or f.get("status") == "dismissed":
            continue
        out["total"] += 1
        out["by_severity"][f["severity"]] = out["by_severity"].get(f["severity"], 0) + 1
        out["by_category"][f["category"]] += 1
    return out


def technologies(store, today: date | None = None) -> list:
    data = eol.load_data()
    rows = []
    for ent in store.entities("file"):
        profile = (ent.get("attrs") or {}).get("profile")
        for tech in eol.technologies(profile or {}):
            r = eol.assess(tech, data, today)
            rows.append({**r, "file": ent["name"]})
    return rows
