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


def assess(store, arts, sec_f, DM, CT, metrics, calc_routines, hard_rates, fin, ev=None) -> list:
    """Rows: control, what the code shows, why it matters, rating (1-5 or None), components.
    ev: evidence from the source (batch totals, the line-by-line review's error-handling findings)."""
    if not fin:
        return []
    from .evidence import cite, totals_sentence
    ev = ev or {}
    rows = []
    appr = approvals(store, arts)
    authz = [f for f in sec_f if f.get("rule") == "SEC-AUTHZ"]
    if appr:
        names = sorted({e["name"] for e in appr})
        art, body = _approval_text(arts, names[0])
        who = bool(re.search(r"ApprovedBy|Approver|User\.Identity|CurrentUser|SYSTEM_USER|USER\b|getRemoteUser|AuditTrail|Audit\w*\.", body, re.I))
        seen = (f"Approval action{'s' if len(names) > 1 else ''} {', '.join(names[:3])}"
                + (f" with no authorization check ({', '.join(_files(authz))})" if authz else "")
                + ("; the approval does not record who approved" if body and not who else "")
                + "; no check that the approver differs from the person who prepared the payment is visible.")
        rows.append(["Maker-checker approval", seen,
                     "The supplied approval path does not establish separation between preparation and approval. Confirm role "
                     "checks, global authorization filters and the workflow used in production.",
                     5 if authz else 4, _files(authz) or [art or ""]])
    else:
        rows.append(["Maker-checker approval", "No approval step was found in the code provided.",
                     "If payments are released without a second person's approval, segregation of duties is not met; "
                     "confirm where approval happens.", None, []])
    aud = next((r for r in CT if r["area"] == "Audit logging"), None)
    audit_calls = sorted({a["name"] for a in arts if re.search(r"AuditTrail|audit_pkg|AIDAUDIT|AUDIT\.LOG|AuditLog|INSERT\s+INTO\s+\w*AUDIT\w*|WRITE\s+FILE\s*\(\s*\w*AUDIT\w*\s*\)|DSN\s*=\s*[\w.]*AUDIT[\w.]*",
                                                                 a.get("transcription") or "", re.I)})
    local = [o for o in DM["occurrences"] if o["engine"].startswith("Windows desktop (local file)")
             and "W" in o["access"] and re.search(r"AUDIT|LOG", o["store"], re.I)]
    seen_a = ((f"Audit-related file operations in {', '.join(audit_calls)}; completeness and protection are unconfirmed. " if audit_calls else "")
              + (f"{', '.join(sorted({o['component'] for o in local}))} writes its audit record to a local file "
                 f"({', '.join(sorted({o['store'] for o in local}))}) on the user's desktop." if local else "")).strip()
    rows.append(["Audit trail integrity", seen_a or (aud.get('seen') if aud else '') or "Audit implementation and coverage could not be established from the supplied source.",
                 "A local audit file may be altered or lost unless permissions, retention and collection controls protect it. "
                 "Those controls are to confirm." if local else
                 "Confirm the audit implementation, user attribution, retention and any central collection before assessing traceability.",
                 4 if local else (aud["rating"] if aud and aud["rating"] else None),
                 sorted({o["component"] for o in local}) or audit_calls])
    errs = [f for f in sec_f if f.get("rule") == "SEC-ERR"]
    bypasses = ev.get('review_bypasses') or []
    if bypasses:
        rows.append(['Business-rule overrides', '; '.join(f'{name}: {statement} ({cite(lines)})'
                     for name, statement, lines in bypasses[:3]),
                     'Confirm whether each override is authorized business policy. Restrict and audit any intended exception; regression-test status precedence.',
                     4, sorted({name for name, _, _ in bypasses})])
    pay_writers = {o["component"] for o in DM["occurrences"] if o["business"] == "Payment" and "W" in o["access"]}
    posting = [f for f in errs if set(_files([f])) & pay_writers] or errs
    unchecked = [r for r in ev.get("review_errors") or [] if r[0] in pay_writers]
    first = []
    for r in unchecked:
        if r[0] not in [x[0] for x in first]:
            first.append(r)
    pick = first + [r for r in unchecked if r not in first]
    if posting:
        seen_e = (f"Errors are swallowed in {', '.join(_files(posting))} ("
                  + P.sentence(sorted({f['detail'].rstrip('.') for f in posting})) + ").")
    elif unchecked:
        seen_e = "The line-by-line review found errors that the posting code does not check: " + "; ".join(
            f"{n}: {P.lower_first(s)} ({cite(ls)})" for n, s, ls in pick[:3]) + "."
    else:
        seen_e = "Error handling is not fully assessed; confirm source-level findings, transaction boundaries and recovery behavior."
    rows.append(["Error handling in posting", seen_e,
                 "Unchecked failures could leave incomplete updates. Confirm transaction boundaries, restart behavior and "
                 "duplicate prevention before assessing the effect of a rerun.",
                 4 if posting or unchecked else None, _files(posting) or sorted({r[0] for r in unchecked})])
    multi = [g for g in DM["entities"] if len(g["copies"]) >= 2 and g["name"] in ("Payment", "District", "Account",
                                                                                     "Invoice", "Ledger", "Transaction")]
    bt = ev.get("totals") or {}
    tot = "; ".join(f"{c}: {totals_sentence(bt, c)}" for c in sorted(bt) if totals_sentence(bt, c))
    rows.append(["Reconciliation between stores",
                 ("; ".join(f"{g['name']} data has {len(g['copies'])} copies on {len(g['platforms'])} platform"
                            f"{'s' if len(g['platforms']) > 1 else ''}" for g in multi) + ". " if multi else "")
                 + (f"Within one program only ({tot}). " if tot else "")
                 + "Cross-store reconciliation has not been established from the supplied code; confirm the comparison and exception-handling process.",
                 "Different stores could diverge if updates are not reconciled. Compare the calculation and posting outputs; "
                 "confirm any reconciliation performed outside these components.",
                 4 if multi else None, sorted({o["component"] for g in multi for o in g["occ"]})])
    outs = [o for o in DM["occurrences"] if o["business"] == "Payment" and o["engine"].endswith("(files)") and "W" in o["access"]]
    if outs:
        writers = sorted({o["component"] for o in outs})
        tw = "; ".join(totals_sentence(bt, w) for w in writers if totals_sentence(bt, w))
        rows.append(["Control totals on file exchanges",
                     f"{', '.join(sorted({o['store'] for o in outs}))} is written by {', '.join(writers)}"
                     + (f" ({tw})" if tw else "") + "; "
                     + "output trailer records and receiving-system checks are to confirm.",
                     "File completeness checks may use record counts, totals or acknowledgements. Confirm what the producer "
                     "writes and what the consumer checks.",
                     None, writers])
    rows.append(["Automated tests on calculations",
                 (f"Calculation routines ({', '.join(calc_routines[:5])}) have no test files in the supplied source."
                  if not metrics.get("tests") else f"{metrics['tests']} test file(s) found."),
                 "Test-file counts do not establish execution coverage. Confirm the available test suite and baseline results "
                 "before changing calculation logic.",
                 4 if not metrics.get("tests") else 2, []])
    if hard_rates:
        rows.append(["Rate and parameter changes",
                     "Rates and parameters held as literals in the code: " + "; ".join(hard_rates[:4]) + ".",
                     "Changing these literals requires a code change. Confirm the business meaning, approval process and release controls.",
                     3, sorted({h.split(" in ")[-1] for h in hard_rates})])
    return rows


