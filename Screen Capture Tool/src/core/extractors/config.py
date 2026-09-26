import json
import re
import xml.etree.ElementTree as ET

from core.langs.structure import connection_target

from .common import entity, mask, rel

_CONN_VALUE = re.compile(r"(Data Source|Server|Initial Catalog|Database|DSN|Provider)\s*=|jdbc:[a-z0-9]+:", re.I)
_URL = re.compile(r"^(https?|net\.tcp|net\.pipe|ldap|ftp|sftp)://([^/:?#]+)", re.I)


def _lines_index(text: str):
    lines = text.splitlines()

    def find(needle: str, start: int = 1) -> int:
        if not needle:
            return start
        for i in range(max(0, start - 1), len(lines)):
            if needle in lines[i]:
                return i + 1
        for i, line in enumerate(lines):
            if needle in line:
                return i + 1
        return start
    return find


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if isinstance(tag, str) else ""


class _Builder:
    def __init__(self, filename):
        self.file = filename
        self.entities, self.relations = [], []
        self.seen = set()

    def item(self, name, line, value="", section=None, **attrs):
        masked, secret = mask(name, value)
        key = (section, name)
        if key in self.seen:
            return
        self.seen.add(key)
        self.entities.append(entity("config_item", name, None, line, line, value=masked[:300] if masked else None,
                                    section=section, hardcoded_secret=secret or None, **attrs))
        self.link_value(name, value, line)

    def link_value(self, name, value, line):
        if not value:
            return
        if _CONN_VALUE.search(value):
            target = connection_target(value)
            if target:
                self.define("data_store", target.upper(), line, store_type="database")
                self.relations.append(rel("connects_to", name, f"data_store:{target.upper()}", line,
                                          store_type="database", connection=mask(name, value)[0][:200]))
        url = _URL.match(value.strip())
        if url:
            self.define("external_system", url.group(2).lower(), line, protocol=url.group(1).lower())
            self.relations.append(rel("connects_to", name, f"external_system:{url.group(2).lower()}", line,
                                      url=value.strip()[:200], protocol=url.group(1).lower()))

    def define(self, kind, name, line, **attrs):
        if (kind, name) in self.seen:
            return
        self.seen.add((kind, name))
        self.entities.append(entity(kind, name, None, line, line, defined_by="config", **attrs))


