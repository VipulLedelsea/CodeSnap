import re

from .config import parse_json_config, parse_properties, parse_xml_config, parse_yaml_config
from .sql import looks_like_sql, parse_sql

PARSER_VERSION = "extractors-v1"
CONFIG_EXTS = {"config", "xml", "properties", "ini", "cfg", "conf", "json", "yaml", "yml", "env"}
SQL_EXTS = {"sql", "ddl", "db2", "tsql", "pls", "pks", "pkb", "prc"}


def kind_for(text: str, filename: str = "", language: str = "") -> str | None:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    lang = (language or "").lower()
    body = (text or "").lstrip()
    if ext in SQL_EXTS or "sql" in lang:
        return "sql"
    if ext in ("config", "xml") or lang == "xml" or body.startswith("<?xml") or body.startswith("<configuration") \
            or body.startswith("<web-app"):
        return "xml" if body.startswith("<") else None
    if ext in ("properties", "ini", "cfg", "conf", "env") or lang in ("ini", "properties"):
        return "properties"
    if ext == "json" or lang == "json":
        return "json"
    if ext in ("yaml", "yml") or lang == "yaml":
        return "yaml"
    if lang in ("", "text", "plain text", "unknown", "ddl", "db2") and ext in ("", "txt") and looks_like_sql(text):
        return "sql"
    return None


def parse_artifact(text: str, filename: str = "", language: str = "") -> dict | None:
    kind = kind_for(text, filename, language)
    if kind == "sql":
        return parse_sql(text, filename)
    if kind == "xml":
        return parse_xml_config(text, filename)
    if kind == "properties":
        return parse_properties(text, filename)
    if kind == "json":
        return parse_json_config(text, filename)
    if kind == "yaml":
        return parse_yaml_config(text, filename)
    return None
