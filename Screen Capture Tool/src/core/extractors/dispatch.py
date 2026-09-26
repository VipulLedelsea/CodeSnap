import re

from .apidefs import load_openapi, looks_like_wsdl, parse_openapi, parse_wsdl
from .config import parse_json_config, parse_properties, parse_xml_config, parse_yaml_config
from .spss import looks_like_spss, parse_spss
from .sql import looks_like_sql, parse_sql
from .ui import parse_ui_json
from .web import looks_like_web, parse_web_page

PARSER_VERSION = "extractors-v1"
CONFIG_EXTS = {"config", "xml", "properties", "ini", "cfg", "conf", "json", "yaml", "yml", "env"}
SQL_EXTS = {"sql", "ddl", "db2", "tsql", "pls", "pks", "pkb", "prc"}
WEB_EXTS = {"html", "htm", "aspx", "ascx", "master", "asp", "jsp", "jspx", "xhtml", "cshtml", "vbhtml"}
FORCED = {"sql": "sql", "db_schema": "sql", "web": "web", "api": "api", "ui_screen": "ui"}


def kind_for(text: str, filename: str = "", language: str = "", artifact_type: str = "") -> str | None:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    lang = (language or "").lower()
    body = (text or "").lstrip()
    if body.startswith("{") and '"codesnap_ui_screen"' in body[:400]:
        return "ui"
    if artifact_type in FORCED:
        return FORCED[artifact_type] if artifact_type != "api" else ("wsdl" if looks_like_wsdl(text) else "openapi")
    if ext == "sps" or lang == "spss" or (lang in ("", "text", "unknown") and looks_like_spss(text)):
        return "spss"
    if ext in ("wsdl",) or looks_like_wsdl(text):
        return "wsdl"
    if ext in ("json", "yaml", "yml") and load_openapi(text):
        return "openapi"
    if ext in SQL_EXTS or "sql" in lang:
        return "sql"
    if ext in WEB_EXTS or lang in ("html", "aspx", "asp.net", "jsp") or (ext in ("", "txt") and looks_like_web(text)):
        return "web"
    if ext in ("config", "xml") or lang == "xml" or body.startswith("<?xml") or body.startswith("<configuration") \
            or body.startswith("<web-app"):
        return "xml" if body.startswith("<") else None
    if ext in ("properties", "ini", "cfg", "conf", "env") or lang in ("ini", "properties"):
        return "properties"
    if ext == "json" or lang == "json":
        return "json"
    if ext in ("yaml", "yml") or lang == "yaml":
        return "yaml"
    if artifact_type == "config":
        return "json" if body.startswith("{") else ("xml" if body.startswith("<") else "properties")
    if lang in ("", "text", "plain text", "unknown", "ddl", "db2") and ext in ("", "txt") and looks_like_sql(text):
        return "sql"
    return None


def parse_artifact(text: str, filename: str = "", language: str = "", artifact_type: str = "") -> dict | None:
    kind = kind_for(text, filename, language, artifact_type)
    if kind == "ui":
        return parse_ui_json(text, filename)
    if kind == "sql":
        return parse_sql(text, filename)
    if kind == "web":
        return parse_web_page(text, filename)
    if kind == "wsdl":
        return parse_wsdl(text, filename)
    if kind == "openapi":
        data = load_openapi(text)
        return parse_openapi(data, text, filename) if data else None
    if kind == "spss":
        return parse_spss(text, filename)
    if kind == "xml":
        return parse_xml_config(text, filename)
    if kind == "properties":
        return parse_properties(text, filename)
    if kind == "json":
        return parse_json_config(text, filename)
    if kind == "yaml":
        return parse_yaml_config(text, filename)
    return None
