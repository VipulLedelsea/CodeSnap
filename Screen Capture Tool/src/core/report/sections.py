"""Sections the template does not have but an enterprise architect expects: data ownership and lineage, financial
controls, application boundary, non-functional requirements, batch operations, identity across platforms,
observability, lifecycle alignment, portfolio position, transition architecture and platform run costs. Each is
written from the evidence where the code shows it, and says plainly what must still be confirmed."""


def _h(doc, before, title):
    return doc.h2_before(before, title)


def _p(doc, text, anchor, bullet=False, bold=None, italic=False):
    return doc.new_para(text, anchor, bullet=bullet, bold=bold, italic=italic)._p


def _table(doc, T, anchor, head, data, src=26, widths=None):
    from .template_docx import _col_widths, _table_after
    t = _table_after(doc, T[src], anchor, head, data)
    if widths:
        _col_widths(t, widths)
    return t._tbl


def data_ownership(doc, T, DM, fin, name):
    from . import dataarch as DA
    a = _h(doc, "6. Application health", "5.5 Data ownership and lineage")
    big = [g for g in DM["entities"] if len(g["copies"]) >= 3]
    lead = DA.fragmentation_sentence(DM)
    a = _p(doc, (lead + " " if lead else "") + (
        "For an application that calculates and pays money, the key architectural questions are which store is "
        "authoritative for each entity and how the others are reconciled with it. Neither can be answered from the "
        "code provided, so both are open items." if fin and big else
        "The table below shows where each business entity is kept and which component uses it."), a)
    head, rows = DA.matrix(DM)
    if rows:
        a = _p(doc, "Where the core business data is held", a, bold=True)
        a = _table(doc, T, a, head, rows)
    a = _p(doc, "System of record by entity", a, bold=True)
    a = _table(doc, T, a, ["Entity", "Copies", "Platforms", "Written by", "System of record", "Reconciliation seen in code"],
               DA.sor_rows(DM), widths=[0.9, 0.6, 1.4, 1.4, 1.6, 1.3])
    for d1, d2 in DM["duplicates"]:
        a = _p(doc, f"The {d1} and {d2} databases have near-identical names and are used by different components; "
                    f"they may be two copies of the same data. Confirm with the database administrators.", a, bullet=True)
    if DM["sql_server"]:
        a = _p(doc, "Microsoft SQL Server is in use although no SQL Server component was listed: the connection strings "
                    f"point at {', '.join(DM['sql_server'])}, and the dbo schema prefix is SQL Server's default.", a, bullet=True)
    a = _p(doc, "Lineage from input to output", a, bold=True)
    for l in DM["lineage"][:8]:
        ins = ", ".join(s_ + ("" if l["in_from"].get(s_) else " (source not identified)") for s_ in l["in"]) or "no input"
        outs = ", ".join(s_ + ("" if l["out_to"].get(s_) else " (consumer not identified)") for s_ in l["out"]) or "no output"
        a = _p(doc, f"{ins} → {l['component']} → {outs}", a, bullet=True)
    unlinked = not any(any(v for v in l["out_to"].values()) for l in DM["lineage"])
    a = _p(doc, ("No component provided reads what another one writes, so the chain from entitlement through payment to "
                 "the accounting system cannot be completed from the code. The systems that produce the input files and "
                 "consume the payment output must be named by the IT owner." if unlinked and fin else
                 "Links between components are shown where one reads what another writes."), a)
    doc.unknown("Name the system of record for each entity in 5.5 and document the reconciliation between copies", "5.5", "IT")
    if fin:
        doc.unknown("Trace lineage from entitlement through payment to the accounting system, with control totals", "5.5", "IT")
    return a


def financial_controls(doc, T, rows):
    from . import plain as P
    a = _h(doc, "9. Risk and impact matrix", "8.6 Financial and business controls")
    a = _p(doc, "The application calculates, approves and posts payments, so the findings below are assessed as financial "
                "controls (segregation of duties, audit integrity, completeness and accuracy of posting) rather than as "
                "code hygiene. Each rated item is carried into the risk register in Section 9 at business impact.", a)
    data = [[r[0], r[1], r[2], f"{r[3]} – {P.LEVEL[r[3]]}" if r[3] else "Not assessed", ", ".join(x for x in r[4] if x) or "–"]
            for r in rows]
    a = _table(doc, T, a, ["Control", "What the code shows", "Why it matters", "Rating", "Components"], data,
               widths=[1.1, 2.4, 2.0, 0.8, 1.3])
    doc.unknown("Confirm maker-checker, reconciliation and audit retention controls with finance and internal audit", "8.6",
                "Business owner")
    return a


