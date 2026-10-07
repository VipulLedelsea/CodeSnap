"""The Word report: the Application Assessment Report template, completed section by section.

Everything the program's source shows is filled in with its reasoning. Business facts the source cannot show (owners,
user counts, licensing, calendars, interviews) come from the report settings; anything still missing is written as
"Unknown" and logged in 13.4 Open items, as the template's own completion guidance requires. The how-to-use guidance,
instruction text and bracketed placeholders are removed so the document can be issued as-is.
"""
import io
import logging
import re
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, RGBColor

from core.text import shorten_at_boundary

from . import rationale as R
from ..diagrams.xmlsafe import xml_safe
from .settings import app_number, get as get_settings

TEMPLATE = Path(__file__).with_name("assets") / "Application_Assessment_Report_Template.docx"
UNKNOWN = "Unknown"
PLACEHOLDER = "<insert {} information here>"


def _specific(label):
    t = re.sub(r"\s*\([^)]*\d[^)]*\)", "", " ".join((label or "").split())).strip(" :-")
    t = t[:70].rstrip()
    return (t[:1].lower() + t[1:]) if t[1:2].islower() else t


def placeholder(label=""):
    t = _specific(label)
    return PLACEHOLDER.format(t) if t else "<insert missing information here>"
log = logging.getLogger(__name__)
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
        return placeholder(what)

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
    text = xml_safe(text)
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
    text = "" if text is None else xml_safe(str(text))
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
    if t.get("status") in ("supported", "ending", None, "unknown") and not t.get("version"):
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

def render(store, report: dict, diagrams: dict, today=None, metadata=None) -> bytes:
    with R.word_ratings():
        return _render(store, report, diagrams, today, metadata=metadata)


def _pain_points(issues, n=6):
    """UI findings as short plain sentences, one per distinct problem, with the screen it was seen on."""
    out, seen = [], set()
    for f in sorted(issues, key=lambda f: SEV.index(f["severity"])):
        head, _, rest = f["title"].partition(" — ")
        detail, _, where = (rest or head).rpartition(": ") if ": " in (rest or head) else (rest or head, "", "")
        detail = detail.strip() or head
        detail = shorten_at_boundary(detail)
        key = detail.lower()[:40]
        if key in seen:
            continue
        seen.add(key)
        out.append(f"{_cap(detail.rstrip('.'))}" + (f" ({where.strip()})" if where.strip() else "") + ".")
        if len(out) == n:
            break
    return out


