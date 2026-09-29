"""The Word report: the Application Assessment Report template, completed section by section.

Everything the program's source shows is filled in with its reasoning. Business facts the source cannot show (owners,
user counts, licensing, calendars, interviews) come from the report settings; anything still missing is written as
"Unknown" and logged in 13.4 Open items, as the template's own completion guidance requires. The how-to-use guidance,
instruction text and bracketed placeholders are removed so the document can be issued as-is.
"""
import io
import re
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, RGBColor

from . import rationale as R
from .settings import app_number, get as get_settings

TEMPLATE = Path(__file__).with_name("assets") / "Application_Assessment_Report_Template.docx"
UNKNOWN = "Unknown"
INK = RGBColor(0x1F, 0x29, 0x37)
SEV = ["critical", "high", "medium", "low", "info"]


# ── document helpers ────────────────────────────────────────────────────────────────────────────────────────────

class Doc:
    def __init__(self, path=TEMPLATE):
        self.d = Document(str(path))
        self.body = self.d.element.body
        self.open_items = []
        self.proto = None
        for p in self.d.paragraphs:
            if p.text.startswith("Summarize in three to five"):
                self.proto = deepcopy(p._p)
        self.bullet_proto = next((deepcopy(p._p) for p in self.d.paragraphs
                                  if p.style is not None and p.style.name == "List Paragraph"), None)

    def para(self, starts):
        return next((p for p in self.d.paragraphs if p.text.strip().startswith(starts)), None)

    def table_after(self, heading_starts, nth=0):
        """The nth table following the paragraph that starts with heading_starts."""
        p = self.para(heading_starts)
        if p is None:
            return None
        el, seen = p._p.getnext(), 0
        from docx.table import Table
        while el is not None:
            if el.tag == qn("w:tbl"):
                if seen == nth:
                    return Table(el, self.d)
                seen += 1
            if el.tag == qn("w:p") and el.xpath("./w:pPr/w:pStyle[@w:val='Heading1' or @w:val='Heading2']"):
                return None
            el = el.getnext()
        return None

    def unknown(self, what, section, owner="Business owner"):
        self.open_items.append((what, section, owner))
        return UNKNOWN

    def new_para(self, text, after_el, bullet=False, italic=False):
        el = deepcopy(self.bullet_proto if bullet and self.bullet_proto is not None else self.proto)
        after_el.addnext(el)
        from docx.text.paragraph import Paragraph
        p = Paragraph(el, self.d)
        _set_para(p, text, italic=italic)
        return p

    def replace(self, starts, texts, bullet=False):
        """Replace an instruction paragraph with one or more content paragraphs."""
        p = self.para(starts)
        if p is None:
            return None
        texts = [t for t in ([texts] if isinstance(texts, str) else texts) if t]
        if not texts:
            texts = ["None identified in the material reviewed."]
        anchor = p._p
        last = None
        for t in texts:
            last = self.new_para(t, anchor if last is None else last._p, bullet=bullet)
        p._p.getparent().remove(p._p)
        return last

    def remove(self, starts):
        p = self.para(starts)
        if p is not None:
            p._p.getparent().remove(p._p)

    def picture(self, png_bytes, after_el, width_in=7.0, max_h=8.0):
        from PIL import Image
        w, h = Image.open(io.BytesIO(png_bytes)).size
        width_in = min(width_in, max_h * w / max(h, 1))
        from docx.text.paragraph import Paragraph
        el = deepcopy(self.proto)
        after_el.addnext(el)
        p = Paragraph(el, self.d)
        for r in list(p.runs):
            r._r.getparent().remove(r._r)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.line_spacing = None
        p.paragraph_format.keep_with_next = True
        p.add_run().add_picture(io.BytesIO(png_bytes), width=Inches(width_in))
        return p


def _set_para(p, text, italic=False, bold=None):
    runs = p.runs
    if not runs:
        r = p.add_run(text)
    else:
        r = runs[0]
        for extra in runs[1:]:
            extra._r.getparent().remove(extra._r)
        r.text = text
    r.font.italic = italic or None
    rpr = r._r.find(qn("w:rPr"))
    if rpr is not None:
        for c in rpr.findall(qn("w:color")):
            rpr.remove(c)
    if bold is not None:
        r.font.bold = bold
    return r


def set_cell(cell, text):
    text = "" if text is None else str(text)
    paras = cell.paragraphs
    had_runs = bool(paras[0].runs)
    for extra in paras[1:]:
        extra._p.getparent().remove(extra._p)
    lines = text.split("\n")
    r = _set_para(paras[0], lines[0])
    if not had_runs:
        from docx.shared import Pt
        r.font.size = Pt(8.5)
    prev = paras[0]._p
    for ln in lines[1:]:
        el = deepcopy(prev)
        prev.addnext(el)
        from docx.text.paragraph import Paragraph
        _set_para(Paragraph(el, cell._parent), ln)
        prev = el


def kv(t, values: dict, start=1):
    """Fill a two-column Attribute / Entry table by the attribute label."""
    if t is None:
        return
    for row in t.rows[start:]:
        label = row.cells[0].text.strip()
        for k, v in values.items():
            if label.lower().startswith(k.lower()):
                set_cell(row.cells[1], v)
                break


def rows(t, data: list, start=1, empty="None identified in the material reviewed."):
    """Replace the example rows (from `start`) with `data` (lists of cell texts), copying the first example row."""
    if t is None:
        return
    proto = deepcopy(t.rows[start]._tr)
    for r in list(t.rows)[start:]:
        r._tr.getparent().remove(r._tr)
    if not data:
        data = [[empty] + [""] * (len(t.columns) - 1)]
    for values in data:
        tr = deepcopy(proto)
        t._tbl.append(tr)
        row = t.rows[-1]
        for i, cell in enumerate(row.cells):
            set_cell(cell, values[i] if i < len(values) else "")


def fill_col(t, col, values_by_label: dict, default=None):
    """Set column `col` of every row whose first cell starts with a key of values_by_label."""
    if t is None:
        return
    for row in t.rows[1:]:
        label = row.cells[0].text.strip()
        hit = next((v for k, v in values_by_label.items() if label.lower().startswith(k.lower())), default)
        if hit is not None:
            vals = hit if isinstance(hit, (list, tuple)) else [hit]
            for j, v in enumerate(vals):
                if col + j < len(row.cells):
                    set_cell(row.cells[col + j], v)


# ── data from the program ───────────────────────────────────────────────────────────────────────────────────────

def _risk_rows(a, num):
    out = []
    comps = sorted(a["components"], key=lambda c: -(c.get("risk") or {}).get("score", 0))
    for i, c in enumerate(comps, 1):
        r = c.get("risk") or {}
        cat = "Security" if (c["scores"]["security"]["score"] or 100) <= min(c["scores"]["supportability"]["score"],
                                                                            c["scores"]["health"]["score"]) else "Technology"
        disp = (c.get("disposition") or {})
        out.append({"id": f"R-{num}-{i:02d}", "c": c, "cat": cat, "L": r.get("likelihood", 1), "I": r.get("impact", 1),
                    "score": r.get("score", 1),
                    "short": f"{c['name']}: " + ("no serious weakness found; every area scored fair or better"
                                                 if disp.get("code") in (None, "retain") else
                                                 _cap((disp.get("reasons") or ["component risk"])[0].split(": ")[0].strip().lower())),
                    "desc": f"{c['name']}: {', '.join((disp.get('reasons') or [])[:1]) or 'component risk'}. "
                                                         f"Rationale: {R.risk_reason(c)}",
                    "mit": f"{disp.get('label', 'Retain')}: {_disp_plain(disp) or 'keep as is with routine maintenance'}"})
    return out


def _layer(t):
    n = f"{t.get('name', '')} {t.get('label', '')} {t.get('product') or ''} {t.get('curated') or ''}".lower()
    rules = [("Presentation / UI", ("html", "asp", "jsp", "jquery", "angular", "react", "winforms", "vb6", "visual basic",
                                    "delphi", "cics bms", "bms", "3270", "mfs", "web forms", "javascript")),
             ("Database", ("db2", "ims", "oracle", "sql server", "postgres", "mysql", "access", "vsam", "idms", "foxpro", "dbf")),
             ("Batch and scheduling", ("jcl", "scheduler", "control-m", "cron")),
             ("Reporting", ("crystal", "ssrs", "power bi", "report")),
             ("Operating system", ("z/os", "ibm i", "windows server", "linux", "aix", "solaris")),
             ("Web and application server", ("iis", "tomcat", "weblogic", "websphere", "jboss")),
             ("Identity and authentication", ("active directory", "ldap", "okta", "entra")),
             ("Application framework", (".net", "java", "spring", "struts", "cics", "node")),
             ("Programming languages", ("cobol", "rpg", "pl/i", "c++", "c#", "python", "perl", "rexx", "fortran", "assembler",
                                        "sas", "spss", "vba"))]
    for layer, keys in rules:
        if any(k in n for k in keys):
            return layer
    return "Third-party libraries and components"