# ── the further areas an enterprise architect expects ───────────────────────────────────────────────────────────

STAGE_CAP = {"inputs": "Aid entitlement intake", "calc": "Aid calculation", "post": "Payment posting",
             "approve": "Payment approval", "out": "Payment disbursement and reporting", "inquire": "Aid inquiry"}


def capability(doc, T, AM, s, fin):
    from .figures import _stage
    a = _h(doc, "3. Technical profile", "2.6 Business capability mapping")
    l1 = s.get("business_area") or "Business operations"
    caps = {}
    for c in AM["components"]:
        caps.setdefault(_stage(c), []).append(c["name"])
    names = STAGE_CAP if fin else {k: v.replace("Aid ", "").replace("Payment ", "") for k, v in STAGE_CAP.items()}
    data = [[l1, names[k], ", ".join(v), "Requires the portfolio inventory"] for k, v in caps.items() if v]
    a = _p(doc, "The capabilities below are derived from what each component does (level 2) under the business area "
                "(level 1). Other applications that serve the same capability, and so the consolidation options, can only "
                "be judged against the portfolio inventory.", a)
    a = _table(doc, T, a, ["Capability (level 1)", "Capability (level 2)", "Supported by", "Other applications with this capability"],
               data, widths=[1.5, 1.8, 3.0, 2.0])
    doc.unknown("Map the capabilities in 2.6 against the portfolio inventory", "2.6", "Enterprise architecture")


def boundary(doc, T, AM, arts, HP, missing):
    a = _h(doc, "4. Architecture and integrations", "3.5 Application boundary and decomposition")
    lines = sum(len((x.get("transcription") or "").splitlines()) for x in arts)
    groups = {}
    for c in AM["components"]:
        key = c["platform"] if c["layer"] != "Presentation" else "Screens"
        groups.setdefault(key, []).append(c["name"])
    a = _p(doc, f"{len(arts)} files ({lines:,} lines) spread over {len(HP)} platforms either are a partial sample of one "
                f"application or several applications grouped under one ID. The components share no data at run time "
                f"that the code shows (5.5), and {len(missing)} referenced components were not provided. The boundary must "
                f"be agreed with the IT owner before the ratings are treated as final.", a)
    data = [[k, ", ".join(v), "Runs on its own platform; shares data only through files and copies"
             if k != "Screens" else "User access to the components above"] for k, v in groups.items()]
    a = _table(doc, T, a, ["Candidate application or subsystem", "Components", "Why it may be separate"], data,
               widths=[2.0, 3.3, 3.0])
    doc.unknown("Agree the application boundary and the component-to-application mapping in 3.5", "3.5", "IT")


