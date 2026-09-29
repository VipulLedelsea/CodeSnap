import math

FIXES = {
    "SEC-SQLI": ("Parameterize SQL", "Replace concatenated SQL with parameters (SqlParameter / PreparedStatement / host variables).", 0.2, 0.5),
    "SEC-SQLDYN": ("Review dynamic SQL", "Confirm dynamic SQL text is not built from user input; switch to static SQL where possible.", 0.2, 0.5),
    "SEC-CRED": ("Remove hard-coded credentials", "Move secrets to a vault or protected configuration and rotate every exposed password.", 0.2, 0.5),
    "SEC-XSS": ("Encode output", "HTML-encode user input before writing it to pages; re-enable request validation.", 0.1, 0.3),
    "SEC-CMD": ("Remove command injection", "Pass arguments as arrays / allow-lists instead of concatenated shell commands.", 0.3, 1.0),
    "SEC-PATH": ("Constrain file paths", "Resolve request-supplied file names against an allow-list directory.", 0.2, 0.5),
    "SEC-DESER": ("Replace unsafe deserialization", "Swap BinaryFormatter / ObjectInputStream for a typed serializer.", 0.5, 2.0),
    "SEC-CRYPTO": ("Upgrade cryptography", "Replace MD5/SHA-1/DES/ECB with SHA-256+/AES-GCM; re-hash stored passwords with a KDF.", 0.3, 1.0),
    "SEC-TLS": ("Encrypt connections", "Enable TLS for service endpoints and database connections (Encrypt=True, https).", 0.3, 1.0),
    "SEC-AUTH": ("Harden authentication", "Enforce authenticated access, remove clear-text credentials, stop cookieless sessions.", 0.5, 1.5),
    "SEC-CONF": ("Production configuration", "Turn off debug/trace, enable custom error pages, stop showing exception text.", 0.05, 0.2),
    "SEC-MEM": ("Replace unsafe C functions", "Swap gets/strcpy/sprintf for bounded versions (fgets, strncpy_s, snprintf).", 0.05, 0.2),
    "SEC-PII": ("Protect personal data", "Inventory personal data fields, restrict access, encrypt at rest, log disclosures.", 0.5, 1.5),
}
UI_FIXES = [
    ("ACC-TERMINAL", "Web front end for 3270 screens", "Put an accessible web UI over the CICS transactions (or rebuild the screens) — terminals cannot meet WCAG 2.1 AA.", 2.0, 6.0, "modernize"),
    ("ACC-", "Fix accessibility (WCAG 2.1 AA)", "Add labels, text alternatives, page titles/language, keyboard access and contrast fixes; test with a screen reader.", 0.05, 0.2, None),
    ("UIB-CRASH", "Stop system failures reaching users", "Trace the abend/exception shown on screen, fix the cause, and show a friendly, logged error instead.", 0.5, 2.0, "stabilize"),
    ("USE-", "Usability fixes", "Clear labels and buttons, input validation, confirmation steps for consequential actions, legends for codes.", 0.05, 0.25, "remediate"),
    ("UIB-", "Usability fixes", "Clear labels and buttons, input validation, confirmation steps for consequential actions, legends for codes.", 0.05, 0.25, "remediate"),
    ("UIS-", "Harden UI security", "POST sensitive forms, add anti-forgery tokens, mask passwords and personal identifiers, remove trusted values from hidden fields.", 0.1, 0.5, None),
    ("WEB-HTTPS", "Enforce HTTPS / modern TLS", "Redirect all HTTP to HTTPS, TLS 1.2+ only, valid certificate, then enable HSTS.", 0.5, 2.0, "stabilize"),
    ("WEB-CERT", "Enforce HTTPS / modern TLS", "Redirect all HTTP to HTTPS, TLS 1.2+ only, valid certificate, then enable HSTS.", 0.5, 2.0, "stabilize"),
    ("WEB-TLS", "Enforce HTTPS / modern TLS", "Redirect all HTTP to HTTPS, TLS 1.2+ only, valid certificate, then enable HSTS.", 0.5, 2.0, "stabilize"),
    ("WEB-EOL", "Upgrade live site platform & libraries", "Move the web server OS/runtime and front-end libraries to supported versions.", 1.0, 3.0, "remediate"),
    ("WEB-CVE", "Upgrade live site platform & libraries", "Move the web server OS/runtime and front-end libraries to supported versions.", 0.0, 0.0, "remediate"),
    ("WEB-", "Harden web server configuration", "Add security headers (HSTS, CSP, frame-ancestors, nosniff, Referrer-Policy), secure cookie flags, hide version banners.", 0.1, 0.3, "remediate"),
]
FIXED_COST = {"SEC-CRED": (0.5, 1.0), "SEC-PII": (1.0, 2.0), "SEC-TLS": (0.5, 1.0), "SEC-AUTH": (0.5, 1.0)}
EOL_FIX = [
    (".NET Framework", "Retarget to .NET Framework 4.8.1", "In-place retarget and regression test; plan the move to modern .NET separately.", 1.0, 2.0, 0.3, 0.6, "remediate"),
    ("jQuery", "Upgrade jQuery to 3.7+", "Upgrade with jquery-migrate, then remove deprecated calls.", 0.5, 1.5, 0.0, 0.0, "remediate"),
    ("Bootstrap", "Upgrade Bootstrap", "Move to Bootstrap 5; markup changes per page.", 1.0, 3.0, 0.0, 0.0, "remediate"),
    ("log4j", "Replace log4j 1.x", "Move to Log4j 2 / SLF4J + Logback (or reload4j as a stop-gap).", 0.5, 1.5, 0.0, 0.0, "stabilize"),
    ("Oracle Java", "Upgrade Java runtime to 21 LTS", "Upgrade JDK and app server, then fix removed APIs.", 1.0, 3.0, 0.3, 0.8, "remediate"),
    ("ASP.NET Web Forms", "Rebuild Web Forms UI", "Rebuild pages on ASP.NET Core (Razor/Blazor); Web Forms has no path to modern .NET.", 2.0, 4.0, 2.0, 4.0, "modernize"),
    ("Apache Struts", "Replace Struts 1", "Rebuild controllers on Spring MVC / Jakarta EE.", 2.0, 4.0, 1.5, 3.0, "modernize"),
    ("Flash", "Replace Flash content", "Rebuild in HTML5/JavaScript.", 1.0, 4.0, 0.0, 0.0, "modernize"),
    ("ActiveX", "Replace ActiveX controls", "Rebuild in HTML5; removes the Internet Explorer dependency.", 1.0, 4.0, 0.0, 0.0, "modernize"),
    ("Silverlight", "Replace Silverlight", "Rebuild in HTML5/JavaScript.", 2.0, 6.0, 0.0, 0.0, "modernize"),
    ("Java applets", "Replace applets", "Rebuild as a web page or desktop app.", 1.0, 4.0, 0.0, 0.0, "modernize"),
    ("Pre-standard C++", "Port pre-standard C++", "Port to ISO C++17 (headers, namespaces, casts) and rebuild with a current compiler.", 1.0, 2.0, 1.0, 2.0, "remediate"),
    ("16-bit Windows", "Replace Win16 code", "Rebuild as 32/64-bit or web.", 2.0, 4.0, 2.0, 4.0, "modernize"),
    ("Borland OWL", "Replace Borland OWL UI", "Rebuild the UI on a supported framework.", 2.0, 4.0, 1.5, 3.0, "modernize"),
    (".NET Remoting", "Replace .NET Remoting", "Move to gRPC / REST.", 1.0, 3.0, 0.0, 0.0, "modernize"),
    ("WCF", "Plan WCF migration", "Move to CoreWCF or REST/gRPC when leaving .NET Framework.", 1.0, 3.0, 0.0, 0.0, "modernize"),
    ("SQL Server", "Upgrade SQL Server", "Upgrade to a supported release.", 1.0, 3.0, 0.0, 0.0, "remediate"),
    ("Db2", "Upgrade Db2", "Upgrade to a supported release.", 1.0, 3.0, 0.0, 0.0, "remediate"),
    ("Windows Server", "Upgrade Windows Server", "Move hosts to a supported release.", 1.0, 2.0, 0.0, 0.0, "remediate"),
]
DISPOSITION_EFFORT = {
    "retain": (0, 0), "rehost": (1.0, 2.0), "replatform": (0.8, 1.5), "refactor": (0.5, 1.2),
    "rearchitect": (3.0, 6.0), "replace": (1.0, 2.5), "retire": (0.2, 0.5),
}
PHASES = [
    ("assess", "Phase 0 — Complete the assessment", "Weeks 0–2"),
    ("stabilize", "Phase 1 — Stabilize & secure", "Months 0–3"),
    ("remediate", "Phase 2 — Remediate", "Months 3–9"),
    ("modernize", "Phase 3 — Modernize", "Months 6–24"),
]