def _status_word(t):
    return {"eol": "Unsupported", "legacy": "Unsupported (no upgrade path)", "extended": "Extended",
            "ending": "Supported (ends within 12 months)", "supported": "Supported"}.get(t.get("status"), "Version not confirmed")


def _months_left(eol, today):
    try:
        d = datetime.strptime(str(eol)[:10], "%Y-%m-%d").date()
    except Exception:  # noqa: BLE001
        return ""
    return str((d.year - today.year) * 12 + d.month - today.month)


CONTROL_AREAS = [
    ("Authentication", ("SEC-AUTH", "UIS-PWFIELD", "UIS-PW")),
    ("Authorization", ("SEC-PATH", "AC-")),
    ("Privileged", ()),
    ("Secrets management", ("SEC-CRED",)),
    ("Encryption in transit", ("SEC-TLS", "WEB-HTTPS", "WEB-TLS", "WEB-CERT")),
    ("Encryption at rest", ("SEC-CRYPTO",)),
    ("Input validation", ("SEC-SQLI", "SEC-SQLDYN", "SEC-XSS", "SEC-CMD", "SEC-DESER", "SEC-MEM")),
    ("Audit logging", ("SEC-CONF",)),
    ("Patch management", ("CVE", "EOL")),
    ("Secure development", ()),
    ("Backup", ()),
    ("Third-party", ("CVE",)),
]
CHECKABLE = {"Secrets management", "Encryption in transit", "Input validation", "Patch management", "Third-party",
             "Encryption at rest", "Authentication"}


def _sev_rating(fs):
    worst = min((SEV.index(f["severity"]) for f in fs), default=None)
    return {0: 5, 1: 4, 2: 3, 3: 2, 4: 2}.get(worst, 1)


# ── the build ───────────────────────────────────────────────────────────────────────────────────────────────────

