import re

from core.cobol.parser import _SQL_READ, _SQL_WRITE

from .common import clean_ident, entity, line_of, rel

IDENT = r'(?:\[[^\]]+\]|"[^"]+"|`[^`]+`|[A-Za-z_#@$][\w#@$]*)'
QNAME = rf"{IDENT}(?:\s*\.\s*{IDENT}){{0,2}}"
_CREATE_TABLE = re.compile(rf"\bCREATE\s+(?:GLOBAL\s+TEMPORARY\s+|TEMPORARY\s+|TEMP\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?({QNAME})\s*\(", re.I)
_CREATE_VIEW = re.compile(rf"\bCREATE\s+(?:OR\s+(?:REPLACE|ALTER)\s+)?(?:MATERIALIZED\s+)?VIEW\s+({QNAME})(?:\s*\([^)]*\))?\s+AS\b", re.I)
_CREATE_ROUTINE = re.compile(rf"\bCREATE\s+(?:OR\s+(?:REPLACE|ALTER)\s+)?(PROCEDURE|PROC|FUNCTION|TRIGGER)\s+({QNAME})", re.I)
_CREATE_INDEX = re.compile(rf"\bCREATE\s+(UNIQUE\s+)?(?:CLUSTERED\s+|NONCLUSTERED\s+)?INDEX\s+({QNAME})\s+ON\s+({QNAME})\s*\(([^)]*)\)", re.I)
_ALTER_FK = re.compile(rf"\bALTER\s+TABLE\s+({QNAME})\s+ADD\s+(?:CONSTRAINT\s+{IDENT}\s+)?FOREIGN\s+KEY\s*\(([^)]*)\)\s*REFERENCES\s+({QNAME})\s*(?:\(([^)]*)\))?", re.I)
_ALTER_PK = re.compile(rf"\bALTER\s+TABLE\s+({QNAME})\s+ADD\s+(?:CONSTRAINT\s+{IDENT}\s+)?PRIMARY\s+KEY\s*\(([^)]*)\)", re.I)
_TRIGGER_ON = re.compile(rf"\b(?:BEFORE|AFTER|INSTEAD\s+OF|FOR)\b[\w\s,]*?\bON\s+({QNAME})", re.I)
_RESERVED = {"AS", "SET", "WHERE", "VALUES", "SELECT", "FROM", "ON", "OF", "INTO", "TABLE", "BEGIN", "END", "OR",
             "AND", "NEW", "OLD", "EACH", "ROW", "FOR"}
_CONSTRAINT_WORDS = {"CONSTRAINT", "PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "INDEX", "KEY", "PERIOD", "LIKE"}


def _strip_comments(sql: str) -> str:
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "'":
            j = i + 1
            while j < n and not (sql[j] == "'" and (j + 1 >= n or sql[j + 1] != "'")):
                j += 2 if sql[j] == "'" else 1
            out.append(sql[i:j + 1])
            i = j + 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join(ch if ch == "\n" else " " for ch in sql[i:j]))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _balanced(sql: str, start: int) -> tuple:
    depth, i = 0, start
    while i < len(sql):
        c = sql[i]
        if c == "'":
            i = sql.find("'", i + 1)
            if i < 0:
                return sql[start + 1:], len(sql)
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return sql[start + 1:i], i
        i += 1
    return sql[start + 1:], len(sql)


def _split_top(body: str) -> list:
    parts, depth, cur, offs, start = [], 0, [], [], 0
    for i, c in enumerate(body):
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if c == "," and depth == 0:
            parts.append((start, "".join(cur)))
            cur, start = [], i + 1
        else:
            cur.append(c)
    parts.append((start, "".join(cur)))
    return parts


def _tables(rx, body: str) -> set:
    return {t for t in (clean_ident(x.group(1)) for x in rx.finditer(body)) if t and t.split(".")[-1] not in _RESERVED}


def _cols(text: str) -> list:
    return [clean_ident(c).split(".")[-1] for c in text.split(",") if c.strip()]


