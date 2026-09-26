import json
import re
import xml.etree.ElementTree as ET

from .common import entity, rel

_HTTP = {"get", "post", "put", "delete", "patch", "head", "options"}


def _local(tag):
    return tag.split("}", 1)[-1] if isinstance(tag, str) else ""


def parse_wsdl(text: str, filename: str = "") -> dict:
    root = ET.fromstring(text)
    lines = text.splitlines()

    def find(needle):
        return next((i for i, l in enumerate(lines, 1) if needle in l), 1)

    entities, relations = [], []
    service_names = [s.attrib.get("name") for s in root.iter() if _local(s.tag) == "service"]
    service = service_names[0] if service_names else (root.attrib.get("name") or filename.rsplit(".", 1)[0])
    for port in root.iter():
        if _local(port.tag) == "portType":
            pname = port.attrib.get("name", "port")
            for op in port:
                if _local(op.tag) == "operation":
                    name = op.attrib.get("name")
                    ep = f"SOAP {service}/{name}"
                    entities.append(entity("api_endpoint", ep, None, find(f'name="{name}"'), find(f'name="{name}"'),
                                           method="SOAP", path=f"{service}/{name}", port_type=pname,
                                           documentation=(op.findtext("{*}documentation") or "").strip() or None))
    for addr in root.iter():
        if _local(addr.tag) == "address" and addr.attrib.get("location"):
            loc = addr.attrib["location"]
            host = re.match(r"^\w+://([^/:]+)", loc)
            if host:
                entities.append(entity("external_system", host.group(1).lower(), None, find(loc), find(loc),
                                       protocol="soap", url=loc))
                for e in [x for x in entities if x["kind"] == "api_endpoint"]:
                    relations.append(rel("connects_to", e["name"], f"external_system:{host.group(1).lower()}",
                                         find(loc), url=loc))
    return {"entities": entities, "relations": relations,
            "file_attrs": {"profile": {"language": "WSDL", "frameworks": ["SOAP web service (WSDL)"]}}}


def parse_openapi(data: dict, text: str, filename: str = "") -> dict:
    lines = text.splitlines()

    def find(needle):
        return next((i for i, l in enumerate(lines, 1) if needle in l), 1)

    entities, relations = [], []
    base = ""
    if "basePath" in data:
        base = data["basePath"].rstrip("/")
    servers = data.get("servers") or []
    for s in servers:
        m = re.match(r"^https?://([^/:]+)", s.get("url", ""))
        if m:
            entities.append(entity("external_system", m.group(1).lower(), None, find(s["url"]), find(s["url"]),
                                   protocol="https", url=s["url"]))
    for path, ops in (data.get("paths") or {}).items():
        if not isinstance(ops, dict):
            continue
        for method, op in ops.items():
            if method.lower() not in _HTTP or not isinstance(op, dict):
                continue
            full = (base + path) if base and not path.startswith(base) else path
            ep = f"{method.upper()} {full}"
            line = find(f'"{path}"') if text.lstrip().startswith("{") else find(path)
            entities.append(entity("api_endpoint", ep, None, line, line, method=method.upper(), path=full,
                                   operation_id=op.get("operationId"), summary=op.get("summary"),
                                   deprecated=op.get("deprecated") or None,
                                   secured=bool(op.get("security") or data.get("security")) or None))
    version = data.get("openapi") or data.get("swagger")
    return {"entities": entities, "relations": relations,
            "file_attrs": {"profile": {"language": "OpenAPI", "frameworks": [f"{'OpenAPI' if data.get('openapi') else 'Swagger'} {version}"]}}}


def load_openapi(text: str):
    try:
        data = json.loads(text)
    except ValueError:
        try:
            import yaml
            data = yaml.safe_load(text)
        except Exception:
            return None
    if isinstance(data, dict) and ("openapi" in data or "swagger" in data) and "paths" in data:
        return data
    return None


def looks_like_wsdl(text: str) -> bool:
    head = (text or "")[:3000]
    return bool(re.search(r"<(\w+:)?definitions\b", head)) and "wsdl" in head.lower()