def render(store, report: dict, diagrams: dict, today=None) -> bytes:
    from core.diagrams.render import png
    from core.security.scan import technologies
    today = today or date.today()
    s = get_settings(store)
    a = report["assessment"]
    num = app_number(s)
    app_id = s["app_id"] or f"APP-{num}"
    name = report["program"]
    doc = Doc()
    comps = a["components"]
    findings = [f for f in store.findings() if f.get("status") not in ("dismissed", "fixed")]
    sec_f = [f for f in findings if f["category"] in ("security", "vulnerability", "ui_security", "website", "privacy")]
    arts = store.artifacts()
    cov = store.coverage()
    techs, seen = [], set()
    for t in technologies(store, today):
        k = (t.get("name"), t.get("cycle") or t.get("label"))
        if k not in seen:
            seen.add(k)
            techs.append(t)
    sessions = store._all("SELECT MIN(started) AS a FROM capture_session") if _has_col(store, "capture_session", "started") else []
    start = (sessions[0]["a"] if sessions and sessions[0]["a"] else store.info.get("created") or "")[:10]
    period = f"{start or UNKNOWN} to {today.isoformat()}"
    risks = _risk_rows(a, num)
    pii = any(f["category"] == "privacy" or f.get("rule") == "SEC-PII" for f in findings) or any(c.get("student_data") for c in comps)
    top = max(risks, key=lambda r: r["score"]) if risks else None
    v = a.get("verdict") or {}
    overall = (a["scores"].get("overall") or {}).get("score")
    ov_c, ov_l = R.condition(overall)
    debt = (a["scores"].get("tech_debt") or {}).get("score")
    debt_level = "Low" if (debt or 0) >= 80 else "Medium" if (debt or 0) >= 60 else "High"
    crit_high = sum(1 for f in sec_f if f["severity"] in ("critical", "high"))
    eol = [t for t in techs if t.get("status") in ("eol", "legacy", "extended", "ending")]
    phases = {p["phase"]: p for p in a["roadmap"]["phases"]}
    horizon = {"good to go": "Short term, 0 to 12 months (maintenance only)", "patch": "Short term, 0 to 12 months",
               "rebuild": "Mid term, 1 to 3 years"}.get(v.get("bucket"), "Mid term, 1 to 3 years")
    DISP = {"retain": "Retain", "rehost": "Re-host", "replatform": "Re-platform", "refactor": "Refactor",
            "rearchitect": "Refactor (re-architect)", "replace": "Replace", "retire": "Retire"}
    disposition = DISP.get(v.get("code"), v.get("label") or UNKNOWN)
    tier = s["criticality_tier"] and f"Tier {s['criticality_tier'].replace('Tier', '').strip()}"
    total = a["roadmap"]["total"]

    # cover, contents, rating scales
    kv(doc.d.tables[0], {"Application": f"{name} ({app_id})", "Client": s["client"] or doc.unknown("Client organization", "Cover"),
                         "Engagement": s["engagement"] or doc.unknown("Engagement name", "Cover"), "Version": s["version"],
                         "Date": today.strftime("%B %d, %Y"), "Classification": s["classification"]}, start=0)
    _fill_toc(doc)
    doc.remove("Right-click the table of contents")
    h = doc.para("How to use this template")
    if h is not None:
        _set_para(h, "Rating scales and definitions")
    for starts in ("One copy of this report is completed", "Completion guidance", "Replace every bracketed placeholder",
                   "Where information cannot be confirmed", "Keep scores consistent", "Mark any field containing"):
        doc.remove(starts)
    scales = doc.para("Standard rating scales")
    if scales is not None:
        doc.new_para("Scores in this report are measured on a 0 to 100 scale (100 = best) from itemised deductions and "
                     f"converted to the condition scale below: {R.BANDS}. Every rating states the deductions behind it.",
                     scales._p.getprevious())

    # document control
    kv(doc.d.tables[3], {"Client": s["client"] or UNKNOWN, "Engagement": s["engagement"] or UNKNOWN, "Application name": name,
                         "Application ID": app_id, "Report version": s["version"], "Assessment period": period,
                         "Prepared by": s["prepared_by"], "Technical reviewer": s["technical_reviewer"] or doc.unknown("Technical reviewer", "Document control", "Assessment lead"),
                         "Business owner reviewer": s["business_owner"] or doc.unknown("Business owner reviewer", "Document control"),
                         "IT reviewer": s["it_reviewer"] or doc.unknown("IT reviewer", "Document control", "IT"),
                         "Classification": s["classification"], "Related applications": s["related_apps"] or "None identified"})
    rows(doc.d.tables[4], [[s["version"].split()[0].lstrip("v"), today.isoformat(), s["prepared_by"], "Assessment report issued"]])

    # 1 summary
    snap = {"Purpose in one sentence": s["purpose"] or doc.unknown("Purpose of the application in one sentence", "1.1"),
            "Business area": s["business_area"] or doc.unknown("Business area or program supported", "1.1"),
            "Business value": s["business_value"] or doc.unknown("Business value or volume supported", "1.1"),
            "Criticality tier": tier or doc.unknown("Criticality tier", "1.1"),
            "Overall health rating": _health_line(a),
            "Technical debt level": f"{debt_level}. {R.explain_program(a, 'tech_debt')}",
            "Open critical or high vulnerabilities": f"{crit_high} ({sum(1 for f in sec_f if f['severity'] == 'critical')} critical, "
                                                     f"{sum(1 for f in sec_f if f['severity'] == 'high')} high); register in 8.3",
            "Highest risk score": (f"{top['score']}, {R.template_rating(top['score'])} ({top['id']}, {top['c']['name']})"
                                   if top else "None"),
            "End-of-life exposure": "; ".join(f"{t.get('name')} {t.get('version') or t.get('cycle') or ''}".strip()
                                              + (f" (ended {t['eol']})" if t.get("eol") else f" ({_status_word(t).lower()})")
                                              for t in eol[:5]) or "None identified",
            "Recommended disposition": f"{disposition}: {_disp_plain(v)}",
            "Recommended timing": horizon}
    kv(doc.d.tables[5], snap)
    sec = a["security"]["by_severity"]
    from . import plain as P
    top_sec = sorted(sec_f, key=lambda f: SEV.index(f["severity"]))
    worst3 = []
    for f in top_sec:
        w = P.what(f.get("rule") or "", f["title"])
        if w not in [x[0] for x in worst3]:
            worst3.append((w, f["severity"]))
        if len(worst3) == 3:
            break
    sec_score = a["scores"]["security"]["score"]
    health_c = _health_total(a)[0]["overall"][0]
    findings_txt = [
        f"In short: {name} is in {LEVEL_WORD.get(health_c, 'unrated')} overall condition "
        f"({health_c or '–'} on a scale where 1 is best and 5 is worst), but "
        + ("it has serious security problems" if sec.get("critical") or sec.get("high") else "it has some security issues to fix")
        + (" and relies on technology the vendor no longer supports." if eol else ".")
        + f" The recommended direction is to {disposition.lower()}: {P.DISPOSITIONS.get(v.get('code'), v.get('meaning', '')).rstrip('.').lower()} "
          f"(Section 12).",
        f"Security (Section 8). The review found {sec.get('critical', 0)} critical, {sec.get('high', 0)} high and "
        f"{sec.get('medium', 0)} medium issues. The most serious: {P.sentence([f'{w} ({sv})' for w, sv in worst3])}. "
        + ("Because the application handles personal data, a breach would expose personal records, so these issues are "
           "rated one level higher than they otherwise would be. " if pii else "")
        + f"Security is rated {R.rating_words(sec_score)} (it scored {sec_score} out of 100).",
        (f"Supportability (Section 6.2). {P.sentence([_eol_plain(t) for t in eol[:3]])}. Unsupported software no longer "
         f"receives security fixes, so its known weaknesses stay open until it is upgraded or replaced.")
        if eol else "Supportability (Section 6.2). Every technology identified is still supported by its vendor.",
        (f"Risk (Section 9). The highest risk is {top['id']}, {top['c']['name']}: {top['score']} of 25, which is "
         f"{R.template_rating(top['score'])}. {R.risk_reason(top['c'])}") if top else "",
        f"Effort (Section 12.4). The recommended work is estimated at {total['low']}–{total['high']} person-weeks, about "
        f"{total['months_one_dev'][0]}–{total['months_one_dev'][1]} months for one developer. The first items are quick "
        f"security fixes that can be made before any wider modernization decision (Section 1.3).",
    ]
    doc.replace("Summarize in three to five", findings_txt)
    doc.replace("List any condition that warrants action", "These problems should be fixed now, before any decision on "
                "modernization, because they expose data or users today:")
    imm = []
    for it in (phases.get("stabilize") or {}).get("items", [])[:8]:
        ids = {str(x) for x in it.get("findings") or []}
        linked = [f for f in sec_f if str(f["id"]) in ids]
        urg = "Within 30 days" if any(f["severity"] == "critical" for f in linked) else "Within 90 days"
        rule = next((f.get("rule") for f in linked if f.get("rule")), "") or it["id"].split(":")[0]
        cond = it["title"] + (f" ({', '.join(it['components'][:2])})" if it["components"] else "")
        if rule and P.why(rule):
            cond += f". Why it matters: {P.why(rule)}."
        imm.append([str(len(imm) + 1), cond, it["action"], "IT", urg])
    rows(doc.d.tables[6], imm, empty="None")

    # 2 business context
    kv(doc.d.tables[7], {"Business capability": s["purpose"] or doc.unknown("Business capability supported", "2.1"),
                         "Regulatory": s["regulatory_basis"] or doc.unknown("Regulatory, contractual or policy basis", "2.1"),
                         "Business owner": s["business_owner"] or UNKNOWN,
                         "Subject matter experts": doc.unknown("Subject matter experts", "2.1"),
                         "Year introduced": doc.unknown("Year introduced and major rewrites", "2.1"),
                         "Known drivers of change": doc.unknown("Known drivers of change", "2.1")})
    screens = [e for e in store.entities("screen")]
    rows(doc.d.tables[8], [["Business users of the application screens", UNKNOWN, doc.unknown("Number of users by group", "2.2"),
                            f"{len(screens)} screen(s): " + ", ".join(e['name'][:40] for e in screens[:4]) if screens else UNKNOWN,
                            UNKNOWN]] + ([["Batch schedule (no interactive users)", "Internal", "Not applicable",
                                           "Scheduled batch jobs", UNKNOWN]] if store.entities("job") else []))
    flows = store.get_meta("ui_flows") or {}
    proc = doc.para("[Insert process flow diagram")
    if proc is not None:
        uf = diagrams.get("userflow")
        if uf:
            pic = doc.picture(png(uf, scale=1.6), proc._p, 6.8, max_h=4.0)
            doc.new_para(f"Figure 2. Current-state screen flow for {name}, drawn from the screens and navigation in the source.",
                         pic._p, italic=True)
        proc._p.getparent().remove(proc._p)
    doc.replace("Document each business process the application supports", "The screen flow below is drawn from the "
                "screens and navigation in the source. Business actors, manual steps and handoffs outside the application "
                "are to be mapped with stakeholders (open item).")
    doc.unknown("Swimlane process map with business actors and manual steps", "2.3")
    steps = []
    for j in (flows.get("journeys") or [])[:3]:
        for st in j["steps"]:
            steps.append([str(len(steps) + 1), "Business user", f"Uses screen {st['screen']}", "Manual (screen entry)",
                          UNKNOWN, UNKNOWN, "" if st.get("captured") else "Screen referenced but not provided"])
    jobs = store.entities("job")
    for jb in jobs[:6]:
        steps.append([str(len(steps) + 1), "Scheduler", f"Runs batch job {jb['name']}", "Automated", UNKNOWN, UNKNOWN, ""])
    rows(doc.d.tables[9], steps, empty="No process steps could be derived from the source; to be mapped with stakeholders.")
    rows(doc.d.tables[10], [[f"Batch job {jb['name']}", doc.unknown(f"Schedule of batch job {jb['name']}", "2.4", "IT"),
                             "High", UNKNOWN] for jb in jobs[:6]],
         empty="No scheduled cycles were identified in the source; business calendar to be confirmed with the business owner.")
    ux_issues = [f for f in findings if f["category"] in ("usability", "accessibility")]
    doc.replace("Record pain points in the words", [
        "Stakeholder interviews were not part of this review, so pain points are not recorded in stakeholders' words "
        "(open item). Issues observable in the application itself:"] +
        [f"{f['title']}" for f in sorted(ux_issues, key=lambda f: SEV.index(f['severity']))[:6]])
    if not ux_issues:
        pass
    doc.unknown("Business pain points in stakeholders' words (interviews)", "2.5")

    # 3 technical profile
    types = sorted({(x.get("artifact_type") or "code") for x in arts})
    langs = {}
    for x in arts:
        langs[x.get("language") or x.get("artifact_type") or "other"] = langs.get(x.get("language") or "other", 0) + len(
            (x.get("transcription") or "").splitlines())
    kinds = cov.get("entities_by_kind") or {}
    app_type = ", ".join(sorted({"Batch process" if k in ("job", "program") else "Web application" if k in ("api_endpoint",) else ""
                                 for k in kinds} - {""})) or UNKNOWN
    if any("screen" in t or "ui" in t for t in types) or kinds.get("screen"):
        app_type = ", ".join(sorted(set(app_type.split(", ")) - {UNKNOWN} | {"Online screens"}))
    cobolish = [x for x in arts if re.search(r"cobol|rpg|pl/i|assembler|jcl|ims", (x.get("language") or "").lower())]
    kv(doc.d.tables[11], {
        "Application type": app_type,
        "Build origin": "Custom built (application source code is maintained by the client)",
        "Legacy lineage": (f"{len(cobolish)} of {len(arts)} files are mainframe or midrange languages "
                           f"({', '.join(sorted({x.get('language') for x in cobolish})[:4])})") if cobolish else "No legacy lineage identified",
        "Deployment model": s["deployment"] or doc.unknown("Deployment model and hosting", "3.1", "IT"),
        "Environments": doc.unknown("Environments (production, test, development, disaster recovery)", "3.1", "IT"),
        "Source code location": doc.unknown("Source code repository and version control", "3.1", "IT"),
        "Size indicators": f"{sum(langs.values()):,} lines in {len(arts)} files; " + ", ".join(
            f"{kinds.get(k)} {k.replace('_', ' ')}(s)" for k in ("program", "class", "screen", "table", "job", "data_store") if kinds.get(k))})
    by_layer = {}
    for t in techs:
        by_layer.setdefault(_layer(t), []).append(t)
    stack = {}
    for layer, ts in by_layer.items():
        stack[layer] = ["; ".join(f"{t.get('name')} {t.get('version') or t.get('cycle') or '(version not confirmed)'}".strip() for t in ts),
                        "; ".join(sorted({(t.get("vendor") or _vendor(t)) for t in ts})),
                        "; ".join(sorted({str(t.get("eol") or t.get("support") or "") for t in ts} - {""})) or UNKNOWN,
                        "; ".join(sorted({str(t.get("extended") or "") for t in ts} - {""})) or UNKNOWN,
                        "; ".join(sorted({_status_word(t) for t in ts}))]
    t12 = doc.d.tables[12]
    for row in t12.rows[1:]:
        label = row.cells[0].text.strip()
        vals = stack.get(label) or ["None identified in the source", "", "", "", ""]
        if label in ("Operating system", "Infrastructure", "Web and application server", "Identity and authentication") and label not in stack:
            vals = [doc.unknown(f"{label} and version", "3.2", "IT"), "", "", "", ""]
        for j, val in enumerate(vals, 1):
            set_cell(row.cells[j], val)
    rows(doc.d.tables[13], [[doc.unknown("Licensing and contracts for commercial products", "3.3", "IT"), "", "", "", "", ""]])
    hard = [f for f in findings if f.get("rule") in ("SEC-CRED",)] + [
        {"title": fct["text"]} for c in comps for fct in c["scores"]["coupling"]["factors"] if "hard" in fct["text"].lower()]
    doc.replace("Describe hard-coded business rules", [
        (f"{len(hard)} hard-coded value(s) were found in the source, including: " + "; ".join(h_['title'] for h_ in hard[:4]) + ".")
        if hard else "No hard-coded business rules or rate tables were identified in the source reviewed.",
        "Where routine policy or rate changes require a code change, the item appears in the technical debt register (7.3)."])

    # 4 architecture
    ref = doc.para("Figure 1. Reference architecture layout")
    if ref is not None:
        img = ref._p.getprevious()
        arch = diagrams.get("architecture")
        if arch is not None and img is not None and img.xpath(".//w:drawing"):
            pic = doc.picture(png(arch, scale=1.6), img, 6.9)
            img.getparent().remove(img)
        _set_para(ref, f"Figure 1. Logical architecture of {name}: layers, components and the systems and data it touches.",
                  italic=True)
    doc.replace("The reference layout below shows", "The architecture below is drawn from the confirmed components in "
                "Section 3, in the standard layer order so it can be read alongside other application reports.")
    doc.remove("Each application report should include the following views")
    fill_col(doc.d.tables[14], 2, {"A.": "Complete (Figure 1)", "B.": "Pending: hosting and network detail not available",
                                   "C.": "Complete (Figure 3)" if diagrams.get("context") else "Pending",
                                   "D.": "Complete (Figure 4)" if diagrams.get("data") else "Pending",
                                   "E.": "Pending: requires the portfolio inventory"})
    doc.unknown("Deployment (physical) architecture: servers, environments, network zones", "4.1", "IT")
    ins = doc.para("[Insert diagrams A to E here")
    if ins is not None:
        anchor = ins._p
        for n, key, cap in ((3, "context", "Integration context: the application with every upstream and downstream system and data store"),
                            (4, "data", "Data model: tables, columns and keys used by the application")):
            dg = diagrams.get(key)
            if dg is None:
                continue
            pic = doc.picture(png(dg, scale=1.5), anchor, 6.8)
            capp = doc.new_para(f"Figure {n}. {cap}. Validation with the IT owner: pending.", pic._p, italic=True)
            anchor = capp._p
        ins._p.getparent().remove(ins._p)

    ints = []
    ext = [e for e in store.entities() if e["kind"] in ("external_system", "data_store", "api_endpoint") and e["origin"] != "placeholder"]
    for i, e in enumerate(ext[:25], 1):
        rels = store.relations(to_id=e["id"]) + store.relations(from_id=e["id"])
        kinds_ = {r["kind"] for r in rels}
        direction = "Bidirectional" if {"reads", "writes"} <= kinds_ else "Outbound" if "writes" in kinds_ else "Inbound" if "reads" in kinds_ else UNKNOWN
        method = {"data_store": "File or dataset", "api_endpoint": "API", "external_system": "System call"}[e["kind"]]
        ints.append([f"INT-{num}-{i:02d}", direction, e["name"], (e.get("attrs") or {}).get("record") or UNKNOWN, method,
                     "Fixed width" if e["kind"] == "data_store" and cobolish else UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN, "No"])
    rows(doc.d.tables[15], ints)
    if ints:
        doc.unknown("Frequency, owner and failure handling of each interface in 4.2", "4.2", "IT")
    missing = [m for m in cov.get("missing") or [] if m["category"] == "missing_code"
               and m.get("kind") in ("program", "copybook", "job", "screen", "transaction", "procedure", "module")]
    extern = [m for m in cov.get("missing") or [] if m["category"] == "external"]
    for starts, text in (("Systems this application depends on", "Systems this application depends on: " + (", ".join(m["name"] for m in extern[:8]) or "none identified in the source")),
                         ("Systems that depend on this application", "Systems that depend on this application: " + doc.unknown("Downstream systems", "4.3", "IT")),
                         ("Shared components", "Shared components: " + (", ".join(e["name"] for e in store.entities("table")[:8]) or "none identified")),
                         ("Hidden or informal dependencies", "Hidden or informal dependencies: " + (
                             "programs referenced but not provided: " + ", ".join(m["name"] for m in missing[:8]) if missing else "none identified in the source"))):
        p = doc.para(starts)
        if p is not None:
            _set_para(p, text)
    cpl = R.program_factors(comps, "coupling", 6)
    doc.replace("Record structural concerns", [f"Coupling is rated {R.condition(a['scores']['coupling']['score'])[0]} "
                                                f"({R.condition(a['scores']['coupling']['score'])[1]}): {R.explain_program(a, 'coupling')}"]
                + [f"{_cap(P.what(f['rule'], f['text']))} ({f.get('component', '')}): {f['text']}." for f in cpl[:4]])

    # 5 data
    tables = store.entities("table")
    rows(doc.d.tables[16], [[t_["name"], UNKNOWN, UNKNOWN, UNKNOWN, "Restricted" if pii else "Internal",
                              "Personal data" if pii else "None identified"] for t_ in tables[:30]] +
         [[d_["name"] + " (file)", UNKNOWN, UNKNOWN, UNKNOWN, "Internal", UNKNOWN] for d_ in store.entities("data_store")[:10]])
    doc.unknown("Data volumes, retention requirements and system-of-record status (5.1)", "5.1")
    fill_col(doc.d.tables[17], 1, {"": ["Not rated", "Requires access to production data; not part of this review."]})
    doc.unknown("Data quality ratings (requires production data)", "5.2")
    rpts = [x for x in arts if re.search(r"report|rpt", (x["name"] + " " + (x.get("language") or "")).lower())]
    rows(doc.d.tables[18], [[f"RPT-{num}-{i:02d}", x["name"], UNKNOWN, x.get("language") or UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN,
                              "Retain" ] for i, x in enumerate(rpts[:15], 1)])
    stats = [x for x in arts if re.search(r"spss|sas|excel|access|vba", (x.get("language") or "").lower())]
    doc.replace("Describe analytical and statistical tools", (
        f"Analytical tooling in the source: {', '.join(sorted({x['language'] for x in stats}))}. Users, skills and licensing "
        f"are open items.") if stats else "No analytical or statistical tooling was identified in the source reviewed.")

    # 6 health
    hs, total_txt = _health_total(a)
    t19 = doc.d.tables[19]
    for row in t19.rows[1:]:
        label = row.cells[0].text.strip()
        if label.startswith("Overall"):
            set_cell(row.cells[2], str(hs["overall"][0]) if hs["overall"][0] else "")
            set_cell(row.cells[3], hs["overall"][1])
            set_cell(row.cells[4], total_txt)
            continue
        for key, val in hs.items():
            if key == "overall":
                continue
            score_c, weighted, why = val
            if label.startswith(key):
                set_cell(row.cells[2], str(score_c) if score_c else "Not rated")
                set_cell(row.cells[3], weighted)
                set_cell(row.cells[4], why)
    eol_rows = []
    for t in techs:
        if t.get("status") in (None, "unknown") and not t.get("eol"):
            continue
        path = "Requires rewrite" if t.get("status") == "legacy" else "Yes" if t.get("status") in ("eol", "extended", "ending") else "Not applicable"
        eol_rows.append([t.get("name"), t.get("version") or t.get("cycle") or "Not confirmed", str(t.get("eol") or "") or "Not published",
                         str(t.get("extended") or "") or "Not published", _months_left(t.get("eol"), today) or "",
                         path, (t.get("note") or t.get("basis") or "")[:90]])
    rows(doc.d.tables[20], eol_rows)

    # 7 technical debt
    debt_f = R.program_factors(comps, "tech_debt", 40)
    cats = {"DEBT-GOTO": "Code", "DEBT-LEGACY": "Code", "DEBT-LONG": "Code", "DEBT-PRESTD": "Code", "DEBT-SIZE": "Architecture",
            "DEBT-TRANSLATED": "Code"}
    dom = sorted({cats.get(f["rule"], "Code") for f in debt_f}) or ["None"]
    refactor = [i for p in a["roadmap"]["phases"] for i in p["items"] if i.get("kind") in ("debt", "refactor") or "refactor" in i["title"].lower()]
    kv(doc.d.tables[21], {"Overall technical debt level": f"{debt_level}. {R.explain_program(a, 'tech_debt')}",
                          "Dominant debt categories": ", ".join(dom),
                          "Estimated total remediation effort": (f"{sum(i['low'] for i in refactor):g}–{sum(i['high'] for i in refactor):g} person-weeks"
                                                                 if refactor else f"Included in the roadmap total of {total['low']}–{total['high']} person-weeks"),
                          "Effect on delivery": (f"{_cap(P.what(debt_f[0]['rule'], debt_f[0]['text']))} "
                                                 f"({debt_f[0].get('component', '')}): {P.why(debt_f[0]['rule']) or 'change is slower and riskier'}.")
                                                if debt_f else "No material effect identified.",
                          "Trend": "Not measurable from a single point-in-time review"})
    doc.replace("Where source code is available, run static analysis", "Indicators below are measured from the source "
                "code provided for this review; indicators that need a running build or test suite are marked not measured.")
    doc.replace("A single interview will often cover several applications", "No stakeholder interviews were held as part "
                "of this review; findings rest on the source code, screens and configuration listed in 13.2.")
    metrics = _metrics(arts)
    fill_col(doc.d.tables[22], 1, {
        "Lines of code": [", ".join(f"{k}: {v:,}" for k, v in sorted(langs.items(), key=lambda kv_: -kv_[1])), "Not applicable", "Source code review", ""],
        "Average and maximum cyclomatic complexity": [f"average {metrics['avg']}, maximum {metrics['max']} ({metrics['max_file']})",
                                                      "Under 15 per routine", "Decision-point count per file", _cmp(metrics["max"], 15)],
        "Code duplication": ["Not measured", "Under 5%", "", "Not assessed in this review"],
        "Maintainability rating": [f"{R.condition(debt)[0]} ({R.condition(debt)[1]})", "2 (Good) or better", "Technical debt score",
                                   f"{debt}/100; deductions in 7.1"],
        "Automated test coverage": ["0% (no automated tests found in the source)" if not metrics["tests"] else f"{metrics['tests']} test file(s)",
                                    "60% or higher", "Source code review", "No test suite provided" if not metrics["tests"] else ""],
        "Outdated third-party dependencies": [str(sum(1 for t in techs if t.get("status") in ("eol", "legacy"))), "0", "Version and support-date review", ""],
        "Dead or unused code": ["Not measured", "", "", "Not assessed in this review"],
        "Share of machine-translated": [f"{metrics['translated']}%", "Not applicable", "Source code review", ""],
        "Hard-coded values": [str(len(hard)), "0", "Source code review", "; ".join(h_["title"] for h_ in hard[:2])],
    })
    reg = []
    for i, f in enumerate(debt_f[:25], 1):
        reg.append([f"TD-{num}-{i:02d}", f"{_cap(P.what(f['rule'], f['text']))}: {f['text']} ({f.get('component', '')})",
                    cats.get(f["rule"], "Code"),
                    {"DEBT-GOTO": "Unstructured legacy style", "DEBT-LEGACY": "Library or construct not upgraded",
                     "DEBT-LONG": "Routines grown over time", "DEBT-SIZE": "Monolithic file", "DEBT-TRANSLATED": "Automated language conversion",
                     "DEBT-PRESTD": "Pre-standard language usage"}.get(f["rule"], "Legacy construct"),
                    _cap(P.why(f["rule"]) or "makes change slower") + f" (−{abs(f['points']):g} maintainability points)", {"DEBT-LEGACY": "Upgrade or replace", "DEBT-GOTO": "Refactor",
                                                                                   "DEBT-TRANSLATED": "Refactor", "DEBT-SIZE": "Refactor"}.get(f["rule"], "Refactor"),
                    "S" if abs(f["points"]) < 5 else "M" if abs(f["points"]) < 12 else "L",
                    "High" if abs(f["points"]) >= 12 else "Medium" if abs(f["points"]) >= 5 else "Low"])
    rows(doc.d.tables[23], reg)
    skills = [fct["text"] for c in comps for fct in c["scores"]["supportability"]["factors"] if fct["rule"] == "SUP-SKILLS"]
    doc.replace("Describe debt that sits outside the code itself", [
        (f"Skills: few people still have {P.sentence(sorted({x.split(' skills are scarce')[0] for x in skills}))} skills, so "
         f"support depends on a small, shrinking pool of in-house staff or vendors.") if skills
        else "No platform or skills debt was identified from the technologies in use.",
        "Release automation, environment parity and batch dependency documentation could not be assessed and are open items."])
    doc.unknown("Release, deployment and environment practices", "7.4", "IT")
    skill_names = P.sentence(sorted({x.split(" skills are scarce")[0] for x in skills})) if skills else ""
    stab = [i["title"] for i in (phases.get("stabilize") or {}).get("items", [])]
    mod = [i["title"] for i in (phases.get("modernize") or {}).get("items", [])]
    doc.replace("Separate remediation that can be addressed independently", [
        "Quick wins to reduce risk now, independent of modernization: " + ("; ".join(stab[:6]) or "none") + ".",
        (f"Debt best retired through the recommended disposition ({disposition}, Section 12) rather than fixed now: "
         + "; ".join(mod[:6]) + ".") if mod else
        f"Because the recommended disposition ({disposition}) keeps the current code, every item in 7.3 can be fixed directly."])

    # 8 security
    t24 = doc.d.tables[24]
    for row in t24.rows[1:]:
        label = row.cells[0].text.strip()
        area = next((ar for ar in CONTROL_AREAS if label.startswith(ar[0])), None)
        if area is None:
            continue
        fs = [f for f in sec_f if any((f.get("rule") or "").startswith(k) for k in area[1])]
        if fs:
            r_ = _sev_rating(fs)
            kinds = []
            for f in sorted(fs, key=lambda f: SEV.index(f["severity"])):
                w = P.what(f.get("rule") or "", f["title"])
                if w not in kinds:
                    kinds.append(w)
            whys = []
            for f in fs:
                w = P.why(f.get("rule") or "")
                if w and w not in whys:
                    whys.append(w)
            set_cell(row.cells[1], f"{len(fs)} issue(s): " + _cap(P.sentence(kinds[:3])) + ".")
            set_cell(row.cells[2], (_cap(P.sentence(whys[:2])) + ".") if whys else "See 8.3")
            set_cell(row.cells[3], f"{r_} – {P.LEVEL[r_]}: the most serious issue here is "
                                   f"{min((f['severity'] for f in fs), key=SEV.index)}")
        elif area[0] in CHECKABLE:
            set_cell(row.cells[1], "No issues found in the source reviewed")
            set_cell(row.cells[2], "None identified")
            set_cell(row.cells[3], "2 – Good: nothing found in the code; not yet confirmed on the running system")
        else:
            set_cell(row.cells[1], doc.unknown(f"Security control: {area[0].lower()}", "8.1", "Information security"))
            set_cell(row.cells[2], "Not assessed")
            set_cell(row.cells[3], "Not rated: this can't be seen in the code")
    code_f = [f for f in sec_f if f["category"] in ("security", "privacy", "ui_security")]
    sca = [f for f in sec_f if f["category"] == "vulnerability"]
    web = [f for f in sec_f if f["category"] == "website"]
    cnt = lambda fs: [str(sum(1 for f in fs if f["severity"] == k)) for k in ("critical", "high", "medium", "low")]
    site = store.get_meta("site_scan") or {}
    fill_col(doc.d.tables[25], 1, {
        "Infrastructure and OS": ["Not performed", "", "Not in scope", "", "", "", ""],
        "Web application": (["Public website review", (site.get("scanned") or "")[:10], site.get("final_url") or site.get("start") or ""] + cnt(web))
        if site else ["Not performed", "", "Not in scope", "", "", "", ""],
        "Static code analysis": ["Source code review", today.isoformat(), f"{len(arts)} files"] + cnt(code_f),
        "Software composition": ["Version and CVE review", today.isoformat(), f"{len(techs)} components"] + cnt(sca),
        "Database configuration": ["Not performed", "", "Not in scope", "", "", "", ""],
        "Penetration test": ["Not performed", "", "Not in scope", "", "", "", ""],
    })
    vr, vgroups = [], {}
    for i, f in enumerate(sorted(sec_f, key=lambda f: (SEV.index(f["severity"]), f["title"]))[:40], 1):
        refs = f.get("refs") or {}
        ev = (f.get("evidence") or [{}])[0] if f.get("evidence") else {}
        days = {"critical": 30, "high": 90, "medium": 180}.get(f["severity"], 365)
        restricted = f.get("rule") in ("SEC-CRED",)
        loc = f"{ev.get('file') or f['title'].split(':')[0]}" + (f":{ev['line']}" if ev.get("line") else "")
        vgroups.setdefault(f.get("rule") or f["title"], {"f": f, "ids": []})["ids"].append(f"VUL-{num}-{i:02d}")
        vr.append([f"VUL-{num}-{i:02d}", loc,
                   ", ".join(x for x in (refs.get("cve"), refs.get("cwe")) if x) or "",
                   str(refs.get("cvss") or "Not scored"), f["severity"].title(),
                   "Internet facing" if f["category"] in ("website", "ui_security") else UNKNOWN,
                   "Y" if refs.get("cve") else "N",
                   _cap(P.fix(f.get("rule") or "") or (f.get("detail") or "").split(". ")[-1][:140])
                   if not restricted else "Change the password and move it to a secrets store",
                   "IT", (today + timedelta(days=days)).isoformat(), "Open", "Appendix D" if restricted else ""])
    rows(doc.d.tables[26], vr)
    anchor = doc.new_para("What these findings mean, in plain terms:", doc.d.tables[26]._tbl)._p
    for g in vgroups.values():
        f, ids = g["f"], g["ids"]
        rule = f.get("rule") or ""
        idtxt = ids[0] if len(ids) == 1 else f"{ids[0]} to {ids[-1]}" if len(ids) > 2 else " and ".join(ids)
        txt = f"{idtxt}: {P.what(rule, f['title'])}."
        if P.why(rule):
            txt += f" Why it matters: {P.why(rule)}."
        if P.fix(rule):
            txt += f" Fix: {P.fix(rule)}."
        anchor = doc.new_para(txt, anchor, bullet=True)._p
    unsup = [t for t in techs if t.get("status") in ("eol", "legacy")]
    doc.replace("List components that can no longer receive security patches", [
        (f"{t.get('name')} {t.get('version') or t.get('cycle') or ''}".strip() + f": {_status_word(t).lower()}"
         + (f" since {t['eol']}" if t.get("eol") else "") + ". Compensating controls: unknown (open item).") for t in unsup]
        or ["No unsupported components were identified."])
    if unsup:
        doc.unknown("Compensating controls for unsupported components", "8.4", "Information security")
    fill_col(doc.d.tables[27], 1, {
        "Client information security policy": ["Y", "Not assessed", doc.unknown("Client security policy and standards", "8.5", "Information security")],
        "Security framework": ["Y", "Partial" if code_f else "Not assessed",
                               f"{s['security_framework'] or 'NIST SP 800-53'} controls referenced by the findings in 8.3"],
        "Data privacy obligations": (["Y", "Partial", f"{s['privacy_obligations'] or 'Applicable privacy law'}: personal data is handled; see 8.3"]
                                     if pii else ["N", "Not applicable", "No personal data identified in the source"]),
        "Payment card data": ["N" if not re.search(r"card|pan\b", " ".join(f["title"].lower() for f in findings)) else "Y", "Not assessed", ""],
        "Records retention schedule": [UNKNOWN, "Not assessed", ""],
        "Open internal or external audit findings": [UNKNOWN, "Not assessed", ""],
    })

    # 9 risk
    rows(doc.d.tables[28], [[r_["id"], r_["short"], r_["cat"], str(r_["L"]), str(r_["I"]), str(r_["score"]),
                             R.template_rating(r_["score"]), UNKNOWN, r_["mit"]] for r_ in risks])
    anchor = doc.new_para("Why each risk is rated as it is:", doc.d.tables[28]._tbl)._p
    for r_ in risks:
        anchor = doc.new_para(f"{r_['id']} ({r_['c']['name']}): {R.risk_reason(r_['c'])}", anchor, bullet=True)._p
    t29 = doc.d.tables[29]
    for row in t29.rows[1:]:
        lab = row.cells[0].text
        vals = {"Complete outage": [s["business_value"] or UNKNOWN, UNKNOWN, UNKNOWN, "Delayed service; see the business calendar (2.4)"],
                "Processing or calculation error": [f"{len(arts)} files of business logic", "Not applicable",
                                                     "None identified in the source", "Incorrect outputs and recovery effort"],
                "Security breach": ["Personal data" if pii else "Application data", "Not applicable", UNKNOWN,
                                    "Notification obligations and legal exposure" if pii else "Reputational harm"],
                "Loss of key technical staff": [f"Maintenance of the {skill_names} code" if skills else "Application maintenance", "Not applicable",
                                                UNKNOWN, "Inability to maintain or change the application"]}
        hit = next((v_ for k, v_ in vals.items() if lab.startswith(k)), None)
        if hit:
            for j, val in enumerate(hit, 1):
                set_cell(row.cells[j], val)
    doc.unknown("Maximum tolerable outage and current workarounds (9.2)", "9.2")
    t30 = doc.d.tables[30]
    for ri, row in enumerate(t30.rows[:5]):
        imp = 5 - ri
        for li in range(1, 6):
            ids = [r_["id"] for r_ in risks if r_["L"] == li and r_["I"] == imp]
            set_cell(row.cells[li], f"{li * imp}" + (f" / {', '.join(ids)}" if ids else ""))
    heat = doc.para("Plot each risk from 9.1")
    if heat is not None:
        _set_para(heat, "Each risk from 9.1 is placed on the 5 by 5 grid below (likelihood across, impact up). "
                        + (f"The application's heat-map position is set by its highest risk, {top['id']} at {top['score']}." if top else ""))

    # 10 operational support
    kv(doc.d.tables[31], {k: doc.unknown(k, "10.1", "IT") for k in (
        "Support team and named contacts", "Number of staff able to support", "Vendor support arrangement",
        "Service level or availability target", "Change and release process", "Monitoring and alerting")})
    fill_col(doc.d.tables[32], 1, {"": [UNKNOWN, "Service management records not provided"]})
    doc.unknown("Support demand for the trailing 24 months (10.2)", "10.2", "IT")
    rows(doc.d.tables[33], [[f"Change to hard-coded value: {h_['title'][:60]}", UNKNOWN, "Value held in source code",
                             "Move to a business-maintained table", "Configuration screen and change controls"] for h_ in hard[:4]],
         empty="No recurring IT activity could be identified from the source; to be confirmed with the support team.")
    doc.replace("Identify any individual whose departure", (
        f"Few people still have {skill_names} skills, so the application depends on a small, shrinking pool of staff "
        f"or vendors. The names of the people who can maintain it today are an open item.")
        if skills else "No scarce-skill dependency was identified from the technologies in use; named individuals are an open item.")
    doc.unknown("Individuals holding key knowledge of the application", "10.4", "IT")

    # 11 user experience
    ux = a["scores"].get("ux") or {}
    uxf = R.program_factors(comps, "ux", 30)
    def ux_row(keys, label_note):
        fs = [f for f in uxf if any(k in (f["rule"] or "") for k in keys)]
        if not fs:
            return ["Not rated", f"No evidence in the material reviewed ({label_note})"]
        pts = sum(f["points"] for f in fs)
        c_ = R.condition(max(0, 100 + pts))
        from .plain import reasons, sentence
        return [str(c_[0]), _cap(f"{c_[1]}: {sentence(reasons(fs, 2))}.")]
    fill_col(doc.d.tables[34], 1, {
        "Ease of navigation": ux_row(("UIB-", "UIF-", "USE-"), "navigation"),
        "Clarity of error messages": ux_row(("UIB-CRASH", "UIB-ERR", "USE-ERR"), "error handling"),
        "Efficiency for high-volume": ["Not rated", "Requires observation of users at work"],
        "Consistency with other client applications": ["Not rated", "Requires the portfolio inventory"],
        "Mobile and browser compatibility": ux_row(("UIB-OBSOLETE", "ACC-TEXTSIZE", "ACC-TERMINAL"), "browser support"),
        "Availability of help": ["Not rated", "Not visible in the source"],
        "User satisfaction": ["Not rated", "Stakeholder interviews not held"],
    })
    acc = [f for f in uxf if (f["rule"] or "").startswith("ACC")]
    doc.replace("Record redesign opportunities in order of user benefit", [
        f"User experience and accessibility are rated {R.condition(ux.get('score'))[0]} ({R.condition(ux.get('score'))[1]}): "
        f"{R.explain_program(a, 'ux')}"] + ([f"Accessibility (measured against WCAG 2.1 AA, the usual legal standard): "
                                   f"{P.sentence(P.reasons(acc, 4))}."] if acc else []))

    # 12 options
    rec_code = v.get("code")
    applicable = {"Retain": "Yes" if rec_code == "retain" else "No: " + ("unsupported components must be addressed" if eol else "security findings must be addressed"),
                  "Re-host": "Yes" if rec_code == "rehost" else "No: moving infrastructure alone does not close the findings in Section 8",
                  "Re-platform": "Yes: recommended" if rec_code == "replatform" else "Possible" if eol else "No",
                  "Refactor": "Yes: recommended" if rec_code in ("refactor", "rearchitect") else "Partly: for the debt items in 7.3",
                  "Replace": "Yes: recommended" if rec_code == "replace" else "Not assessed: requires a market review",
                  "Consolidate": s["related_apps"] and f"Candidates: {s['related_apps']}" or "Not assessed: requires the portfolio inventory",
                  "Retire": "Yes: recommended" if rec_code == "retire" else "No: the function is still in use"}
    fill_col(doc.d.tables[35], 2, applicable)
    options = _options(rec_code)
    t36 = doc.d.tables[36]
    set_cell(t36.rows[0].cells[2], f"Option A: {options[0][0]}")
    set_cell(t36.rows[0].cells[3], f"Option B: {options[1][0]}")
    set_cell(t36.rows[0].cells[4], f"Option C: {options[2][0]}")
    crit_keys = ["Risk reduction", "Business value", "Technical debt retired", "Implementation complexity", "Reduction in IT dependency",
                 "Alignment with client enterprise", "Alignment with industry"]
    weights = [25, 20, 15, 15, 10, 10, 5]
    totals = [0.0, 0.0, 0.0]
    for row in t36.rows[1:]:
        lab = row.cells[0].text
        k = next((i for i, ck in enumerate(crit_keys) if lab.startswith(ck)), None)
        if k is None:
            if lab.lower().startswith("weighted") or lab.lower().startswith("total"):
                for j in range(3):
                    set_cell(row.cells[2 + j], f"{totals[j]:.2f}")
            continue
        for j in range(3):
            sc = options[j][1][k]
            totals[j] += sc * weights[k] / 100
            set_cell(row.cells[2 + j], str(sc))
    score_note = doc.para("Score each shortlisted option")
    if score_note is not None:
        _set_para(score_note, "Each shortlisted option is scored from 1 (poor) to 5 (strong). Weighted totals: "
                  + ", ".join(f"{o[0]} {t_:.2f}" for o, t_ in zip(options, totals)) + ". Rationale:")
        last = score_note._p
        for o in options:
            last = doc.new_para(f"{o[0]}: {o[2]}", last, bullet=True)._p
    kv(doc.d.tables[37], {"Recommended disposition": disposition,
                          "Rationale": " ".join((v.get("reasons") or [])[:3]) or v.get("meaning", ""),
                          "Consolidation grouping": s["related_apps"] or "None identified",
                          "Prerequisites": "; ".join(i["title"] for i in (phases.get("assess") or {}).get("items", [])) or "None",
                          "Key risks of the recommended option": "Regression in business calculations during change; mitigated by "
                                                                 "parallel runs against current outputs",
                          "Interim risk mitigation": "; ".join(stab[:4]) or "None required"})
    kv(doc.d.tables[38], {"Recommended horizon": horizon,
                          "Proposed start window": doc.unknown("Proposed start window (fiscal year and quarter)", "12.4"),
                          "Estimated duration": f"{total['months_one_dev'][0]}–{total['months_one_dev'][1]} months for one developer "
                                                f"({total['low']}–{total['high']} person-weeks)",
                          "Predecessor initiatives": "; ".join(i["title"] for i in (phases.get("assess") or {}).get("items", [])) or "None",
                          "Successor initiatives": "; ".join(mod[:3]) or "None identified",
                          "Business blackout periods": doc.unknown("Business blackout periods", "12.4")})

    # 13 evidence
    rows(doc.d.tables[39], [["None", "", "", "", "Stakeholder interviews were not part of this review", ""]])
    doc.unknown("Stakeholder interviews", "13.1", "Assessment lead")
    ev = []
    for i, x in enumerate(arts, 1):
        typ = {"code": "Source code", "ui_screen": "Application screen", "schema": "Database schema", "config": "Configuration",
               "document": "Document"}.get(x.get("artifact_type"), "Source code")
        ev.append([f"EV-{num}-{i:02d}", x["name"], typ, f"v{x.get('version', 1)}, {(x.get('updated') or x.get('created') or '')[:10]}",
                   f"Program source set: {x['name']}"])
    rows(doc.d.tables[40], ev)
    assumptions = ["Findings reflect the source files listed in 13.2; components not provided are listed in 4.3 and are not scored.",
                   "Business impact defaults to a moderate rating where the business owner has not rated criticality (Section 9).",
                   "Support dates are from published vendor lifecycle information current at the report date."]
    if a["confidence"]["level"] != "high":
        assumptions.append(f"Assessment confidence is {a['confidence']['level']}: " + "; ".join(a["confidence"]["notes"][:3]) + ".")
    constraints = ["No access to production systems, data, service management records or stakeholders was part of this review."]
    p1 = doc.para("[Assumption made in the absence")
    if p1 is not None:
        _set_para(p1, assumptions[0])
        last = p1._p
        for t_ in assumptions[1:]:
            last = doc.new_para(t_, last, bullet=True)._p
    p2 = doc.para("[Constraint on the assessment")
    if p2 is not None:
        _set_para(p2, constraints[0])
    for m in missing[:15]:
        doc.open_items.append((f"Provide the source of {m['kind']} {m['name']} (referenced but not provided)", "4.3", "IT"))
    due = (today + timedelta(days=30)).isoformat()
    rows(doc.d.tables[41], [[f"OI-{num}-{i:02d}", f"{what} (Section {sec_})", owner, due, "Open"]
                            for i, (what, sec_, owner) in enumerate(_dedup(doc.open_items), 1)])
    t42 = doc.d.tables[42]
    for row in t42.rows[1:]:
        lab = row.cells[0].text
        if lab.startswith("Assessment lead"):
            vals = [s["prepared_by"], s["firm"], "Submitted", today.isoformat()]
        else:
            who = {"Business owner": s["business_owner"], "IT application": s["it_reviewer"],
                   "Information security": "", "Client project manager": ""}
            nm = next((v_ for k, v_ in who.items() if lab.startswith(k)), "")
            vals = [nm or "", s["client"] or "", "", ""]
        for j, val in enumerate(vals, 1):
            set_cell(row.cells[j], val)
    for starts, text in (("Appendix A:", "Appendix A: Architecture diagrams in editable Visio (.vsdx) and draw.io formats, supplied with this report"),
                         ("Appendix B:", "Appendix B: Technology and component inventory (Sections 3.2 and 6.2)"),
                         ("Appendix C:", "Appendix C: Technical debt detail (Section 7.3)"),
                         ("Appendix D:", "Appendix D: Restricted security findings, supplied separately to named security staff"),
                         ("Appendix E:", "Appendix E: Screen flow (Figure 2)"),
                         ("Appendix F:", "Appendix F: Report catalog (Section 5.3)"),
                         ("Appendix G:", "Appendix G: Glossary of technical terms (below)")):
        p = doc.para(starts)
        if p is not None:
            _set_para(p, text)
    _glossary(doc)
    _header_footer(doc, name)
    cp = doc.d.core_properties
    cp.author = cp.last_modified_by = s["prepared_by"]
    cp.title = f"{name} — Application Assessment Report"
    cp.subject = f"Prepared for {s['client']}" if s["client"] else "Application Assessment Report"
    cp.comments = cp.keywords = cp.category = ""
    _no_placeholders(doc)
    from .wording import clean
    for t_ in doc.body.iter(qn("w:t")):
        if t_.text:
            t_.text = clean(t_.text)
    buf = io.BytesIO()
    doc.d.save(buf)
    return buf.getvalue()