def _render(store, report: dict, diagrams: dict, today=None, metadata=None) -> bytes:
    from core.diagrams.render import png
    from . import ratings as RT
    from core.security.scan import technologies
    today = today or date.today()
    s = get_settings(store)
    if report.get("client") and report["client"] != "the client":
        s["client"] = report["client"]
    a = report["assessment"]
    num = app_number(s)
    app_id = s["app_id"] or f"APP-{num}"
    name = report["program"]
    doc = Doc()
    T = list(doc.d.tables)      # the template's tables, fixed before any new table is inserted
    comps = a["components"]
    from . import evidence as EV
    from . import sections as SX
    from . import plain as P
    findings = [f for f in store.findings() if f.get("status") not in ("dismissed", "fixed")]
    arts = store.artifacts()
    if not arts:
        doc.d.add_paragraph("No verdict can be given because no components have been reviewed yet.")
    from . import quality as Q
    evidence_quality = Q.summary(store)
    COPIES = EV.screen_copies(arts)
    page_ids = {x["id"] for x in arts if x["name"] in COPIES.values()}
    copy_ids = {x["id"] for x in arts if x["name"] in COPIES}
    page_rules = {f.get("rule") for f in findings if f.get("target_id") in page_ids and f.get("target_type") == "artifact"}
    findings = [f for f in findings if not (f.get("target_type") == "artifact" and f.get("target_id") in copy_ids
                                            and f.get("rule") in page_rules and f["category"] in ("ui_security", "security", "accessibility"))]
    sec_f = EV.apply_review(store, [f for f in findings if f["category"] in ("security", "vulnerability", "ui_security",
                                                                              "website", "privacy")])
    cov = store.coverage()
    from .redact import Redactor
    RD = Redactor(s, [x["name"] for x in arts] + [e["name"] for e in store.entities("screen")])
    diagrams = {k: RD.map(d_) for k, d_ in diagrams.items()}
    yes = lambda v_: str(v_ or "").strip().lower() in ("yes", "y", "true", "1")
    final = yes(s["signed_off"]) and s.get("signed_off_basis") == store.model_stamp() and all(s[k] for k in ("technical_reviewer", "business_owner", "it_reviewer")) and not evidence_quality["blockers"]
    ver = re.sub(r"(?i)\s*\bfinal\b", "", s["version"] or "v1.0").strip() or "v1.0"
    version_txt = f"{ver} Final" if final else ("v0.9 Draft for review" if ver.lower() in ("v1.0", "1.0") else f"{ver} Draft for review")
    techs, seen = [], set()
    ims_dc = EV.ims_dc(arts)
    for t in technologies(store, today):
        k = (t.get("name"), t.get("cycle") or t.get("label"))
        if k not in seen:
            seen.add(k)
            if (t.get("name") or "").startswith("IBM IMS (DB/DC)") and not ims_dc:
                t = {**t, "name": "IBM IMS"}
            techs.append(t)
    sessions = store._all("SELECT MIN(started) AS a FROM capture_session") if _has_col(store, "capture_session", "started") else []
    start = (sessions[0]["a"] if sessions and sessions[0]["a"] else store.info.get("created") or "")[:10]
    period = f"{start or placeholder('engagement start date')} to {today.isoformat()}"
    from . import architecture as A_
    AM = A_.build(store, a, techs)
    personal = EV.personal_entities(store, findings)
    dormant = EV.dormant_personal_data(store, arts)
    pii = bool(personal) or any(c.get("student_data") for c in comps)
    CICS = bool(EV.cics(arts))
    code_arts = [x for x in arts if x.get("artifact_type") != "ui_screen"]
    FX = {"lines": sum(len((x.get("transcription") or "").splitlines()) for x in code_arts), "files": len(code_arts),
          "images": len(arts) - len(code_arts), "creds": EV.credentials(sec_f), "db_creds": EV.db_credentials(sec_f),
          "data_stores": EV.data_stores(store, arts), "screens": EV.screens(store, arts), "formats": EV.record_formats(arts), "totals": EV.batch_totals(arts),
          "sev": {k: sum(1 for f in sec_f if f["severity"] == k) for k in SEV}}
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
    skill_list = sorted({x.split(" skills are scarce")[0].split(" specialist skills required")[0] for x in skills})
    file_ifaces = [e for e in store.entities("data_store") if _is_interface(e)]
    apis = store.entities("api_endpoint")
    SCF = {"tests": metrics["tests"], "skills": skill_list, "platforms": len(AM["platforms"]),
           'confirmed_support': any(t.get('version') and t.get('status') not in (None, 'unknown', 'unconfirmed') for t in techs),
           "silent_errors": sorted({RT._file(f) for f in sec_f if f.get("rule") == "SEC-ERR"}),
           "file_only": bool(file_ifaces or AM["stores"]), "apis": len(apis), "files": len(file_ifaces),
           "confidence": a["confidence"]["level"]}
    from . import dataarch as DA
    from core import deepdive as DDV
    DD = DDV.current_reviews(store)
    DPROG = {} if DDV.program_stale(store) else (store.get_meta("deepdive_program") or {})
    RQ = DDV.rescan_requests(store)
    DM = DA.model(store, AM)
    HP = DA.hosting_platforms(AM, DM)
    SCF["platforms"] = len(HP)
    top_e = DM["entities"][0] if DM["entities"] else None
    SCF.update({"max_copies": len(top_e["copies"]) if top_e else 0, "frag_entity": top_e["name"] if top_e else None})
    plat_of = {c_["name"]: c_["platform"] for c_ in AM["components"]}
    shared_stores = [n_ for n_, s_ in AM["stores"].items() if len(s_["readers"] | s_["writers"]) > 1
                     and len({plat_of.get(x) for x in s_["readers"] | s_["writers"]}) == 1]
    _suspect = re.compile(r"duplicated verbatim|defined twice|identical paragraph name|repeated verbatim|blocks of duplicated|"
                          r"truncated|dangling|syntactically incomplete|corrupted or incompletely|begins mid|two fields both named|"
                          r"identical screen position|compile error", re.I)
    _high = [(x, f_) for x in code_arts for f_ in DDV.review_facts(store).get(x["id"], [])
             if f_.get("severity") == "high" and f_["category"] in ("defect", "data_integrity", "error_handling")]
    review_high = [f"{x['name']}: {P.lower_first(f_['statement'].rstrip('.'))} ({EV.cite(f_['lines'])})"
                   for x, f_ in _high if not _suspect.search(f_["statement"])]
    SCF.update({"shared": bool(shared_stores), "review_high": review_high,
                "capture_suspect": sorted({x["name"] for x, f_ in _high if _suspect.search(f_["statement"])})})
    SC = RT.scorecard(comps, AM, sec_c, sec_txt, SCF)
    conf_level = a["confidence"]["level"]
    cq = SC["Code quality"][0]
    if cq:
        debt_level = "Low" if cq <= 2 else "Medium" if cq == 3 else "High"
    from . import controls as FC
    missing_all = [m for m in _missing(cov, arts) if m["name"].upper() not in FX["formats"]
                   and m.get("kind") in ("program", "copybook", "job", "screen", "transaction", "procedure", "module", "class")]
    calc_routines = sorted({r_ for c in AM["components"] for r_ in c["routines"]
                            if any(w in r_.upper() for w in A_.RULE_WORDS) and not any(w in r_.upper() for w in ("READ", "WRITE", "OPEN", "CLOSE", "INIT", "FINAL", "PRINT"))})
    rates = FC.hard_rates(arts)
    pay_writers = {o["component"] for o in DM["occurrences"] if o["business"] == "Payment" and "W" in o["access"]}
    review_errors = EV.review_statements(store, arts, pay_writers or {x["name"] for x in code_arts},
                                         cats=("error_handling", "defect"), sev=("high", "medium"),
                                         rx=r"not checked|never checked|not detected|undetected|no error|goes undetected|"
                                            r"would stop|without closing|no error indicator")
    FCR = FC.assess(store, arts, sec_f, DM, CT, metrics, calc_routines, rates, fin,
                    ev={"totals": FX["totals"], "review_errors": review_errors,
                        'review_bypasses': EV.review_statements(store, arts, {x['name'] for x in code_arts},
                            cats=('defect', 'security', 'data_integrity'), sev=('high', 'medium'), rx=r'bypass|skip.{0,30}controls|overrides? both')})
    unhandled_txt = ("errors are swallowed in places" if any(f.get("rule") == "SEC-ERR" for f in sec_f) else
                     "the line-by-line review found errors that are not checked" if review_errors else "")
    tier1 = re.sub(r"(?i)tier", "", s["criticality_tier"] or "").strip() == "1"
    eol_comps = {}
    for t in techs:
        if t.get("status") in ("eol", "legacy"):
            eol_comps.setdefault(f"{t.get('name')} {t.get('version') or t.get('cycle') or ''}".strip(), []).append(t.get("file"))
    owner_it = s["it_reviewer"] or "IT application owner (to be named)"
    BR = FC.register({"fin": fin, "tier1": tier1, "fin_controls": FCR, "DM": DM, "rewrite": bool((a.get("facts") or {}).get("no_path")),
                      "eol": list(eol_comps), "eol_comps": eol_comps,
                      "eol_unused": {k_ for k_ in eol_comps if any(f.get("rule") == "CVE" and k_.split()[0].lower() in f["title"].lower()
                                                                     and "without using it" in (f.get("reviewed") or "") for f in sec_f)}, "skills": skill_list, "platforms": len(HP),
                      "creds": sorted({RT._file(f) for f in FX["creds"]}), "db_creds": bool(FX["db_creds"]),
                      "inject": sorted({RT._file(f) for f in sec_f if f.get("rule") in ("SEC-SQLI", "SEC-SQLDYN", "SEC-CMD")}),
                      "inject_live": sorted({RT._file(f) for f in sec_f if f.get("rule") in ("SEC-SQLI", "SEC-SQLDYN", "SEC-CMD")
                                             and not f.get("reviewed")}),
                      "inject_sql": any(f.get("rule") in ("SEC-SQLI", "SEC-SQLDYN") and not f.get("reviewed") for f in sec_f),
                      "inject_cmd": any(f.get("rule") == "SEC-CMD" and not f.get("reviewed") for f in sec_f),
                      "existing_totals": "; ".join(f"{c_}: {EV.totals_sentence(FX['totals'], c_)} (within one program only)"
                                                   for c_ in sorted(FX["totals"]) if EV.totals_sentence(FX["totals"], c_)),
                      "missing": len(missing_all), "owner_it": owner_it,
                      "owner_fin": s["business_owner"] or "Business owner (finance; to be named)",
                      "owner_sec": "Information security (to be named)", "owner_ea": "Enterprise architecture (to be named)"})
    from . import codefindings as CFM
    CF = CFM.select(store, code_arts, DDV.review_facts(store))
    for cf_ in CF:
        L_, I_, why_l_, why_i_ = CFM.rate(cf_)
        BR.append({"title": CFM.short(cf_["text"]), "brief": CFM.short(cf_["text"], 120), "cat": "Code finding", "L": L_, "I": I_,
                   "score": L_ * I_,
                   "why_L": why_l_,
                   "why_I": why_i_,
                   "comps": [cf_["file"]], "owner": owner_it, "existing": "None visible in the code",
                   "mit": "Confirm the intended rule with the business owner, correct the source, and add a test that records the new behavior"})
    BR.sort(key=lambda r_: -r_["score"])
    from core import report_review as RRV
    RR = RRV.verdicts(store)
    if RR:
        _kept = []
        for r_ in BR:
            v_ = RR.get(RRV.claim_key(RRV.risk_text(r_["title"], r_["comps"]))) or {}
            if v_.get("verdict") == "unsupported":
                continue
            if v_.get("verdict") == "partly" and v_.get("correction"):
                r_["why_L"] = f"{r_['why_L']}; the code check corrected this: {v_['correction']}"
            _kept.append(r_)
        BR[:] = _kept
    for i, r_ in enumerate(BR, 1):
        r_["id"], r_["rating"] = f"R-{num}-{i:02d}", FC.band(r_["score"])
    risks = BR
    top = BR[0] if BR else None
    from . import options as OP
    texts = {x["name"]: x.get("transcription") or "" for x in arts}
    legacy_ui = {x["name"] for x in arts if re.search(r"IE ?6|best viewed|<frameset|<font\b|bgcolor=|ActiveX|3270",
                                                         x.get("transcription") or "", re.I)}
    legacy_ui |= {c["name"] for c in comps if any((f.get("rule") or "") == "UIB-OBSOLETE"
                                                  for f in ((c.get("scores") or {}).get("ux") or {}).get("factors", []))}
    CD = OP.components(AM, techs, sec_f, texts, fin, legacy_ui, copies=any(len(g["copies"]) >= 2 for g in DM["entities"]),
                       cics=CICS, screen_copies=COPIES)
    PR = OP.program(CD, len(HP))
    multi_copies = sum(len(g["copies"]) for g in DM["entities"] if len(g["copies"]) >= 2)
    EST = OP.estimate(CD, {"fin": fin, "copies": multi_copies, "fixes": len(CF), "migrate": PR["code"] in ("rearchitect", "replace", "replatform", "rebuild"),
                           "copy_names": [g["name"].lower() for g in DM["entities"] if len(g["copies"]) >= 2]})
    phased = PR["code"] in ("rearchitect", "replace")
    span = OP.months({"phased": phased, "platforms": len(HP), "fin": fin}, EST)
    elapsed = OP.elapsed({"phased": phased, "platforms": len(HP), "fin": fin}, EST)
    cyc = "payment cycles" if fin else "business cycles"
    est_incl = [x for x in ("the test harness" if any(g["skill"] == "Test and QA" for g in EST["lines"]) else "",
                            "parallel runs" if fin and any("parallel" in w for g in EST["lines"] for w in g["work"]) else "",
                            "data migration" if multi_copies else "") if x]
    no_path_names = sorted({f"{t.get('name')}" for t in techs if t.get("status") in ("eol", "legacy")
                            and any(k.lower() in (t.get("name") or "").lower() for k in OP.NO_PATH)})
    OPTS = OP.scores({"no_path": no_path_names, "platforms": len(HP), "program_code": PR["code"], "fixes": len(CF),
                      "posting": sum(1 for c in CD if c["code"] == "consolidate") + (1 if any(c["code"] == "retain" and "Batch" in
                                     next((x["role"] for x in AM["components"] if x["name"] == c["name"]), "") for c in CD) else 0)})
    if OPTS[0][0].split(" (")[0].lower() != PR["label"].split(" (")[0].lower():
        OPTS[0] = (PR["label"],) + tuple(OPTS[0][1:])
    v = {"code": PR["code"], "label": PR["label"], "meaning": PR["meaning"], "meaning_plain": PR["meaning"],
         "bucket": "rebuild" if PR["code"] in ("rearchitect", "replace") else "patch"}
    disposition = PR["label"]
    horizon = (f"Mid term, {span[0]}–{span[1]} months, delivered in phases (12.4)" if PR["code"] in ("rearchitect", "replace")
               else "Short term, 0 to 12 months" if span[1] <= 12 else "Mid term, 1 to 3 years")

    # cover, contents, rating scales
    kv(T[0], {"Application": f"{name} ({app_id})", "Client": s["client"] or doc.unknown("Client organization", "Cover"),
                         "Engagement": s["engagement"] or doc.unknown("Engagement name", "Cover"), "Version": version_txt,
                         "Date": today.strftime("%B %d, %Y"), "Classification": s["classification"]}, start=0)
    title = doc.para('Application Assessment Report')
    if title is not None:
        _set_para(title, re.sub(r'[^\w ]', ' ', name).strip() + ' Application Assessment')
        title.style = doc.d.styles['Title']
        from docx.shared import Pt
        for run in title.runs:
            run.font.color.rgb = RGBColor(0, 0, 0)
            run.font.size = Pt(26)
            run.font.underline = False
        for para in doc.d.paragraphs[:4]:
            pr = para._p.pPr
            if pr is not None:
                for border in list(pr.findall(qn('w:pBdr'))):
                    pr.remove(border)
    doc.new_para('This report assesses the supplied source, its architecture and control findings, and candidate improvements. '
                 'Validate significant source layout differences, approved business policy and deployment details before final acceptance or production change.', T[0]._tbl)
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
            "Technical debt level": f"{debt_level}: code quality is rated {RT.words(cq)} in 6.1, which includes "
                                    f"unconfirmed calculation test coverage. Maintainability alone: {R.explain_program(a, 'tech_debt')}",
            "Open critical or high vulnerabilities": f"{crit_high} ({sum(1 for f in sec_f if f['severity'] == 'critical')} critical, "
                                                     f"{sum(1 for f in sec_f if f['severity'] == 'high')} high); register in 8.3",
            "Highest risk score": (f"{top['score']} of 25, {top['rating']} ({top['id']}: {top.get('brief') or top['title']}); "
                                   f"{sum(1 for r_ in BR if r_['rating'] == 'High')} risk{'s' if sum(1 for r_ in BR if r_['rating'] == 'High') != 1 else ''} rated High in 9.1" if top else "None"),
            "End-of-life exposure": "; ".join(f"{t.get('name')} {t.get('version') or t.get('cycle') or ''}".strip()
                                              + (f" (ended {t['eol']})" if t.get("eol") else f" ({_status_word(t).lower()})")
                                              for t in eol[:5]) or ("None identified; deployed versions are not confirmed (3.2), so exposure is not ruled out"
                                                    if any(not t.get("version") for t in techs) else "None identified"),
            "Recommended disposition": f"{disposition}: {_disp_plain(v)}",
            "Recommended timing": horizon}
    kv(T[5], snap)
    sec = FX["sev"]
    from . import plain as P
    top_sec = sorted(sec_f, key=lambda f: SEV.index(f["severity"]))
    worst3 = []
    for f in top_sec:
        w = P.describe(f)[0]
        if w not in [x[0] for x in worst3]:
            worst3.append((w, f["severity"]))
        if len(worst3) == 3:
            break
    health_c = SC["overall"][0]
    CONCERN = {"Maker-checker approval": "segregation of duties", "Audit trail integrity": "audit integrity",
               "Error handling in posting": "complete and accurate posting",
               "Reconciliation between stores": "undetected misstatement", "Automated tests on calculations":
               "undetected calculation errors", "Control totals on file exchanges": "complete and accurate posting"}
    poor_fc = [r_ for r_ in FCR if r_[3] and r_[3] >= 4]
    reviewed = [x for x in code_arts if str(x["id"]) in DD]
    n_facts = sum(len((DD.get(str(x["id"])) or {}).get("facts") or []) for x in reviewed)
    lead = P.sentence([f"{_lc(r_.get('brief') or r_['title'])}" for r_ in BR[:3]])
    findings_txt = [
        ({1: "One problem stands out: ", 2: "Two problems stand out: "}.get(len(BR[:3]), "Three problems stand out: ")
         + lead + ". " if BR else "")
        + (DA.fragmentation_sentence(DM) + " " if DA.fragmentation_sentence(DM) else "")
        + f"Provisional overall condition is {RT.words(health_c)} (1 is best, 5 is worst)"
        + (", and technology lifecycle concerns need attention (6.2)" if eol else "")
        + f". {_recommend(disposition, _disp_plain(v))}",
        (f"Financial controls (Section 8.6). Rated poor or worse: "
         + P.sentence([_lc(r_[0]) for r_ in poor_fc]) + ". For a payment system these touch "
         + P.sentence(list(dict.fromkeys(CONCERN.get(r_[0], "financial accuracy") for r_ in poor_fc))) + ".")
        if poor_fc else "",
        ("Evidence quality (Section 13.2). "
         + (f"One of the {FX['files']} source files, " if len(RQ) == 1 else f"{len(RQ)} of the {FX['files']} source files, ")
         + P.sentence([f"{r_['name']} ({DDV.report_reason(r_['issues'][0])})" for r_ in RQ[:4]])
         + (", is" if len(RQ) == 1 else ", are") + " incomplete or unclear in places. A complete copy is needed before "
         "the findings that rest on those lines can be relied on, so statements that would rest on them are held back.") if RQ else "",
        ("Code review (Section 3.6). The components have not yet been reviewed line by line; this report rests on the "
         "automated checks only.") if not reviewed else
        (f"Code review (Section 3.6). " + ("Each of the " if len(reviewed) == len(code_arts) else f"{len(reviewed)} of the ")
         + f"{len(code_arts)} source files {'was' if len(reviewed) == 1 or len(reviewed) == len(code_arts) else 'were'} "
           f"reviewed line by line; {n_facts} "
           f"statements passed two checks against the code and are cited by line."),
        (f"Architecture (Sections 4.4 and 5.5). The application spans {len(HP)} platforms for its code and data ({', '.join(HP)}), "
         + ("exchanges data through files and shared databases" if shared_stores else "has no service or API layer identified in the supplied code")
         + f", and needs {len(skill_list)} specialist skill sets ({P.sentence(skill_list)}); availability and support cover are to confirm.")
        if len(HP) >= 3 else "",
        "Security (Section 8). The rule-based scan recorded " + _and([f"{n} {k}" for k, n in (("critical", sec.get("critical", 0)),
            ("high", sec.get("high", 0)), ("medium", sec.get("medium", 0))) if n] or ["no critical, high or medium"]) + " security issues"
        + (", none of them critical" if not sec.get("critical") and (sec.get("high") or sec.get("medium")) else "")
        + (f". The most serious: {P.sentence([P.tagged(w, sv) for w, sv in worst3])}" if worst3 else "") + ". "
        + ("Personal data is referenced in the supplied source. The findings describe where that data may be exposed. " if pii else "")
        + "This does not establish that the application is secure. Calculation and control defects found by the line-by-line review are recorded in 3.6 and 8.6. "
        + f"Security posture is rated {RT.words(sec_c)}, derived from the control ratings in 8.1.",
        (f"Supportability (Section 6.2). {P.sentence([_eol_plain(t) for t in eol[:3]])}. Unsupported software no longer "
         f"receives security fixes, so its known weaknesses stay open until it is upgraded or replaced.")
        if eol else "Supportability (Section 6.2). No end-of-support technology was identified; support for unconfirmed versions remains to confirm.",
        (f"Risk (Section 9). {sum(1 for r_ in BR if r_['rating'] == 'High')} of {len(BR)} risks are rated High. The highest: "
         + P.sentence([f"{_lc(r_.get('brief') or r_['title'])} ({r_['score']} of 25)" for r_ in BR[:3]]) + ".") if top else "",
        f"Effort (Section 12.4). The unvalidated planning scenario is {EST['low']}–{EST['high']} person-weeks across "
        f"{len(EST['lines'])} skill set(s); {elapsed}" + (f", because the order of work and the {cyc}, not the effort, set "
        f"the pace" if phased else "") + ". "
        f"This covers the {FX['files']} source files provided only" + (f" and includes {P.sentence(est_incl)}" if est_incl else "")
        + (f"; {len(missing_all)} referenced components were not provided" if missing_all else "")
        + ". This is not a delivery forecast or budget. Validate scope, staffing and business policy before accepting the estimates or changing production behavior.",
    ]
    from core import exec_summary as ES
    _es = ES.current(store)
    if _es:
        findings_txt = ES.paragraphs(_es)
    _last = doc.replace("Summarize in three to five", [Q.QUALIFICATION] + findings_txt)
    if _es and _last is not None:
        _fact_table(doc, T, store, _es, _last._p)
    doc.replace("List any condition that warrants action", "Validate the source findings and approved business policy before production change. Prioritize any confirmed unintended control override or exposure:")
    imm = []
    owner_it = s["it_reviewer"] or "IT application owner (to be named)"
    groups_ = {}
    for f in sorted(sec_f, key=lambda f: SEV.index(f["severity"])):
        if f["severity"] in ("low", "info") or f["category"] == "privacy":
            continue
        groups_.setdefault("CREDS" if f.get("rule") in EV.CREDENTIAL_RULES else f.get("rule") or f["title"], []).append(f)
    for rule, fs in list(groups_.items())[:8]:
        files = sorted({RT._file(f) for f in fs})
        wh, why_, fix_ = P.describe(fs[0])
        if rule == "CREDS":
            kinds_ = list(dict.fromkeys(P.describe(f)[0] for f in fs))
            page_ = any(f.get("rule") == "UIS-PREFILL" or RT._file(f).lower().endswith((".html", ".htm", ".js", ".asp", ".jsp"))
                        for f in fs)
            wh, why_ = P.sentence(kinds_), ("anyone who can read the code or open the page can use them" if page_
                                            else "anyone who can read the code can use them")
        cond = f"{_cap(wh)}, in {_and(files[:3])}"
        if why_:
            cond += f". {_cap(why_)}."
        act = _cap(fix_ or (fs[0].get("detail") or "Fix the finding")) + "."
        if rule == "CREDS":
            act = "Change the exposed passwords and keys now, then move them to a secrets store and remove them from the code."
        imm.append([str(len(imm) + 1), cond, act, owner_it, f"Within {min(_due_days(f) for f in fs)} days"])
    for r_ in BR:
        if r_["rating"] == "High" or (r_["cat"] == "Financial control" and r_["score"] >= 12):
            imm.append([str(len(imm) + 1), r_["title"], r_["mit"].split(". Owner")[0], r_["owner"],
                        "Within 30 days" if r_["rating"] == "High" else "Within 90 days"])
    rows(T[6], imm, empty="None")

    # 2 business context
    kv(T[7], {"Business capability": s["purpose"] or doc.unknown("Business capability supported", "2.1"),
                         "Regulatory": s["regulatory_basis"] or doc.unknown("Regulatory, contractual or policy basis", "2.1"),
                         "Business owner": s["business_owner"] or UNKNOWN,
                         "Subject matter experts": doc.unknown("Subject matter experts", "2.1"),
                         "Year introduced": doc.unknown("Year introduced and major rewrites", "2.1"),
                         "Known drivers of change": doc.unknown("Known drivers of change", "2.1")})
    screens = FX["screens"]
    rows(T[8], [["Business users of the application screens", UNKNOWN, doc.unknown("Number of users by group", "2.2"),
                            f"{len(screens)} screen(s): " + ", ".join(e['name'][:40].strip() for e in screens[:8])
                            + (f" and {len(screens) - 8} more" if len(screens) > 8 else "") if screens else UNKNOWN,
                            UNKNOWN]] + ([["Batch schedule and operator involvement to confirm", "Internal", "Not applicable",
                                           "Scheduled batch jobs", UNKNOWN]] if _jobs(store) else []))
    flows = store.get_meta("ui_flows") or {}
    figs = {}      # figures actually inserted, so captions and cross-references never claim one that is missing
    proc = doc.para("[Insert process flow diagram")
    if proc is not None:
        from . import figures as FG
        try:
            uf = RD.map(FG.process(AM, DM, name))
        except Exception:  # noqa: BLE001
            uf = diagrams.get("userflow")
        if uf:
            try:
                pic = doc.picture(png(uf, scale=1.6), proc._p, 6.8, max_h=4.0)
                doc.new_para(f"Figure 1. Current-state process for {name}: each step in processing order, grouped by the platform "
                             f"it runs on. The order is inferred from the code and must be confirmed with the business owner.",
                             pic._p, italic=True)
                figs["process"] = 1
            except Exception:  # noqa: BLE001
                log.exception("Process figure could not be inserted; the report continues without it")
        proc._p.getparent().remove(proc._p)
    doc.replace("Document each business process the application supports", "The process below is drawn from what each "
                "component reads, calculates and writes, from the arrival of inputs to the outputs and look-ups. Manual steps, "
                "approval points outside the application and handoffs are to be mapped with stakeholders (open item).")
    doc.unknown("Swimlane process map with business actors and manual steps", "2.3")
    steps = []
    for j in (flows.get("journeys") or [])[:3]:
        for st in j["steps"]:
            steps.append([str(len(steps) + 1), "Business user", f"Uses screen {st['screen']}", "Manual (screen entry)",
                          UNKNOWN, UNKNOWN, "" if st.get("captured") else "Screen referenced but not provided"])
    jobs = _jobs(store)
    for jb in jobs[:6]:
        steps.append([str(len(steps) + 1), "Scheduler", f"Runs batch job {jb['name']}", "Automated", UNKNOWN, UNKNOWN, ""])
    if not (flows.get("journeys") or [])[:3]:
        from .figures import STAGES, _stage, _step
        order = [k for k, _ in STAGES]
        job_names_ = {jb["name"].lower() for jb in jobs}
        for c in sorted((c for c in AM["components"] if c["name"] not in COPIES and c["role"] != "Database definition"
                         and c["name"].rsplit(".", 1)[0].lower() not in job_names_),
                        key=lambda c: order.index(_stage(c))):
            if jobs and c["role"] not in ("Batch program", "Program"):
                continue
            verb, ins, outs = _step(c, DM)
            batch = "Batch" in c["role"] or "procedures" in c["role"]
            job = not batch and bool(c["writes"]) and c["layer"] == "Application"
            steps.append([str(len(steps) + 1), "Scheduled run (to confirm)" if batch else "Program run (trigger to confirm)" if jobs
                          else "User-started program" if job else "Business user", f"{c['name']}: {verb}",
                          "Automated" if batch else "To confirm" if jobs else "Automated, started by a user" if job else "Manual (screen entry)",
                          ", ".join(ins[:4]) or "–", ", ".join(outs[:4]) or "–", ""])
    rows(T[9], steps, empty="No process steps could be derived from the source; to be mapped with stakeholders.")
    cycles = []
    for x in code_arts:
        for n_, l_ in enumerate((x.get("transcription") or "").splitlines()[:40], 1):
            m_ = re.search(r"\b(MONTHLY|DAILY|WEEKLY|QUARTERLY|ANNUAL|YEAR-END|NIGHTLY)\b", l_, re.I)
            if m_ and re.search(r"^\s*(\d{6})?\s*[*]|^\s*\*|//|--|^\s*'|^\s{5,}C?\s*\*", l_):
                cycles.append([f"{m_.group(1).title()} run of {x['name']} (stated in a code comment, line {n_})",
                               doc.unknown(f"Schedule of the {m_.group(1).lower()} run of {x['name']}", "2.4", "IT"),
                               "High", UNKNOWN])
                break
    job_rows, used_cycles = [], set()
    for jb in jobs[:6]:
        hit = next((i_ for i_, c_ in enumerate(cycles) if jb["name"].lower() in c_[0].lower()), None)
        if hit is not None:
            used_cycles.add(hit)
            cm_ = re.match(r"(\w+) run of .*line (\d+)\)", cycles[hit][0])
            job_rows.append([f"Batch job {jb['name']} ({cm_.group(1).lower()}; stated in a code comment, line {cm_.group(2)})" if cm_
                             else f"Batch job {jb['name']}", cycles[hit][1], "High", UNKNOWN])
        else:
            job_rows.append([f"Batch job {jb['name']}", doc.unknown(f"Schedule of batch job {jb['name']}", "2.4", "IT"), "High", UNKNOWN])
    rows(T[10], job_rows + [c_ for i_, c_ in enumerate(cycles) if i_ not in used_cycles],
         empty="No scheduled cycles were identified in the source; business calendar to be confirmed with the business owner.")
    ux_issues = [f for f in findings if f["category"] in ("usability", "accessibility")]
    pain_ = _pain_points(ux_issues)
    doc.replace("Record pain points in the words", [
        "Stakeholder interviews were not part of this review, so pain points are not recorded in stakeholders' words "
        "(open item)." + (" What the screens themselves show:" if pain_ else "")] + pain_)
    if not ux_issues:
        pass
    doc.unknown("Business pain points in stakeholders' words (interviews)", "2.5")

    # 3 technical profile
    types = sorted({(x.get("artifact_type") or "code") for x in arts})
    langs = {}
    for x in code_arts:
        k_ = x.get("language") or x.get("artifact_type") or "other"
        langs[k_] = langs.get(k_, 0) + len((x.get("transcription") or "").splitlines())
    kinds = dict(cov.get("entities_by_kind") or {})
    if kinds.get("screen"):
        kinds["screen"] = len(screens)
    kinds["data_store"] = len(FX["data_stores"])
    app_type = ", ".join(sorted({"Batch process" if k in ("job", "program") else "Web application" if k in ("api_endpoint",) else ""
                                 for k in kinds} - {""})) or UNKNOWN
    if any("screen" in t or "ui" in t for t in types) or kinds.get("screen"):
        app_type = ", ".join(sorted(set(app_type.split(", ")) - {UNKNOWN} | {"Online screens"}))
    cobolish = [x for x in code_arts if re.search(r"cobol|rpg|pl/i|assembl|jcl|ims", (x.get("language") or "").lower())]
    kv(T[11], {
        "Application type": app_type,
        "Build origin": "Custom built (source code provided; who maintains it is to be confirmed)",
        "Legacy lineage": (f"{len(cobolish)} of {len(code_arts)} source files are mainframe or midrange languages "
                           f"({', '.join(sorted({x.get('language') for x in cobolish})[:8])})") if cobolish else "No legacy lineage identified",
        "Deployment model": s["deployment"] or doc.unknown("Deployment model and hosting", "3.1", "IT"),
        "Environments": doc.unknown("Environments (production, test, development, disaster recovery)", "3.1", "IT"),
        "Source code location": doc.unknown("Source code repository and version control", "3.1", "IT"),
        "Size indicators": f"{FX['lines']:,} lines in {FX['files']} source files"
                           + (f" and {FX['images']} screen image(s)" if FX["images"] else "") + "; " + ", ".join(
            f"{kinds.get(k)} {k.replace('_', ' ')}(s)" for k in ("program", "class", "screen", "table", "job", "data_store") if kinds.get(k))})
    by_layer = {}
    for t in techs:
        by_layer.setdefault(_layer(t), []).append(t)
    stack = {}
    for layer, ts in by_layer.items():
        stack[layer] = ["; ".join(f"{t.get('name')} {t.get('version') or t.get('cycle') or '(version not confirmed)'}".strip() for t in ts),
                        "; ".join(sorted({(t.get("vendor") or _vendor(t)) for t in ts})),
                        "; ".join(sorted({str(t.get("mainstream") or t.get("eol") or t.get("support") or "") for t in ts} - {""})) or UNKNOWN,
                        "; ".join(sorted({str(t.get("extended") or (t.get("eol") if t.get("mainstream") else "") or "")
                                          for t in ts} - {""})) or UNKNOWN,
                        "; ".join(sorted({_status_word(t) for t in ts}))]
    _infer_stack(stack, arts, DM, AM, store, jobs=_jobs(store))
    t12 = T[12]
    for row in t12.rows[1:]:
        label = row.cells[0].text.strip()
        vals = stack.get(label) or ["None identified in the source", "", "", "", ""]
        if label in ("Operating system", "Infrastructure", "Web and application server", "Identity and authentication") and label not in stack:
            vals = [doc.unknown(f"{label} and version", "3.2", "IT"), "", "", "", ""]
        for j, val in enumerate(vals, 1):
            set_cell(row.cells[j], val)
    rows(T[13], [[doc.unknown("Licensing and contracts for commercial products", "3.3", "IT"), "", "", "", "", ""]])
    creds_n = len(FX["creds"])
    hard = [{"title": f"Credential: {RT._file(f)}" + (f":{(f.get('evidence') or [{}])[0].get('line')}"
                                                   if (f.get("evidence") or [{}])[0].get("line") else "")} for f in FX["creds"]] + [
        {"title": r_} for r_ in rates] + [
        {"title": f"path {m_.group(1)} in {x['name']}"} for x in code_arts
        for m_ in re.finditer(r"[\"']([A-Za-z]:\\[^\"'\n]{2,60})[\"']", x.get("transcription") or "")] + [
        {"title": fct["text"]} for c in comps for fct in c["scores"]["coupling"]["factors"] if "hard" in fct["text"].lower()]
    cfg_ = [CFM.short(f_["statement"], 120) for fs_ in DDV.review_facts(store).values() for f_ in fs_
            if f_.get("category") == "configuration" and f_.get("review") in (None, "supported", "partly_supported", "corrected")]
    hard += [{"title": t_} for t_ in cfg_[:6]]
    doc.replace("Describe hard-coded business rules", [
        (f"Business rates and run parameters held in the code rather than in a maintained table: {'; '.join(rates[:4])}.")
        if rates else ("The rule-based scan did not match its rate patterns, but the line-by-line review found values fixed in the code: "
                       + "; ".join(cfg_[:3]) + ". Policy owners should confirm whether these should live in a maintained table.") if cfg_ else "The rule-based scan did not match its rate patterns. This does not establish that hard-coded business values are absent; review thresholds, dates, receipt rules and dataset literals in Section 3.6.",
        f"{creds_n} hard-coded credential(s) were also found; they are security findings (8.3), not configuration." if creds_n else "",
        "Where routine policy or rate changes require a code change, the item appears in the technical debt register (7.3)."])

    # 4 architecture
    ref = doc.para("Figure 1. Reference architecture layout")
    if ref is not None:
        img = ref._p.getprevious()
        arch = diagrams.get("architecture")
        has_img = img is not None and bool(img.xpath(".//w:drawing"))
        if has_img:
            img.getparent().remove(img)      # the template's stock picture is not this program's architecture
            if arch is not None:
                try:
                    from .editorial import _diagram
                    doc.picture(_diagram(comps), ref._p.getprevious(), 6.8, max_h=4.0)
                    figs["arch"] = 2
                except Exception:  # noqa: BLE001
                    log.exception("Component overview figure could not be inserted; the report continues without it")
        _set_para(ref, (f"Figure 2. Component overview of {name}. " if figs.get("arch") else f"Component overview of {name} (no diagram in this report). ")
                  + "Layer roles and source-derived connections are listed below; production boundaries need confirmation.",
                  italic=True)
        anchor = doc.new_para("Architecture at a glance", ref._p, bold=True)._p
        for layer in ("Presentation", "Application", "Data", "Integration"):
            cs = [c for c in AM["components"] if c["layer"] == layer]
            if cs:
                anchor = doc.new_para(f"{layer} layer: " + "; ".join(
                    (f"{c['name']}, a screen image of the page in {COPIES[c['name']]}" if c["name"] in COPIES else
                     f"{c['name']}, {c['role'].lower()}" + (f" in {c['language']}" if c["language"] and
                                                            c["language"].lower() not in c["role"].lower() else "")
                     + (f" using {', '.join(c['tech'])}" if c["tech"] else "")) for c in cs) + ".", anchor, bullet=True)._p
        if AM["stores"]:
            held = sorted(AM["stores"])[:12]
            have = [x for x in held if not x.endswith(" (not provided)")]
            gone = [x[:-len(" (not provided)")] for x in held if x.endswith(" (not provided)")]
            anchor = doc.new_para("Data it holds: " + ", ".join(have or ["none provided"]) + "."
                                  + (f" Referenced but not provided: {', '.join(gone)}." if gone else ""), anchor, bullet=True)._p
        anchor = doc.new_para(f"Platforms hosting code or data: {', '.join(HP)}.", anchor, bullet=True)._p
        anchor = doc.new_para("Component inventory", anchor, bold=True)._p
        ct = _table_after(doc, T[20], anchor, ["Component", "Layer", "Role", "Technology", "Reads / uses", "Writes"],
                     [[c["name"], c["layer"], c["role"], ", ".join([c["language"]] + c["tech"]).strip(", ") or UNKNOWN,
                       ", ".join(c["reads"][:6]) or "–", ", ".join(c["writes"][:6]) or "–"] for c in AM["components"]])
        doc.new_para("", ct._tbl)
    doc.replace("The reference layout below shows", "The architecture below is derived from the supplied components in "
                "Section 3, in the standard layer order so it can be read alongside other application reports.")
    doc.remove("Each application report should include the following views")
    doc.unknown("Deployment (physical) architecture: servers, environments, network zones", "4.1", "IT")
    ins = doc.para("[Insert diagrams A to E here")
    if ins is not None:
        anchor = ins._p
        from . import figures as FG
        try:
            diagrams["context_sys"] = RD.map(FG.context(AM, DM, name))
        except Exception:  # noqa: BLE001
            log.exception("System context diagram could not be built; the report continues without it")
        for key, cap in (("context_sys", "System context: user groups, upstream systems and shared-data owners, the "
                                               "application by platform, and downstream systems; dashed boxes are systems "
                                               "still to be named"),
                            ("data", "Data model: tables, columns and keys used by the application")):
            dg = diagrams.get(key)
            if dg is None:
                continue
            n = 3 + sum(1 for k_ in ("context_sys", "data") if figs.get(k_))
            try:
                pic = doc.picture(png(dg, scale=1.5), anchor, 6.8)
                capp = doc.new_para(f"Figure {n}. {cap}. Validation with the IT owner: pending.", pic._p, italic=True)
            except Exception:  # noqa: BLE001
                log.exception("Diagram %s could not be inserted; the report continues without it", key)
                continue
            figs[key] = n
            anchor = capp._p
        ins._p.getparent().remove(ins._p)
    _missing_fig = "not included in this report"
    fill_col(T[14], 2, {"A.": f"Source-derived inventory (Figure {figs['arch']}); production boundary to confirm" if figs.get("arch")
                        else f"Source-derived inventory in 3.2 (diagram {_missing_fig})",
                        "B.": "Inferred only (4.5); hosting and network detail to be confirmed",
                        "C.": f"Complete at system level (Figure {figs['context_sys']}); systems at each end to be named"
                        if figs.get("context_sys") else f"Pending (diagram {_missing_fig})",
                        "D.": f"Complete (Figure {figs['data']})" if figs.get("data") else "Pending",
                        "E.": "Pending: requires the portfolio inventory"})

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
    rd_, wr_ = {}, {}
    for o in DM["occurrences"]:
        (wr_ if "W" in o["access"] else rd_).setdefault(o["store"], set()).add(o["component"])
    in_files = sorted(s_ for s_ in rd_ if s_.endswith("-FILE") and not wr_.get(s_))
    out_files = sorted(s_ for s_ in wr_ if s_.endswith("-FILE"))
    shared_ro = sorted({o["store"] for o in DM["occurrences"] if o["placeholder"] and o["business"] and "W" not in o["access"]})
    ups = ([f"whatever produces {_and(in_files)}"] if in_files else []) + (
        [f"the owners of the shared tables {_and(shared_ro)}"] if shared_ro else []) + \
        [m["name"] for m in extern if m.get("kind") in ("external_system", "system")]
    ups_unnamed = bool(in_files or shared_ro)
    downs = [f"the system that receives {f_} (to be named by APP ID)" for f_ in out_files]
    by_se = {}
    for o in DM["occurrences"]:
        by_se.setdefault((o["store"], o["engine"]), set()).add(o["component"])
    shared = sorted({s_ for (s_, e_), cs_ in by_se.items() if len(cs_) > 1})
    if downs:
        doc.unknown("Name the downstream systems (by APP ID) that receive " + ", ".join(out_files), "4.3", "IT")
    if ups:
        doc.unknown("Name the upstream systems (by APP ID) that produce " + (", ".join(in_files) or "the shared data"), "4.3", "IT")
    for starts, text in (("Systems this application depends on", "Systems this application depends on: " + (P.sentence(ups) or "none identified in the source") + "."
                          + (" None of these has been named yet." if ups_unnamed else "")),
                         ("Systems that depend on this application", "Systems that depend on this application: " + (
                             P.sentence(downs) if downs else doc.unknown("Downstream systems", "4.3", "IT")) + "."),
                         ("Shared components", "Shared components: " + (
                             "data used by more than one component: " + ", ".join(shared) if shared else "no directly shared data was identified in the supplied source")
                          + ("; multiple source definitions describe the same business data (5.5)." if multi_copies else ".")),
                         ("Hidden or informal dependencies", "Hidden or informal dependencies: " + (
                             f"{len(missing)} components referenced but not provided: " + ", ".join(
                                 m["name"] + (" (display file)" if m["name"].upper() in EV.display_files(arts) else "")
                                 for m in missing) + "."
                             if missing else "none identified in the source."))):
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
    obs = [f"{t}. {w} {m}" for t, w, m in obs_src]
    obs.insert(0, f"The current source identifies {len(FX['data_stores'])} data store(s), excluding placeholders and display files (3.1).")
    if (a["scores"].get("coupling") or {}).get("score") is not None:
        obs.append(f"Code-level coupling (calls between files) is {R.explain_program(a, 'coupling')} This only counts "
                   "calls from one program to another, not the shared data described above.")
    doc.replace("Record structural concerns", obs)

    # 5 data
    tables = store.entities("table")
    dstores = [d_ for d_ in store.entities("data_store") if d_["origin"] != "placeholder" and not _is_interface(d_)
               and d_["name"] not in DM["displays"]]
    biz = {o["store"]: o["business"] for o in DM["occurrences"]}

    def _cls(name):
        b = biz.get(name)
        if fin and b in ("Payment", "Account", "Invoice", "Ledger", "Transaction", "Claim", "Payroll"):
            return ("Confidential (financial; review)", "Financial records")
        if name in personal:
            return "Restricted", "Personal data"
        if re.search(r"CONTACT|ADDRESS|BANK|CUSTOMER|PERSON|EMPLOYEE|PAYEE|BENEFICIARY|TAXPAYER", name, re.I):
            return "Confidential (name suggests personal or banking data; review)", "Possible personal or banking data; review"
        if s["privacy_obligations"] or s["regulatory_basis"]:
            return "Internal (review against the client's data practices policy)", "None identified"
        return "Internal", "None identified"
    rows(T[16], [[_entity_label(t_), _sor(store, t_), _volume(t_), UNKNOWN, *_cls(t_["name"])] for t_ in tables[:30]] +
         [[_entity_label(d_), _sor(store, d_), UNKNOWN, UNKNOWN, *_cls(d_["name"])] for d_ in dstores[:10]])
    _col_widths(T[16], [1.7, 1.45, 1.1, 0.9, 0.85, 0.9])
    if fin and any(_cls(x["name"])[1] == "Financial records" for x in list(tables[:30]) + list(dstores[:10])):
        doc.new_para("Financial records should be checked for banking details (account and routing numbers), which "
                     "would need the same protection as personal data.", T[16]._tbl)
    doc.unknown("Data volumes, retention requirements and system-of-record status (5.1)", "5.1")
    fill_col(T[17], 1, {"": ["Not rated", "Requires access to production data; not part of this review."]})
    EDIT = re.compile(r"WHEN\s+OTHER\b(?!S)|NOT\s+NUMERIC|IS\s+NUMERIC|\bINVALID\b|VALIDATE|\bmaxlength=|%CHECK\b", re.I)
    edits = []
    for x in code_arts:
        ln_ = [n_ for n_, l_ in enumerate((x.get("transcription") or "").splitlines(), 1) if EDIT.search(l_)]
        if ln_:
            edits.append(f"{x['name']} ({SX.line_list(ln_[:4])})")
    swallowed = sorted({RT._file(f) for f in sec_f if f.get("rule") == "SEC-ERR"})
    if edits or swallowed:
        fill_col(T[17], 1, {"Validation controls": ["3" if edits else "4",
                                                    (f"Edit checks in the code: {'; '.join(edits[:4])}. " if edits else "")
                                                    + (f"Errors swallowed in {', '.join(swallowed)}, so bad data can pass silently (8.6)."
                                                       if swallowed else "") + " Rated from the code only."]})
    doc.unknown("Data quality ratings (requires production data)", "5.2")
    rpt_rows = []
    for o in DM["occurrences"]:
        if re.search(r"REPORT|RPT", o["store"], re.I) and "W" in o["access"]:
            rpt_rows.append([o["store"], f"Written by {o['component']}" + (" (the run's control report)" if "cobol" in o["component"].lower()
                                                                             or o["component"].lower().endswith(".cbl") else ""),
                             "Batch print / dataset", "Each run"])
    for m in missing_all:
        if re.search(r"RPT|REPORT", m["name"], re.I):
            caller = sorted(n_ for n_, t_ in texts.items() if m["name"] in t_)
            rpt_rows.append([m["name"], f"Report program started by {', '.join(caller) or 'the application'}; source not provided",
                             "Batch program", "Each run (to confirm)"])
    rows(T[18], [[f"RPT-{num}-{i:02d}", r_[0], UNKNOWN, r_[2], r_[3], UNKNOWN, UNKNOWN,
                  "Replace with reporting from the system of record (12.3)"] for i, r_ in enumerate(rpt_rows[:15], 1)])
    if rpt_rows:
        doc.new_para("Report notes: " + "; ".join(f"{r_[0]}: {r_[1]}" for r_ in rpt_rows) + ".", T[18]._tbl)
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
        note = (t.get("note") or "").strip()
        eol_rows.append([t.get("name"), t.get("version") or t.get("cycle") or "Not confirmed",
                         str(t.get("mainstream") or t.get("eol") or "") or "Not published",
                         str(t.get("extended") or (t.get("eol") if t.get("mainstream") else "") or "") or "Not published", ml or "", path, "See note below" if note else ""])
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
                          "Estimated total remediation effort": f"Part of the {EST['low']}–{EST['high']} person-weeks "
                                                                f"estimated in 12.4, which covers the fixes and the "
                                                                f"recommended {_noun(disposition)}",
                          "Effect on delivery": (f"{_cap(P.what(debt_f[0]['rule'], debt_f[0]['text']))} "
                                                 f"({debt_f[0].get('component', '')}): {P.why(debt_f[0]['rule']) or 'change is slower and riskier'}.")
                                                if debt_f else "No material effect identified.",
                          "Trend": "Not measurable from a single point-in-time review"})
    doc.replace("Where source code is available, run static analysis", "Indicators below are measured from the source "
                "code provided for this review; indicators that need a running build or test suite are marked not measured.")
    doc.replace("A single interview will often cover several applications", "No stakeholder interviews were held as part "
                "of this review; findings rest on the source code, screens and configuration listed in 13.2.")
    fill_col(T[22], 1, {
        "Lines of code": [", ".join(f"{k}: {v:,}" for k, v in sorted(langs.items(), key=lambda kv_: -kv_[1])), "Not applicable",
                          "Source code review", f"Screen images are not counted ({FX['images']})" if FX["images"] else ""],
        "Average and maximum cyclomatic complexity": [f"File-level estimate: average {metrics['avg']}, maximum {metrics['max']} ({metrics['max_file']}); routine-level complexity not measured",
                                                      "Routine-level target to confirm", "Decision-point count per file", "Validate with a control-flow analysis per routine"],
        "Code duplication": ["Not measured", "Under 5%", "", "Not assessed in this review"],
        "Maintainability rating": [f"{RT.words(cq)}, rated on the weakest material component" if cq else f"{R.condition(debt_w)[0]} ({R.condition(debt_w)[1]}), weakest file",
                                   "2 (Good) or better", "Health scorecard, code quality (6.1)",
                                   "Same rating as 6.1, which includes the line-by-line review findings"],
        "Automated test coverage": ["Not measured; no test files identified in the supplied source" if not metrics["tests"] else f"{metrics['tests']} test file(s)",
                                    "Coverage target to confirm", "Source code review", "No test suite provided" if not metrics["tests"] else ""],
        "Outdated third-party dependencies": [str(len(eol_names)), "0", "Version and support-date review", ", ".join(eol_names)],
        "Dead or unused code": ["Not measured", "", "", "Not assessed in this review"],
        "Share of machine-translated": ["Not measured", "Not applicable", "", "Source appearance does not establish how code was generated"],
        "Hard-coded values": [str(len(hard)), "Policy to confirm", "Scanner matches plus line-by-line review findings; full count unconfirmed", "; ".join(h_["title"] for h_ in hard[:8])],
    })
    reg = []
    SECURITY_CONSTRUCTS = re.compile(r"EXECUTE IMMEDIATE|QCMDEXC|WHEN OTHERS THEN NULL|Resume Next", re.I)
    STRATEGIC = re.compile(r"IMS|hierarchical|DL/I|ActiveX|OCX|3270|Visual Basic|VB6|ADO Recordset|IE6|Internet Explorer", re.I)
    TRIVIAL = re.compile(r"ArrayList|Hashtable|non-generic|GO TO|goto|indicators|fixed-form", re.I)
    if not metrics["tests"]:
        reg.append(["Calculation test coverage unconfirmed" if fin else "Test coverage unconfirmed",
                    "Test", "No test files were supplied", "Changes could introduce errors that the supplied checks do not detect", "Build characterization tests from current outputs "
                    "before any change (a prerequisite in 12.3)", "L", "High"])
    moved = []
    for f in debt_f[:25]:
        if SECURITY_CONSTRUCTS.search(f["text"]):
            moved.append(f"{f['text'].split(': ', 1)[-1]} ({f.get('component', '')})")
            continue
        strategic, trivial = STRATEGIC.search(f["text"]), TRIVIAL.search(f["text"])
        cat = "Platform (strategic)" if strategic else "Code (local)" if trivial else cats.get(f["rule"], "Code")
        impact = ("Creates a platform dependency; assess support and migration options in 6.2 and 12.3"
                  if strategic else "May increase maintenance effort; business effect is to confirm" if trivial else
                  _cap(P.why(f["rule"]) or "makes change slower"))
        desc = (f"Outdated construct still in use: {f['text'].split(': ', 1)[-1]} ({f.get('component', '')})"
                if f["rule"] == "DEBT-LEGACY" else f"{_cap(P.what(f['rule'], f['text']))}: {f['text']} ({f.get('component', '')})")
        reg.append([desc, cat,
                    {"DEBT-GOTO": "Unstructured legacy style", "DEBT-LEGACY": "Library or construct not upgraded",
                     "DEBT-LONG": "Routines grown over time", "DEBT-SIZE": "Monolithic file", "DEBT-TRANSLATED": "Automated language conversion",
                     "DEBT-PRESTD": "Pre-standard language usage"}.get(f["rule"], "Legacy construct"),
                    impact, "Retire through the component disposition (12.3)" if strategic else
                    "Fix when the file is next changed" if trivial else "Refactor",
                    "L" if strategic else "S" if trivial else "M", "High" if strategic else "Low" if trivial else "Medium"])
    for cf_ in [c_ for c_ in CF if c_["category"] in ("defect", "calculation", "data_integrity", "error_handling")][:14]:
        reg.append([f"{CFM.short(cf_['text'])} ({cf_['file']})", "Code", "Defect or fragile rule in the source as written",
                    "Wrong results or hard-to-change behavior if left as is; business effect to confirm",
                    "Correct the source after the rule is confirmed, and cover it with a test",
                    "S" if cf_["severity"] != "high" else "M", "High" if cf_["severity"] == "high" else "Medium"])
    if RR:
        reg = [r_ for r_ in reg if (RR.get(RRV.claim_key(r_[0])) or {}).get("verdict") != "unsupported"]
    reg.sort(key=lambda r_: ["High", "Medium", "Low"].index(r_[-1]))
    reg = [[f"TD-{num}-{i:02d}"] + r_ for i, r_ in enumerate(reg, 1)]
    if moved:
        doc.new_para("Reclassified as security and control findings (8.3 and 8.6) rather than debt: " + "; ".join(moved) + ".",
                     T[23]._tbl)
    rows(T[23], reg)
    doc.replace("Describe debt that sits outside the code itself", [
        (f"Maintenance requires {P.sentence(sorted({x.split(' skills are scarce')[0].split(' specialist skills required')[0] for x in skills}))} skills. "
         "Available staff, vendor cover and training needs are to confirm.") if skills
        else "No platform or skills debt was identified from the technologies in use.",
        "Release automation, environment parity and batch dependency documentation could not be assessed and are open items."])
    doc.unknown("Release, deployment and environment practices", "7.4", "IT")
    skill_names = P.sentence(sorted({x.split(" skills are scarce")[0].split(" specialist skills required")[0] for x in skills})) if skills else ""
    stab = [i["title"] for i in (phases.get("stabilize") or {}).get("items", [])]
    changing_components = any(c_["code"] not in ("retain", "retire") for c_ in CD)
    mod = [i["title"] for i in (phases.get("modernize") or {}).get("items", [])] if changing_components else []
    small_ = [r_[0] for r_ in reg if r_[-2] == "S"]
    doc.replace("Separate remediation that can be addressed independently", [
        ("Quick wins that reduce risk now, whatever is decided about modernization: "
         + _and([_lc(x) for x in stab[:6]]) + ".") if stab else
        (f"Quick wins that can be done now, each a small fix after the rule is confirmed: {_and(small_[:6])} in 7.3.") if small_ else
        "There are no quick wins separate from the modernization work.",
        (f"Debt that is better retired through the recommended {_noun(disposition)} (Section 12) than fixed now: "
         + _and([_lc(x) for x in mod[:6]]) + ".") if mod else
        ("Debt in the components that are rebuilt or replaced (12.3) is retired with them; the rest of 7.3 can be fixed "
         "directly." if PR["code"] in ("rearchitect", "replace") else
         ("Debt in the components that are rebuilt or retired (12.3) goes with them; the rest of 7.3 can be fixed directly."
          if any(c_["code"] in ("rebuild", "retire", "rearchitect", "replace") for c_ in CD) else
          f"Because the recommended disposition ({disposition.split(' (')[0]}) keeps the current code, every item in 7.3 can "
          f"be fixed directly."))])

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
            lab_ = "Security control: " + {"Privileged": "privileged and service accounts"}.get(r_["area"], r_["area"].lower())
            set_cell(row.cells[1], r_["seen"] or doc.unknown(lab_, "8.1", "Information security"))
            if r_["seen"]:
                doc.unknown(lab_, "8.1", "Information security")
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
        "Static code analysis": ["Source code review", today.isoformat(), f"{FX['files']} source files"
                                 + (f" and {FX['images']} screen image(s)" if FX["images"] else "")] + cnt(code_f),
        "Software composition": ["Version and CVE review", today.isoformat(), (", ".join(f"{t_.get('name')} {t_['version']}" for t_ in techs if t_.get("version")) or "No technology with a known version")
                                 + " (versions must be known to be checked)"] + cnt(sca),
        "Database configuration": ["Not performed", "", "Not in scope", "", "", "", ""],
        "Penetration test": ["Not performed", "", "Not in scope", "", "", "", ""],
    })
    legacy_rt = [t for t in eol_names if not any(t.split()[0].lower() in f["title"].lower() for f in sca)] + (
        ["ADO and ActiveX/OCX controls"] if any(
        re.search(r"ADODB|\.OCX", x.get("transcription") or "", re.I) for x in arts) else [])
    doc.new_para("Composition analysis checks component versions against published vulnerability data"
                 + (f". The legacy runtimes in use ({', '.join(legacy_rt)}) have no maintained vulnerability feed, so zero "
                    f"findings here does not mean zero risk; their coverage must be confirmed by information security."
                    if legacy_rt else "; components whose version is not confirmed (3.2) cannot be checked until it is."),
                 T[25]._tbl)
    vr, vgroups, notes = [], {}, []
    for i, f in enumerate(sorted(sec_f, key=lambda f: (SEV.index(f["severity"]), f["title"]))[:40], 1):
        refs = f.get("refs") or {}
        ev = (f.get("evidence") or [{}])[0] if f.get("evidence") else {}
        restricted = f.get("rule") in EV.CREDENTIAL_RULES
        loc = f"{ev.get('file') or f['title'].split(':')[0]}" + (f":{ev['line']}" if ev.get("line") else "")
        vid = f"VUL-{num}-{i:02d}"
        exposure = "Internet facing (public website)" if f["category"] == "website" else _exposure(loc)
        vgroups.setdefault((f.get("rule") or f["title"], f.get("reviewed") or ""), {"f": f, "ids": []})["ids"].append(vid)
        cv = _cvss_cell(f, refs, exposure)
        sev_txt = f["severity"].title()
        if f.get("lowered_from") or (f.get("reviewed") and not f.get("raised_from")):
            cv = "Not scored: see the note below"
            sev_txt += " (lowered after the line-by-line review)" if f.get("lowered_from") else ""
        elif f.get("raised_from"):
            sev_txt += " (raised after the line-by-line review)"
        else:
            m_ = re.match(r"[\d.]+ (Critical|High|Medium|Low)\b", cv)
            if m_ and m_.group(1) != sev_txt:
                sev_txt += f" (indicative CVSS: {m_.group(1)})"
        vr.append([vid, loc,
                   ", ".join(x for x in (refs.get("cve"), refs.get("cwe")) if x)
                   + "".join(f", NIST {n_}" for n_ in (refs.get("nist") or [])[:2]),
                   cv, sev_txt, exposure,
                   "Not checked" if refs.get("cve") else "N/A (own code)",
                   _cap(P.describe(f)[2] or (f.get("detail") or "").split(". ")[-1][:140])
                   if not restricted else "Change the password or key and move it to a secrets store",
                   owner_it, (today + timedelta(days=_due_days(f))).isoformat(), "Open", "Appendix D" if restricted else ""])
    rows(T[26], vr)
    anchor = doc.new_para("What these findings mean:", T[26]._tbl)._p
    for g in vgroups.values():
        f, ids = g["f"], g["ids"]
        idtxt = ids[0] if len(ids) == 1 else f"{ids[0]} to {ids[-1]}" if len(ids) > 2 else " and ".join(ids)
        wh, why_, fix_ = P.describe(f)
        txt = f"{idtxt}: {wh}."
        if why_:
            txt += f" {_cap(why_)}."
        if fix_:
            txt += f" To fix it, {fix_}."
        if f.get("reviewed"):
            txt += f" Note: {f['reviewed']}."
        anchor = doc.new_para(txt, anchor, bullet=True)._p
    risk_ids_ = {r_["title"]: r_["id"] for r_ in BR}
    sec_cf_ = [c_ for c_ in CF if c_["category"] == "security"]
    if sec_cf_:
        anchor = doc.new_para("No scanner rule produced the register above, but the line-by-line review recorded security-relevant "
                              "items that are tracked as risks in 9.1: "
                              + "; ".join(f"{risk_ids_.get(CFM.short(c_['text']), 'risk')}: {CFM.short(c_['text'])} ({c_['file']})"
                                          for c_ in sec_cf_[:4]) + "." if not vgroups else
                              "The line-by-line review also recorded security-relevant items that are tracked as risks in 9.1: "
                              + "; ".join(f"{risk_ids_.get(CFM.short(c_['text']), 'risk')}: {CFM.short(c_['text'])} ({c_['file']})"
                                          for c_ in sec_cf_[:4]) + ".", anchor, bullet=True)._p
    elif not vgroups:
        anchor = doc.new_para("No vulnerabilities were identified in the material reviewed.", anchor, bullet=True)._p
    unsup = [t for t in techs if t.get("status") in ("eol", "legacy")]
    doc.replace("List components that can no longer receive security patches", [
        (f"{t.get('name')} {t.get('version') or t.get('cycle') or ''}".strip() + f": {_status_word(t).lower()}"
         + (f" since {t['eol']}" if t.get("eol") else "") + ". Compensating controls: unknown (open item).") for t in unsup]
        or ["Vendor support exposure is unconfirmed where deployed versions and entitlements are unknown; no final support conclusion is made."])
    if unsup:
        doc.unknown("Compensating controls for unsupported components", "8.4", "Information security")
    fill_col(T[27], 1, {
        "Client information security policy": ["Y", "Not assessed", doc.unknown("Client security policy and standards", "8.5", "Information security")],
        "Security framework": ["Y", "Not assessed",
                               (f"{s['security_framework'] or 'NIST SP 800-53'} controls referenced by the findings in 8.3; "
                                "compliance against the framework was not assessed")
                               if any((f.get("refs") or {}).get("nist") for f in sec_f) else
                               f"{s['security_framework'] or 'NIST SP 800-53'}: not assessed"],
        "Data privacy obligations": (["Y", "Not assessed", f"{s['privacy_obligations'] or 'Applicable privacy law'}: personal "
                                      f"data is held in {', '.join(sorted(personal)[:4]) or 'components listed in 8.3'}"]
                                     if pii else (["To confirm", "Not assessed", "No component provided holds personal data, but "
                                                   + P.sentence([f"{n_} (lines {a_}–{b_})" for n_, a_, b_ in dormant[:2]])
                                                   + " has code that handles personal data but is never "
                                                     "called; confirm whether the application handles such data elsewhere"]
                                                  if dormant else ["To confirm", "Not assessed", "Privacy applicability requires confirmation; no personal data was identified by the supplied-source checks"])),
        "Payment card data": (["Y", "Not assessed", "Card data may be present (8.3)"] if re.search(r"card|pan\b", " ".join(
            f["title"].lower() for f in findings)) else ["To confirm", "Not assessed", "Card-data applicability requires confirmation; the source scan did not identify it"]),
        "Records retention schedule": [UNKNOWN, "Not assessed", doc.unknown("Retention schedule for financial and payment records", "8.5", "Records management")
                                       if fin else ""],
        "Open internal or external audit findings": [UNKNOWN, "Not assessed", doc.unknown("Open audit findings on payments or this application", "8.5", "Internal audit")
                                                     if fin else ""],
    })

    if FCR:
        from .sections import financial_controls
        verbs = [x for x in ("calculates" if calc_routines else "", "approves" if FC.approvals(store, arts) else "",
                             "records" if pay_writers else "") if x]
        financial_controls(doc, T, FCR, (P.sentence(verbs) or "handles") + " payments")

    # 9 risk
    rows(T[28], [[r_["id"], r_["title"] + (f" ({', '.join(r_['comps'][:3])})" if r_["comps"] else ""), r_["cat"],
                  str(r_["L"]), str(r_["I"]), str(r_["score"]), r_["rating"], r_["existing"],
                  f"{r_['mit']}. Owner: {r_['owner']}"] for r_ in risks])
    _col_widths(T[28], [0.65, 1.9, 0.85, 0.6, 0.55, 0.5, 0.6, 1.1, 1.5])
    anchor = doc.new_para("How each rating was reached. Likelihood comes from end-of-life status, skills, what the code "
                          "shows and incident history where it is known; impact comes from what the component does to "
                          "money and data" + ("" if yes(s["criticality_confirmed"]) or "Tier 1" not in (tier or "") else ", and uses a Tier 1 rating the "
                          "business owner has not yet confirmed") + ".", T[28]._tbl)._p
    for r_ in risks:
        anchor = doc.new_para(f"{r_['id']}: {_because('likelihood', r_['why_L'])}; {_because('impact', r_['why_I'])}.",
                              anchor, bullet=True)._p
    t29 = T[29]
    for row in t29.rows[1:]:
        lab = row.cells[0].text
        vals = {"Complete outage": [s["business_value"] or UNKNOWN, UNKNOWN, UNKNOWN,
                                    "Payments could be delayed; any statutory dates and business effect require confirmation. See the "
                                    "business calendar (2.4)" if fin else "Delayed service; see the business calendar (2.4)"],
                "Processing or calculation error": [f"{len(calc_routines) or len(arts)} calculation routine(s): {', '.join(calc_routines[:4])}"
                                                     if calc_routines else f"{len(arts)} files of business logic", "Not applicable",
                                                     "None identified in the source",
                                                     "Incorrect payments; effort to recover overpayments or pay arrears; misstated "
                                                     "accounts and audit findings" if fin else "Incorrect outputs and recovery effort"],
                "Security breach": ["Personal data" if pii else "Payment and district data" if fin else "Application data", "Not applicable", UNKNOWN,
                                    "Notification obligations and legal exposure" if pii else
                                    ("Fraudulent approval or diversion of payments" if FC.approvals(store, arts) else
                                     "Fraudulent change or diversion of payments") + "; audit findings; reputational harm"
                                    if fin else "Reputational harm"],
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
    rows(T[33], [[f"Change to a rate or run parameter ({r_})", UNKNOWN, "Value held in source code",
                  "Move to a business-maintained, audited parameter table", "Maintenance screen with approval and change history"]
                 for r_ in rates[:4]],
         empty="No recurring IT activity could be identified from the source; to be confirmed with the support team.")
    doc.replace("Identify any individual whose departure", (
        f"Maintenance requires {skill_names} skills. Named maintainers, support cover and succession arrangements "
        "are to confirm with the IT owner.")
        if skills else "Specialist maintenance requirements, named maintainers and support cover are to confirm with the IT owner.")
    doc.unknown("Individuals holding key knowledge of the application", "10.4", "IT")

    # 11 user experience
    ux_intro = doc.para("This section evaluates how well the application serves")
    if ux_intro is not None:
        _set_para(ux_intro, "This section evaluates how well the application serves its internal and external users, "
                            "based on the screens and page code provided; interviews, observation of users and support "
                            "history were not available for this review.")
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
    observed_ui = any(x.get("artifact_type") in ("ui_screen", "web") for x in arts)
    fill_col(T[34], 1, {
        "Ease of navigation": ux_row(("UIB-", "UIF-", "USE-"), "navigation"),
        "Clarity of error messages": ux_row(("UIB-CRASH", "UIB-ERR", "USE-ERR"), "error handling"),
        "Efficiency for high-volume": ["Not rated", "Requires observation of users at work"],
        "Consistency with other client applications": ["Not rated", "Requires the portfolio inventory"],
        "Mobile and browser compatibility": _floor(ux_row(("UIB-OBSOLETE", "ACC-TEXTSIZE"), "browser support"), 4 if any(f["rule"] == "UIB-OBSOLETE" for f in uxf) else 0, "source indicates outdated browser dependency") if observed_ui else ["Not rated", "Map source does not establish usability or supported access channels; confirm user tasks and deployed interfaces."],
        "Availability of help": ["Not rated", "Not visible in the source"],
        "User satisfaction": ["Not rated", "Stakeholder interviews not held"],
    })
    acc = [f for f in uxf if (f["rule"] or "").startswith("ACC")]
    doc.replace("Record redesign opportunities in order of user benefit", [
        "User experience and accessibility require user-task observation and confirmation of the deployed interface. Source checks do not establish conformance or satisfaction."] + ([f"Accessibility source observations; applicable organizational standard to confirm: "
                                   f"{P.sentence(P.reasons_words(acc, 4))}."] if acc else []))

    # 12 options
    rec_code = PR["code"]
    np_txt = ", ".join(no_path_names)
    applicable = {"Retain": ("Yes: provisional recommendation; validate and repair source and control findings in place"
                             if rec_code == "retain" else "Possible: depends on confirmed support status and remediation feasibility"),
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
                  "Retire": "Not assessed: current usage and replacement business capability need confirmation"}
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
        _set_para(score_note, "These option scores are illustrative model outputs; business value, enterprise fit, peer practice and replacement capability remain unconfirmed. Each shortlisted option is scored from 1 to 5 on every criterion, where 5 is always the most "
                  "favourable: for implementation complexity and disruption, 5 means the least complex and least disruptive. "
                  "Weighted totals: " + ", ".join(f"{o[0]} {t_:.2f}" for o, t_ in zip(OPTS, totals)) + ". Rationale:")
        last = score_note._p
        for o in OPTS:
            last = doc.new_para(f"{o[0]}: {o[2]}", last, bullet=True)._p
    high_n = sum(1 for r_ in BR if r_["rating"] == "High")
    kv(T[37], {"Recommended disposition": disposition,
               "Rationale": ((P.sentence([x for x in (f"{len(HP)} platforms" if len(HP) >= 3 else "",
                                                      f"technology with no upgrade path ({np_txt})" if np_txt else "",
                                                      f"{crit_high} critical or high findings in 8.3" if crit_high else "",
                                                      f"{high_n} High risks in 9.1" if high_n else "") if x])
                              + " call for more than fixes in place; each component gets its own disposition (table below).")
                             if PR["code"] in ("rearchitect", "replace") else
                             f"{_cap(PR['meaning'])}. Each component's disposition is in the table below.")
                            + _outscored(OPTS, totals),
               "Consolidation grouping": s["related_apps"] or ("Within the application: the payment posting components"
                                                               if any(c["code"] == "consolidate" for c in CD) else "None identified"),
               "Prerequisites": _cap(P.sentence([f"provide the {len(missing_all)} missing components" if missing_all else "",
                                                 "confirm business criticality",
                                                 "name the system of record for each entity (5.5)" if multi_copies else "",
                                                 "build characterization tests for the calculations" if fin else ""])) + ".",
               "Key risks of the recommended option": (("Regression in payment calculations when findings are fixed in place" + (
                                                           " and data loss during migration" if PR["code"] in ("rearchitect", "replace", "replatform", "rebuild") else "")
                                                       + "; mitigated by tests that record today's results, reconciliation and parallel "
                                                       "runs over at least two payment cycles") if fin else
                                                      "Regression in business logic during change; mitigated by characterization "
                                                      "tests and running old and new side by side until results agree"),
               "Interim risk mitigation": "The immediate actions in 1.3" + (" and the control fixes in 8.6" if FCR else "")})
    if _outscored(OPTS, totals) and "Replace" in _outscored(OPTS, totals).split(" scores")[0] and "market review" not in " ".join(
            it[0] for it in doc.open_items):
        doc.unknown("Market review of commercial or shared solutions for this business area", "12.2", "Enterprise architecture")
    anchor = doc.new_para("Disposition by component", T[37]._tbl, bold=True)._p
    ct = _table_after(doc, T[26], anchor, ["Component", "Platform", "Disposition", "Reason", "Skill set"],
                      [[c["name"], c["platform"], c["label"], _cap(c["why"]) + ".", c["skill"]] for c in CD])
    _col_widths(ct, [1.5, 1.4, 0.9, 3.3, 1.2])
    anchor = doc.new_para("Target architecture (outline)", ct._tbl, bold=True)._p
    anchor = doc.new_para("A candidate architecture for evaluation. Confirm interfaces, transaction boundaries, user requirements and deployment constraints before choosing the target design:",
                          anchor)._p
    for t_ in A_.target_outline(AM, v.get("code")):
        anchor = doc.new_para(t_, anchor, bullet=True)._p
    kv(T[38], {"Recommended horizon": horizon,
               "Proposed start window": doc.unknown("Proposed start window (fiscal year and quarter)", "12.4"),
               "Estimated duration": f"{_cap(elapsed)}" + (f" (set by the order of work below and by parallel runs over {cyc})"
                                                            if phased else "")
                                     + f"; {EST['low']}–{EST['high']} person-weeks of effort across {len(EST['lines'])} "
                                       f"skill set(s) (breakdown below)",
               "Predecessor initiatives": "Security and control fixes (1.3, 8.6); system-of-record decision (5.5); missing code",
               "Successor initiatives": ("Evaluate platform retirement after any agreed migration and acceptance"
                                         if any(c["code"] not in ("retain", "retire") for c in CD)
                                         else "Review support arrangements and validate repairs on the retained platforms"),
               "Business blackout periods": doc.unknown(f"Business blackout periods ({cyc}, year-end)", "12.4")})
    anchor = doc.new_para("Order of work, by dependency", T[38]._tbl, bold=True)._p
    first_of = {}
    for f in sorted(sec_f, key=lambda f: SEV.index(f["severity"])):
        if f["severity"] in ("critical", "high", "medium"):
            first_of.setdefault(f.get("rule"), f)
    fixes_ = list(dict.fromkeys(P.describe(f)[2] for f in first_of.values() if P.describe(f)[2]))
    for ph, txt in OP.sequence({"fin": fin, "fixes": fixes_, "span": span[1],
                                "copies": multi_copies, "consolidate": any(c["code"] == "consolidate" for c in CD),
                                "front_end": any(c["layer"] == "Presentation" and c["code"] != "retain" or c["code"] == "rearchitect" for c in CD),
                                "platforms": len(HP), "phased": phased,
                                "changing": any(c["code"] not in ("retain", "retire") for c in CD)}):
        anchor = doc.new_para(f"{ph}: {txt}", anchor, bullet=True)._p
    anchor = doc.new_para("Estimate by skill set", anchor, bold=True)._p
    et = _table_after(doc, T[26], anchor, ["Skill set", "Work", "Person-weeks", "Basis"],
                      [[g["skill"], "; ".join(g["work"][:4]) + (f"; and {len(g['work']) - 4} more" if len(g["work"]) > 4 else ""),
                        f"{g['lo']:.0f}–{g['hi']:.0f}", "; ".join(g["basis"])] for g in EST["lines"]]
                      + [["Total", "", f"{EST['low']}–{EST['high']}", f"{_cap(elapsed)}; specialists work in parallel, "
                          f"part-time, as each phase needs them"]])
    _col_widths(et, [1.6, 2.9, 1.0, 2.8])
    doc.new_para(f"Assumptions: the estimate covers the {FX['files']} source files provided ({FX['lines']:,} lines); "
                 + (f"{len(missing_all)} referenced components were not provided and the full application size is unknown, so "
                    f"the estimate remains an unvalidated scenario, not a budget. " if missing_all else "the full application size is not confirmed, so "
                    "the estimate remains an unvalidated scenario, not a budget. ")
                 + f"Rates are planning-level and need validating with the delivery teams; "
                 + (f"each skill set needs its own people ({', '.join(EST['skills'][:5])} rarely sit in one person)."
                    if len(EST["skills"]) >= 3 else "the work can be done by one small team."),
                 et._tbl)

    # 13 evidence
    rows(T[39], [["None", "", "", "", "Stakeholder interviews were not part of this review", ""]])
    doc.unknown("Stakeholder interviews", "13.1", "Assessment lead")
    ev = []
    for i, x in enumerate(arts, 1):
        typ = {"code": "Source code", "ui_screen": "Application screen", "schema": "Database schema", "config": "Configuration",
               "document": "Document"}.get(x.get("artifact_type"), "Source code")
        qx = DDV.capture_quality(store, x, (DD.get(str(x["id"])) or {}).get("capture_concerns"))
        qtxt = {"good": "no unresolved capture warning; original-source completeness requires separate validation",
                "rescan": "copy incomplete (" + "; ".join(DDV.report_reason(i) for i in qx["issues"][:2]) + ")",
                "unchecked": "copy not checked line by line"}[qx["status"]]
        if x.get("artifact_type") == "ui_screen":
            qtxt = "screen image, read for its fields and notices" + (f"; the same form as {COPIES[x['name']]}"
                                                                     if x["name"] in COPIES else "")
        elif qx["status"] == "good" and str(x["id"]) not in DD:
            qtxt = "no unresolved capture warning; current line-by-line review pending"
        ev.append([f"EV-{num}-{i:02d}", x["name"], typ, f"v{x.get('version', 1)}, {(x.get('updated') or x.get('created') or '')[:10]}",
                   f"Program source set: {x['name']}; {qtxt}"])
    rows(T[40], ev)
    from core.technology_support import program_coverage
    source_coverage=program_coverage(store)
    if source_coverage:
        coverage_anchor=doc.new_para('Source analysis coverage', T[40]._tbl, bold=True)._p
        doc.new_para('; '.join(row['file']+': '+row['method']+' ('+row['status']+'); '+row['review_status']+
                     ('; limited inventory requires further source analysis' if row['limited'] else '')
                     for row in source_coverage)+
                     '. Analysis covers visible material only; hidden source, deployed versions and runtime behavior remain unconfirmed.', coverage_anchor)
    assumptions = ["Findings reflect the source files listed in 13.2; components not provided are listed in 4.3 and are not scored.",
                   ("Business criticality is provisional (" + ((tier or "").split(" (")[0] or "not entered") + ", not yet confirmed "
                    "by the business owner). The impact ratings in Section 9 use it and would change with a different tier.") if not yes(s["criticality_confirmed"]) else
                   "Business criticality was confirmed by the business owner.",
                   "Support dates are taken from the lifecycle catalog used by this assessment. Verify deployed versions and "
                   "current vendor terms before relying on them; 'Not published' means no date is recorded in the catalog."]
    if a["confidence"]["level"] != "high":
        unconf = sum(row.cells[1].text.count("version not confirmed)") for row in t12.rows[1:])
        assumptions.append(f"Assessment confidence is {a['confidence']['level']}: " + "; ".join(x for x in (
            f"{len(missing_all)} referenced component{'s were' if len(missing_all) != 1 else ' was'} not provided (4.3)"
            if missing_all else "",
            f"{unconf} technology version{'s' if unconf != 1 else ''} could not be confirmed (3.2)" if unconf else "",
            "business criticality has not been entered, so impact ratings use defaults" if not tier else "") if x) + ".")
    _rv = RRV.summary_line(store)
    if _rv:
        assumptions.append(_rv)
    constraints = ["No access to production systems, data, service management records or stakeholders was part of this review."]
    assumptions.append("Findings are tied to current captured text. Quote matching and review do not prove original-source completeness or production correctness. See Appendix H for independent transcription measurements and limitations.")
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
        kind_ = "display file" if m["name"].upper() in EV.display_files(arts) else m["kind"]
        doc.open_items.append((f"Provide the source of {kind_} {m['name']} (referenced but not provided)", "4.3", "IT"))
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
                         ("Appendix D:", "Appendix D: Security findings are recorded in Section 8; any separate restricted distribution requires confirmation"),
                         ("Appendix E:", "Appendix E: Current-state process" + (" (Figure 1)" if figs.get("process") else " (diagram not included)")),
                         ("Appendix F:", "Appendix F: Report catalog (Section 5.3)"),
                         ("Appendix G:", "Appendix G: Glossary of technical terms (below)")):
        p = doc.para(starts)
        if p is not None:
            _set_para(p, text)
    from . import sections as SX
    SX.capability(doc, T, AM, s, fin)
    SX.boundary(doc, T, AM, arts, HP, missing_all, shared=bool(shared_stores), lines=FX["lines"], files=FX["files"])
    SX.code_analysis(doc, T, arts, DD, DPROG, RQ)
    for r_ in RQ:
        doc.open_items.insert(0, (f"Re-obtain a complete copy of {r_['name']}: " + "; ".join(
            DDV.report_reason(i) + (f" ({SX.line_list(i['lines'][:12])})" if i["lines"] else "") for i in r_["issues"][:3]),
            "13.2", "IT"))
    SX.deployment(doc, T, AM, DM, HP, fin, tier=(tier or "").split(" (")[0], cics=CICS, apis=[e["name"] for e in apis],
                  totals=FX["totals"], authz=any(f.get("rule") == "SEC-AUTHZ" for f in sec_f))
    SX.nfr(doc, T, fin, [c["name"] for c in AM["components"] if "Batch" in c["role"] or "procedures" in c["role"]],
           (f"Online screens: {', '.join(e['name'][:40] for e in screens[:4])}" if screens else "No online screens identified"))
    stack_names = []
    for vals in stack.values():
        for n_ in re.split(r";\s*(?![^()]*\))", vals[0] or ""):
            n_ = re.sub(r"\s*\([^)]*\)", "", n_).strip()
            if n_ and n_ not in stack_names and not n_.startswith(("None", "Unknown", "COBOL batch program", "Scheduled job",
                                                                  "Batch reports", "JCL and scheduler")):
                stack_names.append(n_)
    SX.lifecycle(doc, T, techs, stack_names, OP.NO_PATH)
    SX.identity(doc, T, AM, CT, DM, cics=CICS, creds_any=bool(FX["creds"]))
    local_logs = [o for o in DM["occurrences"] if o["engine"].startswith("Windows desktop (local file)")]
    audit_control = next((r for r in FCR if r[0] == "Audit trail integrity"), None)
    SX.operations(doc, T, AM, DM, skill_list, audit_control[1] if audit_control else "Logging implementation, coverage and retention remain unconfirmed", fin,
                  unhandled=unhandled_txt)
    SX.strategy(doc, T, {"overall": RT.words(SC["overall"][0])}, PR, CD, HP, fin,
                (tier or "").split(" (")[0] + (" provisional" if tier and not yes(s["criticality_confirmed"]) else ""), no_path_names,
                DM, CT, mainframe_products=[x for x in ("CICS" if CICS else "", "IMS" if any("IMS" in (t_.get("name") or "")
                                                                                              for t_ in techs) else "") if x])
    for t in techs:
        if not (t.get("version") or t.get("confidence") == "confirmed"):
            doc.open_items.append((f"Confirm the version of {t.get('name')} in use", "3.2", "IT"))
    doc.open_items.extend(('Source validation: ' + item, '13.2', 'Technical reviewer') for item in evidence_quality['blockers'])
    BLOCK = re.compile(r"reviewer|Business owner|criticality|boundary|missing|Provide the source|system of record|^Re-obtain|line by line|^Source validation", re.I)
    items = _dedup(doc.open_items)
    blocking = [it for it in items if BLOCK.search(it[0])]
    if final and blocking:
        draft = "v0.9 Draft for review" if ver.lower() in ("v1.0", "1.0") else f"{ver} Draft for review"
        for text_node in doc.d.element.body.iter(qn("w:t")):
            if text_node.text:
                text_node.text = text_node.text.replace(version_txt, draft).replace(
                    "Assessment report issued", "Draft issued for review; becomes final after sign-off in 13.5")
        final = False
        version_txt = draft

    other = [it for it in items if not BLOCK.search(it[0])]
    oi = []
    for i, (what, sec_, owner) in enumerate(blocking + other, 1):
        blk = (what, sec_, owner) in blocking
        due = (today + timedelta(days=14 if blk else 45 if i <= len(blocking) + 15 else 75)).isoformat()
        what = re.sub(rf"\s*\({re.escape(sec_)}\)$", "", what)
        where = f"Section {sec_}" if re.match(r"\d", sec_) else sec_
        oi.append([f"OI-{num}-{i:02d}", ("Blocks issue: " if blk else "") + f"{what} ({where})", owner, due, "Open"])
    rows(T[41], oi)
    doc.new_para(f"{len(blocking)} of the {len(oi)} open items block issue of the report as final (marked 'Blocks issue', "
                 f"due in 14 days); the rest are due within 75 days of the report date.", T[41]._tbl)
    if metadata is not None:
        metadata.update(verdict=v, final=final, blocking=[item[0] for item in blocking])
    _glossary(doc)
    _quality_appendix(doc, T, store)
    _header_footer(doc, name)
    cp = doc.d.core_properties
    cp.author = cp.last_modified_by = s["prepared_by"]
    cp.title = f"{name} — Application Assessment Report"
    cp.subject = f"Prepared for {s['client']}" if s["client"] else "Application Assessment Report"
    cp.comments = cp.keywords = cp.category = ""
    _no_placeholders(doc)
    _scope_introductions(doc)
    from .wording import clean
    for part in [doc.d.element.body] + [p_.part.element for sec_ in doc.d.sections for p_ in (sec_.header, sec_.footer)]:
        for t_ in part.iter(qn("w:t")):
            if t_.text:
                t_.text = RD(clean(t_.text, verbatim=[a_["name"] for a_ in arts]))
    for field in ("title", "subject", "author", "last_modified_by"):
        setattr(cp, field, RD(getattr(cp, field)))
    from . import editorial
    editorial.apply(doc, a, evidence_quality, s, metadata=metadata, analysis_stage=store.get_meta("analysis_stage"),
                    security_counts={severity: sum(f["severity"] == severity for f in sec_f) for severity in SEV},
                    priority_reasons=[r_["title"] for r_ in BR[:2]], full_summary=bool(_es))
    RRV.apply_to_docx(doc.d, store)
    _fill_toc(doc)
    buf = io.BytesIO()
    doc.d.save(buf)
    return buf.getvalue()


