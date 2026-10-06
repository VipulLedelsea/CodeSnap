"""The report's ratings, built the way an architect would defend them.

- Each health dimension is rated on its weakest material component, not the average, so one bad file is not diluted
  by several good ones; the average is shown for context.
- Dimensions with no evidence are shown as "Insufficient evidence" and the overall rating is capped at 3 (Fair) when
  less than 90% of the scorecard weight could be rated or confidence is low, so missing information never helps.
- Architectural and operational factors (platform count, integration style, data fragmentation, automated tests,
  silent error handling) sit in the scorecard next to the code measures.
- Security posture comes from the control ratings in 8.1; a control the code cannot show is "Not assessed".
- All ratings use one direction: 1 is best, 5 is worst.
"""
import math
import re

from . import plain as P
from . import rationale as R

LEVEL = P.LEVEL
COVERAGE_CAP = 0.9
SEV_RATING = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 2}
SEV = ["critical", "high", "medium", "low", "info"]


def words(c):
    return f"{c} – {LEVEL[c]}" if c else "Insufficient evidence"


def condition(score):
    return R.condition(score)[0] if score is not None else None


# ── security controls (8.1) ─────────────────────────────────────────────────────────────────────────────────────

AREAS = [
    ("Authentication", ("SEC-AUTH", "UIS-PWFIELD", "UIS-PW")),
    ("Authorization", ("SEC-AUTHZ", "SEC-CSRF", "SEC-PATH", "AC-")),
    ("Privileged", ()),
    ("Secrets management", ("SEC-CRED", "UIS-PREFILL")),
    ("Encryption in transit", ("SEC-TLS", "WEB-HTTPS", "WEB-TLS", "WEB-CERT", "UIS-MIXED")),
    ("Encryption at rest", ("SEC-CRYPTO",)),
    ("Input validation", ("SEC-SQLI", "SEC-SQLDYN", "SEC-XSS", "SEC-CMD", "SEC-DESER", "SEC-MEM")),
    ("Audit logging", ("SEC-ERR", "SEC-CONF")),
    ("Patch management", ()),
    ("Secure development", ()),
    ("Backup", ()),
    ("Third-party", ("CVE",)),
]
NOT_VISIBLE = {
    "Patch management": "Not assessed: patching is an operational process and cannot be judged from source code",
    "Secure development": "Not assessed: requires the development process (reviews, testing, pipeline)",
    "Backup": "Not assessed: requires the operations and disaster recovery records",
    "Encryption at rest": "Not assessed: storage encryption is configured outside the code",
    "Third-party": "Not assessed: no maintained vulnerability feed covers the legacy runtimes in use (see 8.2)",
    "Authentication": "Not assessed: sign-in is handled outside the code provided",
    "Authorization": "Not assessed: access rules are not visible in the code provided",
    "Input validation": "Not assessed: no injection weakness found, but validation rules were not reviewed in full",
    "Encryption in transit": "Not assessed: no connection settings found in the code provided",
    "Audit logging": "Not assessed: no logging found in the code provided",
    "Secrets management": "Not assessed: no credentials found in the code provided",
    "Privileged": "Not assessed: service and privileged accounts are managed outside the code",
}


def _users(findings):
    out = []
    for f in findings:
        for ev in f.get("evidence") or []:
            m = re.search(r"User\s*ID\s*=\s*([^;\"']+)", (ev or {}).get("snippet") or "", re.I)
            if m and m.group(1).strip() not in out:
                out.append(m.group(1).strip())
    return out