# ── helpers for the build ───────────────────────────────────────────────────────────────────────────────────────

def _cap(t):
    return t[:1].upper() + t[1:] if t else t


LEVEL_WORD = {1: "excellent", 2: "good", 3: "fair", 4: "poor", 5: "critical"}


def _eol_plain(t):
    nm = f"{t.get('name')} {t.get('version') or t.get('cycle') or ''}".strip()
    return {"eol": f"{nm} is past the vendor's end of support" + (f" (since {t['eol']})" if t.get("eol") else ""),
            "legacy": f"{nm} is no longer developed and has no supported upgrade path",
            "extended": f"{nm} is on paid extended support only",
            "ending": f"{nm} loses vendor support within 12 months" + (f" ({t['eol']})" if t.get("eol") else "")}.get(
        t.get("status"), f"{nm} has an unconfirmed support status")


def _health_line(a):
    hs, _ = _health_total(a)
    c = hs["overall"][0]
    rated = sum(1 for k, v in hs.items() if k != "overall" and v[0])
    if not c:
        return "Not rated"
    return (f"{c} – {LEVEL_WORD[c].title()} (1 is best, 5 is worst). This is the weighted average of the health scorecard "
            f"in Section 6.1, where {rated} of the 7 areas could be rated from the evidence.")


