"""Financial and business controls, and the business risk register.

For an application that calculates, approves or posts money, some code findings are control failures rather than
code hygiene: an approval anyone can call, an audit trail on a desktop, a posting routine that swallows errors, copies
of payment data nobody reconciles, and calculations with no tests. These are rated as controls and carried into the
risk register at business impact, described in business terms rather than file names.
"""
import re

from . import plain as P

LEVEL = P.LEVEL
CALC = re.compile(r"CALC|COMPUTE|HOLDBACK|RATE|PRORAT|ADJUST|ENTITLE|AMOUNT", re.I)


def _files(fs):
    out = []
    for f in fs:
        ev = (f.get("evidence") or [{}])[0] or {}
        n = ev.get("file") or f["title"].split(": ")[-1].split(":")[0]
        if n not in out:
            out.append(n)
    return out


def approvals(store, arts):
    """Approval actions: endpoints or routines whose name says approve / authorise / release."""
    out = []
    for e in store.entities():
        if e["kind"] in ("api_endpoint", "method", "function", "procedure", "paragraph") and re.search(
                r"APPROV|AUTHORI[SZ]E|RELEASE", e["name"], re.I) and e["origin"] != "placeholder":
            out.append(e)
    return out


def _approval_text(arts, name):
    for a in arts:
        t = a.get("transcription") or ""
        m = re.search(rf"\b{re.escape(name.split()[-1].split('/')[-1])}\s*\([^)]*\)\s*\{{(.{{0,1200}}?)\n\s*\}}", t, re.S)
        if m:
            return a["name"], m.group(1)
    return None, ""


def assess(store, arts, sec_f, DM, CT, metrics, calc_routines, hard_rates, fin) -> list:
    """Rows: control, what the code shows, why it matters, rating (1-5 or None), components."""
    if not fin:
        return []
    rows = []
    appr = approvals(store, arts)
    authz = [f for f in sec_f if f.get("rule") == "SEC-AUTHZ"]
    if appr:
        names = sorted({e["name"] for e in appr})
        art, body = _approval_text(arts, names[0])
        who = bool(re.search(r"ApprovedBy|Approver|User\.Identity|CurrentUser|SYSTEM_USER|USER\b|getRemoteUser", body, re.I))
        seen = (f"Approval action{'s' if len(names) > 1 else ''} {', '.join(names[:3])}"
                + (f" with no authorization check ({', '.join(_files(authz))})" if authz else "")
                + ("; the approval does not record who approved" if body and not who else "")
                + "; no check that the approver differs from the person who prepared the payment is visible.")
        rows.append(["Maker-checker approval", seen,
                     "Without a named approver and a second person, one user (or anyone who can reach the endpoint) "
                     "can release a payment; this breaks segregation of duties.",
                     5 if authz else 4, _files(authz) or [art or ""]])
    else:
        rows.append(["Maker-checker approval", "No approval step was found in the code provided.",
                     "If payments are released without a second person's approval, segregation of duties is not met; "
                     "confirm where approval happens.", None, []])
    aud = next((r for r in CT if r["area"] == "Audit logging"), None)
    audit_calls = sorted({a["name"] for a in arts if re.search(r"AuditTrail|audit_pkg|AIDAUDIT|AUDIT\.LOG|AuditLog",
                                                                 a.get("transcription") or "", re.I)})
    local = [o for o in DM["occurrences"] if o["engine"].startswith("Windows desktop (local file)")]
    rows.append(["Audit trail integrity",
                 (f"Audit calls in {', '.join(audit_calls)}; their implementations were not provided. " if audit_calls else "")
                 + (f"{', '.join(sorted({o['component'] for o in local}))} writes its audit record to a local file "
                    f"({', '.join(sorted({o['store'] for o in local}))}) on the user's desktop." if local else ""),
                 "A desktop file can be edited, deleted or lost with the PC, so there is no trustworthy record of who "
                 "calculated or changed a payment.",
                 4 if local else (aud["rating"] if aud and aud["rating"] else None),
                 sorted({o["component"] for o in local}) or audit_calls])
    errs = [f for f in sec_f if f.get("rule") == "SEC-ERR"]
    pay_writers = {o["component"] for o in DM["occurrences"] if o["business"] == "Payment" and "W" in o["access"]}
    posting = [f for f in errs if set(_files([f])) & pay_writers] or errs
    rows.append(["Error handling in posting",
                 (f"Errors are swallowed in {', '.join(_files(posting))} ("
                  + P.sentence(sorted({f['detail'].rstrip('.') for f in posting})) + ").") if posting
                 else "No swallowed errors were found in the code provided.",
                 "A posting run that fails part-way can report success, so some recipients are not paid (or are paid "
                 "twice on a rerun) and nobody is told.",
                 4 if posting else None, _files(posting)])
    multi = [g for g in DM["entities"] if len(g["copies"]) >= 2 and g["name"] in ("Payment", "District", "Account",
                                                                                     "Invoice", "Ledger", "Transaction")]
    rec = DM["reconciliation"]
    rows.append(["Reconciliation between stores",
                 ("; ".join(f"{g['name']} data has {len(g['copies'])} copies on {len(g['platforms'])} platforms" for g in multi)
                  + ". " if multi else "")
                 + ("Control totals or record counts are kept in " + ", ".join(a for a, _ in rec)
                    + ", but no code compares one store with another." if rec else "No reconciliation logic was found."),
                 "Copies that are not reconciled drift apart, so the amount calculated, the amount approved and the amount "
                 "paid can differ without anyone noticing.",
                 4 if multi else None, sorted({o["component"] for g in multi for o in g["occ"]})])
    outs = [o for o in DM["occurrences"] if o["business"] == "Payment" and o["engine"].endswith("(files)") and "W" in o["access"]]
    trailer = any(re.search(r"TRAILER|CONTROL-REC|HASH", a.get("transcription") or "", re.I) for a in arts)
    if outs:
        rows.append(["Control totals on file exchanges",
                     f"{', '.join(sorted({o['store'] for o in outs}))} is written by {', '.join(sorted({o['component'] for o in outs}))}; "
                     + ("totals are printed on the control report, " if rec else "")
                     + ("and a trailer or control record is written." if trailer else
                        "but no trailer or control record is written for the receiving system to check."),
                     "Without a control record the receiving system cannot prove it received every payment, and a "
                     "truncated file can be processed as complete.",
                     2 if trailer else 3, sorted({o["component"] for o in outs})])
    rows.append(["Automated tests on calculations",
                 (f"Calculation routines ({', '.join(calc_routines[:5])}) have no automated tests."
                  if not metrics.get("tests") else f"{metrics['tests']} test file(s) found."),
                 "Any change to a payment formula, including a modernization, cannot be checked against today's results, "
                 "so an error can reach recipients undetected.",
                 4 if not metrics.get("tests") else 2, []])
    if hard_rates:
        rows.append(["Rate and parameter changes",
                     "Rates held as literals in the code: " + "; ".join(hard_rates[:4]) + ".",
                     "A statutory rate change needs a code change and release, outside business approval and audit.",
                     3, sorted({h.split(" in ")[-1] for h in hard_rates})])
    return rows