def _statement_end(sql: str, start: int) -> int:
    m = re.compile(r";|^\s*GO\s*$|^\s*/\s*$|^\s*@\s*$", re.M | re.I).search(sql, start)
    return m.start() if m else len(sql)


def _mask_strings(sql: str) -> str:
    return re.sub(r"'(?:[^']|'')*'", lambda m: "'" + "".join("\n" if c == "\n" else " " for c in m.group(0)[1:-1]) + "'", sql)


def parse_sql(text: str, filename: str = "") -> dict:
    sql = _mask_strings(_strip_comments(text))
    entities, relations = [], []
    tables = {}

    def table_entity(name, line, **attrs):
        tables.setdefault(name, entity("table", name, None, line, line, **attrs))
        return tables[name]

    for m in _CREATE_TABLE.finditer(sql):
        name = clean_ident(m.group(1))
        body, end = _balanced(sql, m.end() - 1)
        line, end_line = line_of(sql, m.start()), line_of(sql, end)
        t = table_entity(name, line, schema_name=name.rsplit(".", 1)[0] if "." in name else None,
                         short_name=name.split(".")[-1])
        t["line_end"] = end_line
        pks = set()
        for offset, part in _split_top(body):
            piece = part.strip()
            if not piece:
                continue
            first = piece.split()[0].upper().strip('[]"`')
            part_line = line_of(sql, m.end() + offset + (len(part) - len(part.lstrip())))
            if first in _CONSTRAINT_WORDS:
                pk = re.search(r"PRIMARY\s+KEY\s*\(([^)]*)\)", piece, re.I)
                if pk:
                    pks |= set(_cols(pk.group(1)))
                fk = re.search(rf"FOREIGN\s+KEY\s*\(([^)]*)\)\s*REFERENCES\s+({QNAME})\s*(?:\(([^)]*)\))?", piece, re.I)
                if fk:
                    relations.append(rel("depends_on", name, f"table:{clean_ident(fk.group(2))}", part_line,
                                         foreign_key=_cols(fk.group(1)), references=_cols(fk.group(3) or "")))
                continue
            cm = re.match(rf"({IDENT})\s+(.*)$", piece, re.S)
            if not cm:
                continue
            col = clean_ident(cm.group(1)).split(".")[-1]
            rest = " ".join(cm.group(2).split())
            ctype = re.match(r"([A-Za-z_][\w ]*?(?:\([^)]*\))?)(?=\s|$)", rest)
            ctype = ctype.group(1).upper() if ctype else rest.split(" ")[0].upper()
            ctype = re.sub(r"\s+(NOT|NULL|DEFAULT|PRIMARY|REFERENCES|CONSTRAINT|WITH|GENERATED|IDENTITY|UNIQUE|CHECK|FOR)\b.*$", "", ctype)
            upper = rest.upper()
            is_pk = "PRIMARY KEY" in upper
            if is_pk:
                pks.add(col)
            entities.append(entity("column", col, name, part_line, part_line, type=ctype,
                                   nullable=False if ("NOT NULL" in upper or is_pk) else True,
                                   primary_key=is_pk or None))
            ref = re.search(rf"REFERENCES\s+({QNAME})\s*(?:\(([^)]*)\))?", rest, re.I)
            if ref:
                relations.append(rel("depends_on", name, f"table:{clean_ident(ref.group(1))}", part_line,
                                     foreign_key=[col], references=_cols(ref.group(2) or "")))
        for e in entities:
            if e["kind"] == "column" and e["parent"] == name and e["name"] in pks:
                e["attrs"]["primary_key"] = True
                e["attrs"]["nullable"] = False

    for m in _CREATE_VIEW.finditer(sql):
        name = clean_ident(m.group(1))
        end = _statement_end(sql, m.end())
        body = sql[m.end():end]
        line = line_of(sql, m.start())
        t = table_entity(name, line, view=True, short_name=name.split(".")[-1])
        t["attrs"]["view"] = True
        t["line_end"] = line_of(sql, end)
        for r in sorted(_tables(_SQL_READ, body)):
            relations.append(rel("reads", name, f"table:{r}", line, verb="VIEW"))

    for m in _CREATE_ROUTINE.finditer(sql):
        kind_word = m.group(1).upper()
        name = clean_ident(m.group(2))
        line = line_of(sql, m.start())
        nxt = _CREATE_ROUTINE.search(sql, m.end())
        body = sql[m.end():nxt.start() if nxt else len(sql)]
        routine = {"PROC": "PROCEDURE"}.get(kind_word, kind_word)
        entities.append(entity("function", name, None, line, line_of(sql, m.end() + len(body.rstrip())),
                               sql_object=routine.lower()))
        if routine == "TRIGGER":
            on = re.match(rf"\s*ON\s+({QNAME})", body, re.I) or _TRIGGER_ON.search(body[:400])
            if on:
                relations.append(rel("depends_on", name, f"table:{clean_ident(on.group(1))}", line, trigger_on=True))
        if routine == "TRIGGER":
            header = re.search(r"\b(AS|BEGIN)\b", body, re.I)
            body = body[header.end():] if header else body
        writes = _tables(_SQL_WRITE, body)
        reads = _tables(_SQL_READ, body) - writes
        for t in sorted(reads):
            relations.append(rel("reads", name, f"table:{t}", line, verb=routine))
        for t in sorted(writes):
            relations.append(rel("writes", name, f"table:{t}", line, verb=routine))
        for call in re.finditer(rf"\b(?:EXEC(?:UTE)?|CALL)\s+(?!IMMEDIATE\b)({QNAME})(?![\w\]`])(?!\s*\.\.)", body, re.I):
            target = clean_ident(call.group(1))
            if target not in ("SQL", "IMMEDIATE"):
                relations.append(rel("calls", name, f"function:{target}", line_of(sql, m.end() + call.start())))

    for m in _CREATE_INDEX.finditer(sql):
        tname = clean_ident(m.group(3))
        t = table_entity(tname, line_of(sql, m.start()))
        t["attrs"].setdefault("indexes", []).append({"name": clean_ident(m.group(2)), "columns": _cols(m.group(4)),
                                                     "unique": bool(m.group(1))})
    for m in _ALTER_FK.finditer(sql):
        relations.append(rel("depends_on", clean_ident(m.group(1)), f"table:{clean_ident(m.group(3))}",
                             line_of(sql, m.start()), foreign_key=_cols(m.group(2)), references=_cols(m.group(4) or "")))
        table_entity(clean_ident(m.group(1)), line_of(sql, m.start()))
    for m in _ALTER_PK.finditer(sql):
        tname = clean_ident(m.group(1))
        for e in entities:
            if e["kind"] == "column" and e["parent"] == tname and e["name"] in _cols(m.group(2)):
                e["attrs"]["primary_key"] = True

    if not tables and not any(e["kind"] == "function" for e in entities):
        stmts_line = 1
        writes = _tables(_SQL_WRITE, sql)
        reads = _tables(_SQL_READ, sql) - writes
        script = (filename or "script.sql").rsplit("/", 1)[-1]
        entities.append(entity("job", script, None, 1, line_of(sql, len(sql)), tool="SQL script"))
        for t in sorted(reads):
            relations.append(rel("reads", script, f"table:{t}", stmts_line))
        for t in sorted(writes):
            relations.append(rel("writes", script, f"table:{t}", stmts_line))
    return {"entities": list(tables.values()) + entities, "relations": relations}


def looks_like_sql(text: str) -> bool:
    body = _strip_comments(text or "")
    return bool(re.search(r"\bCREATE\s+(TABLE|VIEW|INDEX|PROCEDURE|PROC|FUNCTION|TRIGGER)\b|\bALTER\s+TABLE\b", body, re.I)) or \
        len(re.findall(r"^\s*(SELECT|INSERT|UPDATE|DELETE|MERGE)\b", body, re.I | re.M)) >= 2