def _disp_plain(v):
    from .plain import DISPOSITIONS
    return DISPOSITIONS.get(v.get("code"), v.get("meaning", ""))


def _has_col(store, table, col):
    try:
        return any(r["name"] == col for r in store._all(f"PRAGMA table_info({table})"))
    except Exception:  # noqa: BLE001
        return False


def _dedup(items):
    seen, out = set(), []
    for it in items:
        if it[0] not in seen:
            seen.add(it[0])
            out.append(it)
    return out


def _vendor(t):
    n = (t.get("name") or "").lower()
    for k, v in (("ibm", "IBM"), ("cobol", "IBM / Micro Focus"), ("rpg", "IBM"), ("ims", "IBM"), ("db2", "IBM"), ("cics", "IBM"),
                 ("jquery", "OpenJS Foundation"), (".net", "Microsoft"), ("asp", "Microsoft"), ("visual basic", "Microsoft"),
                 ("sql server", "Microsoft"), ("windows", "Microsoft"), ("oracle", "Oracle"), ("java", "Oracle"),
                 ("delphi", "Embarcadero"), ("html", "W3C standard")):
        if k in n:
            return v
    return UNKNOWN


def _cmp(v, limit):
    return "Within threshold" if v <= limit else "Above threshold"


def _metrics(arts):
    from core.assess.scores import text_metrics
    per = []
    tests = 0
    translated = 0
    total = 0
    for x in arts:
        text = x.get("transcription") or ""
        if re.search(r"test", x["name"], re.I):
            tests += 1
        try:
            m = text_metrics(text, x["name"], x.get("language") or "")
        except Exception:  # noqa: BLE001
            continue
        n = m.get("lines") or len(text.splitlines())
        total += n
        if m.get("translated"):
            translated += n
        per.append((m.get("decisions", 0) + 1, x["name"]))
    if not per:
        return {"avg": 0, "max": 0, "max_file": "", "tests": tests, "translated": 0}
    mx = max(per)
    return {"avg": round(sum(p for p, _ in per) / len(per), 1), "max": mx[0], "max_file": mx[1], "tests": tests,
            "translated": round(100 * translated / total) if total else 0}


