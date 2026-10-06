import re
from pathlib import Path

from .compile import to_fixed_layout
from .detect import detect_format, detect_kind

NAME = r"[A-Z0-9][A-Z0-9-]*"
_DIVISION = re.compile(r"^(IDENTIFICATION|ID|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b", re.I)
_SECTION_HDR = re.compile(rf"^({NAME})\s+SECTION\s*\.?\s*$", re.I)
_PARA_HDR = re.compile(rf"^({NAME})\s*\.\s*$", re.I)
_PROGRAM_ID = re.compile(rf"\bPROGRAM-ID\s*\.?\s*['\"]?({NAME})", re.I)
_COPY = re.compile(rf"\bCOPY\s+['\"]?({NAME})['\"]?", re.I)
_SELECT = re.compile(rf"\bSELECT\s+(?:OPTIONAL\s+)?({NAME})\s+ASSIGN\s+(?:TO\s+)?['\"]?([A-Z0-9#@$.-]+)", re.I)
_FD = re.compile(rf"^(FD|SD)\s+({NAME})", re.I)
_LEVEL = re.compile(rf"^(\d{{1,2}})\s+({NAME})?\s*(.*)$", re.I)
_PIC = re.compile(r"\bPIC(?:TURE)?\s+(?:IS\s+)?(\S+?)\.?(?:\s|$)", re.I)
_PERFORM = re.compile(rf"\bPERFORM\s+({NAME})(?:\s+(?:THRU|THROUGH)\s+({NAME}))?(?:\s+(\S+))?", re.I)
_CALL = re.compile(rf"\bCALL\s+(?:'({NAME})'|\"({NAME})\"|({NAME}))", re.I)
_MOVE_LIT = re.compile(rf"\bMOVE\s+['\"]({NAME})['\"]\s+TO\s+({NAME})", re.I)
_OPEN = re.compile(r"\bOPEN\b(.*)", re.I)
_OPEN_MODE = re.compile(r"\b(INPUT|OUTPUT|I-O|EXTEND)\b", re.I)
_READ = re.compile(rf"\bREAD\s+({NAME})", re.I)
_WRITE = re.compile(rf"\b(WRITE|REWRITE)\s+({NAME})", re.I)
_DELETE = re.compile(rf"\bDELETE\s+({NAME})", re.I)
_EXEC_START = re.compile(r"\bEXEC\s+(CICS|SQL|DLI)\b", re.I)
_END_EXEC = re.compile(r"\bEND-EXEC\b", re.I)
_EXEC_CAP = 50                 # an EXEC block longer than this many lines is treated as unterminated
_SELECT_START = re.compile(r"\bSELECT\s+(?:OPTIONAL\s+)?" + NAME, re.I)


def _collect_exec(lines, i, code, ex, stop, stops=()):
    """Body of the EXEC statement starting on lines[i]. Only newly added lines are searched for END-EXEC; the scan
    stops at the next EXEC, a paragraph/section header (`stops`), the cap or `stop`. Returns (body, last_index, closed)."""
    body, j = code[ex.end():], i
    if _END_EXEC.search(body):
        return body, j, True
    while j + 1 < stop and j - i < _EXEC_CAP:
        if (j + 1) in stops or _EXEC_START.search(lines[j + 1][1]):
            break
        j += 1
        piece = lines[j][1]
        body += " " + piece
        if _END_EXEC.search(piece):
            return body, j, True
    return code[ex.end():], i, False
_OPT_VALUE = r"\s*\(\s*['\"]?(" + NAME + r"(?:\." + NAME + r")*)['\"]?\s*\)"
_NOT_PARAGRAPHS = {"EXIT", "GOBACK", "CONTINUE", "STOP", "END-IF", "END-PERFORM", "END-EVALUATE", "END-READ",
                   "ELSE", "END-EXEC", "END-CALL", "END-WRITE", "END-STRING", "END-SEARCH", "REPLACE", "EJECT",
                   "SKIP1", "SKIP2", "SKIP3"}
