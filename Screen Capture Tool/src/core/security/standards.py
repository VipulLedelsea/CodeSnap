FERPA = "FERPA 34 CFR §99.31 (reasonable methods to protect education records)"
MN_GDPA = "Minn. Stat. §13.32 (educational data) / §13.055 (breach of not-public data)"
MNIT = "MNIT Enterprise Security standards (NIST SP 800-53 based)"

RULES = {
    "SEC-CRED": {"title": "Hard-coded credential", "cwe": "CWE-798", "owasp": "A07:2021 Identification and Authentication Failures",
                 "nist": ["IA-5(7)", "IA-5"], "data_risk": True},
    "SEC-SQLI": {"title": "SQL built from string concatenation", "cwe": "CWE-89", "owasp": "A03:2021 Injection",
                 "nist": ["SI-10"], "data_risk": True},
    "SEC-SQLDYN": {"title": "Dynamic SQL", "cwe": "CWE-89", "owasp": "A03:2021 Injection", "nist": ["SI-10"],
                   "data_risk": True},
    "SEC-XSS": {"title": "Unencoded user input written to the page", "cwe": "CWE-79", "owasp": "A03:2021 Injection",
                "nist": ["SI-10", "SI-15"], "data_risk": True},
    "SEC-CMD": {"title": "OS command built from input", "cwe": "CWE-78", "owasp": "A03:2021 Injection",
                "nist": ["SI-10"], "data_risk": False},
    "SEC-PATH": {"title": "File path taken from request input", "cwe": "CWE-22", "owasp": "A01:2021 Broken Access Control",
                 "nist": ["SI-10", "AC-3"], "data_risk": True},
    "SEC-DESER": {"title": "Unsafe deserialization", "cwe": "CWE-502", "owasp": "A08:2021 Software and Data Integrity Failures",
                  "nist": ["SI-10"], "data_risk": False},
    "SEC-CRYPTO": {"title": "Weak or broken cryptography", "cwe": "CWE-327", "owasp": "A02:2021 Cryptographic Failures",
                   "nist": ["SC-13"], "data_risk": True},
    "SEC-TLS": {"title": "Data sent without encryption", "cwe": "CWE-319", "owasp": "A02:2021 Cryptographic Failures",
                "nist": ["SC-8", "SC-8(1)"], "data_risk": True},
    "SEC-AUTH": {"title": "Weak or missing authentication", "cwe": "CWE-287", "owasp": "A07:2021 Identification and Authentication Failures",
                 "nist": ["IA-2", "AC-3", "SC-23"], "data_risk": True},
    "SEC-CONF": {"title": "Insecure configuration / error disclosure", "cwe": "CWE-209", "owasp": "A05:2021 Security Misconfiguration",
                 "nist": ["CM-6", "CM-7", "SI-11"], "data_risk": False},
    "SEC-MEM": {"title": "Unsafe memory / buffer function", "cwe": "CWE-120", "owasp": "A03:2021 Injection",
                "nist": ["SI-16", "SI-10"], "data_risk": False},
    "SEC-PII": {"title": "Student / personal data handled", "cwe": "CWE-359", "owasp": "A01:2021 Broken Access Control",
                "nist": ["PT-2", "SC-28", "AC-3"], "data_risk": True},
    "EOL": {"title": "Unsupported technology", "cwe": "CWE-1104", "owasp": "A06:2021 Vulnerable and Outdated Components",
            "nist": ["SA-22", "SI-2"], "data_risk": False},
    "CVE": {"title": "Known vulnerability", "cwe": "CWE-1395", "owasp": "A06:2021 Vulnerable and Outdated Components",
            "nist": ["RA-5", "SI-2"], "data_risk": False},
}

_BUMP = {"info": "low", "low": "medium", "medium": "high", "high": "critical", "critical": "critical"}


def refs_for(rule: str, student_data: bool = False, extra: dict | None = None) -> dict:
    base = RULES.get(rule.split(":")[0], {})
    refs = {"cwe": base.get("cwe"), "owasp": base.get("owasp"), "nist": base.get("nist", []), "mnit": MNIT}
    if student_data or rule == "SEC-PII":
        refs["ferpa"] = FERPA
        refs["mn_gdpa"] = MN_GDPA
    if extra:
        refs.update(extra)
    return {k: v for k, v in refs.items() if v}


def escalate(severity: str) -> str:
    return _BUMP.get(severity, severity)