def _health_total(a):
    """Map the program scores onto the template's seven health dimensions, each with its reason."""
    S = a["scores"]
    dims = {"Technology currency": (20, ["supportability"]), "Code quality": (15, ["tech_debt", "complexity"]),
            "Stability and reliability": (15, ["health"]), "Performance and scalability": (10, []),
            "Security posture": (15, ["security"]), "Documentation and knowledge": (10, []),
            "Business fit and adaptability": (15, ["coupling"])}
    out, wsum, acc = {}, 0, 0.0
    for key, (w, src) in dims.items():
        vals = [S[d]["score"] for d in src if (S.get(d) or {}).get("score") is not None]
        if not vals:
            out[key] = (None, "Excluded", "Not rated: no evidence for this dimension in the material reviewed (open item).")
            continue
        score = round(sum(vals) / len(vals))
        c, label = R.condition(score)
        why = " ".join(R.explain_program(a, d, 2).split(". ", 1)[1] for d in src)
        out[key] = (c, f"{c * w / 100:.2f}", why)
        wsum += w
        acc += c * w
    overall = round(acc / wsum, 1) if wsum else None
    label = R.CONDITION[min(4, max(0, round(overall) - 1))][2] if overall else "Not rated"
    out["overall"] = (round(overall) if overall else None, f"{overall}" if overall else "")
    rated = len([k for k in out if k != "overall" and out[k][0]])
    txt = (f"{overall} – {label}. The weighted average of the {rated} areas that could be rated; the weights of the "
           f"{7 - rated} unrated areas are left out, so the total is taken over {wsum}%.") if overall else "Not rated"
    return out, txt