def controls(sec_f, audit_logs, sources_of, eol_techs, financial=False) -> list:
    """One row per template control: what the code shows, the gap, a 1-5 rating (None = not assessed) and its reason."""
    rows = []
    for area, rules in AREAS:
        fs = [f for f in sec_f if any((f.get("rule") or "").startswith(k) for k in rules)] if rules else []
        row = {"area": area, "findings": fs, "rating": None, "seen": "", "gap": "", "why": ""}
        if area == "Privileged":
            from .evidence import db_credentials
            creds = db_credentials(sec_f)
            users = _users(creds)
            if creds:
                row.update(rating=4, seen=f"Database accounts{' (' + ', '.join(users) + ')' if users else ''} "
                                         f"sign in with passwords held in the code ({len(creds)} place(s)).",
                           gap="The connection uses a password embedded in the code. Confirm account privileges, individual "
                               "user attribution and how the password is rotated.",
                           why="4 – Poor: shared database accounts with embedded passwords")
        elif area == "Audit logging":
            logs = [e for e in audit_logs]
            local = [e for e in logs if re.search(r"^[A-Za-z]:\\|^/|\.LOG$|\.TXT$", e["name"], re.I)]
            errs = [f for f in fs if f.get("rule") == "SEC-ERR"]
            bits, r_ = [], None
            if local:
                bits.append("Local log file only: " + "; ".join(
                    f"{', '.join(sorted(sources_of(e['id']))) or 'the application'} writes {e['name']}" for e in local[:3]))
                r_ = 4 if financial else 3
            if errs:
                bits.append(f"{len(errs)} place(s) where errors are swallowed: "
                            + ", ".join(sorted({_file(f) for f in errs})))
                r_ = max(r_ or 0, 4 if financial else 3)
            other = [f for f in fs if f.get("rule") != "SEC-ERR"]
            if other:
                r_ = max(r_ or 0, _sev_rating(other))
                bits.append(f"{len(other)} configuration issue(s) that disclose errors")
            if bits:
                row.update(rating=r_, seen=". ".join(bits) + ". No central logging or monitoring was seen in the code.",
                           gap="A local file can be edited or lost without anyone knowing, and a failed step can "
                               "look like success" + (", which for payments means an undetected misstatement" if financial else "") + ".",
                           why=f"{r_} – {LEVEL[r_]}: " + ("the audit trail is local and failures can be silent"
                                                          if local and errs else "the audit trail is local and unmonitored"
                                                          if local else "failures can pass silently"))
            elif logs:
                row.update(seen='Audit-related stores are referenced: ' + ', '.join(e['name'] for e in logs[:6]) + '.',
                           gap='Confirm which writes constitute the audit trail, user attribution, retention and tamper protection.',
                           why='Not assessed: audit references do not establish complete or protected logging.')
        elif area == "Patch management":
            row.update(why=NOT_VISIBLE[area], seen=("Unsupported technology that can no longer be patched: "
                                                    + ", ".join(eol_techs[:4]) + " (see 8.4).") if eol_techs else "")
        elif fs:
            r_ = _sev_rating(fs)
            kinds, whys = [], []
            for f in sorted(fs, key=lambda f: SEV.index(f["severity"])):
                w, y, _ = P.describe(f)
                if w not in kinds:
                    kinds.append(w)
                if y and y not in whys:
                    whys.append(y)
            cves = [f for f in fs if f.get("rule") == "CVE"]
            if len(cves) > 1:
                sub_ = P._subject(cves[0]["title"]) or "a component"
                kinds = [f"{len(cves)} published security weaknesses (CVEs) exist in {sub_}" if k.startswith("a published security weakness")
                         else k for k in kinds]
            many = f" ({len(fs)} places)" if len(fs) > 1 and not (len(cves) == len(fs)) else ""
            row.update(rating=r_, seen=_cap(P.sentence(kinds[:3])) + many + ".",
                       gap=(_cap(P.sentence(whys[:2])) + ".") if whys else "See 8.3",
                       why=f"{r_} – {LEVEL[r_]}: the most serious issue here is "
                           f"{min((f['severity'] for f in fs), key=SEV.index)}")
        if row["rating"] is None and not row["why"]:
            row["why"] = NOT_VISIBLE.get(area, "Not assessed: this cannot be seen in the code")
        rows.append(row)
    return rows


def _file(f):
    ev = (f.get("evidence") or [{}])[0] or {}
    return ev.get("file") or f["title"].split(": ")[-1].split(":")[0]


def _sev_rating(fs):
    return max(SEV_RATING.get(f["severity"], 2) for f in fs) if fs else None