def hard_rates(arts) -> list:
    out = []
    for a in arts:
        t = a.get("transcription") or ""
        t = "\n".join(l for l in t.splitlines() if "[CUT OFF]" not in l
                      and not l.lstrip().startswith(('*', '//*', '--', '/*'))
                      and not (len(l) > 6 and l[6] in ('*', '/')))
        for m in re.finditer(r"\*\s*(\d{3,}(\.\d+)?)\b", t):
            out.append(f"multiplier {m.group(1)} in {a['name']}")
        for m in re.finditer(r"\b([\w-]*(PCT|RATE|PERCENT)[\w-]*)\s+PIC\s+\S+\s+VALUE\s+([\d.]+)", t, re.I):
            out.append(f"{m.group(1)} = {m.group(3).rstrip('.')} in {a['name']}")
        for m in re.finditer(r"\b([\w-]*(PERIOD|YEAR|YYMM|CCYY|DATE)[\w-]*)\s+PIC\s+\S+\s+VALUE\s+(\d{4,8})\b", t, re.I):
            out.append(f"{m.group(1)} = {m.group(3)} in {a['name']}")
    return out


# ── the business risk register ──────────────────────────────────────────────────────────────────────────────────

def band(score):
    return "High" if score >= 15 else "Medium" if score >= 8 else "Low"