_VERBS = ["ACCEPT", "ADD", "CALL", "CLOSE", "COMPUTE", "CONTINUE", "DELETE", "DISPLAY", "DIVIDE", "ELSE", "END-IF",
          "EVALUATE", "EXEC", "EXIT", "GO", "GOBACK", "IF", "INITIALIZE", "INSPECT", "MOVE", "MULTIPLY", "OPEN",
          "PERFORM", "READ", "RETURN", "REWRITE", "SEARCH", "SET", "SORT", "START", "STOP", "STRING", "SUBTRACT",
          "UNSTRING", "WHEN", "WRITE"]
_PERFORM_NOT_TARGET = {"UNTIL", "VARYING", "TEST", "WITH", "FOREVER"}
SQLNAME = r"[A-Z0-9_][A-Z0-9_$#@-]*"
_SQL_READ = re.compile(rf"\b(?:FROM|JOIN)\s+({SQLNAME}(?:\.{SQLNAME})?)", re.I)
_SQL_WRITE = re.compile(rf"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+({SQLNAME}(?:\.{SQLNAME})?)", re.I)
_SQL_INCLUDE = re.compile(rf"^\s*INCLUDE\s+({NAME})\s*$", re.I)
_SQL_CURSOR = re.compile(rf"\bDECLARE\s+({NAME})\s+CURSOR\b", re.I)


def _opt(name: str, body: str) -> str | None:
    m = re.search(r"\b" + name + _OPT_VALUE, body, re.I)
    return m.group(1).upper() if m else None


def logical_lines(text: str) -> list:
    layout = to_fixed_layout(text)
    fixed = detect_format(layout) != "free"
    out = []
    for n, raw in enumerate(layout.splitlines(), 1):
        line = raw.expandtabs(8)
        if fixed:
            indicator = line[6] if len(line) > 6 else " "
            if indicator in "*/":
                continue
            area_a = len(line) > 7 and line[7:11].strip() != ""
            code = line[7:72]
            if indicator == "-" and out:
                prev_n, prev_code, prev_a = out[-1]
                piece = code.lstrip()
                if piece[:1] in "'\"":
                    piece = piece[1:]
                out[-1] = (prev_n, prev_code.rstrip() + piece, prev_a)
                continue
        else:
            if line.lstrip().startswith("*>"):
                continue
            code = line.split("*>")[0]
            area_a = not line[:1].isspace()
        code = code.rstrip()
        if code.strip():
            out.append((n, code, area_a))
    return out


def _entity(kind, name, parent=None, start=None, end=None, **attrs):
    return {"kind": kind, "name": name, "parent": parent, "line_start": start, "line_end": end,
            "attrs": {k: v for k, v in attrs.items() if v not in (None, "", [], {})}}


def _rel(kind, source, target, line, target_kind=None, **attrs):
    return {"kind": kind, "source": source, "target": target, "target_kind": target_kind, "line": line,
            "attrs": {k: v for k, v in attrs.items() if v not in (None, "", [], {})}}


def _data_items(lines, owner, start_index, stop, entities):
    stack = []
    for n, code, _ in lines[start_index:stop]:
        stripped = code.strip()
        if _DIVISION.match(stripped) or _SECTION_HDR.match(stripped) or _FD.match(stripped):
            continue
        m = _LEVEL.match(stripped)
        if not m or not m.group(2):
            continue
        level, name, rest = int(m.group(1)), m.group(2).upper(), m.group(3)
        if name == "FILLER" or level == 66:
            continue
        pic = _PIC.search(rest)
        if level == 88:
            parent = stack[-1][1] if stack else owner
            entities.append(_entity("field", name, parent, n, n, level=88, condition=True))
            continue
        while stack and stack[-1][0] >= level and level != 77:
            stack.pop()
        parent = stack[-1][1] if stack and level != 77 else owner
        entities.append(_entity("field", name, parent, n, n, level=level, picture=pic.group(1) if pic else None))
        if level != 77:
            stack.append((level, name))