def posture(rows) -> tuple:
    """Security posture from the assessed controls: the rounded mean, but never more than one level better than the
    worst control, and 5 if any control is critical."""
    rated = [r["rating"] for r in rows if r["rating"]]
    if not rated:
        return None, "Insufficient evidence: no security control could be assessed from the code."
    worst, mean = max(rated), sum(rated) / len(rated)
    c = max(math.floor(mean + 0.5), worst - 1)
    poor = [{"privileged": "privileged and service accounts"}.get(r["area"].lower(), r["area"].lower()) for r in rows if r["rating"] and r["rating"] >= 4]
    na = sum(1 for r in rows if not r["rating"])
    txt = (f"{words(c)}. Derived from the {len(rated)} controls in 8.1 that the code shows (average {mean:.1f}, worst "
           f"{worst}; the posture is never rated more than one level better than the worst control)."
           + (f" Rated poor or worse: {P.sentence(poor)}." if poor else "")
           + (f" {na} control(s) could not be assessed from the code and are open items." if na else ""))
    return c, txt


# ── indicative CVSS 3.1 ─────────────────────────────────────────────────────────────────────────────────────────

CVSS_BASE = {
    "SEC-SQLI": "AC:L/PR:L/UI:N/S:U/C:H/I:H/A:N", "SEC-SQLDYN": "AC:H/PR:L/UI:N/S:U/C:H/I:H/A:N",
    "SEC-CRED": "AC:L/PR:L/UI:N/S:U/C:H/I:H/A:N", "SEC-TLS": "AC:H/PR:N/UI:N/S:U/C:H/I:L/A:N",
    "SEC-AUTHZ": "AC:L/PR:L/UI:N/S:U/C:N/I:H/A:N", "SEC-CSRF": "AC:L/PR:N/UI:R/S:U/C:N/I:H/A:N",
    "SEC-CMD": "AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H", "SEC-XSS": "AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N",
    "SEC-PATH": "AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N", "SEC-DESER": "AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",
    "SEC-CRYPTO": "AC:H/PR:N/UI:N/S:U/C:H/I:N/A:N", "SEC-AUTH": "AC:L/PR:N/UI:N/S:U/C:H/I:L/A:N",
    "UIS-PWFIELD": "AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
}
FIXED_AV = {"SEC-TLS": "A", "UIS-PWFIELD": "P", "SEC-CSRF": "N"}
_W = {"AV": {"N": .85, "A": .62, "L": .55, "P": .2}, "AC": {"L": .77, "H": .44}, "UI": {"N": .85, "R": .62},
      "CIA": {"H": .56, "L": .22, "N": 0}}


def _roundup(x):
    i = round(x * 100000)
    return i / 100000.0 if i % 10000 == 0 else (math.floor(i / 10000) + 1) / 10.0


def cvss(rule: str, exposure: str):
    """(score, vector) for a code finding, with the attack vector taken from where the component runs."""
    base = CVSS_BASE.get((rule or "").split(":")[0])
    if not base:
        return None, ""
    e = (exposure or "").lower()
    av = FIXED_AV.get(rule) or ("N" if ("internet" in e or "network" in e) else "L" if "desktop" in e else "A")
    m = dict(kv.split(":") for kv in f"AV:{av}/{base}".split("/"))
    changed = m["S"] == "C"
    pr = {"N": .85, "L": .68 if changed else .62, "H": .5 if changed else .27}[m["PR"]]
    iss = 1 - (1 - _W["CIA"][m["C"]]) * (1 - _W["CIA"][m["I"]]) * (1 - _W["CIA"][m["A"]])
    impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15 if changed else 6.42 * iss
    expl = 8.22 * _W["AV"][m["AV"]] * _W["AC"][m["AC"]] * pr * _W["UI"][m["UI"]]
    if impact <= 0:
        return 0.0, f"CVSS:3.1/AV:{av}/{base}"
    score = _roundup(min(1.08 * (impact + expl), 10)) if changed else _roundup(min(impact + expl, 10))
    return score, f"CVSS:3.1/AV:{av}/{base}"


def cvss_band(score):
    return "Critical" if score >= 9 else "High" if score >= 7 else "Medium" if score >= 4 else "Low" if score > 0 else "None"


# ── health scorecard (6.1) ──────────────────────────────────────────────────────────────────────────────────────