def hard_rates(arts) -> list:
    out = []
    for a in arts:
        t = a.get("transcription") or ""
        for m in re.finditer(r"\*\s*(\d{3,}(\.\d+)?)\b", t):
            out.append(f"multiplier {m.group(1)} in {a['name']}")
        for m in re.finditer(r"\b([\w-]*(PCT|RATE|PERCENT)[\w-]*)\s+PIC\s+\S+\s+VALUE\s+([\d.]+)", t, re.I):
            out.append(f"{m.group(1)} = {m.group(3).rstrip('.')} in {a['name']}")
    return out


# ── the business risk register ──────────────────────────────────────────────────────────────────────────────────

def band(score):
    return "High" if score >= 15 else "Medium" if score >= 8 else "Low"


def register(ctx) -> list:
    """Business risks from the evidence, each with the reason for its likelihood and impact."""
    fin, tier1 = ctx["fin"], ctx["tier1"]
    imp_pay = 5 if fin and tier1 else 4
    basis_imp = ("5: the application pays public money and is Tier 1"
                 if imp_pay == 5 else "4: the application writes business data; to be confirmed by the business owner")
    out = []

    def add(title, cat, L, lbasis, I, ibasis, comps, mit, owner, existing="None visible in the code"):
        out.append({"title": title, "cat": cat, "L": L, "I": I, "score": L * I, "why_L": lbasis, "why_I": ibasis,
                    "comps": comps, "mit": mit, "owner": owner, "existing": existing})
    fc = {r[0]: r for r in ctx["fin_controls"]}
    if fc.get("Maker-checker approval") and fc["Maker-checker approval"][3] and fc["Maker-checker approval"][3] >= 4:
        add("Payments can be approved without an authorized second person", "Financial control", 4,
            "4: the approval action has no visible authorization check and is reachable over the network",
            imp_pay, basis_imp, fc["Maker-checker approval"][4],
            "Require a named approver role, enforce maker-checker, and log approver identity; review approvals made to date",
            ctx["owner_fin"])
    if fc.get("Error handling in posting") and fc["Error handling in posting"][3]:
        add("A failed posting run can report success, so payments are missed or duplicated", "Financial control", 3,
            "3: any database error in the posting run is swallowed; incident history is unknown", imp_pay, basis_imp,
            fc["Error handling in posting"][4],
            "Raise and log every error, stop the run on failure, and reconcile posted totals to calculated totals",
            ctx["owner_it"])
    frag = [g for g in ctx["DM"]["entities"] if len(g["copies"]) >= 3]
    if frag:
        g = frag[0]
        add(f"{g['name']} and related data disagree between the {len(g['copies'])} copies held on "
            f"{len(g['platforms'])} platforms", "Data integrity", 4,
            "4: no system of record is named and no reconciliation between stores is visible in the code",
            imp_pay if fin else 4, basis_imp,
            sorted({o["component"] for g_ in frag for o in g_["occ"]})[:6],
            "Name a system of record per entity (5.5), then add reconciliation with control totals between the copies",
            ctx["owner_it"], existing=("Control totals and record counts in " + ", ".join(a for a, _ in ctx["DM"]["reconciliation"])
                                       + " (within one program only)") if ctx["DM"]["reconciliation"] else "None visible in the code")
    if fc.get("Audit trail integrity") and (fc["Audit trail integrity"][3] or 0) >= 4:
        add("The audit trail can be altered or lost", "Financial control", 3,
            "3: the audit record is a local desktop file that any user of the PC can change", imp_pay if fin else 3,
            basis_imp if fin else "3: loss of audit evidence", fc["Audit trail integrity"][4],
            "Write audit events to a central, append-only log with retention", ctx["owner_sec"])
    if fc.get("Automated tests on calculations") and fc["Automated tests on calculations"][3] >= 4:
        add("A change to the payment calculations introduces an error nobody detects", "Delivery", 4 if ctx["rewrite"] else 3,
            ("4: there are no automated tests, and the recommended work rewrites components that hold the calculations"
             if ctx["rewrite"] else "3: there are no automated tests, and any fix or modernization touches the calculations"),
            imp_pay, basis_imp, [], "Build characterization tests from current outputs before any change; run in parallel",
            ctx["owner_it"])
    for t in ctx["eol"]:
        add(f"{t} fails or is compromised with no vendor fix available", "Technology", 4,
            f"4: {t} is past end of vendor support, so security fixes and support are no longer available",
            4, "4: the component calculates or displays payment data" if fin else "4: the component is in daily use",
            ctx["eol_comps"].get(t, []), "Replace the component (12.3); until then isolate it and restrict who can run it",
            ctx["owner_it"])
    if len(ctx["skills"]) >= 3:
        add(f"Too few people can support the {len(ctx['skills'])} legacy platforms", "People", 4,
            f"4: scarce skills are needed for {P.sentence(ctx['skills'])}; named staff are unknown (10.4)", 4,
            "4: an unresolved fault during a payment cycle would delay payments", [],
            "Name the people per platform, document the run books, and fund cross-training or vendor cover",
            ctx["owner_it"])
    if ctx["platforms"] >= 4:
        add(f"The application is spread over {ctx['platforms']} platforms, which multiplies cost and change effort", "Architecture",
            3, "3: every change that crosses platforms needs several skill sets and release processes", 3,
            "3: slower change and higher run cost rather than an outage", [], "Reduce platforms in the target architecture (12.6)",
            ctx["owner_ea"])
    if ctx["creds"]:
        add("Shared database passwords in the code are misused", "Security", 3,
            "3: the passwords are readable by anyone with access to the code and cannot be rotated without a release",
            imp_pay if fin else 4, basis_imp, ctx["creds"], "Rotate the passwords now and move them to a secrets store",
            ctx["owner_sec"])
    if ctx["inject"]:
        add("Crafted input changes or exposes payment data (injection)", "Security", 3,
            "3: queries or commands are built from input in " + ", ".join(ctx["inject"][:3]), imp_pay if fin else 4,
            basis_imp, ctx["inject"], "Parameterize the statements; validate input", ctx["owner_sec"])
    if ctx["missing"]:
        add(f"Unreviewed code ({ctx['missing']} referenced components not provided) changes the picture", "Assessment", 4,
            "4: the components are referenced by the code but were not provided for review", 3,
            "3: the ratings and estimate may be understated", [], "Provide the missing source and re-run the assessment",
            ctx["owner_it"])
    rank = ["Financial control", "Data integrity", "Security", "Delivery", "Technology", "People", "Assessment", "Architecture"]
    out.sort(key=lambda r: (-r["score"], rank.index(r["cat"]) if r["cat"] in rank else 9))
    return out
