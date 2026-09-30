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
        self.h2_proto = next((deepcopy(p._p) for p in self.d.paragraphs
                              if p.style is not None and p.style.name == "Heading 2"), None)

    def h2_before(self, starts, title):
        """A new Heading 2 placed just before the paragraph that starts with `starts` (normally the next section)."""
        from docx.text.paragraph import Paragraph
        p = self.para(starts)
        el = deepcopy(self.h2_proto)
        p._p.addprevious(el)
        _set_para(Paragraph(el, self.d), title)
        return el

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

    def new_para(self, text, after_el, bullet=False, italic=False, bold=None):
        el = deepcopy(self.bullet_proto if bullet and self.bullet_proto is not None else self.proto)
        after_el.addnext(el)
        from docx.text.paragraph import Paragraph
        p = Paragraph(el, self.d)
        _set_para(p, text, italic=italic, bold=bold)
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
    if t.get("status") in ("supported", "ending", None, "unknown") and not (t.get("version") or t.get("confidence") == "confirmed"):
        return "To confirm (version not confirmed)"
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
    R.WORDS = True
    try:
        return _render(store, report, diagrams, today)
    finally:
        R.WORDS = False


def _render(store, report: dict, diagrams: dict, today=None) -> bytes:
    from core.diagrams.render import png
    from . import ratings as RT
    from core.security.scan import technologies
    today = today or date.today()
    s = get_settings(store)
    a = report["assessment"]
    num = app_number(s)
    app_id = s["app_id"] or f"APP-{num}"
    name = report["program"]
    doc = Doc()
    T = list(doc.d.tables)      # the template's tables, fixed before any new table is inserted
    comps = a["components"]
    findings = [f for f in store.findings() if f.get("status") not in ("dismissed", "fixed")]
    sec_f = [f for f in findings if f["category"] in ("security", "vulnerability", "ui_security", "website", "privacy")]
    arts = store.artifacts()
    cov = store.coverage()
    from .redact import Redactor
    RD = Redactor(s, [x["name"] for x in arts] + [e["name"] for e in store.entities("screen")])
    diagrams = {k: RD.map(d_) for k, d_ in diagrams.items()}
    yes = lambda v_: str(v_ or "").strip().lower() in ("yes", "y", "true", "1")
    final = yes(s["signed_off"]) and all(s[k] for k in ("technical_reviewer", "business_owner", "it_reviewer"))
    ver = re.sub(r"(?i)\s*\bfinal\b", "", s["version"] or "v1.0").strip() or "v1.0"
    version_txt = f"{ver} Final" if final else ("v0.9 Draft for review" if ver.lower() in ("v1.0", "1.0") else f"{ver} Draft for review")
    techs, seen = [], set()
    for t in technologies(store, today):
        k = (t.get("name"), t.get("cycle") or t.get("label"))
        if k not in seen:
            seen.add(k)
            techs.append(t)
    sessions = store._all("SELECT MIN(started) AS a FROM capture_session") if _has_col(store, "capture_session", "started") else []
    start = (sessions[0]["a"] if sessions and sessions[0]["a"] else store.info.get("created") or "")[:10]
    period = f"{start or UNKNOWN} to {today.isoformat()}"
    from . import architecture as A_
    AM = A_.build(store, a, techs)
    pii = any(f["category"] == "privacy" or f.get("rule") == "SEC-PII" for f in findings) or any(c.get("student_data") for c in comps)
    v = a.get("verdict") or {}
    overall = (a["scores"].get("overall") or {}).get("score")
    ov_c, ov_l = R.condition(overall)
    debt = (a["scores"].get("tech_debt") or {}).get("score")
    debt_w = ((a["scores"].get("tech_debt") or {}).get("worst") or {}).get("score", debt)
    debt_level = "Low" if (debt_w or 0) >= 75 else "Medium" if (debt_w or 0) >= 55 else "High"
    crit_high = sum(1 for f in sec_f if f["severity"] in ("critical", "high"))
    eol = [t for t in techs if t.get("status") in ("eol", "legacy", "extended", "ending")]
    phases = {p["phase"]: p for p in a["roadmap"]["phases"]}
    horizon = {"good to go": "Short term, 0 to 12 months (maintenance only)", "patch": "Short term, 0 to 12 months",
               "rebuild": "Mid term, 1 to 3 years"}.get(v.get("bucket"), "Mid term, 1 to 3 years")
    DISP = {"retain": "Retain", "rehost": "Re-host", "replatform": "Re-platform", "refactor": "Refactor",
            "rearchitect": "Refactor (re-architect)", "replace": "Replace", "retire": "Retire"}
    disposition = DISP.get(v.get("code"), v.get("label") or UNKNOWN)
    tier = s["criticality_tier"] and f"Tier {s['criticality_tier'].replace('Tier', '').strip()}"
    if tier and not yes(s["criticality_confirmed"]):
        tier += " (provisional: not yet confirmed by the business owner; the impact ratings in Section 9 use it)"
    total = a["roadmap"]["total"]
    fin = _is_financial(store, arts)
    audit_logs = [e for e in store.entities("data_store") if re.search(r"AUDIT|\bLOG\b|\.LOG$", e["name"].upper())]
    eol_names = [f"{t.get('name')} {t.get('version') or t.get('cycle') or ''}".strip() for t in techs
                 if t.get("status") in ("eol", "legacy")]
    CT = RT.controls(sec_f, audit_logs, lambda eid: _sources_of(store, eid), eol_names, fin)
    sec_c, sec_txt = RT.posture(CT)
    metrics = _metrics(arts)
    skills = [fct["text"] for c in comps for fct in c["scores"]["supportability"]["factors"] if fct["rule"] == "SUP-SKILLS"]
    skill_list = sorted({x.split(" skills are scarce")[0] for x in skills})
    file_ifaces = [e for e in store.entities("data_store") if _is_interface(e)]
    apis = store.entities("api_endpoint")
    SCF = {"tests": metrics["tests"], "skills": skill_list, "platforms": len(AM["platforms"]),
           "silent_errors": sorted({RT._file(f) for f in sec_f if f.get("rule") == "SEC-ERR"}),
           "file_only": bool(file_ifaces or AM["stores"]), "apis": len(apis), "files": len(file_ifaces),
           "confidence": a["confidence"]["level"]}
    from . import dataarch as DA
    DM = DA.model(store, AM)
    HP = DA.hosting_platforms(AM, DM)
    SCF["platforms"] = len(HP)
    top_e = DM["entities"][0] if DM["entities"] else None
    SCF.update({"max_copies": len(top_e["copies"]) if top_e else 0, "frag_entity": top_e["name"] if top_e else None})
    SC = RT.scorecard(comps, AM, sec_c, sec_txt, SCF)
    conf_level = a["confidence"]["level"]
    cq = SC["Code quality"][0]
    if cq:
        debt_level = "Low" if cq <= 2 else "Medium" if cq == 3 else "High"
    from . import controls as FC
    missing_all = _missing(cov, arts)
    calc_routines = sorted({r_ for c in AM["components"] for r_ in c["routines"]
                            if any(w in r_.upper() for w in A_.RULE_WORDS) and not any(w in r_.upper() for w in ("READ", "WRITE", "OPEN", "CLOSE", "INIT", "FINAL", "PRINT"))})
    rates = FC.hard_rates(arts)
    FCR = FC.assess(store, arts, sec_f, DM, CT, metrics, calc_routines, rates, fin)
    tier1 = re.sub(r"(?i)tier", "", s["criticality_tier"] or "").strip() == "1"
    eol_comps = {}
    for t in techs:
        if t.get("status") in ("eol", "legacy"):
            eol_comps.setdefault(f"{t.get('name')} {t.get('version') or t.get('cycle') or ''}".strip(), []).append(t.get("file"))
    owner_it = s["it_reviewer"] or "IT application owner (to be named)"
    BR = FC.register({"fin": fin, "tier1": tier1, "fin_controls": FCR, "DM": DM, "rewrite": bool((a.get("facts") or {}).get("no_path")),
                      "eol": list(eol_comps), "eol_comps": eol_comps, "skills": skill_list, "platforms": len(HP),
                      "creds": sorted({RT._file(f) for f in sec_f if f.get("rule") == "SEC-CRED"}),
                      "inject": sorted({RT._file(f) for f in sec_f if f.get("rule") in ("SEC-SQLI", "SEC-SQLDYN", "SEC-CMD")}),
                      "missing": len(missing_all), "owner_it": owner_it,
                      "owner_fin": s["business_owner"] or "Business owner (finance; to be named)",
                      "owner_sec": "Information security (to be named)", "owner_ea": "Enterprise architecture (to be named)"})
    for i, r_ in enumerate(BR, 1):
        r_["id"], r_["rating"] = f"R-{num}-{i:02d}", FC.band(r_["score"])
    risks = BR
    top = BR[0] if BR else None
    from . import options as OP
    texts = {x["name"]: x.get("transcription") or "" for x in arts}
    CD = OP.components(AM, techs, sec_f, texts)
    PR = OP.program(CD, len(HP))
    multi_copies = sum(len(g["engines"]) for g in DM["entities"] if len(g["copies"]) >= 2)
    EST = OP.estimate(CD, {"fin": fin, "copies": multi_copies})
    phased = PR["code"] in ("rearchitect", "replace")
    elapsed = "18–30 months elapsed" if phased else f"{EST['months'][0]}–{EST['months'][1]} months elapsed"
    no_path_names = sorted({f"{t.get('name')}" for t in techs if t.get("status") in ("eol", "legacy")
                            and any(k.lower() in (t.get("name") or "").lower() for k in OP.NO_PATH)})
    OPTS = OP.scores({"no_path": no_path_names, "platforms": len(HP), "program_code": PR["code"],
                      "posting": sum(1 for c in CD if c["code"] == "consolidate") + (1 if any(c["code"] == "retain" and "Batch" in
                                     next((x["role"] for x in AM["components"] if x["name"] == c["name"]), "") for c in CD) else 0)})
    v = {"code": PR["code"], "label": PR["label"], "meaning": PR["meaning"], "meaning_plain": PR["meaning"],
         "bucket": "rebuild" if PR["code"] in ("rearchitect", "replace") else "patch"}
    disposition = PR["label"]
    horizon = ("Mid term, 1 to 3 years, delivered in phases (12.4)" if PR["code"] in ("rearchitect", "replace")
               else horizon)

    # cover, contents, rating scales
    kv(T[0], {"Application": f"{name} ({app_id})", "Client": s["client"] or doc.unknown("Client organization", "Cover"),
                         "Engagement": s["engagement"] or doc.unknown("Engagement name", "Cover"), "Version": version_txt,
                         "Date": today.strftime("%B %d, %Y"), "Classification": s["classification"]}, start=0)
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
    kv(T[3], {"Client": s["client"] or UNKNOWN, "Engagement": s["engagement"] or UNKNOWN, "Application name": name,
                         "Application ID": app_id, "Report version": version_txt, "Assessment period": period,
                         "Prepared by": s["prepared_by"], "Technical reviewer": s["technical_reviewer"] or doc.unknown("Technical reviewer", "Document control", "Assessment lead"),
                         "Business owner reviewer": s["business_owner"] or doc.unknown("Business owner reviewer", "Document control"),
                         "IT reviewer": s["it_reviewer"] or doc.unknown("IT reviewer", "Document control", "IT"),
                         "Classification": s["classification"], "Related applications": s["related_apps"] or "None identified"})
    rows(T[4], [[version_txt.split()[0].lstrip("v"), today.isoformat(), s["prepared_by"],
                 "Assessment report issued" if final else "Draft issued for review; becomes final after sign-off in 13.5"]])

    # 1 summary
    snap = {"Purpose in one sentence": s["purpose"] or doc.unknown("Purpose of the application in one sentence", "1.1"),
            "Business area": s["business_area"] or doc.unknown("Business area or program supported", "1.1"),
            "Business value": s["business_value"] or doc.unknown("Business value or volume supported", "1.1"),
            "Criticality tier": tier or doc.unknown("Criticality tier", "1.1"),
            "Overall health rating": RT.overall_text(SC, conf_level),
            "Technical debt level": f"{debt_level}: code quality is rated {RT.words(cq)} in 6.1, which includes the missing "
                                    f"automated tests. Maintainability alone: {R.explain_program(a, 'tech_debt')}",
            "Open critical or high vulnerabilities": f"{crit_high} ({sum(1 for f in sec_f if f['severity'] == 'critical')} critical, "
                                                     f"{sum(1 for f in sec_f if f['severity'] == 'high')} high); register in 8.3",
            "Highest risk score": (f"{top['score']} of 25, {top['rating']} ({top['id']}: {top['title']}); "
                                   f"{sum(1 for r_ in BR if r_['rating'] == 'High')} risks rated High in 9.1" if top else "None"),
            "End-of-life exposure": "; ".join(f"{t.get('name')} {t.get('version') or t.get('cycle') or ''}".strip()
                                              + (f" (ended {t['eol']})" if t.get("eol") else f" ({_status_word(t).lower()})")
                                              for t in eol[:5]) or "None identified",
            "Recommended disposition": f"{disposition}: {_disp_plain(v)}",
            "Recommended timing": horizon}
    kv(T[5], snap)
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
    health_c = SC["overall"][0]
    sec_n = sec.get("critical", 0) + sec.get("high", 0) or sum(sec.values())
    sec_files = len({(f.get("target_type"), f.get("target_id")) for f in sec_f
                     if f["severity"] in ("critical", "high")}) or 1
    sec_worst = (a["scores"]["security"].get("worst") or {})
    findings_txt = [
        f"In short: the most important findings are business risks rather than code quality: "
        + P.sentence([f"{r_['title'][:1].lower() + r_['title'][1:]}" for r_ in BR[:3]]) + ". "
        + (DA.fragmentation_sentence(DM) + " " if DA.fragmentation_sentence(DM) else "")
        + f"Overall condition is {RT.words(health_c)} (1 is best, 5 is worst)"
        + (", and the application relies on technology the vendor no longer supports" if eol else "")
        + f". The recommended direction is to {disposition.lower()}: {_disp_plain(v).rstrip('.').lower()} (Section 12).",
        (f"Financial controls (Section 8.6). " + _cap(P.sentence([f"{r_[0].lower()} is rated {r_[3]} – {P.LEVEL[r_[3]].lower()}"
                                                              for r_ in FCR if r_[3] and r_[3] >= 4]))
         + ". For a payment system these touch segregation of duties, audit integrity and undetected misstatement.")
        if any(r_[3] and r_[3] >= 4 for r_ in FCR) else "",
        (f"Architecture (Sections 4.4 and 5.5). The application runs on {len(HP)} platforms ({', '.join(HP)}), exchanges data "
         f"through files and shared databases, and needs {len(skill_list)} scarce skill sets ({', '.join(skill_list)}).")
        if len(HP) >= 3 else "",
        f"Security (Section 8). The review found {sec.get('critical', 0)} critical, {sec.get('high', 0)} high and "
        f"{sec.get('medium', 0)} medium issues. The most serious: {P.sentence([f'{w} ({sv})' for w, sv in worst3])}. "
        + ("Because the application handles personal data, a breach would expose personal records, so these issues are "
           "rated one level higher than they otherwise would be. " if pii else "")
        + f"Security posture is rated {RT.words(sec_c)}, derived from the control ratings in 8.1.",
        (f"Supportability (Section 6.2). {P.sentence([_eol_plain(t) for t in eol[:3]])}. Unsupported software no longer "
         f"receives security fixes, so its known weaknesses stay open until it is upgraded or replaced.")
        if eol else "Supportability (Section 6.2). Every technology identified is still supported by its vendor.",
        (f"Risk (Section 9). {sum(1 for r_ in BR if r_['rating'] == 'High')} of {len(BR)} risks are rated High. The highest: "
         + P.sentence([f"{r_['title'].lower()} ({r_['score']} of 25)" for r_ in BR[:3]]) + ".") if top else "",
        f"Effort (Section 12.4). The work is estimated at {EST['low']}–{EST['high']} person-weeks across "
        f"{len(EST['skills'])} skill sets; {elapsed}, because the order of work and the payment cycles, not the effort, set "
        f"the pace. "
        f"This covers the {len(arts)} components provided only and includes the test harness, parallel runs and data "
        f"migration; with {len(missing_all)} referenced components not provided, treat it as a floor. The first items are "
        f"security and control fixes that should be made before any wider decision (Section 1.3).",
    ]
    doc.replace("Summarize in three to five", findings_txt)
    doc.replace("List any condition that warrants action", "These problems should be fixed now, before any decision on "
                "modernization, because they expose data or users today:")
    imm = []
    owner_it = s["it_reviewer"] or "IT application owner (to be named)"
    groups_ = {}
    for f in sorted(sec_f, key=lambda f: SEV.index(f["severity"])):
        if f["severity"] in ("low", "info") or f["category"] == "privacy":
            continue
        groups_.setdefault(f.get("rule") or f["title"], []).append(f)
    for rule, fs in list(groups_.items())[:8]:
        files = sorted({RT._file(f) for f in fs})
        exposed = any("Network" in _exposure(RT._file(f)) or f["category"] in ("website", "ui_security") for f in fs)
        worst_sev = fs[0]["severity"]
        urg = ("Within 30 days" if worst_sev == "critical" or (worst_sev == "high" and (exposed or rule in ("SEC-CRED", "SEC-AUTHZ")))
               else "Within 60 days" if worst_sev == "high" else "Within 90 days")
        cond = f"{_cap(P.what(rule, fs[0]['title']))} ({', '.join(files[:3])})"
        if P.why(rule):
            cond += f". Why it matters: {P.why(rule)}."
        act = _cap(P.fix(rule) or (fs[0].get("detail") or "Fix the finding")) + "."
        if rule == "SEC-CRED":
            act = "Rotate the exposed passwords now, then move them to a secrets store and remove them from the code."
        imm.append([str(len(imm) + 1), cond, act, owner_it, urg])
    rows(T[6], imm, empty="None")

    # 2 business context
    kv(T[7], {"Business capability": s["purpose"] or doc.unknown("Business capability supported", "2.1"),
                         "Regulatory": s["regulatory_basis"] or doc.unknown("Regulatory, contractual or policy basis", "2.1"),
                         "Business owner": s["business_owner"] or UNKNOWN,
                         "Subject matter experts": doc.unknown("Subject matter experts", "2.1"),
                         "Year introduced": doc.unknown("Year introduced and major rewrites", "2.1"),
                         "Known drivers of change": doc.unknown("Known drivers of change", "2.1")})
    screens = [e for e in store.entities("screen")]
    rows(T[8], [["Business users of the application screens", UNKNOWN, doc.unknown("Number of users by group", "2.2"),
                            f"{len(screens)} screen(s): " + ", ".join(e['name'][:40] for e in screens[:4]) if screens else UNKNOWN,
                            UNKNOWN]] + ([["Batch schedule (no interactive users)", "Internal", "Not applicable",
                                           "Scheduled batch jobs", UNKNOWN]] if store.entities("job") else []))
    flows = store.get_meta("ui_flows") or {}
    proc = doc.para("[Insert process flow diagram")
    if proc is not None:
        from . import figures as FG
        try:
            uf = RD.map(FG.process(AM, DM, name))
        except Exception:  # noqa: BLE001
            uf = diagrams.get("userflow")
        if uf:
            pic = doc.picture(png(uf, scale=1.6), proc._p, 6.8, max_h=4.0)
            doc.new_para(f"Figure 1. Current-state process for {name}: each step in processing order, grouped by the platform "
                         f"it runs on. The order is inferred from the code and must be confirmed with the business owner.",
                         pic._p, italic=True)
        proc._p.getparent().remove(proc._p)
    doc.replace("Document each business process the application supports", "The process below is drawn from what each "
                "component reads, calculates and writes, from the arrival of input files to payment and look-up. Manual steps, "
                "approval points outside the application and handoffs are to be mapped with stakeholders (open item).")
    doc.unknown("Swimlane process map with business actors and manual steps", "2.3")
    steps = []
    for j in (flows.get("journeys") or [])[:3]:
        for st in j["steps"]:
            steps.append([str(len(steps) + 1), "Business user", f"Uses screen {st['screen']}", "Manual (screen entry)",
                          UNKNOWN, UNKNOWN, "" if st.get("captured") else "Screen referenced but not provided"])
    jobs = store.entities("job")
    for jb in jobs[:6]:
        steps.append([str(len(steps) + 1), "Scheduler", f"Runs batch job {jb['name']}", "Automated", UNKNOWN, UNKNOWN, ""])
    rows(T[9], steps, empty="No process steps could be derived from the source; to be mapped with stakeholders.")
    rows(T[10], [[f"Batch job {jb['name']}", doc.unknown(f"Schedule of batch job {jb['name']}", "2.4", "IT"),
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
    kv(T[11], {
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
    _infer_stack(stack, arts, DM, AM, store, jobs=store.entities("job"))
    t12 = T[12]
    for row in t12.rows[1:]:
        label = row.cells[0].text.strip()
        vals = stack.get(label) or ["None identified in the source", "", "", "", ""]
        if label in ("Operating system", "Infrastructure", "Web and application server", "Identity and authentication") and label not in stack:
            vals = [doc.unknown(f"{label} and version", "3.2", "IT"), "", "", "", ""]
        for j, val in enumerate(vals, 1):
            set_cell(row.cells[j], val)
    rows(T[13], [[doc.unknown("Licensing and contracts for commercial products", "3.3", "IT"), "", "", "", "", ""]])
    hard = [f for f in findings if f.get("rule") in ("SEC-CRED",)] + [
        {"title": fct["text"]} for c in comps for fct in c["scores"]["coupling"]["factors"] if "hard" in fct["text"].lower()]
    creds_n = sum(1 for h_ in hard if "credential" in h_["title"].lower())
    doc.replace("Describe hard-coded business rules", [
        (f"Business rates held in the code rather than in a maintained table: {'; '.join(rates[:4])}.")
        if rates else "No hard-coded business rules or rate tables were identified in the source reviewed.",
        f"{creds_n} hard-coded credential(s) were also found; they are security findings (8.3), not configuration." if creds_n else "",
        "Where routine policy or rate changes require a code change, the item appears in the technical debt register (7.3)."])

    # 4 architecture
    ref = doc.para("Figure 1. Reference architecture layout")
    if ref is not None:
        img = ref._p.getprevious()
        arch = diagrams.get("architecture")
        if arch is not None and img is not None and img.xpath(".//w:drawing"):
            pic = doc.picture(png(arch, scale=1.6), img, 6.9)
            img.getparent().remove(img)
        _set_para(ref, f"Figure 2. Logical architecture of {name}: layers, components and the systems and data it touches.",
                  italic=True)
        anchor = doc.new_para("Architecture at a glance", ref._p, bold=True)._p
        for layer in ("Presentation", "Application", "Data", "Integration"):
            cs = [c for c in AM["components"] if c["layer"] == layer]
            if cs:
                anchor = doc.new_para(f"{layer} layer: " + "; ".join(
                    f"{c['name']}, {c['role'].lower()}" + (f" in {c['language']}" if c["language"] else "")
                    + (f" using {', '.join(c['tech'])}" if c["tech"] else "") for c in cs) + ".", anchor, bullet=True)._p
        if AM["stores"]:
            anchor = doc.new_para("Data it holds: " + ", ".join(sorted(AM["stores"])[:12]) + ".", anchor, bullet=True)._p
        anchor = doc.new_para(f"Platforms hosting code or data: {', '.join(HP)}.", anchor, bullet=True)._p
        anchor = doc.new_para("Component inventory", anchor, bold=True)._p
        ct = _table_after(doc, T[20], anchor, ["Component", "Layer", "Role", "Technology", "Reads / uses", "Writes"],
                     [[c["name"], c["layer"], c["role"], ", ".join([c["language"]] + c["tech"]).strip(", ") or UNKNOWN,
                       ", ".join(c["reads"][:6]) or "–", ", ".join(c["writes"][:6]) or "–"] for c in AM["components"]])
        doc.new_para("", ct._tbl)
    doc.replace("The reference layout below shows", "The architecture below is drawn from the confirmed components in "
                "Section 3, in the standard layer order so it can be read alongside other application reports.")
    doc.remove("Each application report should include the following views")
    fill_col(T[14], 2, {"A.": "Complete (Figure 2)", "B.": "Inferred only (4.5); hosting and network detail to be confirmed",
                                   "C.": "Complete at system level (Figure 3); systems at each end to be named",
                                   "D.": "Complete (Figure 4)" if diagrams.get("data") else "Pending",
                                   "E.": "Pending: requires the portfolio inventory"})
    doc.unknown("Deployment (physical) architecture: servers, environments, network zones", "4.1", "IT")
    ins = doc.para("[Insert diagrams A to E here")
    if ins is not None:
        anchor = ins._p
        from . import figures as FG
        try:
            diagrams["context_sys"] = RD.map(FG.context(AM, DM, name))
        except Exception:  # noqa: BLE001
            pass
        for n, key, cap in ((3, "context_sys", "System context: user groups, upstream systems and shared-data owners, the "
                                               "application by platform, and downstream systems; dashed boxes are systems "
                                               "still to be named"),
                            (4, "data", "Data model: tables, columns and keys used by the application")):
            dg = diagrams.get(key)
            if dg is None:
                continue
            pic = doc.picture(png(dg, scale=1.5), anchor, 6.8)
            capp = doc.new_para(f"Figure {n}. {cap}. Validation with the IT owner: pending.", pic._p, italic=True)
            anchor = capp._p
        ins._p.getparent().remove(ins._p)

    ints = []
    ext = [e for e in store.entities() if _is_interface(e)]
    by_art = {x["name"]: x for x in arts}
    comp_of = {c["name"]: c for c in AM["components"]}
    for i, e in enumerate(ext[:25], 1):
        rels = store.relations(to_id=e["id"]) + store.relations(from_id=e["id"])
        kinds_ = {r["kind"] for r in rels}
        at = e.get("attrs") or {}
        users = sorted(_sources_of(store, e["id"]))
        ucomp = [comp_of[u] for u in users if u in comp_of]
        if e["kind"] == "api_endpoint":
            direction, method = "Inbound", f"REST API (HTTP {at.get('method') or 'request'})"
            data = f"Served by {', '.join(users) or 'the application'}"
            fmt, freq = "HTTP", "On demand, per request"
        else:
            direction = ("Bidirectional" if {"reads", "writes"} <= kinds_ else "Outbound" if "writes" in kinds_
                         else "Inbound" if "reads" in kinds_ else UNKNOWN)
            method = {"data_store": "File or dataset", "external_system": "System call"}[e["kind"]]
            who = ", ".join(users) or "the application"
            data = (f"{'Written' if direction == 'Outbound' else 'Read' if direction == 'Inbound' else 'Used'} by {who}"
                    + (f" (DD {at['assign']})" if at.get("assign") else ""))
            if at.get("record"):
                data = f"{at['record']}; {data}"
            batch = any(u["role"] == "Batch program" for u in ucomp)
            fmt = "Fixed-width records" if cobolish and at.get("assign") else ("Text log file" if "LOG" in e["name"].upper() else UNKNOWN)
            freq = ("Each batch run (schedule to confirm)" if batch else
                    "Each user transaction" if any("Interactive" in u["role"] for u in ucomp) else UNKNOWN)
        ints.append([f"INT-{num}-{i:02d}", direction, e["name"], data, method, fmt, freq, "IT (to confirm)", UNKNOWN, "No"])
    rows(T[15], ints)
    _col_widths(T[15], [0.7, 0.7, 1.0, 1.35, 0.8, 0.7, 0.85, 0.7, 0.7, 0.75])
    anchor = doc.new_para("How data moves between the components", T[15]._tbl, bold=True)._p
    for fl in A_.flows(AM) or ["No data movement could be traced in the source."]:
        anchor = doc.new_para(fl, anchor, bullet=True)._p
    if ints:
        doc.unknown("Frequency, owner and failure handling of each interface in 4.2", "4.2", "IT")
    missing = missing_all
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
    obs_src = list(AM["observations"])
    frag = DA.fragmentation_sentence(DM)
    if frag:
        obs_src.insert(0, ("Core business data is fragmented across platforms", frag + " See the ownership matrix in 5.5.",
                           "Every copy can drift from the others, so totals and balances can disagree between systems; any "
                           "modernization must first decide which copy is authoritative and how the rest are reconciled."))
    obs_src = [(t, (f"The application runs on {len(HP)} platforms: {', '.join(HP)}." if t.startswith("The application spans")
                    else w), m) for t, w, m in obs_src]
    obs = [f"{t}. What we see: {w} Why it matters: {m}" for t, w, m in obs_src]
    if (a["scores"].get("coupling") or {}).get("score") is not None:
        obs.append(f"Code-level coupling (calls between files) is rated {R.rating_words(a['scores']['coupling']['score'])}: "
                   + R.explain_program(a, "coupling").split(". ", 1)[-1]
                   + " This score counts program-to-program calls only; the data-level coupling described above is not "
                     "included in it.")
    doc.replace("Record structural concerns", obs)

    # 5 data
    tables = store.entities("table")
    dstores = [d_ for d_ in store.entities("data_store") if d_["origin"] != "placeholder" and not _is_interface(d_)
               and d_["name"] not in DM["displays"]]
    biz = {o["store"]: o["business"] for o in DM["occurrences"]}

    def _cls(name):
        b = biz.get(name)
        if fin and b in ("Payment", "Account", "Invoice", "Ledger", "Transaction", "Claim", "Payroll"):
            return ("Confidential (financial; review)", "Financial records; check for banking details (review)")
        if pii:
            return "Restricted", "Personal data"
        if s["privacy_obligations"] or s["regulatory_basis"]:
            return "Internal (review against the client's data practices policy)", "None identified"
        return "Internal", "None identified"
    rows(T[16], [[_entity_label(t_), _sor(store, t_), _volume(t_), UNKNOWN, *_cls(t_["name"])] for t_ in tables[:30]] +
         [[_entity_label(d_), _sor(store, d_), UNKNOWN, UNKNOWN, *_cls(d_["name"])] for d_ in dstores[:10]])
    _col_widths(T[16], [1.7, 1.45, 1.1, 0.9, 0.85, 0.9])
    doc.unknown("Data volumes, retention requirements and system-of-record status (5.1)", "5.1")
    fill_col(T[17], 1, {"": ["Not rated", "Requires access to production data; not part of this review."]})
    edits = sorted({x["name"] for x in arts if re.search(r"WHEN\s+OTHER|NOT\s+NUMERIC|IS\s+NUMERIC|INVALID|VALIDATE|%FOUND|SQLCODE\s+NOT", x.get("transcription") or "", re.I)})
    swallowed = sorted({RT._file(f) for f in sec_f if f.get("rule") == "SEC-ERR"})
    if edits or swallowed:
        fill_col(T[17], 1, {"Validation controls": ["3" if edits and swallowed else "2" if edits else "4",
                                                    (f"Edit checks in the code: {', '.join(edits[:4])}. " if edits else "")
                                                    + (f"Errors swallowed in {', '.join(swallowed)}, so bad data can pass silently (8.6)."
                                                       if swallowed else "") + " Rated from the code only."]})
    doc.unknown("Data quality ratings (requires production data)", "5.2")
    rpts = [x for x in arts if re.search(r"report|rpt", (x["name"] + " " + (x.get("language") or "")).lower())]
    rows(T[18], [[f"RPT-{num}-{i:02d}", x["name"], UNKNOWN, x.get("language") or UNKNOWN, UNKNOWN, UNKNOWN, UNKNOWN,
                              "Retain" ] for i, x in enumerate(rpts[:15], 1)])
    stats = [x for x in arts if re.search(r"spss|sas|excel|access|vba", (x.get("language") or "").lower())]
    doc.replace("Describe analytical and statistical tools", (
        f"Analytical tooling in the source: {', '.join(sorted({x['language'] for x in stats}))}. Users, skills and licensing "
        f"are open items.") if stats else "No analytical or statistical tooling was identified in the source reviewed.")

    from .sections import data_ownership
    data_ownership(doc, T, DM, fin, name)

    # 6 health
    t19 = T[19]
    for row in t19.rows[1:]:
        label = row.cells[0].text.strip()
        if label.startswith("Overall"):
            ov, raw, cov, cap = SC["overall"]
            set_cell(row.cells[2], str(ov) if ov else "Insufficient evidence")
            set_cell(row.cells[3], f"{raw:.2f}" if raw else "")
            set_cell(row.cells[4], RT.overall_text(SC, conf_level))
            continue
        for key, w in RT.DIMS:
            if label.startswith(key):
                c_, why = SC[key]
                set_cell(row.cells[2], str(c_) if c_ else "Insufficient evidence")
                set_cell(row.cells[3], f"{c_ * w / 100:.2f}" if c_ else "Not included")
                set_cell(row.cells[4], why)
    eol_rows, eol_notes = [], []
    for t in techs:
        if t.get("status") in (None, "unknown") and not t.get("eol"):
            continue
        nopath = t.get("status") == "legacy" or any(k.lower() in (t.get("name") or "").lower() for k in OP.NO_PATH)
        path = ("No (rewrite required)" if nopath else "Yes" if t.get("status") in ("eol", "extended", "ending")
                else "Not applicable")
        ml = _months_left(t.get("eol"), today)
        if ml and int(ml) < 0:
            try:
                ml = "Expired " + datetime.strptime(str(t["eol"])[:10], "%Y-%m-%d").strftime("%B %Y")
            except Exception:  # noqa: BLE001
                ml = "Expired"
        note = (t.get("note") or t.get("basis") or "").strip()
        eol_rows.append([t.get("name"), t.get("version") or t.get("cycle") or "Not confirmed", str(t.get("eol") or "") or "Not published",
                         str(t.get("extended") or "") or "Not published", ml or "", path, "See note below" if note else ""])
        if note:
            eol_notes.append(f"{t.get('name')}: {note}")
    rows(T[20], eol_rows)
    anchor = T[20]._tbl
    for nt in eol_notes:
        anchor = doc.new_para(nt, anchor, bullet=True)._p

    # 7 technical debt
    debt_f = R.program_factors(comps, "tech_debt", 40)
    cats = {"DEBT-GOTO": "Code", "DEBT-LEGACY": "Code", "DEBT-LONG": "Code", "DEBT-PRESTD": "Code", "DEBT-SIZE": "Architecture",
            "DEBT-TRANSLATED": "Code"}
    dom = sorted({cats.get(f["rule"], "Code") for f in debt_f}) or ["None"]
    refactor = [i for p in a["roadmap"]["phases"] for i in p["items"] if i.get("kind") in ("debt", "refactor") or "refactor" in i["title"].lower()]
    kv(T[21], {"Overall technical debt level": f"{debt_level}: code quality is rated {RT.words(cq)} in 6.1. Maintainability "
                                               f"alone: {R.explain_program(a, 'tech_debt')}",
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
    fill_col(T[22], 1, {
        "Lines of code": [", ".join(f"{k}: {v:,}" for k, v in sorted(langs.items(), key=lambda kv_: -kv_[1])), "Not applicable", "Source code review", ""],
        "Average and maximum cyclomatic complexity": [f"average {metrics['avg']}, maximum {metrics['max']} ({metrics['max_file']})",
                                                      "Under 15 per routine", "Decision-point count per file", _cmp(metrics["max"], 15)],
        "Code duplication": ["Not measured", "Under 5%", "", "Not assessed in this review"],
        "Maintainability rating": [f"{R.condition(debt_w)[0]} ({R.condition(debt_w)[1]}), weakest file", "2 (Good) or better", "Technical debt rating",
                                   "Deductions in 7.1"],
        "Automated test coverage": ["0% (no automated tests found in the source)" if not metrics["tests"] else f"{metrics['tests']} test file(s)",
                                    "60% or higher", "Source code review", "No test suite provided" if not metrics["tests"] else ""],
        "Outdated third-party dependencies": [str(sum(1 for t in techs if t.get("status") in ("eol", "legacy"))), "0", "Version and support-date review", ""],
        "Dead or unused code": ["Not measured", "", "", "Not assessed in this review"],
        "Share of machine-translated": [f"{metrics['translated']}%", "Not applicable", "Source code review", ""],
        "Hard-coded values": [str(len(hard)), "0", "Source code review", "; ".join(h_["title"] for h_ in hard[:2])],
    })
    reg = []
    SECURITY_CONSTRUCTS = re.compile(r"EXECUTE IMMEDIATE|QCMDEXC|WHEN OTHERS THEN NULL|Resume Next", re.I)
    STRATEGIC = re.compile(r"IMS|hierarchical|DL/I|ActiveX|OCX|3270|Visual Basic|VB6|ADO Recordset|IE6|Internet Explorer", re.I)
    TRIVIAL = re.compile(r"ArrayList|Hashtable|non-generic|GO TO|goto|indicators|fixed-form", re.I)
    if not metrics["tests"]:
        reg.append(["No automated tests on the payment calculations" if fin else "No automated tests",
                    "Test", "Tests were never built", "Every change, fix or modernization is unverifiable; errors reach "
                    "users" + (" and recipients" if fin else ""), "Build characterization tests from current outputs "
                    "before any change (a prerequisite in 12.3)", "L", "High"])
    moved = []
    for f in debt_f[:25]:
        if SECURITY_CONSTRUCTS.search(f["text"]):
            moved.append(f"{f['text'].split(': ', 1)[-1]} ({f.get('component', '')})")
            continue
        strategic, trivial = STRATEGIC.search(f["text"]), TRIVIAL.search(f["text"])
        cat = "Platform (strategic)" if strategic else "Code (local)" if trivial else cats.get(f["rule"], "Code")
        impact = ("Ties the component to an unsupported or scarce platform; retired by the disposition in 12.3"
                  if strategic else "Minor: slows maintenance, no business effect" if trivial else
                  _cap(P.why(f["rule"]) or "makes change slower"))
        reg.append([f"{_cap(P.what(f['rule'], f['text']))}: {f['text']} ({f.get('component', '')})", cat,
                    {"DEBT-GOTO": "Unstructured legacy style", "DEBT-LEGACY": "Library or construct not upgraded",
                     "DEBT-LONG": "Routines grown over time", "DEBT-SIZE": "Monolithic file", "DEBT-TRANSLATED": "Automated language conversion",
                     "DEBT-PRESTD": "Pre-standard language usage"}.get(f["rule"], "Legacy construct"),
                    impact, "Retire through the component disposition (12.3)" if strategic else
                    "Fix when the file is next changed" if trivial else "Refactor",
                    "L" if strategic else "S" if trivial else "M", "High" if strategic else "Low" if trivial else "Medium"])
    reg.sort(key=lambda r_: ["High", "Medium", "Low"].index(r_[-1]))
    reg = [[f"TD-{num}-{i:02d}"] + r_ for i, r_ in enumerate(reg, 1)]
    if moved:
        doc.new_para("Reclassified as security and control findings (8.3 and 8.6) rather than debt: " + "; ".join(moved) + ".",
                     T[23]._tbl)
    rows(T[23], reg)
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
    t24 = T[24]
    by_area = {r_["area"]: r_ for r_ in CT}
    for row in t24.rows[1:]:
        label = row.cells[0].text.strip()
        r_ = next((v_ for k, v_ in by_area.items() if label.startswith(k)), None)
        if r_ is None:
            continue
        if r_["rating"]:
            set_cell(row.cells[1], r_["seen"])
            set_cell(row.cells[2], r_["gap"])
            set_cell(row.cells[3], r_["why"])
        else:
            set_cell(row.cells[1], r_["seen"] or doc.unknown(f"Security control: {r_['area'].lower()}", "8.1", "Information security"))
            set_cell(row.cells[2], "Not assessed")
            set_cell(row.cells[3], r_["why"])
    doc.new_para(f"Security posture: {sec_txt}", T[24]._tbl)
    code_f = [f for f in sec_f if f["category"] in ("security", "privacy", "ui_security")]
    sca = [f for f in sec_f if f["category"] == "vulnerability"]
    web = [f for f in sec_f if f["category"] == "website"]
    cnt = lambda fs: [str(sum(1 for f in fs if f["severity"] == k)) for k in ("critical", "high", "medium", "low")]
    site = store.get_meta("site_scan") or {}
    fill_col(T[25], 1, {
        "Infrastructure and OS": ["Not performed", "", "Not in scope", "", "", "", ""],
        "Web application": (["Public website review", (site.get("scanned") or "")[:10], site.get("final_url") or site.get("start") or ""] + cnt(web))
        if site else ["Not performed", "", "Not in scope", "", "", "", ""],
        "Static code analysis": ["Source code review", today.isoformat(), f"{len(arts)} files"] + cnt(code_f),
        "Software composition": ["Version and CVE review", today.isoformat(), f"{len(techs)} components"] + cnt(sca),
        "Database configuration": ["Not performed", "", "Not in scope", "", "", "", ""],
        "Penetration test": ["Not performed", "", "Not in scope", "", "", "", ""],
    })
    doc.new_para("Composition analysis checks component versions against published vulnerability data. The legacy runtimes "
                 "in use (for example the VB6 runtime, ADO and ActiveX/OCX controls) have no maintained vulnerability feed, "
                 "so zero findings here does not mean zero risk; their coverage must be confirmed by information security.",
                 T[25]._tbl)
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
                   _cvss_cell(f, refs, "Internet facing" if f["category"] in ("website", "ui_security") else _exposure(loc)),
                   f["severity"].title(),
                   "Internet facing" if f["category"] in ("website", "ui_security") else _exposure(loc),
                   "Y" if refs.get("cve") else "N",
                   _cap(P.fix(f.get("rule") or "") or (f.get("detail") or "").split(". ")[-1][:140])
                   if not restricted else "Change the password and move it to a secrets store",
                   owner_it, (today + timedelta(days=days)).isoformat(), "Open", "Appendix D" if restricted else ""])
    rows(T[26], vr)
    anchor = doc.new_para("What these findings mean, in plain terms:", T[26]._tbl)._p
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
    fill_col(T[27], 1, {
        "Client information security policy": ["Y", "Not assessed", doc.unknown("Client security policy and standards", "8.5", "Information security")],
        "Security framework": ["Y", "Partial" if code_f else "Not assessed",
                               f"{s['security_framework'] or 'NIST SP 800-53'} controls referenced by the findings in 8.3"],
        "Data privacy obligations": (["Y", "Partial", f"{s['privacy_obligations'] or 'Applicable privacy law'}: personal data is handled; see 8.3"]
                                     if pii else ["N", "Not applicable", "No personal data identified in the source"]),
        "Payment card data": ["N" if not re.search(r"card|pan\b", " ".join(f["title"].lower() for f in findings)) else "Y", "Not assessed", ""],
        "Records retention schedule": [UNKNOWN, "Not assessed", doc.unknown("Retention schedule for financial and payment records", "8.5", "Records management")
                                       if fin else ""],
        "Open internal or external audit findings": [UNKNOWN, "Not assessed", doc.unknown("Open audit findings on payments or this application", "8.5", "Internal audit")
                                                     if fin else ""],
    })

    if FCR:
        from .sections import financial_controls
        financial_controls(doc, T, FCR)

    # 9 risk
    rows(T[28], [[r_["id"], r_["title"] + (f" ({', '.join(r_['comps'][:3])})" if r_["comps"] else ""), r_["cat"],
                  str(r_["L"]), str(r_["I"]), str(r_["score"]), r_["rating"], r_["existing"],
                  f"{r_['mit']}. Owner: {r_['owner']}"] for r_ in risks])
    _col_widths(T[28], [0.65, 1.9, 0.85, 0.6, 0.55, 0.5, 0.6, 1.1, 1.5])
    anchor = doc.new_para("Why each risk is rated as it is (likelihood reflects end-of-life status, skills, the code "
                          "findings and incident history where known; impact reflects what the component does to money "
                          "and data):", T[28]._tbl)._p
    for r_ in risks:
        anchor = doc.new_para(f"{r_['id']}: likelihood {r_['why_L']}; impact {r_['why_I']}.", anchor, bullet=True)._p
    t29 = T[29]
    for row in t29.rows[1:]:
        lab = row.cells[0].text
        vals = {"Complete outage": [s["business_value"] or UNKNOWN, UNKNOWN, UNKNOWN,
                                    "Payments to recipients are delayed and statutory payment dates may be missed; see the "
                                    "business calendar (2.4)" if fin else "Delayed service; see the business calendar (2.4)"],
                "Processing or calculation error": [f"{len(calc_routines) or len(arts)} calculation routine(s): {', '.join(calc_routines[:4])}"
                                                     if calc_routines else f"{len(arts)} files of business logic", "Not applicable",
                                                     "None identified in the source",
                                                     "Incorrect payments; effort to recover overpayments or pay arrears; misstated "
                                                     "accounts and audit findings" if fin else "Incorrect outputs and recovery effort"],
                "Security breach": ["Personal data" if pii else "Payment and district data" if fin else "Application data", "Not applicable", UNKNOWN,
                                    "Notification obligations and legal exposure" if pii else
                                    "Fraudulent approval or diversion of payments; audit findings; reputational harm" if fin else "Reputational harm"],
                "Loss of key technical staff": [f"Maintenance of the {skill_names} code" if skills else "Application maintenance", "Not applicable",
                                                UNKNOWN, "Inability to maintain or change the application"]}
        hit = next((v_ for k, v_ in vals.items() if lab.startswith(k)), None)
        if hit:
            for j, val in enumerate(hit, 1):
                set_cell(row.cells[j], val)
    doc.unknown("Maximum tolerable outage and current workarounds (9.2)", "9.2")
    t30 = T[30]
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
    kv(T[31], {k: doc.unknown(k, "10.1", "IT") for k in (
        "Support team and named contacts", "Number of staff able to support", "Vendor support arrangement",
        "Service level or availability target", "Change and release process", "Monitoring and alerting")})
    fill_col(T[32], 1, {"": [UNKNOWN, "Service management records not provided"]})
    doc.unknown("Support demand for the trailing 24 months (10.2)", "10.2", "IT")
    rows(T[33], [[f"Change to a statutory rate or parameter ({r_})", UNKNOWN, "Value held in source code",
                  "Move to a business-maintained, audited rate table", "Maintenance screen with approval and change history"]
                 for r_ in rates[:4]],
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
        from .plain import reasons_words, sentence
        return [str(c_[0]), _cap(f"{c_[1]}: {sentence(reasons_words(fs, 2))}.")]
    fill_col(T[34], 1, {
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
        f"User experience and accessibility are rated {R.explain_program(a, 'ux')}"] + ([f"Accessibility (measured against WCAG 2.1 AA, the usual legal standard): "
                                   f"{P.sentence(P.reasons_words(acc, 4))}."] if acc else []))

    # 12 options
    rec_code = PR["code"]
    np_txt = ", ".join(no_path_names)
    applicable = {"Retain": "No: " + ("unsupported components must be addressed" if eol else "security findings must be addressed"),
                  "Re-host": "No: moving infrastructure alone does not close the findings in Section 8 or reduce the platforms",
                  "Re-platform": ("Partly: for components with a supported successor; " + np_txt + " has no upgrade path")
                  if no_path_names else ("Yes: recommended" if rec_code == "replatform" else "Possible"),
                  "Refactor": "Partly: to fix findings in the components that are kept (see the table below)",
                  "Replace": ("Should be assessed: commercial or shared solutions for "
                              + (s["business_area"] or "this business area").lower() + " may exist (market review not done)"),
                  "Consolidate": ("Yes: within the application, " + str(sum(1 for c in CD if c["code"] == "consolidate") + 1)
                                  + " components post or calculate payments; keep one")
                  if any(c["code"] == "consolidate" for c in CD) else (s["related_apps"] and f"Candidates: {s['related_apps']}" or
                                                                       "Not assessed: requires the portfolio inventory"),
                  "Retire": "No: the function is still in use"}
    fill_col(T[35], 2, applicable)
    last_row = T[35].rows[-1]._tr
    new_row = deepcopy(T[35].rows[1]._tr)
    last_row.addnext(new_row)
    rr = T[35].rows[-1]
    set_cell(rr.cells[0], "Re-architect / rebuild")
    set_cell(rr.cells[1], "Rebuild the application on a service-based architecture, component by component")
    set_cell(rr.cells[2], "Yes: recommended" if rec_code == "rearchitect" else "Possible")
    t36 = T[36]
    for j in range(3):
        set_cell(t36.rows[0].cells[2 + j], f"Option {'ABC'[j]}: {OPTS[j][0]}")
    totals = [0.0, 0.0, 0.0]
    for row in t36.rows[1:]:
        lab = row.cells[0].text
        k = next((i for i, ck in enumerate(OP.CRITERIA) if lab.startswith(ck)), None)
        if k is None:
            if lab.lower().startswith("weighted") or lab.lower().startswith("total"):
                for j in range(3):
                    set_cell(row.cells[2 + j], f"{totals[j]:.2f}")
            continue
        for j in range(3):
            sc = OPTS[j][1][k]
            totals[j] += sc * OP.WEIGHTS[k] / 100
            set_cell(row.cells[2 + j], str(sc))
    score_note = doc.para("Score each shortlisted option")
    if score_note is not None:
        _set_para(score_note, "Each shortlisted option is scored from 1 to 5 on every criterion, where 5 is always the most "
                  "favourable: for implementation complexity and disruption, 5 means the least complex and least disruptive. "
                  "Weighted totals: " + ", ".join(f"{o[0]} {t_:.2f}" for o, t_ in zip(OPTS, totals)) + ". Rationale:")
        last = score_note._p
        for o in OPTS:
            last = doc.new_para(f"{o[0]}: {o[2]}", last, bullet=True)._p
    high_n = sum(1 for r_ in BR if r_["rating"] == "High")
    kv(T[37], {"Recommended disposition": disposition,
               "Rationale": (f"{len(HP)} platforms, {len(no_path_names)} component technology with no upgrade path"
                             f"{' (' + np_txt + ')' if np_txt else ''}, {crit_high} critical or high findings in 8.3 and "
                             f"{high_n} High risks in 9.1 cannot be closed by fixing code in place; each component gets "
                             f"its own disposition (table below)."),
               "Consolidation grouping": s["related_apps"] or "Within the application: the payment posting components",
               "Prerequisites": P.sentence([f"provide the {len(missing_all)} missing components" if missing_all else "",
                                            "confirm business criticality", "name the system of record for each entity (5.5)",
                                            "characterization tests for the calculations" if fin else ""]),
               "Key risks of the recommended option": "Regression in payment calculations and data loss during migration; "
                                                      "mitigated by characterization tests, reconciliation and parallel runs "
                                                      "over at least two payment cycles",
               "Interim risk mitigation": "The immediate actions in 1.3 and the control fixes in 8.6"})
    anchor = doc.new_para("Disposition by component", T[37]._tbl, bold=True)._p
    ct = _table_after(doc, T[26], anchor, ["Component", "Platform", "Disposition", "Reason", "Skill set"],
                      [[c["name"], c["platform"], c["label"], _cap(c["why"]) + ".", c["skill"]] for c in CD])
    _col_widths(ct, [1.5, 1.4, 0.9, 3.3, 1.2])
    anchor = doc.new_para("Target architecture (outline)", ct._tbl, bold=True)._p
    anchor = doc.new_para("A planning-level view of where each layer should end up under the "
                          "recommended option; it is product-neutral and needs validating with the enterprise architecture team:",
                          anchor)._p
    for t_ in A_.target_outline(AM, v.get("code")):
        anchor = doc.new_para(t_, anchor, bullet=True)._p
    kv(T[38], {"Recommended horizon": horizon,
               "Proposed start window": doc.unknown("Proposed start window (fiscal year and quarter)", "12.4"),
               "Estimated duration": f"{_cap(elapsed)} (set by the order of work below and by parallel runs over payment "
                                     f"cycles); {EST['low']}–{EST['high']} person-weeks of effort across {len(EST['skills'])} "
                                     f"skill sets (breakdown below)",
               "Predecessor initiatives": "Security and control fixes (1.3, 8.6); system-of-record decision (5.5); missing code",
               "Successor initiatives": "Platform retirement once the last component on each platform has moved",
               "Business blackout periods": doc.unknown("Business blackout periods (payment cycles, year-end)", "12.4")})
    anchor = doc.new_para("Order of work, by dependency", T[38]._tbl, bold=True)._p
    for ph, txt in OP.sequence({"fin": fin}):
        anchor = doc.new_para(f"{ph}: {txt}", anchor, bullet=True)._p
    anchor = doc.new_para("Estimate by skill set", anchor, bold=True)._p
    et = _table_after(doc, T[26], anchor, ["Skill set", "Work", "Person-weeks", "Basis"],
                      [[g["skill"], "; ".join(g["work"][:4]) + (f"; and {len(g['work']) - 4} more" if len(g["work"]) > 4 else ""),
                        f"{g['lo']:.0f}–{g['hi']:.0f}", "; ".join(g["basis"])] for g in EST["lines"]]
                      + [["Total", "", f"{EST['low']}–{EST['high']}", f"{_cap(elapsed)}; specialists work in parallel, "
                          f"part-time, as each phase needs them"]])
    _col_widths(et, [1.6, 2.9, 1.0, 2.8])
    doc.new_para(f"Assumptions: the estimate covers the {len(arts)} components provided ({sum(c['lines'] for c in CD):,} lines); "
                 f"{len(missing_all)} referenced components were not provided and the full application size is unknown, so "
                 f"this is a floor, not a budget. Rates are planning-level and need validating with the delivery teams; "
                 f"each skill set needs its own people (COBOL, RPG, PL/SQL and .NET skills rarely sit in one person).",
                 et._tbl)

    # 13 evidence
    rows(T[39], [["None", "", "", "", "Stakeholder interviews were not part of this review", ""]])
    doc.unknown("Stakeholder interviews", "13.1", "Assessment lead")
    ev = []
    for i, x in enumerate(arts, 1):
        typ = {"code": "Source code", "ui_screen": "Application screen", "schema": "Database schema", "config": "Configuration",
               "document": "Document"}.get(x.get("artifact_type"), "Source code")
        ev.append([f"EV-{num}-{i:02d}", x["name"], typ, f"v{x.get('version', 1)}, {(x.get('updated') or x.get('created') or '')[:10]}",
                   f"Program source set: {x['name']}"])
    rows(T[40], ev)
    assumptions = ["Findings reflect the source files listed in 13.2; components not provided are listed in 4.3 and are not scored.",
                   ("Business criticality is provisional (" + (tier or "not entered") + "); impact ratings in Section 9 use it "
                    "and change if the business owner rates it differently.") if not yes(s["criticality_confirmed"]) else
                   "Business criticality was confirmed by the business owner.",
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
    t42 = T[42]
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
                         ("Appendix E:", "Appendix E: Current-state process (Figure 1)"),
                         ("Appendix F:", "Appendix F: Report catalog (Section 5.3)"),
                         ("Appendix G:", "Appendix G: Glossary of technical terms (below)")):
        p = doc.para(starts)
        if p is not None:
            _set_para(p, text)
    from . import sections as SX
    SX.capability(doc, T, AM, s, fin)
    SX.boundary(doc, T, AM, arts, HP, missing_all)
    SX.deployment(doc, T, AM, DM, HP, fin)
    SX.nfr(doc, T, fin, [c["name"] for c in AM["components"] if "Batch" in c["role"] or "procedures" in c["role"]])
    stack_names = []
    for vals in stack.values():
        for n_ in re.split(r";\s*(?![^()]*\))", vals[0] or ""):
            n_ = re.sub(r"\s*\([^)]*\)", "", n_).strip()
            if n_ and n_ not in stack_names and not n_.startswith(("None", "Unknown", "COBOL batch program", "Scheduled job",
                                                                  "Batch reports")):
                stack_names.append(n_)
    SX.lifecycle(doc, T, techs, stack_names, OP.NO_PATH)
    SX.identity(doc, T, AM, CT, DM)
    local_logs = [o for o in DM["occurrences"] if o["engine"].startswith("Windows desktop (local file)")]
    SX.operations(doc, T, AM, DM, skill_list, "; ".join(f"{o['component']} writes {o['store']} on the desktop" for o in local_logs)
                  + ("; audit calls elsewhere have implementations that were not provided" if local_logs else ""))
    SX.strategy(doc, T, {"overall": RT.words(SC["overall"][0])}, PR, CD, HP, fin,
                (tier or "").split(" (")[0] + (" provisional" if tier and not yes(s["criticality_confirmed"]) else ""), no_path_names)
    for t in techs:
        if not (t.get("version") or t.get("confidence") == "confirmed"):
            doc.open_items.append((f"Confirm the version of {t.get('name')} in use", "3.2", "IT"))
    BLOCK = re.compile(r"reviewer|Business owner|criticality|boundary|missing|Provide the source|system of record", re.I)
    items = _dedup(doc.open_items)
    blocking = [it for it in items if BLOCK.search(it[0])]
    other = [it for it in items if not BLOCK.search(it[0])]
    oi = []
    for i, (what, sec_, owner) in enumerate(blocking + other, 1):
        blk = (what, sec_, owner) in blocking
        due = (today + timedelta(days=14 if blk else 45 if i <= len(blocking) + 15 else 75)).isoformat()
        oi.append([f"OI-{num}-{i:02d}", ("Blocks issue: " if blk else "") + f"{what} (Section {sec_})", owner, due, "Open"])
    rows(T[41], oi)
    doc.new_para(f"{len(blocking)} of the {len(oi)} open items block issue of the report as final (marked 'Blocks issue', "
                 f"due in 14 days); the rest are scheduled over the following 75 days.", T[41]._tbl)
    _glossary(doc)
    _fill_toc(doc)
    _header_footer(doc, name)
    cp = doc.d.core_properties
    cp.author = cp.last_modified_by = s["prepared_by"]
    cp.title = f"{name} — Application Assessment Report"
    cp.subject = f"Prepared for {s['client']}" if s["client"] else "Application Assessment Report"
    cp.comments = cp.keywords = cp.category = ""
    _no_placeholders(doc)
    from .wording import clean
    for part in [doc.d.element.body] + [p_.part.element for sec_ in doc.d.sections for p_ in (sec_.header, sec_.footer)]:
        for t_ in part.iter(qn("w:t")):
            if t_.text:
                t_.text = RD(clean(t_.text))
    cp.title = RD(cp.title)
    buf = io.BytesIO()
    doc.d.save(buf)
    return buf.getvalue()


# ── helpers for the build ───────────────────────────────────────────────────────────────────────────────────────

FIN_WORDS = re.compile(r"PAYMENT|\bPAY\b|PAY[-_]|AMOUNT|LEDGER|INVOICE|DISBURS|REMIT|\bEFT\b|HOLDBACK|GROSS|"
                       r"\bNET\b|BILLING|CLAIM|ENTITLE|REFUND|GENERAL[-_ ]LEDGER", re.I)


def _add_stack(stack, layer, tech, vendor, status="To confirm (inferred from the code)"):
    cur = stack.get(layer)
    if cur is None:
        stack[layer] = [tech, vendor, UNKNOWN, UNKNOWN, status]
        return
    if tech.split(" (")[0].lower() in cur[0].lower():
        return
    cur[0] = f"{cur[0]}; {tech}"
    if vendor not in cur[1]:
        cur[1] = f"{cur[1]}; {vendor}"
    if status not in cur[4]:
        cur[4] = f"{cur[4]}; {status}"


def _infer_stack(stack, arts, DM, AM, store, jobs=()):
    """Facts the code shows even when no version is stated: languages, database engines, batch, reports, platforms."""
    langs = []
    for x in arts:
        lang = x.get("language") or ""
        if x.get("artifact_type") == "ui_screen" or not lang or lang.lower() in ("ui screen",):
            continue
        lab = {"Assembly": "IBM Assembler (IMS DBD macros)", "PL/SQL": "Oracle PL/SQL", "Visual Basic 6": "Visual Basic 6.0",
               "RPG": "RPG (IBM i)", "COBOL": "Enterprise COBOL (z/OS)" if "CICS" in (x.get("transcription") or "")
               or "IBM-370" in (x.get("transcription") or "") else "COBOL"}.get(lang, lang)
        if lab not in langs:
            langs.append(lab)
    for lab in langs:
        _add_stack(stack, "Programming languages", f"{lab} (version not confirmed)", _vendor({"name": lab}) if _vendor({"name": lab}) != UNKNOWN
                   else "Microsoft" if "C#" in lab else "IBM" if "Assembler" in lab else UNKNOWN)
    for sq in DM.get("sql_server") or []:
        _add_stack(stack, "Database", f"Microsoft SQL Server ({sq}; version not confirmed)", "Microsoft")
    if DM.get("db2"):
        _add_stack(stack, "Database", "IBM Db2 for z/OS (EXEC SQL in COBOL; version not confirmed)", "IBM")
    if any((x.get("language") or "").upper().startswith("RPG") for x in arts):
        _add_stack(stack, "Database", "Db2 for i (IBM i database files)", "IBM")
    batch = []
    for x in arts:
        t = x.get("transcription") or ""
        dds = __import__("re").findall(r"ASSIGN\s+TO\s+([A-Z0-9-]+)", t)
        if dds and "cobol" in (x.get("language") or "").lower() and "CICS" not in t:
            batch.append(f"COBOL batch program {x['name']} (DD names {', '.join(dds[:6])}); JCL and scheduler not provided")
    for jb in jobs:
        batch.append(f"Scheduled job {jb['name']}; scheduler to confirm")
    for b in batch:
        _add_stack(stack, "Batch and scheduling", b, "IBM" if "COBOL" in b else UNKNOWN)
    rpt = [e["name"] for e in store.entities() if __import__("re").search(r"REPORT|RPT", e["name"], __import__("re").I)
           and e["kind"] in ("data_store", "program", "job")]
    if rpt:
        _add_stack(stack, "Reporting", "Batch reports: " + ", ".join(sorted(set(rpt))[:5]) + " (content in 5.3)", "Custom (in-house)")
    plats = set(AM["platforms"])
    if "IBM mainframe (z/OS)" in plats:
        _add_stack(stack, "Operating system", "IBM z/OS (with CICS and IMS; version not confirmed)", "IBM")
    if "Windows desktop (VB6)" in plats:
        _add_stack(stack, "Operating system", "Microsoft Windows desktops running the VB6 runtime (versions not confirmed)", "Microsoft")
    if "Microsoft .NET (Windows server)" in plats:
        _add_stack(stack, "Operating system", "Microsoft Windows Server with IIS for the .NET application (inferred)", "Microsoft")
        _add_stack(stack, "Web and application server", "Microsoft IIS / ASP.NET MVC (inferred from the controller code)", "Microsoft")
    if "IBM i (AS/400)" in plats:
        _add_stack(stack, "Operating system", "IBM i (version not confirmed)", "IBM")


def _missing(cov, arts) -> list:
    """Every referenced component that was not provided, once, leaving out routines defined in a provided file."""
    text = "\n".join(x.get("transcription") or "" for x in arts)
    out, seen = [], set()
    for m in cov.get("missing") or []:
        if m["category"] != "missing_code" or m["name"] in seen:
            continue
        n = re.escape(m["name"])
        if re.search(rf"\b{n}\s+BEGSR\b|\bBEGSR\s+{n}\b|^\s*\d*\s+{n}\.\s*$|\bSub\s+{n}\b|\bdef\s+{n}\b", text, re.M | re.I):
            continue
        seen.add(m["name"])
        out.append(m)
    return out


def _cvss_cell(f, refs, exposure):
    from . import ratings as RT
    if refs.get("cvss"):
        return str(refs["cvss"])
    sc, vec = RT.cvss(f.get("rule") or "", exposure)
    if sc is None:
        return "Not applicable (control weakness, see 8.6)" if f.get("rule") == "SEC-ERR" else "Not scored"
    return f"{sc} {RT.cvss_band(sc)} (indicative; {vec.replace('CVSS:3.1/', '')})"


def _is_financial(store, arts) -> bool:
    """The application calculates, approves or posts money: payment, amount, ledger or entitlement data."""
    names = " ".join(e["name"] for e in store.entities() if e["kind"] in ("data_store", "table", "column", "field",
                                                                          "api_endpoint", "procedure", "paragraph"))
    hits = len(FIN_WORDS.findall(names)) + sum(len(FIN_WORDS.findall((x.get("transcription") or "")[:20000])) > 3 for x in arts)
    return hits >= 4


def _sources_of(store, eid) -> set:
    return {r["name"] for r in store._all(
        "SELECT a.name FROM entity_source es JOIN artifact a ON a.id = es.artifact_id "
        "WHERE a.is_current = 1 AND es.entity_id = ?", (eid,))}


def _is_interface(e) -> bool:
    """Files, APIs and external systems cross the application boundary; databases are data it holds (5.1)."""
    if e["origin"] == "placeholder":
        return False
    if e["kind"] in ("api_endpoint", "external_system"):
        return True
    return e["kind"] == "data_store" and (e.get("attrs") or {}).get("store_type", "file") == "file"


def _entity_label(e) -> str:
    at = e.get("attrs") or {}
    if at.get("ims_segment"):
        return f"{e['name']} (IMS segment in {at.get('dbd') or 'the database'})"
    if e["kind"] == "data_store":
        st = at.get("store_type") or "data store"
        return f"{e['name']} ({'IMS database' if 'IMS' in st else 'database file' if st == 'database file' else st})"
    return e["name"] + (" (not provided)" if e.get("origin") == "placeholder" else "")


def _sor(store, e) -> str:
    kinds_ = {r["kind"] for r in store.relations(to_id=e["id"])}
    at = e.get("attrs") or {}
    if "writes" in kinds_ or at.get("ims_segment") or at.get("dbd") or "IMS" in (at.get("store_type") or ""):
        return "Y (the application writes or defines it; to confirm)"
    if "reads" in kinds_:
        return "N (read only here; owned elsewhere, to confirm)"
    users = sorted(_sources_of(store, e["id"]))
    return f"To confirm (used by {', '.join(users[:2])})" if users else UNKNOWN


def _volume(e) -> str:
    b = (e.get("attrs") or {}).get("bytes")
    return f"Record size {b} bytes; record count unknown" if b else UNKNOWN


def _exposure(loc: str) -> str:
    l = loc.lower()
    if l.split(":")[0].endswith((".cs", ".aspx", ".asp", ".jsp", ".java", ".php", ".js", ".html", ".htm")):
        return "Network (web or API; to confirm)"
    if l.split(":")[0].endswith((".frm", ".bas", ".vb", ".cls")):
        return "Internal desktop (to confirm)"
    return "Internal (to confirm)"


def _risk_owner(s, cat) -> str:
    if cat == "Security":
        return "Information security (to confirm)"
    return (s.get("it_reviewer") or "IT application owner") + " (to confirm)"


def _col_widths(t, inches):
    from docx.shared import Inches
    from docx.oxml.ns import qn
    if len(t.columns) != len(inches):
        return
    tbl = t._tbl
    grid = tbl.tblGrid
    for gc, w in zip(grid.findall(qn("w:gridCol")), inches):
        gc.set(qn("w:w"), str(int(w * 1440)))
    for row in t.rows:
        for cell, w in zip(row.cells, inches):
            cell.width = Inches(w)


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
    return v.get("meaning_plain") or DISPOSITIONS.get(v.get("code"), v.get("meaning", ""))


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


def _table_after(doc, src, anchor_el, head, data):
    """A new table in the template's style (copied from `src`, trimmed to len(head) columns) placed after anchor_el."""
    from docx.table import Table
    tbl = deepcopy(src._tbl)
    n = len(head)
    grid = tbl.find(qn("w:tblGrid"))
    cols = grid.findall(qn("w:gridCol"))
    total = sum(int(c.get(qn("w:w")) or 0) for c in cols) or 10800
    for c in cols[n:]:
        grid.remove(c)
    for c in grid.findall(qn("w:gridCol")):
        c.set(qn("w:w"), str(total // n))
    for tr in tbl.findall(qn("w:tr")):
        tcs = tr.findall(qn("w:tc"))
        for tc in tcs[n:]:
            tr.remove(tc)
        for tc in tr.findall(qn("w:tc")):
            w = tc.find(qn("w:tcPr") + "/" + qn("w:tcW"))
            if w is not None:
                w.set(qn("w:w"), str(total // n))
    anchor_el.addnext(tbl)
    t = Table(tbl, doc.d)
    for i, h in enumerate(head):
        set_cell(t.rows[0].cells[i], h)
    rows(t, data)
    return t


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
