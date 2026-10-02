import json
import re
import urllib.request
from pathlib import Path

OSV_QUERY = "https://api.osv.dev/v1/query"

ECOSYSTEM = {"jquery": ("npm", "jquery"), "bootstrap": ("npm", "bootstrap"), "angularjs": ("npm", "angular"),
             "log4j": ("Maven", "log4j:log4j"), "apache-struts": ("Maven", "struts:struts"),
             "spring-framework": ("Maven", "org.springframework:spring-core"),
             "hibernate-orm": ("Maven", "org.hibernate:hibernate-core")}

CURATED = {
    "jquery": [
        ("CVE-2011-4969", "<1.6.3", "medium", "XSS: selectors built from location.hash can be parsed as HTML"),
        ("CVE-2012-6708", "<1.9.0", "medium", "XSS: selector strings starting with text can be parsed as HTML"),
        ("CVE-2015-9251", "<3.0.0", "medium", "XSS: cross-domain AJAX responses executed as script"),
        ("CVE-2019-11358", "<3.4.0", "medium", "Prototype pollution in jQuery.extend(true, ...)"),
        ("CVE-2020-11022", "<3.5.0", "medium", "XSS: HTML passed to DOM manipulation methods can run untrusted code"),
        ("CVE-2020-11023", "<3.5.0", "medium", "XSS: <option> elements passed to DOM manipulation methods"),
    ],
    "bootstrap": [
        ("CVE-2018-14040", "<3.4.0", "medium", "XSS in collapse data-parent attribute"),
        ("CVE-2018-14042", "<3.4.0", "medium", "XSS in tooltip data-container attribute"),
        ("CVE-2019-8331", "<3.4.1", "medium", "XSS in tooltip / popover data-template attribute"),
    ],
    "log4j": [
        ("CVE-2019-17571", "1", "critical", "SocketServer deserializes untrusted data (remote code execution)"),
        ("CVE-2021-4104", "1", "high", "JMSAppender deserialization when attacker controls configuration"),
        ("CVE-2022-23302", "1", "high", "JMSSink deserialization of untrusted data"),
        ("CVE-2022-23305", "1", "critical", "JDBCAppender SQL injection via logged messages"),
        ("CVE-2022-23307", "1", "high", "Chainsaw deserialization of untrusted data"),
    ],
    "apache-struts": [
        ("CVE-2014-0114", "1", "high", "ClassLoader manipulation through the class parameter of ActionForm"),
        ("CVE-2016-1181", "1", "high", "ActionServlet multithreaded ActionForm handling allows remote code execution"),
        ("CVE-2016-1182", "1", "medium", "ActionServlet does not restrict Validator configuration (XSS / DoS)"),
    ],
}


def _vtuple(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:4]) or (0,)


def _affects(spec: str, version: str | None) -> bool | None:
    if spec[0].isdigit():
        return None if version is None and spec != "1" else (version or "1").split(".")[0] == spec.split(".")[0]
    if version is None:
        return None
    return _vtuple(version) < _vtuple(spec.lstrip("<"))


def curated(product: str, version: str | None) -> list:
    out = []
    for cve, spec, severity, summary in CURATED.get(product, []):
        hit = _affects(spec, version)
        if hit is False:
            continue
        out.append({"id": cve, "severity": severity, "summary": summary, "affected": spec,
                    "confirmed": hit is True, "source": "curated (verify with OSV)",
                    "url": f"https://nvd.nist.gov/vuln/detail/{cve}"})
    return out


def _severity(vuln: dict) -> str:
    level = str((vuln.get("database_specific") or {}).get("severity") or "").lower()
    return {"critical": "critical", "high": "high", "moderate": "medium", "medium": "medium",
            "low": "low"}.get(level, "medium")


def _post(url: str, body: dict):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json",
                                                                             "User-Agent": "CodeSnap"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def osv_lookup(product: str, version: str, cache_dir: Path | None = None, post=None) -> list | None:
    if product not in ECOSYSTEM or not version:
        return None
    ecosystem, name = ECOSYSTEM[product]
    cache = None
    if cache_dir:
        cache = Path(cache_dir) / f"{ecosystem}_{name.replace(':', '_')}_{version}.json"
        if cache.exists():
            return json.loads(cache.read_text())
    data = (post or _post)(OSV_QUERY, {"package": {"name": name, "ecosystem": ecosystem}, "version": version})
    out = []
    for v in data.get("vulns") or []:
        aliases = [a for a in v.get("aliases") or [] if a.startswith("CVE-")]
        vid = aliases[0] if aliases else v.get("id")
        out.append({"id": vid, "osv_id": v.get("id"), "aliases": v.get("aliases") or [], "severity": _severity(v),
                    "summary": (v.get("summary") or v.get("details") or "")[:300], "confirmed": True,
                    "source": "OSV", "url": f"https://osv.dev/vulnerability/{v.get('id')}"})
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out))
    return out


def lookup(product: str, version: str | None, online: bool = False, cache_dir: Path | None = None, post=None) -> dict:
    if online and version and product in ECOSYSTEM:
        try:
            found = osv_lookup(product, version, cache_dir, post)
            if found is not None:
                return {"source": "OSV", "vulns": found}
        except Exception as exc:
            return {"source": "curated", "vulns": curated(product, version), "error": f"OSV lookup failed: {exc}"}
    return {"source": "curated", "vulns": curated(product, version)}