def deployment(doc, T, AM, DM, HP, fin):
    a = _h(doc, "5. Data profile and reporting", "4.5 Deployment view (inferred) and interface controls")
    rows = []
    plats = {c["platform"] for c in AM["components"]}
    if "IBM mainframe (z/OS)" in plats:
        rows.append(["z/OS mainframe", "COBOL batch, CICS inquiry, IMS database" + (", Db2" if DM["db2"] else ""),
                     "COBOL, CICS and IMS code", "LPAR, CICS region, batch scheduler, disaster recovery site"])
    if "IBM i (AS/400)" in plats:
        rows.append(["IBM i partition", "RPG posting program and its database files", "RPG F-specs", "Partition, backup and HA"])
    if "Oracle Database" in plats:
        rows.append(["Oracle database server", "PL/SQL posting package and tables", "PL/SQL package", "Version, host, HA, backup"])
    for sq in DM["sql_server"]:
        rows.append([f"SQL Server ({sq.split(' on ')[-1]})", f"Database {sq.split(' on ')[0]}", "Connection string in the code",
                     "Version, HA, encryption, backup"])
    if "Microsoft .NET (Windows server)" in plats:
        rows.append(["Windows web server (IIS)", "ASP.NET MVC payment controller", "C# controller code",
                     "Network zone, internet exposure, TLS certificate"])
    if "Windows desktop (VB6)" in plats:
        rows.append(["Staff Windows desktops", "VB6 calculation client with a local audit file", "VB6 form and local path",
                     "Number of desktops, Windows version, VB6 runtime support"])
    a = _p(doc, "No hosting or network information was provided. The nodes below are inferred from the code and are the "
                "starting point for the physical view; for a " + ("Tier 1 payment system" if fin else "business system")
                + " the network zones, availability and disaster recovery of each node are essential and are open items.", a)
    a = _table(doc, T, a, ["Node (inferred)", "Hosts", "Evidence", "To confirm"], rows, widths=[1.6, 2.6, 1.8, 2.3])
    ifs = []
    for o in DM["occurrences"]:
        if o["engine"].endswith("(files)") and not o["skip"]:
            ifs.append([o["store"], "Not shown (SFTP, Connect:Direct or MQ?)", "Not shown",
                        "Totals on the control report only" if DM["reconciliation"] else "None seen",
                        "Mainframe dataset security (RACF or equivalent) to confirm"])
    for o in DM["occurrences"]:
        pass
    a = _p(doc, "Interface controls", a, bold=True)
    a = _table(doc, T, a, ["Interface", "Transport", "Encryption", "Control totals", "Authentication"],
               ifs + [["REST endpoints (4.2)", "HTTPS assumed; not shown", "TLS to confirm", "Not applicable",
                       "No [Authorize] attribute seen; confirm the global filter"]], widths=[1.6, 1.9, 1.2, 1.6, 2.0])
    doc.unknown("Physical deployment: hosts, network zones, HA and disaster recovery for each node in 4.5", "4.5", "IT")
    doc.unknown("Transport, encryption, volumes and control totals for each file interface (4.5)", "4.5", "IT")


def nfr(doc, T, fin, batch_names):
    a = _h(doc, "7. Technical debt", "6.3 Non-functional requirements")
    a = _p(doc, "Performance and resilience could not be measured from the code. The requirements below are the ones "
                "that matter for this application; each is an open item for the operations team.", a)
    rows = [["Availability target", "Unknown", "Unknown", "Staff screens and the web page are used during the payment cycle"],
            ["Recovery time objective (RTO)", "Unknown", "Unknown", "How long payments can be delayed after a failure"],
            ["Recovery point objective (RPO)", "Unknown", "Unknown", "How much posted payment data can be lost"],
            ["Batch window", "Unknown", "Unknown", f"Batch components: {', '.join(batch_names) or 'none identified'}"],
            ["Peak volumes", "Unknown", "Unknown", "Monthly payment runs" if fin else "Business peaks"],
            ["Online response time", "Unknown", "Unknown", "Inquiry and approval screens"]]
    a = _table(doc, T, a, ["Requirement", "Target", "Current", "Why it matters here"], rows, widths=[2.0, 1.2, 1.2, 3.9])
    doc.unknown("Availability, RTO, RPO, batch window and peak volumes (6.3)", "6.3", "IT")


def lifecycle(doc, T, techs, stack_names, no_path):
    a = _h(doc, "7. Technical debt", "6.4 Technology lifecycle alignment")
    rows = []
    seen = set()
    for n in stack_names:
        if n in seen:
            continue
        seen.add(n)
        low = n.lower()
        if any(k.lower() in low for k in no_path) or "visual basic" in low:
            pos, when, why = "Retire", "With the front-end rebuild (12.4)", "No vendor support and no upgrade path"
        elif any(k in low for k in ("ims", "assembler", "rpg", "cics")):
            pos, when, why = "Tolerate, then retire", "After data consolidation (12.4)", "Supported but scarce skills; exit planned"
        elif any(k in low for k in ("cobol", "db2", "z/os", "ibm i")):
            pos, when, why = "Tolerate", "Review at the data decision", "Supported; batch logic retained through the transition"
        elif any(k in low for k in (".net", "c#", "sql server", "oracle", "windows server", "iis")):
            pos, when, why = "Invest (current versions)", "Not applicable", "Candidate target platform once versions are confirmed"
        else:
            pos, when, why = "To classify", "Not applicable", "Position against the client's standards to confirm"
        rows.append([n, pos, when, why])
    a = _p(doc, "Each technology is given a proposed position against the client's technology standards (invest, tolerate "
                "or retire). The positions are proposals until the client's standards are applied.", a)
    a = _table(doc, T, a, ["Technology", "Proposed position", "Exit by", "Reason"], rows[:14], widths=[2.6, 1.5, 1.8, 2.4])
    doc.unknown("Confirm the technology positions in 6.4 against the client's technology standards", "6.4", "Enterprise architecture")


