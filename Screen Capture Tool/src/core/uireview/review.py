import re
from datetime import date

from core.security import cves, eol
from core.security.rules import family
from core.security.standards import MN_GDPA, FERPA, MNIT

from .flows import journeys
from .page import check_page
from .screens import check_screens
from .site import IIS, scan_site

CATEGORIES = ("accessibility", "usability", "ui_security", "website")
TITLES = {
    "ACC-ALT": "Image without text alternative", "ACC-LABEL": "Form field without a label", "ACC-TITLE": "Page has no title",
    "ACC-LANG": "Page language not declared", "ACC-HEADINGS": "No headings", "ACC-CONTRAST": "Low text contrast",
    "ACC-KEYBOARD": "Not keyboard accessible", "ACC-LINK": "Unclear link text", "ACC-ZOOM": "Zoom blocked",
    "ACC-DEPRECATED": "Obsolete presentational HTML", "ACC-TABLE": "Table without headers",
    "ACC-TERMINAL": "Terminal-only interface", "USE-LONGFORM": "Very long form", "USE-VALIDATION": "No input validation",
    "USE-CONFIRM": "No confirmation for a consequential action", "USE-BUTTON": "Unclear button label",
    "USE-CODES": "Cryptic codes on screen", "UIB-CRASH": "System failure visible to users",
    "UIB-ERROR": "Error shown to users", "UIB-OBSERVED": "Observed usability problem",
    "ACC-COLOR": "Meaning shown by colour only", "ACC-TEXTSIZE": "Text too small", "UIB-OBSOLETE": "Built for an obsolete browser",
    "UIS-GET": "Sensitive data sent in the URL", "UIS-CSRF": "No cross-site request forgery protection",
    "UIS-BLANK": "Reverse tabnabbing", "UIS-MIXED": "Mixed / plain-HTTP content", "UIS-HIDDEN": "Trusted value in hidden field",
    "UIS-PWFIELD": "Password shown as typed", "UIS-PREFILL": "Password written in the page source", "UIS-PII": "Student data shown in full",
    "WEB-HTTPS": "No HTTPS", "WEB-CERT": "Invalid TLS certificate", "WEB-TLS": "Obsolete TLS", "WEB-HSTS": "No HSTS",
    "WEB-CSP": "No Content-Security-Policy", "WEB-XCTO": "No nosniff header", "WEB-REFERRER": "No Referrer-Policy",
    "WEB-FRAME": "Clickjacking possible", "WEB-COOKIE": "Insecure cookie", "WEB-DISCLOSURE": "Server version disclosed",
    "WEB-EOL": "Unsupported technology on the live site", "WEB-CVE": "Known vulnerability in site library",
}
WEB_EXT = ("html", "htm", "aspx", "ascx", "master", "jsp", "jspx", "asp", "cshtml", "xhtml")


def _sentence(d):
    d = (d or "").strip()
    first = d.split(" ", 1)[0] if d else ""
    if d and d[0].islower() and not any(c.isupper() for c in first):
        d = d[0].upper() + d[1:]
    return d if d.endswith((".", ")")) else d + "."


def _refs(f):
    r = dict(f.get("refs") or {})
    out = {k: v for k, v in r.items() if k in ("wcag", "cwe", "nist", "cve", "eol_status", "eol_date")}
    if r.get("wcag"):
        out["standard"] = "WCAG 2.1 AA · Section 508"
    if r.get("ferpa"):
        out["ferpa"], out["mn_gdpa"] = FERPA, MN_GDPA
    if f["category"] in ("ui_security", "website"):
        out["mnit"] = MNIT
    return out


def _site_libs(summary, add, today):
    data = eol.load_data()
    for src in summary.get("libraries") or []:
        m = re.search(r"(jquery|bootstrap|angular(?:js)?)[.-]?(\d+(?:\.\d+){1,3})", src.rsplit("/", 1)[-1], re.I)
        if not m:
            continue
        for tech in eol.technologies({"libraries": [f"{m.group(1).lower()} {m.group(2)}"]}):
            res = eol.assess(tech, data, today)
            if res.get("status") in ("eol", "extended", "ending"):
                add("WEB-EOL", "high" if res["status"] == "eol" else "medium", src,
                    f"{res['name']} {tech['version']} on the live site is {res['status']}"
                    + (f" ({res['eol']})" if res.get("eol") else ""), src, eol_status=res["status"], eol_date=res.get("eol"))
            for v in cves.curated(tech["product"], tech["version"]):
                add("WEB-CVE", v["severity"], src, f"{v['id']}: {v['summary']}", src, cve=v["id"])
    for kind, ver in summary.get("technologies") or []:
        if kind == "iis":
            prod, cyc = IIS[ver]
            p = data["products"][prod]
            c = next((x for x in p["cycles"] if x["cycle"] == cyc), None)
            if c:
                st = eol.cycle_status(c, today)
                if st["status"] != "supported":
                    add("WEB-EOL", "high" if st["status"] == "eol" else "medium", summary.get("final_url"),
                        f"IIS {ver} implies {p['label']} {cyc}: {st['status']}" + (f" ({st.get('eol')})" if st.get("eol") else ""),
                        f"Server: Microsoft-IIS/{ver}", eol_status=st["status"], eol_date=st.get("eol"))


