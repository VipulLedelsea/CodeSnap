import http.client
import re
import socket
import ssl
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from .page import check_page

UA = "CodeSnap-PlatformHolisticReview/2.0 (+Ledelsea assessment)"
PAGE_EXT = re.compile(r"\.(aspx?|jsp|html?|php|do|action|cfm)?$", re.I)
IIS = {"6.0": ("windows-server", "2003-sp2"), "7.0": ("windows-server", "2008-sp2"), "7.5": ("windows-server", "2008-r2-sp1"),
       "8.0": ("windows-server", "2012"), "8.5": ("windows-server", "2012-r2")}
HEADER_RULES = [
    ("strict-transport-security", "WEB-HSTS", "medium", "no HSTS header — browsers may connect over plain HTTP", "SC-8"),
    ("content-security-policy", "WEB-CSP", "medium", "no Content-Security-Policy — no browser defence against injected scripts", "SI-10"),
    ("x-content-type-options", "WEB-XCTO", "low", "no X-Content-Type-Options: nosniff", "SI-10"),
    ("referrer-policy", "WEB-REFERRER", "low", "no Referrer-Policy — full URLs (with query data) leak to other sites", "SC-8"),
]


def fetch(url, timeout=12, max_redirects=5):
    chain, tls = [], None
    for _ in range(max_redirects + 1):
        u = urlparse(url)
        host, port = u.hostname, u.port or (443 if u.scheme == "https" else 80)
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        try:
            if u.scheme == "https":
                ctx = ssl.create_default_context()
                conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
            else:
                conn = http.client.HTTPConnection(host, port, timeout=timeout)
            conn.request("GET", path, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
            resp = conn.getresponse()
            if u.scheme == "https" and conn.sock is not None:
                cert = conn.sock.getpeercert() or {}
                tls = {"version": conn.sock.version(), "cert_ok": True, "expires": cert.get("notAfter"),
                       "issuer": dict(x[0] for x in cert.get("issuer", ())).get("organizationName")}
            headers = [(k.lower(), v) for k, v in resp.getheaders()]
            body = resp.read(2_000_000).decode(resp.headers.get_content_charset() or "utf-8", "replace")
            conn.close()
        except ssl.SSLCertVerificationError as exc:
            return {"url": url, "status": None, "headers": [], "body": "", "chain": chain,
                    "tls": {"version": None, "cert_ok": False, "error": str(exc)[:200]}, "error": "certificate"}
        except (OSError, socket.timeout, http.client.HTTPException) as exc:
            return {"url": url, "status": None, "headers": [], "body": "", "chain": chain, "tls": tls,
                    "error": str(exc)[:200]}
        chain.append((url, resp.status))
        loc = dict(headers).get("location")
        if resp.status in (301, 302, 303, 307, 308) and loc:
            url = urljoin(url, loc)
            continue
        return {"url": url, "status": resp.status, "headers": headers, "body": body, "chain": chain, "tls": tls}
    return {"url": url, "status": None, "headers": [], "body": "", "chain": chain, "tls": tls, "error": "too many redirects"}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs, self.scripts = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.hrefs.append(a["href"])
        if tag == "script" and a.get("src"):
            self.scripts.append(a["src"])


def _robots(base, fetcher):
    r = fetcher(urljoin(base, "/robots.txt"))
    rules, active = [], False
    for line in (r.get("body") or "").splitlines() if r.get("status") == 200 else []:
        line = line.split("#")[0].strip()
        if line.lower().startswith("user-agent:"):
            active = line.split(":", 1)[1].strip() in ("*", "CodeSnap")
        elif active and line.lower().startswith("disallow:"):
            p = line.split(":", 1)[1].strip()
            if p:
                rules.append(p)
    return rules


def scan_site(start_url, fetcher=None, max_pages=10, respect_robots=True) -> dict:
    fetcher = fetcher or fetch
    if not re.match(r"^https?://", start_url or "", re.I):
        start_url = "https://" + (start_url or "").lstrip("/")
    findings = []

    def add(rule, severity, url, detail, snippet="", category="website", **refs):
        findings.append({"rule": rule, "category": category, "severity": severity, "url": url, "line": None,
                         "detail": detail, "snippet": str(snippet)[:160], "refs": refs})

    first = fetcher(start_url)
    host = urlparse(first.get("url") or start_url).hostname
    summary = {"start": start_url, "final_url": first.get("url"), "status": first.get("status"), "tls": first.get("tls"),
               "redirects": first.get("chain"), "scanned": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "pages": [], "headers": {}, "libraries": [], "error": first.get("error")}
    if first.get("error") == "certificate":
        add("WEB-CERT", "high", start_url, f"TLS certificate is not valid: {first['tls'].get('error')}", cwe="CWE-295",
            nist=["SC-8", "SC-17"])
    if first.get("status") is None:
        return {"summary": summary, "findings": findings}
    final = urlparse(first["url"])
    if final.scheme != "https":
        add("WEB-HTTPS", "high", first["url"], "site is served over plain HTTP (no redirect to HTTPS)", cwe="CWE-319",
            nist=["SC-8"])
    elif start_url.startswith("https://"):
        plain = fetcher("http://" + start_url.split("://", 1)[1])
        if plain.get("status") and urlparse(plain.get("url") or "").scheme != "https":
            add("WEB-HTTPS", "medium", "http://" + host, "plain-HTTP version of the site does not redirect to HTTPS",
                cwe="CWE-319", nist=["SC-8"])
    tls = first.get("tls") or {}
    if tls.get("version") in ("SSLv3", "TLSv1", "TLSv1.1"):
        add("WEB-TLS", "high", first["url"], f"obsolete protocol {tls['version']} negotiated", cwe="CWE-327", nist=["SC-8", "SC-13"])
    hdrs = {}
    for k, v in first["headers"]:
        hdrs.setdefault(k, []).append(v)
    summary["headers"] = {k: v[0] for k, v in hdrs.items() if k in ("server", "x-powered-by", "x-aspnet-version",
                                                                    "x-aspnetmvc-version", "strict-transport-security",
                                                                    "content-security-policy", "x-frame-options",
                                                                    "x-content-type-options", "referrer-policy")}
    if final.scheme == "https":
        for name, rule, sev, text, nist in HEADER_RULES:
            if name not in hdrs:
                add(rule, sev, first["url"], text, cwe="CWE-693", nist=[nist])
    csp = " ".join(hdrs.get("content-security-policy", []))
    if "x-frame-options" not in hdrs and "frame-ancestors" not in csp:
        add("WEB-FRAME", "medium", first["url"], "page can be framed by other sites (clickjacking)", cwe="CWE-1021", nist=["SC-18"])
    for c in hdrs.get("set-cookie", []):
        name = c.split("=", 1)[0].strip()
        missing = [f for f, rx in (("Secure", r";\s*secure"), ("HttpOnly", r";\s*httponly"), ("SameSite", r";\s*samesite"))
                   if not re.search(rx, c, re.I)]
        if missing:
            add("WEB-COOKIE", "medium" if "Secure" in missing or "HttpOnly" in missing else "low", first["url"],
                f"cookie '{name}' missing {', '.join(missing)}", name, cwe="CWE-614", nist=["SC-8", "SC-23"])
    techs = []
    for k in ("server", "x-powered-by", "x-aspnet-version", "x-aspnetmvc-version"):
        for v in hdrs.get(k, []):
            if re.search(r"\d", v):
                add("WEB-DISCLOSURE", "low", first["url"], f"{k} header reveals version: {v}", f"{k}: {v}", cwe="CWE-200",
                    nist=["CM-7"])
            m = re.search(r"Microsoft-IIS/(\d+\.\d+)", v)
            if m and m.group(1) in IIS:
                techs.append(("iis", m.group(1)))
            m = re.search(r"^(4\.0\.30319|2\.0\.50727)", v) if k == "x-aspnet-version" else None
            if m:
                techs.append(("aspnet", m.group(1)))
    summary["technologies"] = techs
    rules = _robots(first["url"], fetcher) if respect_robots else []
    queue, seen, pages = deque([first["url"]]), {first["url"]}, 0
    cache = {first["url"]: first}
    libs = set()
    while queue and pages < max_pages:
        url = queue.popleft()
        r = cache.pop(url, None) or fetcher(url)
        ctype = dict(r.get("headers") or []).get("content-type", "text/html")
        if not r.get("status") or r["status"] >= 400 or "html" not in ctype:
            summary["pages"].append({"url": url, "status": r.get("status")})
            continue
        pages += 1
        summary["pages"].append({"url": url, "status": r["status"]})
        for f in check_page(r["body"]):
            findings.append({**f, "url": url})
        lp = _Links()
        try:
            lp.feed(r["body"])
        except Exception:
            pass
        for src in lp.scripts:
            libs.add(urljoin(url, src))
        for href in lp.hrefs:
            nxt = urljoin(url, href.split("#")[0])
            pu = urlparse(nxt)
            if pu.scheme in ("http", "https") and pu.hostname == host and nxt not in seen and PAGE_EXT.search(pu.path or "/") \
                    and not any(pu.path.startswith(p) for p in rules):
                seen.add(nxt)
                queue.append(nxt)
    summary["libraries"] = sorted(libs)
    return {"summary": summary, "findings": findings}