# ── helpers for the build ───────────────────────────────────────────────────────────────────────────────────────

FIN_WORDS = re.compile(r"PAYMENT|\bPAY\b|PAY[-_]|AMOUNT|LEDGER|INVOICE|DISBURS|REMIT|\bEFT\b|HOLDBACK|GROSS|"
                       r"\bNET\b|BILLING|CLAIM|ENTITLE|REFUND|GENERAL[-_ ]LEDGER", re.I)



def _scope_introductions(doc):
    """Keep section introductions within the evidence available to this assessment."""
    introductions = {
        "This section gives client leadership": "The summary brings together the main findings, the assessment ratings and the proposed direction. The following sections provide the supporting detail.",
        "This section establishes why the application": "Business purpose, ownership, users and schedules need confirmation from the business owner. Source-derived process steps are shown separately from these open items.",
        "This section inventories every technical": "The technical profile lists components and technology identifiers found in the supplied material. Missing versions, deployment details and support status are marked for confirmation.",
        "This section provides the visual architecture": "The architecture view shows components and connections derived from the supplied code. It does not establish the full production topology or every external integration.",
        "This section documents what data": "The data inventory shows structures referenced or defined in the supplied code. Ownership, record volumes, retention and downstream reporting dependencies remain to confirm.",
        "This section produces the overall health": "The health scorecard combines the areas that could be assessed. Ratings use the condition scale from 1 to 5; unassessed areas and weighting are explained below.",
        "This section identifies the shortcuts": "The debt register records code and technology findings that may increase maintenance effort. Proposed remediation is included in the planning estimate in Section 12.",
        "This section assesses the application's security": "The security review records findings and the controls visible in the supplied material. Production configuration and operational controls need separate confirmation; sensitive details are restricted to the appendix.",
        "This section consolidates the risks": "The risk register connects the technical findings to possible business consequences. Likelihood and impact are assessment judgments, not measured incident probabilities.",
        "This section quantifies the effort": "Operational workload and support arrangements cannot be measured from source alone. The activities below are starting points for review with the IT owner.",
        "This section evaluates how well": "The usability findings come from the supplied screens and page code. They do not establish user satisfaction, accessibility conformance or the experience of every user group.",
        "This section compares the credible": "The options compare changes suggested by the findings. The recommendation and effort ranges support planning; product fit, deployment constraints and delivery assumptions need confirmation.",
        "This section records where each finding": "The evidence register identifies the material reviewed. Open items record missing information and the confirmations needed before the client accepts the assessment."
    }
    for starts, text in introductions.items():
        paragraph = doc.para(starts)
        if paragraph is not None:
            _set_para(paragraph, text)

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
        lab = {"Assembly": "Assembly", "PL/SQL": "Oracle PL/SQL", "Visual Basic 6": "Visual Basic 6.0",
               "RPG": "RPG (IBM i)", "COBOL": "COBOL"}.get(lang, lang)
        if lab not in langs:
            langs.append(lab)
    for lab in langs:
        from core.technology_support import stack_category
        category=stack_category(lab)
        layer={'Application frameworks and platforms':'Application framework',
               'Development and data tooling':'Third-party libraries and components',
               'Integration and middleware':'Application framework'}.get(category,category)
        detail=f"{lab} (version not confirmed)" if category=='Programming languages' else f"{lab} (source label; deployed use and version not confirmed)"
        _add_stack(stack, layer, detail, _vendor({"name": lab}) if _vendor({"name": lab}) != UNKNOWN
                   else "Microsoft" if "C#" in lab else "IBM" if "Assembler" in lab else UNKNOWN)
    if any((x.get("name") or "").lower().endswith(".bms") or
           re.search(r"\bDFHMSD\b|\bDFHMDI\b", x.get("transcription") or "") for x in arts):
        _add_stack(stack, "Presentation / UI", "CICS BMS map source (deployed interface and version to confirm)", "IBM")
    for sq in DM.get("sql_server") or []:
        _add_stack(stack, "Database", f"Microsoft SQL Server ({sq}; version not confirmed)", "Microsoft")
    if DM.get("db2"):
        _add_stack(stack, "Database", "Embedded SQL in COBOL (database engine and version not confirmed)", UNKNOWN)
    has_sql_ = any((x.get("name") or "").lower().endswith(".sql") for x in arts)
    if has_sql_ and "Database" not in stack:
        _add_stack(stack, "Database", "SQL database definition (database engine and version to confirm)", UNKNOWN)
    if not has_sql_ and any((x.get("language") or "").upper().startswith("RPG") for x in arts):
        _add_stack(stack, "Database", "RPG file access (database engine to confirm)", "IBM")
    batch, cobol_batch = [], []
    supplied_jcl = [j['name'] for j in arts if j['name'].lower().endswith('.jcl') or (j.get('language') or '').upper() == 'JCL']
    for x in arts:
        t = x.get("transcription") or ""
        dds = __import__("re").findall(r"ASSIGN\s+TO\s+([A-Z0-9-]+)", t)
        if dds and "cobol" in (x.get("language") or "").lower() and "CICS" not in t:
            cobol_batch.append(f"{x['name']} (DD names {', '.join(dict.fromkeys(dds[:6]))})")
    if cobol_batch:
        batch.append(f"COBOL batch program{'s' if len(cobol_batch) > 1 else ''} {_and(cobol_batch)}; "
                     + (f"JCL supplied: {', '.join(supplied_jcl)}; job-to-program mapping and scheduler to confirm" if supplied_jcl
                        else "JCL and scheduler not provided"))
    for jb in jobs:
        if not any(jb['name'].lower() in j.lower() for j in supplied_jcl) or not cobol_batch:
            batch.append(f"Scheduled job {jb['name']}; scheduler to confirm")
    for b in batch:
        _add_stack(stack, "Batch and scheduling", b, "IBM" if "COBOL" in b else UNKNOWN)
    rpt = [e["name"] for e in store.entities() if __import__("re").search(r"REPORT|RPT", e["name"], __import__("re").I)
           and e["kind"] in ("data_store", "program", "job")]
    if rpt:
        _add_stack(stack, "Reporting", "Batch reports: " + ", ".join(sorted(set(rpt))[:5]) + " (content in 5.3)", "Custom (in-house)")
    plats = set(AM["platforms"])
    if "IBM mainframe (z/OS)" in plats:
        from .evidence import cics
        subs = [x for x in ("CICS" if cics(arts) else "", "IMS" if any((x.get("language") or "").upper().startswith(("IMS", "ASSEMB"))
                                                                        and re.search(r"\bDBD\b", x.get("transcription") or "")
                                                                        for x in arts) else "") if x]
        _add_stack(stack, "Operating system", "IBM z/OS (" + (f"with {' and '.join(subs)}; " if subs else "")
                   + "version not confirmed)", "IBM")
    if "Windows desktop (VB6)" in plats:
        _add_stack(stack, "Operating system", "Microsoft Windows desktops running the VB6 runtime (versions not confirmed)", "Microsoft")
    if "Microsoft .NET (host to confirm)" in plats:
        _add_stack(stack, "Operating system", "Operating system for the .NET application: to confirm", "Microsoft")
        _add_stack(stack, "Web and application server", "Web and application server for .NET: to confirm", "Microsoft")
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
        if m['name'].upper() in ('IEFBR14', 'IEBGENER'):
            continue  # IBM utilities are runtime dependencies, not missing custom source.
        if any((a.get('name') or '').lower().endswith('.jcl') for a in arts) and not re.search(rf'(?<![\w-]){n}(?![\w-])', text, re.I):
            continue  # A stale parser placeholder cannot establish a missing component.
        if re.search(rf"\b{n}\s+BEGSR\b|\bBEGSR\s+{n}\b|^\s*\d*\s+{n}\.\s*$|\bSub\s+{n}\b|\bdef\s+{n}\b", text, re.M | re.I):
            continue
        seen.add(m["name"])
        out.append(m)
    return out


