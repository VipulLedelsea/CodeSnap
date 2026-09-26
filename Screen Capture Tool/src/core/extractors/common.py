import re

SECRET_KEY = re.compile(r"(password|passwd|pwd|secret|token|apikey|api_key|accesskey|privatekey|credential)", re.I)
_PASSWORD_IN_VALUE = re.compile(r"((?:Password|Pwd)\s*=\s*)([^;\"']*)", re.I)


def entity(kind, name, parent=None, start=None, end=None, **attrs):
    return {"kind": kind, "name": name, "parent": parent, "line_start": start, "line_end": end,
            "attrs": {k: v for k, v in attrs.items() if v not in (None, "", [], {})}}


def rel(kind, source, target, line, target_kind=None, **attrs):
    return {"kind": kind, "source": source, "target": target, "target_kind": target_kind, "line": line,
            "attrs": {k: v for k, v in attrs.items() if v not in (None, "", [], {})}}


def mask(key: str, value: str) -> tuple:
    value = value or ""
    if SECRET_KEY.search(key or ""):
        return ("****" if value else ""), bool(value)
    masked = _PASSWORD_IN_VALUE.sub(lambda m: m.group(1) + ("****" if m.group(2) else ""), value)
    return masked, masked != value


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def clean_ident(name: str) -> str:
    parts = [p.strip().strip('[]"`') for p in re.split(r"\.(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", name.strip())]
    return ".".join(p for p in parts if p).upper()