def run_ui_review(store, *, site_url=None, fetcher=None, max_pages=10, today=None) -> dict:
    today = today or date.today()
    kept = {(f["rule"], f["title"]): f["status"] for f in store.findings()
            if f["category"] in CATEGORIES and f.get("status", "open") != "open"}
    site_prior = store.get_meta("site_scan")
    if site_url:
        store.clear_findings(CATEGORIES)
    else:
        store.clear_findings(("accessibility", "usability", "ui_security"), keep_source_prefix="live scan")
    arts = {a["id"]: a for a in store.artifacts()}
    frames = {}

    def ev(aid, line=None, snippet="", url=None, screen=None):
        if url:
            return {"file": url, "url": url, "line": line, "snippet": snippet, "screenshots": []}
        if aid not in frames:
            frames[aid] = [e["id"] for e in store.artifact_evidence(aid)] if aid else []
        out = {"artifact_id": aid, "file": (arts.get(aid) or {}).get("name"), "line": line, "screenshots": frames[aid]}
        if snippet:
            out["snippet"] = snippet
        if screen:
            out["screen"] = screen
        return out

    def store_f(f, evidence, source, target_id=None):
        title = TITLES.get(f["rule"], f["rule"])
        if f.get("title"):
            title = f"{title} — {f['title']}"
        where = evidence.get("file") or ""
        store.add_finding(f["category"], f["severity"], f"{title}: {where}{':' + str(evidence['line']) if evidence.get('line') else ''}",
                          detail=_sentence(f["detail"]), source=source,
                          target_type="artifact" if target_id else None, target_id=target_id, evidence=[evidence],
                          rule=f["rule"], refs=_refs(f))

    count = 0
    for aid, a in arts.items():
        ext = a["name"].rsplit(".", 1)[-1].lower() if "." in a["name"] else ""
        if ext not in WEB_EXT and family(a["name"], a.get("language") or "") != "web":
            continue
        for f in check_page(a.get("transcription") or ""):
            store_f(f, ev(aid, f["line"], f.get("snippet", "")), f"rule {f['rule']} (page source)", aid)
            count += 1
    for f in check_screens(store):
        src = "screen review (vision-observed)" if f.get("observed") else f"rule {f['rule']} (screens)"
        store_f(f, ev(f["artifact_id"], None, f.get("snippet", ""), screen=f.get("screen")), src, f["artifact_id"])
        count += 1
    site = None
    if site_url:
        site = scan_site(site_url, fetcher=fetcher, max_pages=max_pages)
        stamp = site["summary"]["scanned"][:10]

        def add(rule, severity, url, detail, snippet="", **refs):
            site["findings"].append({"rule": rule, "category": "website", "severity": severity, "url": url, "line": None,
                                     "detail": detail, "snippet": snippet, "refs": refs})
        _site_libs(site["summary"], add, today)
        for f in site["findings"]:
            cat = f["category"] if f["category"] in ("accessibility", "usability") else "website"
            store_f({**f, "category": cat}, ev(None, f.get("line"), f.get("snippet", ""), url=f["url"]),
                    f"live scan {stamp} ({site['summary']['final_url'] or site_url})")
            count += 1
        store.set_meta("site_scan", site["summary"])
    for f in store.findings():
        st = kept.get((f["rule"], f["title"]))
        if st and f["category"] in CATEGORIES:
            store.set_finding_status(f["id"], st)
    from core.model.corrections import apply_corrections
    apply_corrections(store)
    flows = journeys(store)
    store.set_meta("ui_flows", flows)
    store.log_run("ui_review", prompt_version="ui-review-v1", ok=True)
    return {"findings": count, "site": (site or {}).get("summary") or site_prior, "flows": flows, "summary": summary(store)}


def summary(store) -> dict:
    out = {c: {"total": 0, "high": 0} for c in CATEGORIES}
    for f in store.findings():
        if f["category"] in CATEGORIES and f.get("status") != "dismissed":
            out[f["category"]]["total"] += 1
            if f["severity"] in ("critical", "high"):
                out[f["category"]]["high"] += 1
    return out