def _jobs(store) -> list:
    """Scheduled jobs; a SQL script is modelled as a job but nothing shows that it is scheduled."""
    return [j for j in store.entities("job") if (j.get("attrs") or {}).get("tool") != "SQL script"]


def _due_days(f) -> int:
    """Days to fix, used by both the immediate actions (1.3) and the register (8.3)."""
    rule = f.get("rule") or ""
    exposed = f["category"] in ("website", "ui_security") or "Network" in _exposure(_loc_file(f))
    if f["severity"] == "critical":
        return 30
    if f["severity"] == "high":
        return 30 if exposed or rule in ("SEC-CRED", "SEC-AUTHZ", "UIS-PREFILL") else 60
    return {"medium": 90, "low": 180}.get(f["severity"], 365)


def _loc_file(f):
    ev = (f.get("evidence") or [{}])[0] or {}
    return ev.get("file") or f["title"].split(": ")[-1].split(":")[0]


def _outscored(opts, totals) -> str:
    """Say plainly when an option scores higher than the recommended one (Option A), and why it is not recommended."""
    best = max(range(len(opts)), key=lambda j: totals[j])
    if best == 0 or totals[best] < totals[0]:
        best = next((j for j in range(1, len(opts)) if totals[j] == totals[0]), None)
        if best is None:
            return ""
    name = opts[best][0]
    tie = totals[best] == totals[0]
    why = ("its scores assume a suitable product exists, and no market review has been done (open item); until one "
           "confirms a fit, it cannot be recommended" if name.startswith("Replace") else
           "it scores higher on paper, but the component dispositions below do not support it")
    return (f" {name} scores " + ("the same" if tie else "higher") + f" ({totals[best]:.2f} against {totals[0]:.2f} in 12.2), but {why}.")