def parse_xml_config(text: str, filename: str = "") -> dict:
    root = ET.fromstring(text)
    find = _lines_index(text)
    b = _Builder(filename)
    kind = _local(root.tag)
    profile = {"frameworks": [], "libraries": [], "settings": {}}
    for el in root.iter():
        tag = _local(el.tag)
        a = el.attrib
        if tag == "add" and "connectionString" in a:
            name = a.get("name", "connection")
            b.item(name, find(f'name="{name}"'), a["connectionString"], section="connectionStrings",
                   provider=a.get("providerName"))
        elif tag == "add" and "key" in a and "value" in a:
            b.item(a["key"], find(f'key="{a["key"]}"'), a["value"], section="appSettings")
        elif tag == "endpoint" and "address" in a:
            name = a.get("name") or a.get("contract") or a["address"]
            b.item(name, find(a["address"]), a["address"], section="serviceModel", contract=a.get("contract"),
                   binding=a.get("binding"))
        elif tag in ("compilation", "httpRuntime"):
            if "targetFramework" in a:
                profile["settings"]["targetFramework"] = a["targetFramework"]
            if tag == "compilation" and a.get("debug", "").lower() == "true":
                profile["settings"]["debug"] = True
        elif tag == "supportedRuntime":
            profile["settings"].setdefault("supportedRuntime", []).append(a.get("sku") or a.get("version"))
        elif tag == "assemblyIdentity" and "name" in a:
            profile["libraries"].append(a["name"])
        elif tag == "bindingRedirect" and profile["libraries"]:
            profile["libraries"][-1] += f" {a.get('newVersion', '')}".rstrip()
        elif tag == "customErrors":
            profile["settings"]["customErrors"] = a.get("mode")
        elif tag == "authentication" and "mode" in a:
            profile["settings"]["authentication"] = a["mode"]
        elif tag == "sessionState" and "mode" in a:
            profile["settings"]["sessionState"] = a["mode"]
        elif tag == "servlet":
            sname = (el.findtext("{*}servlet-name") or el.findtext("servlet-name") or "").strip()
            sclass = (el.findtext("{*}servlet-class") or el.findtext("servlet-class") or "").strip()
            if sname and sclass:
                profile.setdefault("servlets", {})[sname] = sclass
        elif tag == "servlet-mapping":
            sname = (el.findtext("{*}servlet-name") or el.findtext("servlet-name") or "").strip()
            pattern = (el.findtext("{*}url-pattern") or el.findtext("url-pattern") or "").strip()
            if sname and pattern:
                profile.setdefault("mappings", []).append((sname, pattern))
    if kind == "web-app":
        for p in root.iter():
            if _local(p.tag) in ("context-param", "init-param"):
                name = next((c.text or "" for c in p if _local(c.tag) == "param-name"), "").strip()
                value = next((c.text or "" for c in p if _local(c.tag) == "param-value"), "").strip()
                if name:
                    b.item(name, find(name), value, section=_local(p.tag))
        for sname, pattern in profile.get("mappings", []):
            sclass = profile.get("servlets", {}).get(sname)
            ep = f"ANY {pattern}"
            line = find(pattern)
            b.entities.append(entity("api_endpoint", ep, None, line, line, method="ANY", path=pattern, servlet=sname))
            if sclass:
                b.relations.append(rel("calls", ep, f"class:{sclass.split('.')[-1]}", line, servlet_class=sclass))
    if profile["settings"].get("targetFramework"):
        profile["frameworks"].append(f".NET Framework {profile['settings']['targetFramework']}")
    if kind == "configuration" and any(_local(e.tag) == "system.web" for e in root.iter()):
        profile["frameworks"].append("ASP.NET (system.web)")
    if kind == "web-app":
        version = root.attrib.get("version")
        profile["frameworks"].append(f"Java Servlet {version}" if version else "Java Servlet (web.xml)")
    profile.pop("mappings", None)
    return {"entities": b.entities, "relations": b.relations,
            "file_attrs": {"profile": {"language": "XML config", "document": kind, **profile}}}


def parse_properties(text: str, filename: str = "") -> dict:
    b = _Builder(filename)
    section = None
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line[0] in "#;!":
            continue
        sec = re.match(r"^\[([^\]]+)\]$", line)
        if sec:
            section = sec.group(1)
            continue
        m = re.match(r"^([^=:\s][^=:]*?)\s*[=:]\s*(.*)$", line)
        if m:
            b.item(m.group(1).strip(), n, m.group(2).strip(), section=section)
    return {"entities": b.entities, "relations": b.relations,
            "file_attrs": {"profile": {"language": "INI/properties config"}}}


def parse_json_config(text: str, filename: str = "") -> dict:
    data = json.loads(text)
    find = _lines_index(text)
    b = _Builder(filename)

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, path + [str(k)])
        elif isinstance(node, list):
            for i, v in enumerate(node[:50]):
                walk(v, path + [str(i)])
        elif node is not None and path:
            key = ":".join(path)
            b.item(key, find(f'"{path[-1]}"'), str(node), section=path[0] if len(path) > 1 else None)

    walk(data, [])
    return {"entities": b.entities, "relations": b.relations, "file_attrs": {"profile": {"language": "JSON config"}}}


def parse_yaml_config(text: str, filename: str = "") -> dict | None:
    try:
        import yaml
    except ImportError:
        return None
    data = yaml.safe_load(text)
    return parse_json_config(json.dumps(data if data is not None else {}), filename) if isinstance(data, (dict, list)) else None
