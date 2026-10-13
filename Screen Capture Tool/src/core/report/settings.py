"""Per-program report details (client, engagement, IDs, reviewers). Nothing client-specific is built in: anything not
entered is reported as an "<insert … information here>" prompt and listed as an open item."""

from core.diagrams.xmlsafe import xml_safe

FIELDS = [
    ("client", "Client organization"),
    ("engagement", "Engagement name"),
    ("app_id", "Application ID (e.g. APP-001)"),
    ("version", "Report version"),
    ("classification", "Classification"),
    ("prepared_by", "Prepared by (name, role)"),
    ("firm", "Assessment firm"),
    ("technical_reviewer", "Technical reviewer"),
    ("business_owner", "Business owner"),
    ("it_reviewer", "IT reviewer"),
    ("purpose", "Purpose in one sentence"),
    ("business_area", "Business area or program supported"),
    ("business_value", "Business value or volume supported"),
    ("criticality_tier", "Criticality tier (1, 2 or 3)"),
    ("regulatory_basis", "Regulatory, contractual or policy basis"),
    ("privacy_obligations", "Data privacy obligations (e.g. FERPA, HIPAA, state law)"),
    ("security_framework", "Security framework in use"),
    ("deployment", "Deployment model"),
    ("related_apps", "Related applications (by ID)"),
    ("criticality_confirmed", "Criticality confirmed by the business owner (yes/no)"),
    ("signed_off", "Report signed off by the reviewers in 13.5 (yes/no)"),
    ("client_short", "Name used in place of hidden names (e.g. CLIENT)"),
    ("redact_terms", "Names to hide in the report, comma separated (real client names, schema or host prefixes)"),
]
# Business inputs the report would otherwise ask for again and again. Each one is shown in the "Business inputs" group of
# the form, goes to the executive summary, and closes the open items listed in CLOSES once every key it needs is entered.
BUSINESS_INPUTS = [
    ("users_volumes", "Users by group and business volumes (for example 40 clerks, 12,000 payments a month)"),
    ("run_times", "Availability target, recovery time and point, batch window and peak volumes"),
    ("hosting_cost", "Current licence, hosting and support cost per year, by platform"),
    ("incident_history", "Incidents and support tickets in the last 24 months"),
    ("change_backlog", "Change requests waiting and changes planned"),
    ("available_skills", "Named people who can maintain each platform, and cover"),
    ("test_coverage", "Existing tests and baseline outputs"),
    ("documentation", "Design documents, run books and data dictionaries that exist"),
    ("change_drivers", "Known drivers of change (regulation, vendor end of support, cost, risk)"),
    ("year_introduced", "Year introduced and major rewrites"),
]
FIELDS += BUSINESS_INPUTS
BUSINESS_KEYS = [k for k, _ in BUSINESS_INPUTS]
# open-item wording -> the inputs that close it (all of them must be entered)
CLOSES = [
    (r"Number of users by group", ["users_volumes"]),
    (r"Availability, RTO, RPO", ["run_times"]),
    (r"Current licensing and capacity costs", ["hosting_cost"]),
    (r"Ticket counts for 24 months", ["incident_history", "available_skills"]),
    (r"Known drivers of change", ["change_drivers"]),
    (r"Year introduced and major rewrites", ["year_introduced"]),
]
DEFAULTS = {"version": "v1.0", "classification": "Confidential", "firm": "Ledelsea", "prepared_by": "Ledelsea"}


def get(store) -> dict:
    saved = store.get_meta("report_settings") or {}
    out = {k: (saved.get(k) or DEFAULTS.get(k) or "") for k, _ in FIELDS}
    out["signed_off_basis"] = saved.get("signed_off_basis", "")
    return out


def save(store, values: dict) -> dict:
    cur = store.get_meta("report_settings") or {}
    for k, _ in FIELDS:
        if k in (values or {}):
            cur[k] = xml_safe(str(values[k] or "")).strip()
    store.set_meta("report_settings", cur)
    if "signed_off" in (values or {}):
        cur["signed_off_basis"] = store.model_stamp() if cur.get("signed_off", "").lower() in ("yes", "y", "true", "1") else ""
        store.set_meta("report_settings", cur)
    return get(store)


def app_number(s: dict) -> str:
    import re
    m = re.search(r"(\d+)", s.get("app_id") or "")
    return m.group(1).zfill(3) if m else "001"
