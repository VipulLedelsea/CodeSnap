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
