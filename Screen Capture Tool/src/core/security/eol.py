import json
import re
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from core.model.workspace import programs_root

DATA_PATH = Path(__file__).with_name("eol_data.json")
API = "https://endoflife.date/api/{}.json"
SOON_DAYS = 365


def cache_path() -> Path:
    return programs_root().parent / "cache" / "eol_data.json"


def load_data() -> dict:
    data = json.loads(DATA_PATH.read_text())
    cached = cache_path()
    if cached.exists():
        try:
            fresh = json.loads(cached.read_text())
            if fresh.get("snapshot", "") > data["snapshot"]:
                data["products"].update(fresh.get("products", {}))
                data["snapshot"], data["source"] = fresh["snapshot"], fresh.get("source", data["source"])
        except (ValueError, KeyError):
            pass
    return data


def refresh(fetch=None, today: date | None = None) -> dict:
    fetch = fetch or _fetch
    data = json.loads(DATA_PATH.read_text())
    updated, failed = {}, []
    for slug, product in data["products"].items():
        try:
            rows = fetch(API.format(slug))
        except Exception as exc:
            failed.append(f"{slug}: {exc}")
            continue
        cycles = [{k: v for k, v in {"cycle": str(r.get("cycle")), "release": r.get("releaseDate"),
                                      "support": r.get("support"), "eol": r.get("eol"),
                                      "extended": r.get("extendedSupport")}.items() if v is not None}
                  for r in rows if r.get("cycle") is not None]
        if cycles:
            updated[slug] = {**product, "cycles": cycles}
    out = {"snapshot": (today or date.today()).isoformat(), "source": "https://endoflife.date", "products": updated}
    if updated:
        path = cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=1))
    return {"updated": sorted(updated), "failed": failed, "snapshot": out["snapshot"]}