def _floor(row, floor, why):
    """A 1-5 rating row [rating, text] raised to at least `floor`, saying why."""
    if not floor or not str(row[0]).isdigit() or int(row[0]) >= floor:
        return row
    from .plain import LEVEL
    return [str(floor), f"{LEVEL[floor]}: {why}; " + row[1].split(": ", 1)[-1]]


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
        return "To confirm (the supplied code writes or defines it)"
    if "reads" in kinds_:
        return "To confirm (read only in the supplied code)"
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


def _lc(t):
    t = t or ""
    first = t.split(" ", 1)[0]
    return t if sum(ch.isupper() for ch in first) >= 2 else t[:1].lower() + t[1:]


def _cap(t):
    return t[:1].upper() + t[1:] if t else t


LEVEL_WORD = {1: "excellent", 2: "good", 3: "fair", 4: "poor", 5: "critical"}


def _eol_plain(t):
    nm = f"{t.get('name')} {t.get('version') or t.get('cycle') or ''}".strip()
    if "visual basic 6" in nm.lower():
        return (f"{nm} development tools are past the vendor's end of support" + (f" (since {t['eol']})" if t.get("eol") else "")
                + "; only its runtime is still supported, as part of Windows")
    return {"eol": f"{nm} is past the vendor's end of support" + (f" (since {t['eol']})" if t.get("eol") else ""),
            "legacy": f"{nm} is no longer developed and has no supported upgrade path",
            "extended": f"{nm} is on paid extended support only",
            "ending": f"{nm} loses vendor support within 12 months" + (f" ({t['eol']})" if t.get("eol") else "")}.get(
        t.get("status"), f"{nm} has an unconfirmed support status")