def register(ctx) -> list:
    """Business risks from the evidence, each with the reason for its likelihood and impact."""
    fin, tier1 = ctx["fin"], ctx["tier1"]
    imp_pay = 5 if fin and tier1 else 4
    basis_imp = ("5: payment-related source and the entered Tier 1 classification; business impact is to confirm"
                 if imp_pay == 5 else "4: the application writes business data; to be confirmed by the business owner")
    out = []

    def add(title, cat, L, lbasis, I, ibasis, comps, mit, owner, existing="None visible in the code"):
        out.append({"title": title, "cat": cat, "L": L, "I": I, "score": L * I, "why_L": lbasis, "why_I": ibasis,
                    "comps": comps, "mit": mit, "owner": owner, "existing": existing})
    fc = {r[0]: r for r in ctx["fin_controls"]}
    if fc.get('Business-rule overrides'):
        add('Source logic can override payment controls', 'Financial control', 3,
            '3 (provisional): the reviewed source contains override paths (8.6); production reachability and approved policy are unconfirmed',
            imp_pay, basis_imp, fc['Business-rule overrides'][4],
            'Validate the intended exception rules, restrict and audit authorized overrides, and test status precedence', ctx['owner_fin'])
    if fc.get("Maker-checker approval") and fc["Maker-checker approval"][3] and fc["Maker-checker approval"][3] >= 4:
        add("Payments can be approved without an authorized second person", "Financial control", 4,
            "4: the supplied approval path does not establish maker-checker enforcement; deployment access is to confirm",
            imp_pay, basis_imp, fc["Maker-checker approval"][4],
            "Require a named approver role, enforce maker-checker, and log approver identity; review approvals made to date",
            ctx["owner_fin"])
    if fc.get("Error handling in posting") and fc["Error handling in posting"][3]:
        swallowed = "swallowed" in (fc["Error handling in posting"][1] or "")
        add("Unchecked posting errors could leave incomplete or duplicate updates", "Financial control", 3,
            ("3: errors in the posting run are swallowed" if swallowed else
             "3: the line-by-line review found file and write errors the posting code does not check (8.6)")
            + "; incident history is unknown", imp_pay, basis_imp,
            fc["Error handling in posting"][4],
            "Raise and log every error, stop the run on failure, and reconcile posted totals to calculated totals",
            ctx["owner_it"])
    frag = [g for g in ctx["DM"]["entities"] if len(g["copies"]) >= 3]
    if frag:
        g = frag[0]
        add(f"{g['name']} data could drift apart between the {len(g['copies'])} copies held on "
            f"{len(g['platforms'])} platform{'s' if len(g['platforms']) > 1 else ''}", "Data integrity", 4,
            "4: no system of record is named and no reconciliation between stores is visible in the code",
            imp_pay if fin else 4, basis_imp,
            sorted({o["component"] for g_ in frag for o in g_["occ"]})[:6],
            "Name a system of record per entity (5.5), then add reconciliation with control totals between the copies",
            ctx["owner_it"], existing=ctx.get("existing_totals") or "None visible in the code")
    if fc.get("Audit trail integrity") and (fc["Audit trail integrity"][3] or 0) >= 4:
        add("The audit trail can be altered or lost", "Financial control", 3,
            "3: a local audit file is referenced; filesystem permissions and central retention are to confirm", imp_pay if fin else 3,
            basis_imp if fin else "3: loss of audit evidence", fc["Audit trail integrity"][4],
            "Write audit events to a central, append-only log with retention", ctx["owner_sec"])
    if fc.get("Automated tests on calculations") and fc["Automated tests on calculations"][3] >= 4:
        add("Calculation changes need verified regression coverage", "Delivery",
            4 if ctx["rewrite"] else 3,
            ("4: no test files were supplied, and the proposed work changes calculation components; existing test coverage is to confirm"
             if ctx["rewrite"] else "3: no test files were supplied; changes to calculation logic would need verified baseline results"),
            imp_pay, basis_imp, [], "Build characterization tests from current outputs before any change; run in parallel",
            ctx["owner_it"])
    for t in ctx["eol"]:
        lib = bool(re.search(r"jquery|angular|bootstrap|react|vue|library", t, re.I))
        unused = t in (ctx.get("eol_unused") or set())
        vb6 = "visual basic 6" in t.lower()
        add(f"{t} needs a support and upgrade decision", "Technology",
            2 if unused else 4,
            ("2: the page loads it but does not use it (3.6); removing the include closes the exposure" if unused else
             f"4: {t} development tools are unsupported and only the runtime is supported, so fixes are limited and "
             f"specialist maintenance and support cover need confirmation" if vb6 else
             f"4: {t} has a lifecycle concern recorded in 6.2; confirm the deployed version, support entitlement and upgrade options"),
            4, "4: the component calculates or displays payment data" if fin else "4: the component appears in the supplied application source; usage and business impact are to confirm",
            ctx["eol_comps"].get(t, []),
            ("Remove the include if it is not used, or upgrade it (12.3)" if lib else
             "Upgrade or replace it (12.3); until then isolate it and restrict who can run it"),
            ctx["owner_it"])
    if len(ctx["skills"]) >= 3:
        add(f"Support cover for {len(ctx['skills'])} specialist skill sets is to confirm", "People", 2,
            f"2 (planning assumption, not measured): maintenance requires {P.sentence(ctx['skills'])}; named staff and support cover are to confirm (10.4)", 4,
            "4: limited support cover could delay recovery from a fault; staffing and recovery targets are to confirm", [],
            "Name the people per platform, document the run books, and fund cross-training or vendor cover",
            ctx["owner_it"])
    if ctx["platforms"] >= 4:
        add(f"The application is spread over {ctx['platforms']} platforms, which multiplies cost and change effort", "Architecture",
            3, "3: every change that crosses platforms needs several skill sets and release processes", 3,
            "3: slower change and higher run cost rather than an outage", [], "Reduce platforms in the target architecture (12.6)",
            ctx["owner_ea"])
    if ctx["creds"]:
        db = ctx.get("db_creds")
        add("Database credentials in the source could be misused" if db else "Passwords or keys in the source could be misused",
            "Security", 3,
            "3: they are readable by anyone with access to the code and cannot be changed without a release",
            imp_pay if fin else 4, basis_imp, ctx["creds"], "Change them now and move them to a secrets store",
            ctx["owner_sec"])
    inj = ctx.get("inject_live") if ctx.get("inject_live") is not None else ctx["inject"]
    if inj:
        sql, cmd = ctx.get("inject_sql"), ctx.get("inject_cmd")
        what = "queries or commands" if sql and cmd else "system commands" if cmd else "queries"
        fix = P.sentence([x for x in ("use parameterised queries" if sql else "",
                                      "pass command arguments separately" if cmd else "") if x]) or "use parameterised queries"
        add("Crafted input could change or expose payment data (injection)" if fin else "Crafted input could change or expose data (injection)",
            "Security", 3, f"3: {what} are built from input in " + ", ".join(inj[:3]), imp_pay if fin else 4, basis_imp, inj,
            fix[:1].upper() + fix[1:] + "; validate input", ctx["owner_sec"])
    if ctx["missing"]:
        add(f"Unreviewed code ({ctx['missing']} referenced components not provided) could change the assessment", "Assessment", 4,
            "4: the components are referenced by the code but were not provided for review", 3,
            "3: the ratings and estimate may be understated", [], "Provide the missing source and re-run the assessment",
            ctx["owner_it"])
    rank = ["Financial control", "Data integrity", "Security", "Delivery", "Technology", "People", "Assessment", "Architecture"]
    out.sort(key=lambda r: (-r["score"], rank.index(r["cat"]) if r["cat"] in rank else 9))
    return out
