import re

from core.security.rules import code_lines, family

DIMENSIONS = ("health", "tech_debt", "security", "supportability", "complexity", "coupling", "ux")
LABELS = {"health": "Health", "tech_debt": "Tech debt", "security": "Security", "supportability": "Supportability",
          "complexity": "Complexity", "coupling": "Coupling", "ux": "UX & accessibility"}
UX_POINTS = {"accessibility": {"high": 15, "medium": 6, "low": 2}, "usability": {"high": 12, "medium": 5, "low": 2}}
SEC_POINTS = {"critical": 25, "high": 15, "medium": 7, "low": 3, "info": 0}
EOL_POINTS = {"eol": 35, "extended": 20, "legacy": 20, "ending": 15, "unknown": 3}
_DECISION = {
    "cobol": r"\b(IF|EVALUATE|WHEN|PERFORM\s+UNTIL|PERFORM\s+VARYING|GO\s+TO)\b",
    "default": r"\b(if|else\s+if|elif|case|for|foreach|while|catch|switch)\b|\?\s*[^:;]+:|&&|\|\|",
}
_DECISION["legacy"] = (r"\b(IF|ELSEIF|ELSIF|ELSE\s+IF|WHEN|CASE|SELECT\s+CASE|DECIDE|FOR|FOREACH|WHILE|UNTIL|DOW|DOU|"
                       r"DO\s+WHILE|DO\s+UNTIL|CATCH|ON\s+ERROR|SCAN|IFEQ|IFNE|IFGT|IFLT|IFGE|IFLE|DOWEQ|DOWNE|CABEQ|CABNE)\b")
_GOTO = {"cobol": r"\bGO\s+TO\b", "default": r"(?<!Error )\bgoto\s+\w+",
         "legacy": r"(?<!Error )\bGO\s*TO\b|\bGOSUB\b|\bSIGNAL\s+(?!ON\b|OFF\b)\w+|\bCABEQ\b|\bCABNE\b|\bESCAPE\s+(TOP|BOTTOM)\b"}
SKILL_SCARCE = ("COBOL", "COBOL copybook", "CICS BMS map", "JCL")
SCARCE_FAMILIES = {
    "cobol": "COBOL", "rpg": "RPG / IBM i", "cl": "IBM i CL", "natural": "Natural/Adabas", "pli": "PL/I",
    "asm": "mainframe assembler", "easytrieve": "Easytrieve", "rexx": "REXX / TSO", "clist": "TSO CLIST",
    "powerbuilder": "PowerBuilder", "foxpro": "Visual FoxPro", "informix4gl": "Informix 4GL", "progress": "Progress ABL",
    "delphi": "Delphi", "vb6": "Visual Basic 6", "basic": "DOS-era BASIC", "fortran": "Fortran",
    "ims_dbd": "IMS", "ims_psb": "IMS", "ims_mfs": "IMS MFS", "oracle_forms": "Oracle Forms", "informix_form": "Informix 4GL",
    "datawindow": "PowerBuilder", "dfm": "Delphi", "ispf_panel": "ISPF",
}


class Score:
    def __init__(self, dim):
        self.dim, self.value, self.factors = dim, 100, []

    def deduct(self, points, rule, text, refs=None, cap=None):
        points = min(points, cap) if cap is not None else points
        if points <= 0:
            return
        self.value = max(0, self.value - points)
        self.factors.append({"rule": rule, "points": -round(points, 1), "text": text, "refs": refs or {}})

    def out(self):
        return {"score": round(self.value), "factors": self.factors}


def grade(score) -> str:
    if score is None:
        return "n/a"
    return "good" if score >= 80 else "fair" if score >= 60 else "poor" if score >= 40 else "critical"


def text_metrics(text: str, name: str, language: str = "") -> dict:
    fam = family(name, language, text or "")
    lines = code_lines(text or "", fam)
    code = [l for l in lines if l.strip()]
    from core.security.rules import PACK_IDS
    key = "cobol" if fam == "cobol" else "legacy" if (fam in PACK_IDS and fam not in ("javascript", "python", "perl", "php", "shell")) \
        or fam == "vb" else "default"
    flags = re.I if key in ("cobol", "legacy") else 0
    decisions = sum(len(re.findall(_DECISION[key], l, flags)) for l in code)
    gotos = sum(len(re.findall(_GOTO[key], l, flags)) for l in code)
    return {"lines": len(code), "decisions": decisions, "gotos": gotos, "family": fam}