def parse_cobol(text: str, filename: str = "") -> dict:
    lines = logical_lines(text)
    entities, relations = [], []
    program = None
    for n, code, _ in lines:
        m = _PROGRAM_ID.search(code)
        if m:
            program = m.group(1).upper()
            break
    program = program or (Path(filename).stem.upper() if filename else "PROGRAM")
    last_line = lines[-1][0] if lines else 1
    entities.append(_entity("program", program, None, lines[0][0] if lines else 1, last_line, language="COBOL"))

    division = None
    proc_index = None
    data_start = None
    for i, (n, code, _) in enumerate(lines):
        d = _DIVISION.match(code.strip())
        if d:
            division = d.group(1).upper()
            if division == "DATA" and data_start is None:
                data_start = i
            if division == "PROCEDURE" and proc_index is None:
                proc_index = i
    proc_index = len(lines) if proc_index is None else proc_index

    files, records = {}, {}
    current_fd = None
    warnings = []
    for i, (n, code, _) in enumerate(lines[:proc_index]):
        stripped = code.strip()
        s = None
        sm = _SELECT_START.search(stripped)
        if sm:
            joined, j = stripped[sm.start():], i
            while not joined.rstrip().endswith(".") and j + 1 < proc_index and j - i < 10:
                nxt = lines[j + 1][1].strip()
                if _SELECT_START.search(nxt) or _FD.match(nxt) or _DIVISION.match(nxt) or _SECTION_HDR.match(nxt):
                    break
                j += 1
                joined += " " + nxt
            s = _SELECT.search(joined)
        if s:
            fname = s.group(1).upper()
            files[fname] = n
            entities.append(_entity("data_store", fname, None, n, n, assign=s.group(2).upper().rstrip("."), store_type="file"))
        fd = _FD.match(stripped)
        if fd:
            current_fd = fd.group(2).upper()
            continue
        if re.match(r"^(WORKING-STORAGE|LOCAL-STORAGE|LINKAGE)\s+SECTION", stripped, re.I):
            current_fd = None
        lv = _LEVEL.match(stripped)
        if current_fd and lv and lv.group(1) == "01" and lv.group(2):
            records[lv.group(2).upper()] = current_fd
        for c in _COPY.finditer(stripped):
            relations.append(_rel("includes", program, f"copybook:{c.group(1).upper()}", n,
                                  section="FD " + current_fd if current_fd else None))
    if data_start is not None:
        _data_items(lines, program, data_start, proc_index, entities)

    names = {}
    current_section = None
    headers = []
    for i in range(proc_index + 1, len(lines)):
        n, code, area_a = lines[i]
        stripped = code.strip()
        sec = _SECTION_HDR.match(stripped)
        par = _PARA_HDR.match(stripped)
        if sec and area_a:
            current_section = sec.group(1).upper()
            headers.append((i, "section", current_section, program))
            names[current_section] = "section"
        elif par and area_a and par.group(1).upper() not in _NOT_PARAGRAPHS:
            name = par.group(1).upper()
            headers.append((i, "paragraph", name, current_section or program))
            names.setdefault(name, "paragraph")
    for idx, (i, kind, name, parent) in enumerate(headers):
        later = [h[0] for h in headers[idx + 1:] if kind == "paragraph" or h[1] == "section"]
        end_i = later[0] - 1 if later else len(lines) - 1
        entities.append(_entity(kind, name, parent, lines[i][0], lines[end_i][0]))

    moved = {}
    open_mode = None
    current = program
    header_at = {i: name for i, _, name, _ in headers}
    i = proc_index + 1
    while i < len(lines):
        n, code, _ = lines[i]
        if i in header_at:
            current = header_at[i]
            i += 1
            continue
        ex = _EXEC_START.search(code)
        if ex:
            start = n
            body, j, closed = _collect_exec(lines, i, code, ex, len(lines), header_at)
            if not closed:
                warnings.append(f"line {n}: EXEC {ex.group(1).upper()} has no END-EXEC; treated as ending on this line")
            body = _END_EXEC.split(body)[0]
            relations += _exec_relations(ex.group(1).upper(), " ".join(body.split()), current, start)
            code = code[:ex.start()]
            i = j
        for m in _MOVE_LIT.finditer(code):
            moved.setdefault(m.group(2).upper(), set()).add(m.group(1).upper())
        for m in _PERFORM.finditer(code):
            target, thru, after = m.group(1).upper(), m.group(2), (m.group(3) or "").upper()
            if target in _PERFORM_NOT_TARGET or target.isdigit() or after.startswith("TIMES"):
                continue
            if target not in names and not re.search(r"\d|-", target):
                continue
            if target not in names:
                target = f"paragraph:{program}.{target}"
            relations.append(_rel("calls", current, target, n, "paragraph", verb="PERFORM",
                                  thru=thru.upper() if thru else None))
        for m in _CALL.finditer(code):
            literal = (m.group(1) or m.group(2) or "").upper()
            if literal:
                relations.append(_rel("calls", current, f"program:{literal}", n, verb="CALL"))
            else:
                var = m.group(3).upper()
                for target in sorted(moved.get(var, ())):
                    relations.append(_rel("calls", current, f"program:{target}", n, verb="CALL", dynamic=var))
                if var not in moved:
                    entities[0]["attrs"].setdefault("dynamic_calls", []).append(var)
        om = _OPEN.search(code)
        continuing = open_mode and re.match(r"^\s*(INPUT|OUTPUT|I-O|EXTEND|" + NAME + r")\b", code, re.I) \
            and not re.match(r"^\s*(" + "|".join(_VERBS) + r")\b", code, re.I)
        if om or continuing:
            mode = None if om else open_mode
            for token in (om.group(1) if om else code).split():
                t = token.upper().rstrip(".")
                if _OPEN_MODE.fullmatch(t):
                    mode = t
                elif mode and t in files:
                    kinds = {"INPUT": ["reads"], "OUTPUT": ["writes"], "EXTEND": ["writes"],
                             "I-O": ["reads", "writes"]}[mode]
                    for k in kinds:
                        relations.append(_rel(k, current, f"data_store:{t}", n, verb="OPEN", mode=mode))
            open_mode = mode or "INPUT"
            if code.rstrip().endswith("."):
                open_mode = None
        else:
            open_mode = None
        for m in _READ.finditer(code):
            if m.group(1).upper() in files:
                relations.append(_rel("reads", current, f"data_store:{m.group(1).upper()}", n, verb="READ"))
        for m in _WRITE.finditer(code):
            record = m.group(2).upper()
            target = records.get(record) or (record if record in files else None)
            if target:
                relations.append(_rel("writes", current, f"data_store:{target}", n, verb=m.group(1).upper(),
                                      record=record if record != target else None))
        for m in _DELETE.finditer(code):
            if m.group(1).upper() in files:
                relations.append(_rel("writes", current, f"data_store:{m.group(1).upper()}", n, verb="DELETE"))
        i += 1

    for i, (n, code, _) in enumerate(lines[:proc_index]):
        ex = _EXEC_START.search(code)
        if ex and ex.group(1).upper() == "SQL":
            body, j, closed = _collect_exec(lines, i, code, ex, proc_index)
            if not closed:
                warnings.append(f"line {n}: EXEC SQL has no END-EXEC; treated as ending on this line")
            body = " ".join(_END_EXEC.split(body)[0].split())
            inc = _SQL_INCLUDE.match(body)
            if inc and inc.group(1).upper() not in ("SQLCA", "SQLDA"):
                relations.append(_rel("includes", program, f"copybook:{inc.group(1).upper()}", n, verb="SQL INCLUDE"))
            elif not inc:
                relations += _exec_relations("SQL", body, program, n)
    result = {"entities": entities, "relations": _dedupe(relations)}
    if warnings:
        result["warnings"] = warnings
        entities[0]["attrs"]["parse_warnings"] = warnings[:20]
    return result


