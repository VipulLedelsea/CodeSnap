"""Cross-file reference checks: a name that one file uses and another file does not agree with. A role asked for that the role list
does not contain, a table the code reads that no schema creates, the same password or key written into several files, a stylesheet
the page links that is not in the folder, a settings file no program reads. Read from the source text; no model call."""
import re

_ROLE_LIST = re.compile(r"\bROLES\s*=\s*[(\[]([^)\]]*)[)\]]")
_ROLE_ASK = re.compile(r"\bhas_role\(\s*[\w.\[\]'\"]+\s*,\s*[\"'](\w+)[\"']\s*\)")
_TABLE_USE = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+(?:[A-Za-z_]\w*\.)?([A-Za-z_]\w*)", re.I)
_EXEC_SQL = re.compile(r"EXEC\s+SQL\b(.*?)(?:END-EXEC|;)", re.I | re.S)       # embedded SQL in COBOL, PL/I and RPG, which spans lines
_TABLE_DEF = re.compile(r"\bCREATE\s+(?:TEMP(?:ORARY)?\s+)?(?:TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:[\[\"`]?\w+[\]\"`]?\.)?[\[\"`]?([A-Za-z_]\w*)", re.I)
_SECRET_NAME = r"(?:password|passwd|secret|api[_-]?key|token|sms_key)"
_LITERALS = [
    re.compile(r"\b\w*" + _SECRET_NAME + r"\w*\s*=\s*[\"']([^\"'\s]{8,})[\"']", re.I),                       # python / shell
    re.compile(r"\b\w*" + _SECRET_NAME + r"\w*\s*[:=]\s*([^\s\"'#]{8,})\s*$", re.I | re.M),                  # yaml / shell export
    re.compile(r"\b\w*" + _SECRET_NAME + r"\w*[^\n]{0,60}?,\s*[\"']([^\"'\s]{8,})[\"']\s*\)", re.I),        # environ.get(name, "default")
]
_NOT_SECRET = re.compile(r"^(\$|\{|<|%|os\.environ|null|none|true|false|changeme$)", re.I)
_ASSET = re.compile(r"(?:href|src)=[\"'](/?[\w./-]+\.(?:css|js|png|jpg|svg|ico))[\"']", re.I)
_SQL_WORDS = {"select", "values", "set", "where", "the", "dual", "sqlite_master", "information_schema", "of", "lock", "locks", "share", "only", "table", "final"}


def _code(store):
    return [(a, a.get("transcription") or "") for a in store.artifacts() if (a.get("transcription") or "").strip()]


def _line(text, pos):
    return text.count("\n", 0, pos) + 1


def _join(names):
    return ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]


def _obs(title, statement, hits, source, severity="high"):
    """hits: [(artifact name, line)]"""
    names = sorted({n for n, _ in hits})
    return {"title": title, "statement": statement, "facts": [], "basis": "observed", "files": names,
            "cites": [f"{n} lines {l}–{l}" for n, l in hits[:6]], "source": source, "severity": severity}


def role_names(store):
    roles, where = set(), None
    for a, t in _code(store):
        m = _ROLE_LIST.search(t)
        if m:
            roles |= {x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()}
            where = (a["name"], _line(t, m.start()))
    if not roles or not where:
        return []
    out = []
    for a, t in _code(store):
        for m in _ROLE_ASK.finditer(t):
            ask = m.group(1)
            if ask not in roles:
                near = [r for r in roles if r.startswith(ask) or ask.startswith(r)]
                hint = f" ({near[0]!r} is the closest role in the list)" if near else ""
                out.append(_obs(f"{a['name']} asks for the role '{ask}', which the role list does not contain",
                                f"{a['name']} checks has_role(..., '{ask}') at line {_line(t, m.start())}, but the role list in {where[0]} "
                                f"(line {where[1]}) is {', '.join(sorted(roles))}; no user can hold '{ask}'{hint}, so the check passes "
                                f"for no one (or only for a role that passes every check). The code that depends on it can never run for the people it is meant for.",
                                [(a["name"], _line(t, m.start())), where], "role names"))
    return out