def identity(doc, T, AM, CT, DM):
    a = _h(doc, "9. Risk and impact matrix", "8.7 Identity and access across platforms")
    creds = next((r for r in CT if r["area"] == "Privileged"), {})
    rows = []
    plats = {c["platform"] for c in AM["components"]}
    typical = {"IBM mainframe (z/OS)": "RACF, ACF2 or Top Secret; CICS transaction security",
               "IBM i (AS/400)": "IBM i user profiles and object authority",
               "Oracle Database": "Database accounts and roles",
               "Microsoft .NET (Windows server)": "Active Directory / Windows authentication or forms sign-in",
               "Windows desktop (VB6)": "Windows sign-in; the application connects with its own database account"}
    for p in sorted(plats):
        if p in typical:
            ev = ("Shared database account in the code" if p in ("Microsoft .NET (Windows server)", "Windows desktop (VB6)")
                  and creds.get("rating") else "Not shown in the code")
            rows.append([p, typical[p], ev, "Provisioning, review and removal of access"])
    for sq in DM["sql_server"]:
        rows.append([f"SQL Server ({sq})", "SQL logins or Windows authentication", "SQL logins with passwords in the code",
                     "Move to integrated authentication or a vaulted service account"])
    a = _p(doc, "Each platform has its own security model, so a person's access is granted and reviewed in several places, "
                "and the shared service accounts in the code mean database activity cannot be traced to a person.", a)
    a = _table(doc, T, a, ["Platform", "Security model (typical)", "Evidence in the code", "To confirm"], rows,
               widths=[1.9, 2.4, 2.0, 2.0])
    doc.unknown("Authentication and authorization model per platform, service accounts and access reviews (8.7)", "8.7",
                "Information security")


def operations(doc, T, AM, DM, skill_list, audit):
    a = _h(doc, "11. User experience", "10.5 Batch operations")
    rows = []
    for l in DM["lineage"]:
        c = next((x for x in AM["components"] if x["name"] == l["component"]), None)
        if not c or not ("Batch" in c["role"] or "procedures" in c["role"] or "posts" in c["role"].lower()
                         or c["platform"] == "IBM i (AS/400)"):
            continue
        rows.append([l["component"], c["platform"], "Scheduler not provided", ", ".join(l["in"]) or "–",
                     ", ".join(l["out"]) or "–", "No restart or checkpoint logic seen", "Order relative to the other runs unknown"])
    a = _p(doc, "Several components run as scheduled work on different platforms and must run in the right order within the "
                "payment cycle. The job chain, scheduler, restart and recovery procedures and run books were not provided.", a)
    a = _table(doc, T, a, ["Program", "Platform", "Trigger", "Inputs", "Outputs", "Restart and recovery", "Dependencies"],
               rows, widths=[1.4, 1.2, 1.0, 1.3, 1.3, 1.2, 1.0])
    doc.unknown("Job chains, scheduler, restart and recovery procedures and run books (10.5)", "10.5", "IT")
    a = _h(doc, "11. User experience", "10.6 Observability")
    lines = ["Logging: " + (audit or "no logging found") + ".",
             "Monitoring and alerting: none seen in the code; errors are swallowed in places (8.6), so failures may not "
             "reach anyone.",
             "Response: who is alerted and responds to a failed run or a failed approval is unknown (10.1)."]
    for t in lines:
        a = _p(doc, t, a, bullet=True)
    a = _h(doc, "11. User experience", "10.7 Skills and key people by platform")
    a = _table(doc, T, a, ["Skill set", "Scarcity", "Named people", "Cover"],
               [[k, "Scarce", "Unknown", "Unknown"] for k in skill_list] or [["None identified", "", "", ""]],
               widths=[2.6, 1.2, 2.2, 2.3])
    doc.unknown("Ticket counts for 24 months and the named people who can maintain each platform (10.2, 10.7)", "10.7", "IT")