def _options(code):
    """Three shortlisted options scored against the template criteria (risk, value, debt, complexity, IT dependency,
    architecture fit, peer practice), each with its reason."""
    lib = {
        "replatform": ("Re-platform", [4, 3, 3, 3, 3, 4, 4], "closes end-of-life and known-vulnerability exposure with targeted code "
                       "change; keeps proven business logic, so value and debt retired are moderate."),
        "refactor": ("Refactor", [4, 3, 4, 3, 3, 4, 4], "fixes security findings and restructures the worst code on the current "
                     "platform; retires the most debt short of a rebuild, with moderate disruption."),
        "rearchitect": ("Re-architect", [5, 4, 5, 1, 4, 5, 4], "removes platform and debt risk entirely but is the most complex "
                        "and disruptive option."),
        "rehost": ("Re-host", [2, 2, 1, 4, 2, 3, 3], "moves infrastructure with little code change; low disruption but leaves code "
                   "findings and debt in place."),
        "replace": ("Replace", [5, 4, 5, 2, 4, 4, 4], "retires the custom code; high risk reduction but depends on a market fit "
                    "and data migration."),
        "retain": ("Retain", [1, 2, 1, 5, 1, 2, 2], "no disruption, but every finding and end-of-life exposure remains open."),
        "retire": ("Retire", [5, 1, 5, 3, 5, 3, 3], "removes all risk if the function is no longer needed."),
    }
    first = code if code in lib else "refactor"
    alt = {"replatform": "refactor", "refactor": "replatform", "rearchitect": "replace", "replace": "rearchitect",
           "rehost": "replatform", "retain": "refactor", "retire": "retain"}[first]
    third = "retain" if "retain" not in (first, alt) else "rehost"
    return [lib[first], lib[alt], lib[third]]