def _profile(file_entity):
    return ((file_entity or {}).get("attrs") or {}).get("profile") or {}


def _legacy_rules():
    from core.langpacks.specs import PACKS
    return {label: rx for p in PACKS for label, rx in p.get("legacy", [])}


RENAMED = {"RPG cycle / indicators (*INxx)": ("numbered indicators (*INxx)", "indicator operations (SETON/SETOF)")}


def _markers(markers, text):
    """Legacy markers that the file's current text still shows (profiles stored before a rule changed are rechecked)."""
    rules, out = _legacy_rules(), []
    for m in markers:
        for label in RENAMED.get(m, (m,)):
            rx = rules.get(label)
            if (rx is None and label == m) or (rx and any(re.search(rx, l, re.I) for l in text.splitlines())):
                if label not in out:
                    out.append(label)
    return out


def score_component(c: dict) -> dict:
    s = {d: Score(d) for d in DIMENSIONS}
    art, prof, m = c["artifact"], _profile(c.get("file")), c["metrics"]

    h = s["health"]
    if art.get("status") == "failed":
        h.deduct(40, "HLT-FAILED", "capture or transcription failed")
    if c["missing_code"]:
        h.deduct(3 * c["missing_code"], "HLT-GAPS", f"calls {c['missing_code']} program(s)/class(es) not captured", cap=15)
    for f in c["findings"]:
        if f["category"] == "security" and f["rule"] in ("SEC-MEM", "SEC-CONF") and f["severity"] in ("high", "medium"):
            h.deduct(3, "HLT-FRAGILE", f"{f['title']}", {"finding": f["id"]}, cap=3)

    d = s["tech_debt"]
    legacy = _markers(prof.get("legacy_markers") or [], art.get("transcription") or "")
    for marker in legacy[:6]:
        d.deduct(7, "DEBT-LEGACY", f"legacy construct: {marker}", {"evidence": (prof.get("evidence") or {}).get(marker)})
    if str(prof.get("dialect") or "").startswith("pre-standard"):
        d.deduct(20, "DEBT-PRESTD", "pre-standard C++ dialect — must be ported before any modern compiler builds it")
    if prof.get("cobol_translated"):
        d.deduct(20, "DEBT-TRANSLATED", "machine-translated COBOL→.NET (COBOL naming, paragraph methods, GOTO labels)")
    if m["gotos"]:
        d.deduct(2 * m["gotos"], "DEBT-GOTO", f"{m['gotos']} GO TO / goto statement(s)", cap=15)
    if m["lines"] > 5000:
        d.deduct(20, "DEBT-SIZE", f"very large file ({m['lines']} code lines)")
    elif m["lines"] > 2000:
        d.deduct(10, "DEBT-SIZE", f"large file ({m['lines']} code lines)")
    long_units = [u for u in c["units"] if (u["line_end"] or 0) - (u["line_start"] or 0) > 200]
    if long_units:
        d.deduct(3 * len(long_units), "DEBT-LONG", f"{len(long_units)} routine(s) over 200 lines: "
                 + ", ".join(u["name"] for u in long_units[:4]), cap=15)

    sec = s["security"]
    for f in c["findings"]:
        if f["category"] in ("security", "vulnerability", "ui_security") or (
                f["category"] == "website" and f.get("rule") != "WEB-EOL"):
            sec.deduct(SEC_POINTS.get(f["severity"], 0), f["rule"] or f["category"], f["title"], {"finding": f["id"]})
    if c["student_data"] and any(f["category"] == "security" and f["severity"] in ("critical", "high")
                                 for f in c["findings"]):
        sec.deduct(10, "SEC-FERPA", "high-severity issue in a component that handles personal data")

    sup = s["supportability"]
    for f in c["findings"]:
        if f["category"] == "eol" or f.get("rule") == "WEB-EOL":
            status = (f.get("refs") or {}).get("eol_status")
            pts = EOL_POINTS.get(status, 0) * (0.5 if "not confirmed" in (f.get("detail") or "") else 1)
            if pts and status not in (None, 'unknown', 'unconfirmed'):
                sup.deduct(pts, "SUP-EOL", f["title"], {"finding": f["id"]})
    lang = art.get("language") or prof.get("language") or ""
    scarce = SCARCE_FAMILIES.get(c["metrics"]["family"]) or SCARCE_FAMILIES.get(prof.get("pack") or "")
    if lang in SKILL_SCARCE:
        scarce = "COBOL"
    if (prof.get("language") or "").upper().startswith("IMS"):
        scarce = "IMS"
    if scarce == "COBOL" and ("CICS" in (prof.get("frameworks") or []) or re.search(r"\bEXEC\s+CICS\b|DFHCOMMAREA|\bEIBCALEN\b",
                                                                                  art.get("transcription") or "", re.I)):
        scarce = "COBOL/CICS"
    if prof.get("pack") == "cobol" and set(prof.get("frameworks") or []) & {"IDMS", "IMS DB/DC"}:
        scarce = "COBOL + " + "/".join(sorted(set(prof["frameworks"]) & {"IDMS", "IMS DB/DC"}))
    if scarce:
        sup.deduct(10, "SUP-SKILLS", f"{scarce} specialist skills required — support availability to confirm; provisional supportability deduction")

    cx = s["complexity"]
    units = max(1, len(c["units"]))
    per_unit = m["decisions"] / units
    density = m["decisions"] / max(1, m["lines"]) * 100
    if per_unit > 20:
        cx.deduct(35, "CPX-DECISIONS", f"{per_unit:.0f} decision points per routine on average")
    elif per_unit > 10:
        cx.deduct(20, "CPX-DECISIONS", f"{per_unit:.0f} decision points per routine on average")
    if density > 25:
        cx.deduct(15, "CPX-DENSITY", f"{density:.0f} decisions per 100 lines")
    if m["lines"] > 1000:
        cx.deduct(10, "CPX-SIZE", f"{m['lines']} code lines in one file")
    if len(c["units"]) > 60:
        cx.deduct(10, "CPX-UNITS", f"{len(c['units'])} routines in one file")

    k = s["coupling"]
    if c["fan_out"] > 20:
        k.deduct(30, "CPL-FANOUT", f"depends on {c['fan_out']} things in other files")
    elif c["fan_out"] > 10:
        k.deduct(15, "CPL-FANOUT", f"depends on {c['fan_out']} things in other files")
    if c["fan_in"] > 10:
        k.deduct(15, "CPL-FANIN", f"used by {c['fan_in']} other files — changes ripple widely")
    elif c["fan_in"] > 5:
        k.deduct(8, "CPL-FANIN", f"used by {c['fan_in']} other files")
    if c["shared_writes"]:
        k.deduct(5 * len(c["shared_writes"]), "CPL-SHARED", "writes tables other files also write: "
                 + ", ".join(sorted(c["shared_writes"])[:4]), cap=20)
    if c["external"]:
        k.deduct(5 * len(c["external"]), "CPL-EXTERNAL", "connects to external systems/stores: "
                 + ", ".join(sorted(c["external"])[:4]), cap=20)
    ux = s["ux"]
    for f in c["findings"]:
        pts = UX_POINTS.get(f["category"], {}).get(f["severity"], 0)
        if f.get("rule") == "ACC-TERMINAL":
            pts = 0  # terminal interface type alone establishes no accessibility failure
        ux.deduct(pts, f.get("rule") or f["category"], f["title"], {"finding": f["id"]})
    return {dim: sc.out() for dim, sc in s.items()}