def _r(x):
    return round(x * 2) / 2 if x >= 1 else round(x, 1)


def _kloc(lines):
    return max(lines, 1) / 1000


def solutions(components: list, program: dict) -> list:
    items = {}
    lines_by_name = {c["name"]: c["metrics"]["lines"] for c in components}

    def add(key, title, action, phase, lo, hi, component, finding_ids, kind):
        it = items.setdefault(key, {"id": key, "title": title, "action": action, "phase": phase, "low": 0.0,
                                    "high": 0.0, "components": [], "findings": [], "kind": kind})
        it["low"] += lo
        it["high"] += hi
        if component and component not in it["components"]:
            it["components"].append(component)
        it["findings"] += [f for f in finding_ids if f not in it["findings"]]

    for c in components:
        for f in c["findings"]:
            rule = f.get("rule")
            if f["category"] in ("security", "privacy") and rule in FIXES:
                title, action, lo, hi = FIXES[rule]
                phase = "stabilize" if f["severity"] in ("critical", "high") or rule == "SEC-PII" else "remediate"
                add(f"{rule}:{phase}", title, action, phase, lo, hi, c["name"], [f["id"]], "security")
            elif f["category"] in ("accessibility", "usability", "ui_security", "website"):
                for prefix, title, action, lo, hi, phase in UI_FIXES:
                    if (rule or "").startswith(prefix):
                        ph = phase or ("stabilize" if f["severity"] in ("critical", "high") else "remediate")
                        key = f"UI:{title}:{ph}"
                        first = key not in items
                        add(key, title, action, ph, lo + (0.5 if first and prefix.startswith("WEB-") and hi < 1 else 0),
                            hi + (1.0 if first and prefix.startswith("WEB-") and hi < 1 else 0), c["name"], [f["id"]], "ui")
                        break
            elif f["category"] == "eol" and (f.get("refs") or {}).get("eol_status") in ("eol", "extended", "legacy", "ending"):
                for name, title, action, lo, hi, per_lo, per_hi, phase in EOL_FIX:
                    if name.lower() in f["title"].lower():
                        k = _kloc(lines_by_name.get(c["name"], 0))
                        key = f"EOL:{title}"
                        first = key not in items
                        add(key, title, action, phase, (lo if first else 0) + per_lo * k,
                            (hi if first else 0) + per_hi * k, c["name"], [f["id"]], "eol")
                        break
            elif f["category"] == "vulnerability":
                for name, title, *_ in EOL_FIX:
                    if name.lower() in f["title"].lower() and f"EOL:{title}" in items:
                        items[f"EOL:{title}"]["findings"].append(f["id"])
    for rule, (lo, hi) in FIXED_COST.items():
        for key, it in items.items():
            if key.startswith(rule + ":"):
                it["low"] += lo
                it["high"] += hi
                break
    for c in components:
        disp = c.get("disposition") or {}
        code = disp.get("code")
        covered = any(c["name"] in it["components"] for it in items.values() if it["phase"] == "modernize")
        if code in ("rearchitect", "replace", "rehost", "retire") and c.get("own_disposition") and not covered:
            lo, hi = DISPOSITION_EFFORT[code]
            k = _kloc(c["metrics"]["lines"])
            add(f"DISP:{c['name']}", f"{disp['label']}: {c['name']}", disp["meaning"], "modernize",
                max(0.5, lo * k), max(1.0, hi * k), c["name"], [], "disposition")
        if c["scores"]["tech_debt"]["score"] < 50 and code not in ("rearchitect", "replace", "retire"):
            k = _kloc(c["metrics"]["lines"])
            add(f"DEBT:{c['name']}", f"Refactor {c['name']}", "Break up long routines, remove GO TO / translated-COBOL "
                "patterns, add characterization tests first.", "remediate", max(0.5, 0.5 * k), max(1.0, 1.2 * k),
                c["name"], [], "debt")
    pd = program["disposition"]
    if pd["code"] in ("rearchitect", "replace", "rehost", "retire"):
        lo, hi = DISPOSITION_EFFORT[pd["code"]]
        k = _kloc(sum(lines_by_name.values()))
        add("DISP:program", f"{pd['label']} the program", pd["meaning"], "modernize", max(1, lo * k), max(2, hi * k),
            None, [], "disposition")
    gaps = program["coverage"].get("missing_counts", {}).get("missing_code", 0)
    if gaps:
        add("ASSESS:gaps", f"Provide {gaps} missing component(s)", "Provide the source of the programs and classes that "
            "are referenced but were not reviewed, so the verdict covers the whole program.", "assess", 0.2, 0.5, None, [], "assess")
    if not program["inputs"].get("components"):
        add("ASSESS:criticality", "Confirm business criticality", "Business owners rate each component's criticality and "
            "failure impact (1–5) on the Assessment panel.", "assess", 0.1, 0.2, None, [], "assess")
    out = []
    for it in items.values():
        it["low"], it["high"] = _r(it["low"]), _r(max(it["high"], it["low"]))
        out.append(it)
    order = {p[0]: i for i, p in enumerate(PHASES)}
    return sorted(out, key=lambda i: (order[i["phase"]], -i["high"]))


def roadmap(items: list) -> dict:
    phases = []
    for key, title, window in PHASES:
        rows = [i for i in items if i["phase"] == key]
        if not rows:
            continue
        phases.append({"phase": key, "title": title, "window": window, "items": rows,
                       "low": _r(sum(i["low"] for i in rows)), "high": _r(sum(i["high"] for i in rows))})
    total_lo, total_hi = sum(p["low"] for p in phases), sum(p["high"] for p in phases)
    return {"phases": phases, "total": {"low": _r(total_lo), "high": _r(total_hi),
                                        "months_one_dev": [math.ceil(total_lo / 4.3), math.ceil(total_hi / 4.3)]},
            "unit": "person-weeks"}