def _fetch(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "CodeSnap"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _as_date(value):
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return date.fromisoformat(value)
    return value


def find_cycle(product: dict, version: str | None):
    if not version:
        return None
    v = version.lower().lstrip("v").replace(" ", "")
    best, best_len = None, -1
    for c in product["cycles"]:
        cyc = c["cycle"].lower()
        base = cyc.split("-")[0]
        if v == cyc or v == base or v.startswith(base + ".") or v.startswith(cyc + "."):
            if len(cyc) > best_len:
                best, best_len = c, len(cyc)
    return best


def cycle_status(cycle: dict, today: date | None = None) -> dict:
    today = today or date.today()
    eol, support, extended = (_as_date(cycle.get(k)) for k in ("eol", "support", "extended"))
    if eol is True or (isinstance(eol, date) and eol <= today):
        if isinstance(extended, date) and extended > today:
            return {"status": "extended", "eol": str(eol), "extended_until": str(extended)}
        return {"status": "eol", "eol": str(eol) if isinstance(eol, date) else None}
    if isinstance(eol, date):
        if eol - today <= timedelta(days=SOON_DAYS):
            return {"status": "ending", "eol": str(eol)}
        out = {"status": "supported", "eol": str(eol)}
    else:
        out = {"status": "supported", "eol": None}
    if isinstance(support, date) and support <= today:
        out["active_support_ended"] = str(support)
    return out


def curated_status(entry: dict, data: dict, today: date | None = None) -> dict:
    if entry.get("product"):
        product = data["products"][entry["product"]]
        cycle = next(c for c in product["cycles"] if c["cycle"] == entry["cycle"])
        return {**cycle_status(cycle, today), "url": product["url"], "cycle": cycle["cycle"]}
    if entry.get("status") == "auto":
        out = cycle_status({"eol": entry.get("eol"), "extended": entry.get("extended")}, today)
        return {**out, "url": entry["url"], "note": entry.get("note")}
    out = {"status": entry["status"], "url": entry["url"], "note": entry.get("note")}
    if entry.get("eol"):
        out["eol"] = entry["eol"]
    return out


_LIB_PRODUCTS = {"jquery": "jquery", "bootstrap": "bootstrap", "angular": "angularjs", "angularjs": "angularjs",
                 "log4j": "log4j", "struts": "apache-struts", "spring": "spring-framework", "hibernate": "hibernate-orm"}
_FRAMEWORK_CURATED = [
    (r"^log4j 1", "log4j1"), (r"^Struts 1", "struts1"), (r"Remoting", "remoting"), (r"^ASP\.NET Web Forms", "webforms"),
    (r"^WCF$", "wcf"), (r"^ASMX", "asmx"), (r"^EJB 2", "ejb2"), (r"^Applet", "applet"), (r"^Win16", "win16"),
    (r"^Borland OWL", "owl"),
]
_LEGACY_CURATED = [(r"^ActiveX", "activex"), (r"^Flash", "flash"), (r"^Silverlight", "silverlight"),
                   (r"^Java applet", "applet")]
_JAVA_LEVELS = {"Java 5 generics/annotations": "5", "Java 7 try-with-resources/diamond": "7",
                "Java 8 lambdas/streams": "8", "Java 10+ var": "10"}
_CS_LEVELS = {"C# 2.0 generics": ".NET Framework 2.0+", "C# 3.0 LINQ/var": ".NET Framework 3.5+",
              "C# 5.0 async": ".NET Framework 4.5+", "C# 6+ features": ".NET Framework 4.6+ / Roslyn"}


_HINT_CURATED = [(r"visual basic 6|\bvb6\b", "vb6"), (r"oracle forms", "oracle-forms"), (r"powerbuilder", "powerbuilder"),
                 (r"foxpro", "visual-foxpro"), (r"\baccess\b", "ms-access"), (r"delphi", "delphi-bde"),
                 (r"crystal reports", "crystal-reports"), (r"5250|as/?400|ibm i\b", "product:ibm-i:"),
                 (r"coldfusion", "product:coldfusion:"), (r"angularjs", "angularjs1")]


def _first_evidence(profile: dict) -> list:
    ev = profile.get("evidence") or {}
    for label in profile.get("legacy_markers") or []:
        if ev.get(label):
            return list(ev[label])[:1]
    return []


def _lines_for(profile: dict, label: str) -> list:
    return list((profile.get("evidence") or {}).get(label) or [])


def technologies(profile: dict) -> list:
    out = []

    def add(product=None, version=None, curated=None, label="", lines=(), confidence="confirmed", basis=""):
        out.append({"product": product, "version": version, "curated": curated, "label": label,
                    "lines": list(lines), "confidence": confidence, "basis": basis})

    settings = profile.get("settings") or {}
    tf = settings.get("targetFramework")
    if tf:
        add("dotnetfx", str(tf).lstrip("v"), label=f".NET Framework {tf}", basis="targetFramework in config")
    for rt in settings.get("supportedRuntime") or []:
        if rt and str(rt).lower().startswith("v2.0"):
            add("dotnetfx", "3.5", label=f".NET CLR {rt} (.NET Framework 2.0–3.5)", basis="supportedRuntime in config")
        elif rt and re.search(r"v?4\.\d", str(rt)):
            ver = re.search(r"(4(\.\d+)+)", str(rt)).group(1)
            add("dotnetfx", ver, label=f".NET Framework {ver}", basis="supportedRuntime in config")
    for lib in profile.get("libraries") or []:
        m = re.match(r"^([A-Za-z][\w.\-]*?)[\s\-]+v?(\d+(?:\.\d+)*)", str(lib))
        name = (m.group(1) if m else str(lib).split()[0]).lower()
        version = m.group(2) if m else None
        product = _LIB_PRODUCTS.get(name)
        if name == "angular" and version and not version.startswith("1."):
            product = None
        if product:
            add(product, version, label=f"{lib}", basis="script / library reference",
                confidence="confirmed" if version else "unconfirmed")
    for fw in profile.get("frameworks") or []:
        for pattern, key in _FRAMEWORK_CURATED:
            if re.search(pattern, fw):
                add(curated=key, label=fw, lines=_lines_for(profile, fw), basis="framework detected in code")
    for marker in profile.get("legacy_markers") or []:
        for pattern, key in _LEGACY_CURATED:
            if re.search(pattern, marker):
                line = re.search(r"\(L(\d+)\)", marker)
                add(curated=key, label=marker, lines=[int(line.group(1))] if line else _lines_for(profile, marker),
                    basis="legacy component in page")
    if profile.get("dialect", "") and str(profile.get("dialect")).startswith("pre-standard"):
        lines = [n for k, v in (profile.get("evidence") or {}).items() if k.startswith(("pre-standard", "no std"))
                 for n in v]
        add(curated="prestd-cpp", label=profile["dialect"], lines=sorted(set(lines))[:5], basis="C++ dialect signals")
    for t in profile.get("techs") or []:
        key = t.get("curated")
        label = t.get("label") or (key or t.get("product") or "").replace("-", " ")
        add(t.get("product") if not key else None, t.get("version"), curated=key, label=label,
            lines=_first_evidence(profile), confidence="unconfirmed" if t.get("unconfirmed") or (
                t.get("product") and not t.get("version")) else "confirmed",
            basis=f"{profile.get('language') or 'code'} source detected" + (
                f" ({', '.join(profile.get('legacy_markers')[:2])})" if profile.get("legacy_markers") else ""))
    if profile.get("language") == "UI screen":
        for hint in profile.get("frameworks") or []:
            for pattern, key in _HINT_CURATED:
                if re.search(pattern, hint, re.I):
                    if key.startswith("product:"):
                        _, prod, ver = key.split(":")
                        m = re.search(r"\b(\d+\.\d+|(?:19|20)\d\d)\b", hint)
                        add(prod, m.group(1) if m else (ver or None), label=hint, confidence="unconfirmed",
                            basis="visible in a screenshot")
                    else:
                        add(curated=key, label=hint, confidence="unconfirmed", basis="visible in a screenshot")
                    break
    lang = profile.get("language")
    level = profile.get("level_signal")
    if lang == "Java":
        floor = _JAVA_LEVELS.get(level, "1.4")
        add("oracle-jdk", None, label=f"Java source level ≥ {floor}", lines=_lines_for(profile, level or ""),
            confidence="unconfirmed",
            basis=f"newest language feature seen: {level or 'none (pre-Java 5 style)'}; runtime version not captured")
    if lang == "C#" and not tf:
        add("dotnetfx", None, label=f"C# code ({_CS_LEVELS.get(level, 'framework version unknown')})",
            lines=_lines_for(profile, level or ""), confidence="unconfirmed",
            basis="no targetFramework captured; capture web.config / .csproj to confirm")
    return out


def assess(tech: dict, data: dict, today: date | None = None) -> dict:
    if tech.get("curated"):
        entry = data["curated"][tech["curated"]]
        return {**tech, "name": entry["label"], "product": entry.get("product") or tech.get("product"),
                **curated_status(entry, data, today),
                "source": "curated vendor notice" if not entry.get("product") else
                f"endoflife.date snapshot {data['snapshot']}"}
    product = data["products"][tech["product"]]
    base = {**tech, "name": product["label"], "url": product["url"],
            "source": f"endoflife.date snapshot {data['snapshot']}"}
    cycle = find_cycle(product, tech.get("version"))
    if cycle:
        return {**base, "cycle": cycle["cycle"], **cycle_status(cycle, today)}
    return {**base, "status": "unknown"}


SEVERITY = {"eol": "high", "extended": "medium", "ending": "medium", "legacy": "medium", "unknown": "info",
            "supported": None}