_NOUNS = {"consolidate": "consolidation", "re-architect": "re-architecture", "replace": "replacement", "refactor": "refactoring",
          "re-platform": "re-platforming", "retain": "retention", "retire": "retirement", "rehost": "rehosting"}


def _noun(disposition):
    verb = disposition.split(" (")[0].lower()
    return _NOUNS.get(verb, verb)


def _because(what, basis):
    n, sep, why = str(basis).partition(": ")
    return f"{what} {n} because {why}" if sep and n.strip().isdigit() else f"{what} {basis}"


def _and(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


_HOW = {"phased, by component": "in phases, component by component", "phased": "in phases"}


def _recommend(disposition, plain):
    verb, _, how = disposition.partition(" (")
    how = _HOW.get(how.rstrip(")"), how.rstrip(")"))
    plain = plain.rstrip(".").replace(": ", ", ")
    if "component by component" in plain:
        how = how.replace(", component by component", "")
    return (f"Our recommendation is to {verb.lower()}" + (f" {how}" if how else "") + f" (Section 12): "
            f"{_lc(plain)}.")


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


_TEST_WORD = re.compile(r"(?:^|[/\\_.\- ])tests?(?:[/\\_.\- ]|$)|^tests?\d", re.I)
_TEST_CAMEL = re.compile(r"(?<=[a-z0-9])Tests?(?=\.[^./\\]+$|$)")


def is_test_file(name) -> bool:
    """A test file by its name: a whole word 'test'/'tests' (test_x.py, x_test.go, tests/x) or a CamelCase suffix
    (PaymentTest.java). Names that merely contain the letters, such as LATEST.cbl or ATTESTRPT.cbl, are not tests."""
    base = str(name or "")
    return bool(_TEST_WORD.search(base) or _TEST_CAMEL.search(base))


def _metrics(arts):
    from core.assess.scores import text_metrics
    per = []
    tests = 0
    translated = 0
    total = 0
    for x in arts:
        text = x.get("transcription") or ""
        if is_test_file(x["name"]):
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


def _quality_appendix(doc, tables, store):
    """The same version-bound evidence contract used by HTML, in the Word template."""
    from . import quality
    head = doc.d.add_paragraph('Appendix H Transcription validation and software improvements', 'Heading 1')
    head.paragraph_format.page_break_before = True
    anchor = head._p
    for block in quality.blocks(store):
        kind = block['type']
        if kind == 'table':
            table = _table_after(doc, tables[26], anchor, block['head'], block['rows'])
            _col_widths(table, [4.3, .9, .9, .9] if len(block['head']) == 4 else [1.6, 5.4])
            table.autofit = False
            width = table._tbl.tblPr.find(qn('w:tblW'))
            if width is not None:
                width.set(qn('w:type'), 'dxa')
                width.set(qn('w:w'), str(7 * 1440))
            anchor = table._tbl
        elif kind == 'h':
            para = doc.d.add_paragraph(block['text'], 'Heading 2')
            anchor.addnext(para._p)
            anchor = para._p
        elif kind == 'bullets':
            for item in block['items']:
                anchor = doc.new_para(item, anchor, bullet=True)._p
        else:
            anchor = doc.new_para(block['text'], anchor)._p


def _fact_table(doc, tables, store, summary, anchor):
    """The findings the executive summary cites, so every [file:F12] can be looked up. Kept under 1.2: the report
    layout drops any heading that is not in the template."""
    from core import exec_summary as ES
    index = ES.finding_index(store)
    cited = {f for r in summary.get("risks") or [] for f in r["facts"]}
    for text in ES.paragraphs(summary):
        for name, ids in ES._CITE.findall(text):
            cited |= {f"{name.strip()}:{i}" for i in re.findall(r"F\d+", ids)}
    cited = sorted(cited & set(index), key=lambda k: (k.rsplit(":F", 1)[0], int(k.rsplit(":F", 1)[1])))
    if not cited:
        return
    rows_ = [[k, index[k].get("severity") or index[k].get("category") or "",
              f"{index[k]['lines'][0]}-{index[k]['lines'][-1]}", index[k].get("statement") or ""] for k in cited]
    table = _table_after(doc, tables[26], anchor, ["Fact ID", "Severity or type", "Lines", "Finding"], rows_)
    _col_widths(table, [1.9, 1.0, .7, 3.4])


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
    heads = [p for p in doc.d.paragraphs if p.style is not None and p.style.name == "Heading 1"
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


def _label_unknowns(doc):
    """A cell that still says Unknown becomes an insert prompt named after its row and column."""
    lead = re.compile(r"^Unknown\b")
    for table in doc.d.tables:
        rows = table.rows
        if len(rows) < 2:
            continue
        head = [c.text.strip() for c in rows[0].cells]
        for row in rows[1:]:
            cells = row.cells
            for i, cell in enumerate(cells):
                text = cell.text.strip()
                if not lead.match(text):
                    continue
                row_label = cells[0].text.strip() if i else ""
                col_label = head[i] if i < len(head) and head[i] != row_label else ""
                label = row_label if len(cells) == 2 else " ".join(x for x in (_specific(row_label), _specific(col_label)) if x)
                set_cell(cell, lead.sub(placeholder(label or col_label), text, count=1))


def _no_placeholders(doc):
    """Anything still in [brackets] is a template placeholder nobody filled: ask for the specific information."""
    _label_unknowns(doc)
    rx = re.compile(r"\[[A-Z][^\]]{1,80}\]")
    CITE = re.compile(r"\[[^\[\]:]{1,80}:F\d+\]")     # a finding reference such as [FILE.cbl:F12] is not a placeholder
    for p in doc.body.iter(qn("w:t")):
        if p.text and rx.search(p.text) and "CUT OFF" not in p.text:
            p.text = rx.sub(lambda m: m.group(0) if CITE.fullmatch(m.group(0)) else placeholder(m.group(0)[1:-1]), p.text)