def missing_tables(store):
    defined, schema_files = set(), set()
    uses = {}
    for a, t in _code(store):
        for m in _TABLE_DEF.finditer(t):
            defined.add(m.group(1).lower())
            schema_files.add(a["name"])
        if a["name"].lower().endswith((".sql",)):
            continue
        for m in _TABLE_USE.finditer(t):
            name = m.group(1).lower()
            if name in _SQL_WORDS or not re.search(r"[\"'`]\s*(?:SELECT|INSERT|UPDATE|DELETE)\b|\bSELECT\b[^\n]{0,200}\bFROM\b", t[max(0, m.start() - 200):m.end()], re.I):
                continue
            uses.setdefault(name, []).append((a["name"], _line(t, m.start())))
        for block in _EXEC_SQL.finditer(t):
            for m in _TABLE_USE.finditer(block.group(1)):
                name = m.group(1).lower()
                if name in _SQL_WORDS or name in ("commit", "rollback") or re.match(r"(insert|delete|select|values|update)$", name):
                    continue
                line = _line(t, block.start(1) + m.start())
                if (a["name"], line) not in uses.get(name, []):
                    uses.setdefault(name, []).append((a["name"], line))
    if not defined:
        return []
    out = []
    for name, hits in sorted(uses.items()):
        if name in defined:
            continue
        files = sorted({n for n, _ in hits})
        out.append(_obs(f"The table '{name}' is used but no schema creates it",
                        f"{', '.join(files)} read or write a table named '{name}' ({len(hits)} place{'s' if len(hits) > 1 else ''}), but the schema "
                        f"({', '.join(sorted(schema_files))}) never creates it, so the first call that touches it fails with 'no such table' "
                        f"unless something outside the files given creates it.", hits[:4] + [(sorted(schema_files)[0], 1)], "missing table"))
    return out


def repeated_secrets(store):
    seen = {}
    for a, t in _code(store):
        for rx in _LITERALS:
            for m in rx.finditer(t):
                v = m.group(1).strip()
                if _NOT_SECRET.match(v) or v.lower() in ("password", "required", "optional"):
                    continue
                seen.setdefault(v, {}).setdefault(a["name"], _line(t, m.start()))
    out = []
    for v, files in sorted(seen.items()):
        if len(files) < 2:
            continue
        hits = sorted(files.items())
        out.append(_obs(f"The same secret is written into {_join([n for n, _ in hits])}",
                        f"The value '{v}' is written as a password or key in {', '.join(f'{n} (line {l})' for n, l in hits)}. One leak exposes every place it is used, "
                        f"and changing it means finding and editing each copy; it should live in one secrets store.", hits, "repeated secrets"))
    return out


def missing_assets(store):
    allnames = {a["name"].split("/")[-1].lower() for a in store.artifacts()}
    out = []
    for a, t in _code(store):
        if not a["name"].lower().endswith((".html", ".htm")):
            continue
        for m in _ASSET.finditer(t):
            base = m.group(1).split("/")[-1].lower()
            if base not in allnames:
                out.append(_obs(f"{a['name']} links {m.group(1)}, which is not in the files given",
                                f"{a['name']} line {_line(t, m.start())} loads {m.group(1)}, but no file of that name was provided, so the page loses its styling or behaviour if it is missing from the "
                                f"deployment, and what it contains was not reviewed if it was left out.",
                                [(a["name"], _line(t, m.start()))], "missing asset", "low"))
    return out


def unread_settings(store):
    files = _code(store)
    out = []
    for a, t in files:
        if not a["name"].lower().endswith((".yaml", ".yml", ".ini", ".toml")):
            continue
        base = a["name"].split("/")[-1]
        if re.search(r"docker|compose|\.github|workflow|pipeline|ci\.ya?ml|k8s|kubernetes|helm|ansible|playbook|swagger|openapi", a["name"], re.I):
            continue          # deployment and build files are read by tools, not by the programs
        others = [(n["name"], x) for n, x in files if n["name"] != a["name"] and not n["name"].lower().endswith((".yaml", ".yml", ".ini", ".toml"))]
        if any(re.search(re.escape(base), x) or re.search(r"\b(yaml|configparser|tomllib|toml)\b", x, re.I) for _, x in others):
            continue
        if not any(re.search(r"environ|getenv", x) for _, x in others):
            continue          # nothing else reads settings either way: not enough to say
        out.append(_obs(f"{base} is not read by any program",
                        f"{base} holds settings but no program given loads it, because none names the file or imports a settings reader and the programs take their settings from "
                        f"environment variables instead, so the values in {base} (limits, minimum lengths, switches) are not applied and people may believe they are.",
                        [(a["name"], 1)], "unread settings", "medium"))
    return out


def conflicts(store):
    out = []
    for fn in (role_names, missing_tables, repeated_secrets, missing_assets, unread_settings):
        try:
            out += fn(store)
        except Exception:  # noqa: BLE001 - one check failing must not hide the others
            continue
    return out