DIMS = [("Technology currency", 20), ("Code quality", 15), ("Stability and reliability", 15),
        ("Performance and scalability", 10), ("Security posture", 15), ("Documentation and knowledge", 10),
        ("Business fit and adaptability", 15)]


# Dimensions that cannot be judged from source code at all (they need operations records and documents). They are
# shown as "Insufficient evidence" and left out of both the overall rating and the coverage figure, so the coverage
# cap measures what the code could have shown.
NOT_FROM_CODE = ("Performance and scalability", "Documentation and knowledge")


def material(comps, AM) -> list:
    """Code components that carry the application: 15+ lines, or they write data, or they define a data store."""
    roles = {c["name"]: c for c in AM["components"]}
    out = []
    for c in comps:
        am = roles.get(c["name"]) or {}
        if (c.get("type") or am.get("layer")) == "ui_screen" or am.get("layer") == "Presentation" and not c.get("lines"):
            continue
        if am.get("layer") == "Presentation" and (c.get("type") == "ui_screen" or c["name"].endswith(".screen")):
            continue
        if (c.get("lines") or 0) >= 15 or am.get("writes") or am.get("role") == "Database definition":
            out.append(c)
    return out or list(comps)


def _weakest(mat, dims):
    best = None
    for c in mat:
        vals = [(c["scores"].get(d) or {}).get("score") for d in dims]
        vals = [v for v in vals if v is not None]
        if not vals:
            continue
        v = min(vals)
        if best is None or v < best[1]:
            best = (c, v)
    return best


def _avg(mat, dims):
    vals = [(c["scores"].get(d) or {}).get("score") for c in mat for d in dims]
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals)) if vals else None


def _reasons(c, dims, n=3):
    fs = []
    for d in dims:
        fs += [{**f, "component": c["name"]} for f in (c["scores"].get(d) or {}).get("factors", [])]
    return P.reasons_words(sorted(fs, key=lambda f: f["points"]), n)