def strategy(doc, T, SCF, PR, CD, HP, fin, tier, no_path):
    a = _h(doc, "13. Evidence, open items and sign-off", "12.5 Portfolio position")
    tech = SCF.get("overall")
    a = _p(doc, f"Business value is taken as high ({tier or 'criticality not entered'}), and technical fit as low "
                f"(overall condition {tech or 'not rated'}). On a business value against technical fit grid this places the "
                f"application in Migrate: keep the business function, move it off the current technology. The placement is "
                f"provisional until business value is confirmed and the other portfolio applications are placed.", a)
    a = _h(doc, "13. Evidence, open items and sign-off", "12.6 Transition architecture and decisions")
    states = [["Now", f"{len(HP)} platforms; data copies without a system of record; approval without authorization",
               "Stabilize (1.3, 8.6)"],
              ["Interim 1", "Security and control gaps closed; system of record named; reconciliation running", "Data decision"],
              ["Interim 2", "Business logic behind an API; one posting service; old screens still in use",
               "Services first"],
              ["Interim 3", "New web front end in use; VB6 and terminal screens retired", "Front ends"],
              ["Target", "Consolidated data on the chosen store; platforms not needed are retired", "Platform exit"]]
    a = _table(doc, T, a, ["State", "What is true", "Reached by (12.4)"], states, widths=[1.1, 5.0, 2.2])
    a = _p(doc, "Key architecture decisions", a, bold=True)
    decisions = [
        "AD-1 System of record for district and payment data: choose one store per entity before any rebuild. Reason: "
        "every later step depends on it.",
        "AD-2 Integration style: an API layer in front of the business logic, with managed file transfer for the files "
        "that remain. Reason: one visible, monitored interface instead of file drops and shared tables.",
        f"AD-3 Front end: one accessible web front end replacing {', '.join(n for n in no_path) or 'the legacy'} "
        "desktop and terminal screens. Reason: no upgrade path and accessibility.",
        "AD-4 Posting: consolidate the posting implementations into one service. Reason: several copies of the same "
        "business rule on different platforms cannot be kept consistent.",
        "AD-5 Identity: the organisation's identity service and a secrets store for all components. Reason: shared "
        "accounts and embedded passwords today."]
    for d in decisions:
        a = _p(doc, d, a, bullet=True)
    a = _p(doc, "Principles applied: settle the data before the screens; keep the old path running until parallel runs "
                "agree; no cutover in a payment cycle; reduce platforms at every step; security and audit built in, not "
                "added per component.", a)
    a = _h(doc, "13. Evidence, open items and sign-off", "12.7 Platform run costs and licensing")
    drivers = {"IBM mainframe (z/OS)": ("MSU / MIPS capacity charges, IMS, CICS and Db2 licences", "Retire when the batch and IMS data move"),
               "IBM i (AS/400)": ("Per-core IBM i licence and hardware maintenance", "Retire with posting consolidation"),
               "Oracle Database": ("Per-processor or named-user Oracle licence and support", "Retained or retired by the data decision"),
               "Microsoft SQL Server": ("Per-core SQL Server licence", "Likely target; consolidate the two databases"),
               "Microsoft .NET (Windows server)": ("Windows Server licences; .NET itself is free", "Retained (current .NET)"),
               "Windows desktop (VB6)": ("Desktop estate support; VB6 runtime unsupported", "Removed with the web front end")}
    rows = [[p, *drivers.get(p, ("To confirm", "To confirm")), "Unknown"] for p in HP]
    a = _p(doc, "Full cost estimates are out of scope, but platform charges often drive the case to exit a platform. The "
                "cost drivers per platform and the licences each disposition removes are listed for the finance team to cost.", a)
    a = _table(doc, T, a, ["Platform", "Cost drivers", "Effect of the recommendation", "Current annual cost"], rows,
               widths=[1.9, 2.8, 2.4, 1.2])
    doc.unknown("Current licensing and capacity costs per platform (12.7)", "12.7", "Finance")