PARSER_VERSION = "cobol-parser-v1"


def _exec_relations(kind: str, body: str, source: str, line: int) -> list:
    out = []
    upper = body.upper()
    if kind == "CICS":
        verb = upper.split()[0] if upper.split() else ""
        program = _opt("PROGRAM", body)
        if verb in ("LINK", "XCTL", "LOAD") and program:
            out.append(_rel("calls", source, f"program:{program}", line, verb=f"CICS {verb}"))
        if verb in ("SEND", "RECEIVE") and re.search(r"\bMAP\b", upper):
            mapname, mapset = _opt("MAP", body), _opt("MAPSET", body)
            if mapname:
                out.append(_rel("displays" if verb == "SEND" else "reads", source, f"screen:{mapname}", line,
                                verb=f"CICS {verb} MAP", mapset=mapset))
        dataset = _opt("FILE", body) or _opt("DATASET", body)
        if dataset and verb in ("READ", "READNEXT", "READPREV", "STARTBR"):
            out.append(_rel("reads", source, f"data_store:{dataset}", line, verb=f"CICS {verb}", store_type="VSAM"))
        if dataset and verb in ("WRITE", "REWRITE", "DELETE"):
            out.append(_rel("writes", source, f"data_store:{dataset}", line, verb=f"CICS {verb}", store_type="VSAM"))
        queue = _opt("QUEUE", body) or _opt("QNAME", body)
        if queue and verb in ("READQ", "WRITEQ", "DELETEQ"):
            out.append(_rel("reads" if verb == "READQ" else "writes", source, f"data_store:{queue}", line,
                            verb=f"CICS {verb}", store_type="queue"))
        transid = _opt("TRANSID", body)
        if transid and verb in ("RETURN", "START"):
            out.append(_rel("invokes_transaction", source, f"transaction:{transid}", line, verb=f"CICS {verb}"))
    elif kind == "SQL":
        writes = {m.group(1).upper() for m in _SQL_WRITE.finditer(body)}
        reads = {m.group(1).upper() for m in _SQL_READ.finditer(body)} - writes
        if upper.startswith("DELETE"):
            reads -= writes
        for table in sorted(reads):
            out.append(_rel("reads", source, f"table:{table}", line, verb="SQL " + upper.split()[0]))
        for table in sorted(writes):
            out.append(_rel("writes", source, f"table:{table}", line, verb="SQL " + upper.split()[0]))
    return out