def _glossary(doc):
    """Appendix G: every technical term the report uses, explained in one line."""
    from .plain import glossary
    anchor = doc.para("Appendix G:")
    h2 = next((p for p in doc.d.paragraphs if p.style is not None and p.style.name == "Heading 2"), None)
    if anchor is None or h2 is None:
        return
    text = "\n".join(p.text for p in doc.d.paragraphs) + "\n".join(c.text for t in doc.d.tables for r in t.rows for c in r.cells)
    terms = glossary(text)
    if not terms:
        return
    from docx.text.paragraph import Paragraph
    head = deepcopy(h2._p)
    anchor._p.addnext(head)
    _set_para(Paragraph(head, doc.d), "Appendix G. Glossary")
    tbl = deepcopy(doc.d.tables[7]._tbl)
    head.addnext(tbl)
    from docx.table import Table
    t = Table(tbl, doc.d)
    set_cell(t.rows[0].cells[0], "Term")
    set_cell(t.rows[0].cells[1], "Meaning")
    rows(t, [[a, b] for a, b in terms])


def _fill_toc(doc):
    """Put the section list into the contents field so it reads correctly before Word refreshes page numbers."""
    fld = doc.body.xpath(".//w:instrText[contains(., 'TOC')]")
    if not fld:
        return
    first_p = fld[0].getparent().getparent()
    heads = [p for p in doc.d.paragraphs if p.style is not None and p.style.name in ("Heading 1", "Heading 2")
             and p.text.strip() and not p.text.startswith("How to use")]
    anchor = first_p
    for h in heads:
        el = deepcopy(doc.proto)
        from docx.text.paragraph import Paragraph
        p = Paragraph(el, doc.d)
        _set_para(p, ("    " if h.style.name == "Heading 2" else "") + h.text.strip())
        p.paragraph_format.keep_with_next = False
        p.paragraph_format.space_after = 0
        anchor.addnext(el)
        anchor = el


def _header_footer(doc, name):
    for sec in doc.d.sections:
        for part in (sec.header, sec.first_page_header, sec.even_page_header):
            for p in part.paragraphs:
                for r in p.runs:
                    if "[Application Name]" in r.text:
                        r.text = r.text.replace("[Application Name]", name)


def _no_placeholders(doc):
    """Anything still in [brackets] is a template placeholder nobody filled: say Unknown instead."""
    rx = re.compile(r"\[[A-Z][^\]]{1,80}\]")
    for p in doc.body.iter(qn("w:t")):
        if p.text and rx.search(p.text) and "CUT OFF" not in p.text:
            p.text = rx.sub(UNKNOWN, p.text)