def scorecard(comps, AM, sec_rating, sec_text, facts) -> dict:
    """{dimension: (rating or None, reason)} plus the overall line. facts: tests, silent_errors, platforms,
    file_only, max_copies, frag_entity, confidence, skills."""
    mat = material(comps, AM)
    out = {}
    if not comps:
        why = "Insufficient evidence: no components were supplied, so nothing could be measured."
        out = {k: (None, why) for k, _ in DIMS}
        out["overall"] = (None, None, 0.0, "")
        return out

    def from_code(dims, label, extra=None):
        w = _weakest(mat, dims)
        if not w:
            return None, "Insufficient evidence: no material component could be measured."
        c, v = w
        rating = condition(v)
        rs = _reasons(c, dims)
        avg = condition(_avg(mat, dims))
        txt = (f"Rated on the weakest material component, {c['name']} ({words(rating)})"
               + (f"; the average across {len(mat)} components would be {avg}" if avg and avg != rating else "")
               + (f", mainly because {P.sentence(rs)}." if rs else ". No deductions."))
        for bump, why in (extra or []):
            if bump and rating:
                new = min(5, rating + bump)
                if new != rating:
                    txt += f" {why} Rating moved from {rating} to {new}."
                    rating = new
        return rating, txt

    out["Technology currency"] = from_code(["supportability"], "technology currency", [
        (0,
         f"It needs {len(facts.get('skills') or [])} required skill sets ({P.sentence(facts.get('skills') or [])}).")])
    if facts.get('confirmed_support') is False:
        out['Technology currency'] = (None, 'Insufficient evidence: deployed versions and vendor support entitlement are unconfirmed. Specialist maintenance skills are identified; available support cover needs confirmation.')
    out["Code quality"] = from_code(["tech_debt", "complexity"], "code quality", [
        (1 if not facts.get("tests") else 0, "No test files were identified in the supplied source; existing test coverage and baseline outputs are to confirm.")])
    out["Stability and reliability"] = from_code(["health"], "stability", [
        (1 if facts.get("silent_errors") else 0,
         f"Errors are swallowed in {', '.join(facts.get('silent_errors') or [])}, so a failure can look like success.")])
    hi = facts.get("review_high") or []
    st, st_txt = out["Stability and reliability"]
    if hi and st:
        floor = 4 if len(hi) >= 3 else 3
        if floor > st:
            st_txt += (f" The line-by-line review found {len(hi)} high-severity defect{'s' if len(hi) > 1 else ''} "
                       f"(3.6), for example: {hi[0]}. Rating moved from {st} to {floor}.")
            st = floor
        out["Stability and reliability"] = (st, st_txt)
    out["Performance and scalability"] = (None, "Insufficient evidence: needs run times, batch window and peak volumes "
                                                "from operations (see 6.3). Not included in the overall rating.")
    out["Security posture"] = (sec_rating, sec_text)
    out["Documentation and knowledge"] = (None, "Insufficient evidence: no design documents, run books or data "
                                                "dictionaries were provided. Indicators: " + P.sentence([x for x in (
        "no automated test files identified in supplied source" if not facts.get("tests") else "",
        f"file layouts found in supplied code ({facts['files']} file interface(s))" if facts.get("files") else "",
        f"{len(facts.get('skills') or [])} required skill sets" if facts.get("skills") else "") if x])
                                          + ". Not included in the overall rating.")
    arch = []
    p = facts.get("platforms")
    if p:
        arch.append((1 if p <= 1 else 2 if p == 2 else 3 if p == 3 else 4 if p <= 5 else 5,
                     f"it runs on {p} platform(s)"))
    if facts.get("file_only"):
        arch.append((3, ("supplied components exchange data through files and shared databases; no service or API layer was identified"
                         if facts.get("shared") else "no service or API layer was identified in supplied source, and no supplied component uses data another "
                         "one writes") if not facts.get("apis") else "most exchanges are files and shared databases; APIs are few"))
    mc = facts.get("max_copies") or 0
    if mc >= 3:
        arch.append((4 if mc >= 4 else 3, f"{(facts.get('frag_entity') or 'core').lower()} data is held in {mc} places with no named "
                                           f"system of record"))
    cpl = _weakest(mat, ["coupling"])
    if cpl:
        arch.append((condition(cpl[1]), f"code-level coupling is {words(condition(cpl[1])).split(' – ')[1].lower()}"))
    arch = [(a, w) for a, w in arch if a]
    if arch:
        r_ = max(a for a, _ in arch)
        out["Business fit and adaptability"] = (r_, f"Rated on architecture, because business fit needs the business owner: "
                                                   f"{P.sentence([w for _, w in sorted(arch, key=lambda x: -x[0])])}. The "
                                                   f"worst of these sets the rating.")
    else:
        out["Business fit and adaptability"] = (None, "Insufficient evidence: no architecture facts (platforms, "
                                                      "integration, data placement) could be established.")
    rated = [(k, w) for k, w in DIMS if out[k][0]]
    wsum = sum(w for _, w in rated)
    raw = sum(out[k][0] * w for k, w in rated) / wsum if wsum else None
    rateable = sum(w for k, w in DIMS if k not in NOT_FROM_CODE)
    cov = min(1.0, sum(w for k, w in rated if k not in NOT_FROM_CODE) / rateable) if rateable else 0.0
    conf = facts.get("confidence") or "medium"
    overall = math.floor(raw + 0.5) if raw else None
    cap_note = ""
    if overall and (cov < COVERAGE_CAP or conf == "low") and overall < 3:
        cap_note = (f" Capped at 3 – Fair because only {round(cov * 100)}% of the scorecard weight that source code can show could be rated"
                    + (" and assessment confidence is low" if conf == "low" else "") + "; the rating cannot be better "
                    "than Fair until the missing evidence is provided.")
        overall = 3
    out["overall"] = (overall, raw, cov, cap_note)
    return out


def overall_text(sc, confidence) -> str:
    overall, raw, cov, cap = sc["overall"]
    if not overall:
        return "Insufficient evidence"
    return (f"{words(overall)}. Weighted average {raw:.2f} across the rated areas, rounded half up"
            + f" to {math.floor(raw + 0.5)}.{cap} Evidence coverage: {round(cov * 100)}% of the scorecard weight; "
            f"assessment confidence: {confidence}.")


def _cap(t):
    return t[:1].upper() + t[1:] if t else t