def _dedupe(relations: list) -> list:
    seen, out = set(), []
    for r in relations:
        key = (r["kind"], r["source"], r["target"], r["line"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def parse_copybook(text: str, filename: str = "") -> dict:
    name = Path(filename).stem.upper() if filename else "COPYBOOK"
    lines = logical_lines(text)
    entities = [_entity("copybook", name, None, lines[0][0] if lines else 1, lines[-1][0] if lines else 1)]
    _data_items(lines, name, 0, len(lines), entities)
    relations = [_rel("includes", name, f"copybook:{c.group(1).upper()}", n)
                 for n, code, _ in lines for c in _COPY.finditer(code)]
    return {"entities": entities, "relations": relations}


_BMS_STMT = re.compile(r"^([A-Z0-9#@$]{1,8})?\s+(DFHMSD|DFHMDI|DFHMDF)\b(.*)$", re.I)


def _bms_statements(text: str) -> list:
    stmts, current = [], None
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.expandtabs(8)
        if not line.strip() or line.startswith("*"):
            continue
        body = line[:71].rstrip()
        continued = len(line) > 71 and line[71] != " "
        if current and current.get("more"):
            current["text"] += body.strip()
            current["end"] = n
        else:
            current = {"start": n, "end": n, "text": body}
            stmts.append(current)
        current["more"] = continued
    return stmts


def parse_bms(text: str, filename: str = "") -> dict:
    entities, relations = [], []
    mapset, screen = None, None
    for stmt in _bms_statements(text):
        m = _BMS_STMT.match(stmt["text"])
        if not m:
            continue
        label, macro, ops = (m.group(1) or "").upper(), m.group(2).upper(), m.group(3)
        if macro == "DFHMSD" and "TYPE=FINAL" not in ops.upper():
            mapset = label or Path(filename).stem.upper()
        elif macro == "DFHMDI" and label:
            screen = label
            size = re.search(r"SIZE=\((\d+),(\d+)\)", ops, re.I)
            entities.append(_entity("screen", label, None, stmt["start"], stmt["end"], map_name=label,
                                    mapset=mapset, size=f"{size.group(1)}x{size.group(2)}" if size else None))
        elif macro == "DFHMDF" and screen:
            pos = re.search(r"POS=\((\d+),(\d+)\)", ops, re.I)
            length = re.search(r"LENGTH=(\d+)", ops, re.I)
            attrb = re.search(r"ATTRB=\(?([A-Z,]+)\)?", ops, re.I)
            initial = re.search(r"INITIAL='([^']*)'", ops, re.I)
            name = label or (f"LABEL@{pos.group(1)},{pos.group(2)}" if pos and initial else None)
            if not name:
                continue
            attrs = (attrb.group(1).upper().split(",") if attrb else [])
            entities.append(_entity("ui_element", name, screen, stmt["start"], stmt["end"],
                                    pos=f"{pos.group(1)},{pos.group(2)}" if pos else None,
                                    length=int(length.group(1)) if length else None,
                                    attributes=attrs, text=initial.group(1) if initial else None,
                                    input="UNPROT" in attrs))
    if mapset and screen is not None:
        for e in entities:
            if e["kind"] == "screen":
                e["attrs"]["mapset"] = mapset
    return {"entities": entities, "relations": relations}


_JCL = re.compile(r"^//([A-Z0-9#@$]*)\s+(JOB|EXEC|DD)\b\s*(.*)$", re.I)


def _operand(text: str) -> str:
    """First blank-delimited (outside quotes) token of a JCL operand field; what follows is a comment."""
    quote = False
    for k, ch in enumerate(text):
        if ch == "'":
            quote = not quote
        elif ch == " " and not quote:
            return text[:k]
    return text


def _jcl_statements(text: str) -> list:
    stmts = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line.startswith("//") or line.startswith("//*"):
            continue
        m = _JCL.match(line[:72])
        if m:
            operand = _operand(m.group(3).strip())
            stmts.append({"line": n, "label": m.group(1).upper(), "op": m.group(2).upper(), "text": operand,
                          "open": operand.endswith(",")})
        elif stmts and stmts[-1].get("open"):
            operand = _operand(line[2:72].strip())
            stmts[-1]["text"] += operand
            stmts[-1]["open"] = operand.endswith(",")
    return stmts


def parse_jcl(text: str, filename: str = "") -> dict:
    entities, relations = [], []
    job = Path(filename).stem.upper() if filename else "JOB"
    step, program = None, None
    stmts = _jcl_statements(text)
    for s in stmts:
        params = s["text"].split(" ")[0]
        if s["op"] == "JOB":
            job = s["label"] or job
            last = stmts[-1]["line"] if stmts else s["line"]
            entities.append(_entity("job", job, None, s["line"], last))
        elif s["op"] == "EXEC":
            step = s["label"] or None
            pgm = re.search(r"\bPGM=([A-Z0-9#@$]+)", params, re.I)
            proc = re.search(r"^(?:PROC=)?([A-Z0-9#@$]+)(?:,|$)", params, re.I)
            program = pgm.group(1).upper() if pgm else None
            if program:
                relations.append(_rel("calls", job, f"program:{program}", s["line"], step=step))
            elif proc:
                relations.append(_rel("calls", job, f"job:{proc.group(1).upper()}", s["line"], step=step,
                                      proc=True))
        elif s["op"] == "DD":
            dsn = re.search(r"\bDSN(?:AME)?=([A-Z0-9#@$.()&+-]+?)(?:,|$)", params, re.I)
            if not dsn:
                continue
            disp = re.search(r"\bDISP=\(?([A-Z]*)", params, re.I)
            mode = (disp.group(1).upper() or "NEW") if disp else "SHR"
            kind = "reads" if mode in ("SHR", "OLD") else "writes"
            relations.append(_rel(kind, job, f"data_store:{dsn.group(1).upper()}", s["line"], step=step,
                                  program=program, ddname=s["label"] or None, disp=mode, store_type="dataset"))
    if not any(e["kind"] == "job" for e in entities):
        entities.insert(0, _entity("job", job, None, 1, stmts[-1]["line"] if stmts else 1))
    return {"entities": entities, "relations": relations}


PARSERS = {"cobol": parse_cobol, "copybook": parse_copybook, "bms": parse_bms, "jcl": parse_jcl}


def parse(text: str, filename: str = "", language: str = "") -> dict | None:
    kind = detect_kind(text, language, Path(filename).suffix if filename else "")
    parser = PARSERS.get(kind)
    return parser(text, filename) if parser else None