WEIGHTS = {"health": 0.15, "tech_debt": 0.18, "security": 0.24, "supportability": 0.18, "complexity": 0.08,
           "coupling": 0.07, "ux": 0.1}


def overall(scores: dict) -> int:
    return round(sum(scores[d]["score"] * w for d, w in WEIGHTS.items()))


def program_scores(components: list) -> dict:
    out = {}
    for dim in DIMENSIONS:
        weighted = [(c["scores"][dim]["score"], max(20, c["metrics"]["lines"])) for c in components]
        if not weighted:
            out[dim] = {"score": None, "worst": None, "grade": "n/a"}
            continue
        avg = sum(v * w for v, w in weighted) / sum(w for _, w in weighted)
        worst = min(components, key=lambda c: c["scores"][dim]["score"])
        value = avg
        if dim in ("security", "supportability"):
            value = min(avg, worst["scores"][dim]["score"] + 25)
        out[dim] = {"score": round(value), "average": round(avg), "grade": grade(value),
                    "worst": {"component": worst["name"], "score": worst["scores"][dim]["score"]}}
    valid = {d: v for d, v in out.items() if v["score"] is not None}
    out["overall"] = {"score": overall(valid) if len(valid) == len(DIMENSIONS) else None}
    out["overall"]["grade"] = grade(out["overall"]["score"])
    return out
