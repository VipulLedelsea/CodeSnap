"""Parsers for legacy non-procedural artifacts (IMS DBD/PSB/MFS, SSIS, Oracle Forms/Reports, ISPF panels,
Informix forms, Delphi forms, XAML/Silverlight, PowerBuilder DataWindows) and COBOL enrichment for
IDMS and IMS DL/I database access. All deterministic, 0 tokens."""
import re

from core.extractors.common import entity, mask, rel
from core.langs.structure import connection_target, mask_connection

from .engine import SQL_READ, SQL_SKIP, SQL_WRITE

R = re.compile


def _profile(language, pack, family, legacy=None, frameworks=None, techs=None, evidence=None, dialect=None):
    legacy = legacy or {}
    frameworks = frameworks or {}
    return {"language": language, "dialect": dialect, "frameworks": sorted(frameworks), "legacy_markers": sorted(legacy),
            "evidence": {**legacy, **frameworks, **(evidence or {})}, "techs": techs or [], "pack": pack, "family": family}


def _line(text, offset):
    return text.count("\n", 0, max(0, offset)) + 1


def _sql_rels(sql, src, n, out):
    for m in SQL_READ.finditer(sql or ""):
        t = m.group(1).strip("[]\"").upper()
        if t and t not in SQL_SKIP and not t.startswith(":"):
            out.append(rel("reads", src, f"table:{t}", n))
    for m in SQL_WRITE.finditer(sql or ""):
        t = m.group(1).strip("[]\"").upper()
        if t and t not in SQL_SKIP:
            out.append(rel("writes", src, f"table:{t}", n))


def _stem(filename, default):
    return (filename.rsplit("/", 1)[-1].rsplit(".", 1)[0] or default) if filename else default


def _dedupe(relations):
    seen, out = set(), []
    for r in relations:
        k = (r["kind"], r["source"], r["target"], r["line"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def _kw(stmt, key):
    m = re.search(rf"\b{key}\s*=\s*\(?\s*'?([\w#@$]+)", stmt, re.I)
    return m.group(1).upper() if m else None


def _asm_statements(text):
    """Join assembler-style macro statements: continuation = non-blank in column 72 (or trailing comma)."""
    out, buf, start = [], "", None
    for n, raw in enumerate((text or "").splitlines(), 1):
        if raw.startswith("*") or not raw.strip():
            continue
        body = raw[:71].rstrip() if len(raw) > 71 else raw.rstrip()
        cont = len(raw) > 71 and raw[71:72].strip() != ""
        if buf:
            buf += body.strip()
        else:
            buf, start = body, n
        if cont or body.endswith(","):
            continue
        out.append((start, buf))
        buf = ""
    if buf:
        out.append((start, buf))
    return out


# ---------------------------------------------------------------- IMS DBD / PSB / MFS
def looks_ims_dbd(text):
    return bool(re.search(r"^\s*(\S+\s+)?DBD\s+NAME=", text or "", re.M | re.I)) and bool(re.search(r"\bSEGM\s+NAME=", text or "", re.I))


def looks_ims_psb(text):
    return bool(re.search(r"\bPCB\s+TYPE=", text or "", re.I)) and bool(re.search(r"\b(PSBGEN|SENSEG)\b", text or "", re.I))


def looks_ims_mfs(text):
    return len(re.findall(r"\b(FMT|DEV|DIV|DPAGE|DFLD|MSG|MFLD|FMTEND|MSGEND)\b", text or "", re.I)) >= 4 and \
        bool(re.search(r"\bDFLD\b", text or "", re.I))


def parse_ims_dbd(text, filename=""):
    stmts = _asm_statements(text)
    dbd, access, entities, relations = None, None, [], []
    seg, segs = None, {}
    for n, s in stmts:
        op = re.match(r"^(?:\S+)?\s+(\w+)\s+(.*)$", s) or re.match(r"^(\w+)\s+(.*)$", s)
        if not op:
            continue
        verb, args = op.group(1).upper(), op.group(2)
        if verb == "DBD":
            dbd, access = _kw(args, "NAME"), _kw(args, "ACCESS")
            entities.append(entity("data_store", dbd or _stem(filename, "DBD").upper(), None, n, None,
                                   store_type="IMS database", access=access))
        elif verb == "DATASET":
            dd = _kw(args, "DD1")
            if dd:
                relations.append(rel("uses", dbd, f"data_store:{dd}", n, store_type="dataset"))
        elif verb == "SEGM":
            seg = _kw(args, "NAME")
            parent = _kw(args, "PARENT")
            parent = None if parent in (None, "0") else parent
            size = re.search(r"BYTES=\(?(\d+)", args, re.I)
            segs[seg] = entity("table", seg, None, n, n, ims_segment=True, dbd=dbd, bytes=int(size.group(1)) if size else None,
                               parent_segment=parent)
            entities.append(segs[seg])
            relations.append(rel("contains", dbd, f"table:{seg}", n))
            if parent:
                relations.append(rel("depends_on", seg, f"table:{parent}", n, hierarchy="child of"))
        elif verb == "FIELD" and seg:
            name = _kw(args, "NAME")
            if name:
                key = bool(re.search(r"NAME=\(\s*\w+\s*,\s*SEQ", args, re.I))
                ln = re.search(r"BYTES=(\d+)", args, re.I)
                entities.append(entity("column", name, seg, n, n, key=key or None, bytes=int(ln.group(1)) if ln else None,
                                       type=(re.search(r"TYPE=(\w)", args, re.I) or [None, None])[1]))
                segs[seg]["line_end"] = n
        elif verb == "LCHILD":
            tgt = re.search(r"NAME=\(\s*(\w+)\s*,\s*(\w+)", args, re.I)
            if tgt and seg:
                relations.append(rel("depends_on", seg, f"table:{tgt.group(1).upper()}", n, logical=True, dbd=tgt.group(2).upper()))
    if dbd is None:
        return None
    entities[0]["line_end"] = stmts[-1][0] if stmts else 1
    prof = _profile("IMS DBD", "ims_dbd", "asm", legacy={"IMS hierarchical database": [entities[0]["line_start"]]},
                    techs=[{"curated": "ims"}], dialect=f"ACCESS={access}" if access else None)
    return {"entities": entities, "relations": _dedupe(relations), "file_attrs": {"profile": prof}}


def parse_ims_psb(text, filename=""):
    stmts = _asm_statements(text)
    psb = None
    pcbs, relations = [], []
    cur_dbd, procopt = None, "G"
    for n, s in stmts:
        m = re.match(r"^(?:\S+)?\s+(\w+)\s+(.*)$", s)
        if not m:
            continue
        verb, args = m.group(1).upper(), m.group(2)
        if verb == "PCB":
            ptype = _kw(args, "TYPE")
            cur_dbd = _kw(args, "DBDNAME") if ptype == "DB" else None
            procopt = (_kw(args, "PROCOPT") or "G").upper()
            lterm = _kw(args, "LTERM")
            pcbs.append((n, ptype, cur_dbd or lterm, procopt))
        elif verb == "SENSEG" and cur_dbd:
            seg = _kw(args, "NAME")
            po = (_kw(args, "PROCOPT") or procopt).upper()
            if seg:
                relations.append(rel("reads", "PSB", f"table:{seg}", n, procopt=po, dbd=cur_dbd))
                if set(po) & set("IRDA"):
                    relations.append(rel("writes", "PSB", f"table:{seg}", n, procopt=po, dbd=cur_dbd))
        elif verb == "PSBGEN":
            psb = _kw(args, "PSBNAME")
    psb = psb or _stem(filename, "PSB").upper()
    entities = [entity("module", psb, None, 1, stmts[-1][0] if stmts else 1, language="IMS PSB", psb=True)]
    for n, ptype, tgt, po in pcbs:
        if ptype == "DB" and tgt:
            entities.append(entity("data_store", tgt, None, n, n, store_type="IMS database"))
            relations.append(rel("uses", psb, f"data_store:{tgt}", n, procopt=po))
        elif tgt:
            relations.append(rel("uses", psb, f"external_system:{tgt}", n, pcb_type=ptype))
    for r in relations:
        if r["source"] == "PSB":
            r["source"] = psb
    prof = _profile("IMS PSB", "ims_psb", "asm", techs=[{"curated": "ims"}])
    return {"entities": entities, "relations": _dedupe(relations), "file_attrs": {"profile": prof}}


def parse_ims_mfs(text, filename=""):
    stmts = _asm_statements(text)
    entities, relations, screen = [], [], None
    for n, s in stmts:
        m = re.match(r"^(\S+)?\s+(\w+)\b\s*(.*)$", s)
        if not m:
            continue
        label, verb, args = (m.group(1) or "").upper(), m.group(2).upper(), m.group(3)
        if verb == "FMT":
            screen = label or _stem(filename, "MFS").upper()
            entities.append(entity("screen", screen, None, n, None, technology="IMS MFS"))
        elif verb == "DFLD" and screen:
            lit = re.match(r"\s*'([^']*)'", args)
            name = label or (None if lit else args.split(",")[0].strip())
            if name:
                entities.append(entity("ui_element", name, screen, n, n, pos=(re.search(r"POS=\(([\d,]+)\)", args) or [None, None])[1],
                                       length=(re.search(r"LTH=(\d+)", args) or [None, None])[1]))
        elif verb == "MSG":
            relations.append(rel("uses", screen or label, f"transaction:{label}", n, mfs_message=True,
                                 direction=(re.search(r"TYPE=(\w+)", args) or [None, None])[1]))
        elif verb == "FMTEND" and entities:
            entities[0]["line_end"] = n
    if not screen:
        return None
    prof = _profile("IMS MFS", "ims_mfs", "asm", legacy={"IMS MFS 3270 formats": [entities[0]["line_start"]]}, techs=[{"curated": "ims"}])
    return {"entities": entities, "relations": relations, "file_attrs": {"profile": prof}}


# ---------------------------------------------------------------- SSIS .dtsx
def looks_ssis(text):
    return "DTS:Executable" in (text or "") or "www.microsoft.com/SqlServer/Dts" in (text or "")


def _attr(tag, name):
    m = re.search(rf'\b{name}\s*=\s*"([^"]*)"', tag)
    return m.group(1) if m else None


def _unxml(s):
    return (s or "").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&").replace("&#xA;", "\n")


def parse_ssis(text, filename=""):
    pkg = None
    entities, relations = [], []
    for m in re.finditer(r"<DTS:Executable\b[^>]*>", text):
        tag, n = m.group(0), _line(text, m.start())
        name = _attr(tag, "DTS:ObjectName")
        ctype = _attr(tag, "DTS:ExecutableType") or _attr(tag, "DTS:CreationName") or ""
        if pkg is None:
            pkg = name or _stem(filename, "Package")
            fmt = re.search(r'PackageFormatVersion"?\s*[=>]\s*"?(\d+)', text)
            entities.append(entity("job", pkg, None, 1, len(text.splitlines()), tool="SSIS package",
                                   format_version=fmt.group(1) if fmt else None))
            continue
        if name:
            kind = re.sub(r"^(Microsoft\.|SSIS\.)", "", ctype.split(",")[0]).replace("Task", " task")
            entities.append(entity("function", name, pkg, n, n, task_type=kind or None))
    if pkg is None:
        return None
    for m in re.finditer(r"<DTS:ConnectionManager\b[^>]*>", text):
        tag, n = m.group(0), _line(text, m.start())
        name = _attr(tag, "DTS:ObjectName")
        ctype = (_attr(tag, "DTS:CreationName") or "").upper()
        window = text[m.start(): m.start() + 4000]
        cs = re.search(r'DTS:ConnectionString\s*=\s*"([^"]*)"', window)
        conn = _unxml(cs.group(1)) if cs else ""
        target = connection_target(conn) if conn else None
        store = (target or name or "CONNECTION").upper()
        stype = "database" if ctype in ("OLEDB", "ADO.NET", "ODBC", "ADO") or "Catalog" in conn else "file"
        if stype == "file" and conn:
            store = conn.rsplit("\\", 1)[-1].upper()
        entities.append(entity("data_store", store, None, n, n, store_type=stype, connection_manager=name))
        masked, secret = mask("ConnectionString", conn) if re.search(r"Password\s*=", conn, re.I) else (mask_connection(conn), False)
        relations.append(rel("connects_to", pkg, f"data_store:{store}", n, store_type=stype, connection=masked[:200],
                             hardcoded_secret=secret or None))
    for m in re.finditer(r'SQLTask:SqlStatementSource\s*=\s*"([^"]*)"|<SqlCommand[^>]*>([^<]*)<|name="SqlCommand"[^>]*>([^<]*)<',
                         text):
        sql = _unxml(next(g for g in m.groups() if g is not None))
        n = _line(text, m.start())
        owner = next((e["name"] for e in reversed(entities) if e["kind"] == "function" and (e["line_start"] or 0) <= n), pkg)
        _sql_rels(sql, owner, n, relations)
    for m in re.finditer(r'name="OpenRowset"[^>]*>([^<]+)<', text):
        t = m.group(1).replace("[", "").replace("]", "").upper()
        n = _line(text, m.start())
        owner = next((e["name"] for e in reversed(entities) if e["kind"] == "function" and (e["line_start"] or 0) <= n), pkg)
        relations.append(rel("reads", owner, f"table:{t}", n))
    names = {e["name"] for e in entities if e["kind"] == "function"}
    for m in re.finditer(r"<DTS:PrecedenceConstraint\b[^>]*>", text):
        tag, n = m.group(0), _line(text, m.start())
        a = (_attr(tag, "DTS:From") or "").rsplit("\\", 1)[-1]
        b = (_attr(tag, "DTS:To") or "").rsplit("\\", 1)[-1]
        if a in names and b in names:
            relations.append(rel("calls", a, f"function:{b}", n, precedence=True))
    legacy = {}
    if re.search(r"ScriptTask|ScriptComponent", text):
        legacy["Script tasks (embedded C#/VB)"] = [1]
    if re.search(r'DTS:ProtectionLevel="?(0|DontSaveSensitive)"?', text) is None and re.search(r"Password\s*=", text, re.I):
        legacy["Sensitive data saved in package"] = [1]
    fmt = re.search(r'PackageFormatVersion"?\s*[=>]\s*"?(\d+)', text)
    version = {"2": "9.0", "3": "10.0", "6": "11.0", "8": "13.0"}.get(fmt.group(1)) if fmt else None
    year = {"9.0": "2005", "10.0": "2008", "11.0": "2012", "13.0": "2016"}.get(version)
    techs = [{"product": "mssqlserver", "version": version, "label": f"SSIS (SQL Server {year})" if version else "SSIS"}] if version \
        else [{"product": "mssqlserver", "label": "SSIS"}]
    prof = _profile("SSIS package", "ssis", "etl", legacy=legacy, techs=techs, frameworks={"SSIS": [1]})
    return {"entities": entities, "relations": _dedupe(relations), "file_attrs": {"profile": prof}}


# ---------------------------------------------------------------- Oracle Forms / Reports (XML exports)
def looks_oracle_forms(text):
    return bool(re.search(r"<(FormModule|Module)\b[^>]*>|<FormModule\b", text or "")) and "Block" in (text or "")


def looks_oracle_reports(text):
    return bool(re.search(r"<report\b[^>]*DTDVersion|<dataSource\b", text or "", re.I)) and "<select" in (text or "").lower()


def parse_oracle_forms(text, filename=""):
    from .engine import parse_with
    fm = re.search(r'<FormModule\b[^>]*\bName="([^"]+)"', text)
    form = (fm.group(1) if fm else _stem(filename, "FORM")).upper()
    total = len(text.splitlines())
    entities = [entity("screen", form, None, 1, total, technology="Oracle Forms")]
    relations = []
    block = None
    for m in re.finditer(r"<(Block|Item|Trigger|ProgramUnit|LOV|RecordGroup|Canvas)\b([^>]*)>", text):
        tag, attrs, n = m.group(1), m.group(2), _line(text, m.start())
        name = (_attr(attrs, "Name") or "").upper()
        if tag == "Block":
            block = name
            src = _attr(attrs, "QueryDataSourceName") or (name if _attr(attrs, "DatabaseBlock") != "false" else None)
            entities.append(entity("ui_element", name, form, n, n, block=True, data_source=src))
            if src and _attr(attrs, "DatabaseBlock") != "false":
                relations.append(rel("reads", form, f"table:{src.upper()}", n, block=name))
                if _attr(attrs, "InsertAllowed") != "false" or _attr(attrs, "UpdateAllowed") != "false":
                    relations.append(rel("writes", form, f"table:{src.upper()}", n, block=name))
        elif tag == "Item" and name:
            entities.append(entity("ui_element", f"{block}.{name}" if block else name, form, n, n,
                                   item_type=_attr(attrs, "ItemType"), column=_attr(attrs, "ColumnName")))
        elif tag in ("Trigger", "ProgramUnit") and name:
            body = _unxml(_attr(attrs, "TriggerText") or _attr(attrs, "ProgramUnitText") or "")
            unit = f"{block}.{name}" if (block and tag == "Trigger") else name
            entities.append(entity("function", unit, form, n, n, trigger=tag == "Trigger" or None))
            _sql_rels(body, unit, n, relations)
            for c in re.finditer(r"\b(CALL_FORM|OPEN_FORM|NEW_FORM)\s*\(\s*'([\w./]+)'", body, re.I):
                relations.append(rel("navigates_to", unit, f"screen:{c.group(2).upper().rsplit('/', 1)[-1].split('.')[0]}", n))
            for c in re.finditer(r"\bRUN_(?:REPORT_OBJECT|PRODUCT)\s*\(\s*(?:REPORTS\s*,\s*)?'([\w./]+)'", body, re.I):
                relations.append(rel("calls", unit, f"program:{c.group(1).upper().split('.')[0]}", n))
            for c in re.finditer(r"\bHOST\s*\(", body, re.I):
                relations.append(rel("uses", unit, "external_system:OS HOST command", n))
        elif tag == "RecordGroup":
            q = _unxml(_attr(attrs, "RecordGroupQuery") or "")
            _sql_rels(q, form, n, relations)
    legacy = {"Oracle Forms client/server UI": [1]}
    if re.search(r"HOST\s*\(", text, re.I):
        legacy["HOST() operating-system calls"] = [1]
    prof = _profile("Oracle Forms", "oracle_forms", "4gl", legacy=legacy, techs=[{"curated": "oracle-forms"}])
    return {"entities": entities, "relations": _dedupe(relations), "file_attrs": {"profile": prof}}


def parse_oracle_reports(text, filename=""):
    rm = re.search(r'<report\b[^>]*\bname="([^"]+)"', text, re.I)
    name = (rm.group(1) if rm else _stem(filename, "REPORT")).upper()
    entities = [entity("program", name, None, 1, len(text.splitlines()), language="Oracle Reports", report=True)]
    relations = []
    for m in re.finditer(r'<dataSource\b[^>]*name="([^"]+)"[^>]*>.*?<select[^>]*>(.*?)</select>', text, re.S | re.I):
        q, n = _unxml(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(2))), _line(text, m.start())
        entities.append(entity("function", m.group(1).upper(), name, n, _line(text, m.end()), query=True))
        _sql_rels(q, m.group(1).upper(), n, relations)
    prof = _profile("Oracle Reports", "oracle_reports", "report", techs=[{"curated": "oracle-forms", "label": "Oracle Reports"}])
    return {"entities": entities, "relations": _dedupe(relations), "file_attrs": {"profile": prof}}


# ---------------------------------------------------------------- ISPF panels
def looks_ispf_panel(text):
    return len(re.findall(r"^\)(ATTR|BODY|INIT|PROC|MODEL|END)\b", text or "", re.M | re.I)) >= 2


def parse_ispf_panel(text, filename=""):
    name = _stem(filename, "PANEL").upper()
    lines = (text or "").splitlines()
    entities = [entity("screen", name, None, 1, len(lines), technology="ISPF panel")]
    relations, section, attrs = [], None, {}
    seen = set()
    for n, line in enumerate(lines, 1):
        s = re.match(r"^\)(\w+)", line)
        if s:
            section = s.group(1).upper()
            continue
        if section == "ATTR":
            a = re.match(r"^\s*(\S)\s+TYPE\((\w+)\)", line, re.I)
            if a:
                attrs[a.group(1)] = a.group(2).upper()
        elif section in ("BODY", "MODEL"):
            for ch, t in {"_": "INPUT", **attrs}.items():
                if t in ("INPUT", "OUTPUT", "DATAIN", "DATAOUT"):
                    for v in re.findall(re.escape(ch) + r"([A-Z#@$][\w#@$]{0,7})", line, re.I):
                        if v.upper() not in seen:
                            seen.add(v.upper())
                            entities.append(entity("ui_element", v.upper(), name, n, n, io=t.lower()))
        elif section == "PROC":
            for v in re.finditer(r"\bVER\s*\(\s*&(\w+)", line, re.I):
                relations.append(rel("depends_on", name, f"ui_element:{v.group(1).upper()}", n, validation=True))
            for v in re.finditer(r"&ZSEL\s*=\s*TRANS\(.*?\b\d+\s*,\s*'?(?:CMD|PGM|PANEL)\((\w+)", line, re.I):
                relations.append(rel("navigates_to", name, f"program:{v.group(1).upper()}", n))
    prof = _profile("ISPF panel", "ispf_panel", "script", legacy={"ISPF 3270 panel": [1]}, techs=[{"curated": "zos"}])
    return {"entities": entities, "relations": _dedupe(relations), "file_attrs": {"profile": prof}}


# ---------------------------------------------------------------- Informix .per forms
def looks_informix_form(text):
    return bool(re.search(r"^\s*DATABASE\s+\w+", text or "", re.M | re.I)) and bool(re.search(r"^\s*ATTRIBUTES\b", text or "", re.M | re.I))


def parse_informix_form(text, filename=""):
    name = _stem(filename, "FORM").upper()
    lines = (text or "").splitlines()
    entities = [entity("screen", name, None, 1, len(lines), technology="Informix form")]
    relations, section = [], None
    db = re.search(r"^\s*DATABASE\s+(\w+)", text, re.M | re.I)
    if db:
        entities.append(entity("data_store", db.group(1).upper(), None, _line(text, db.start()), None, store_type="database"))
        relations.append(rel("connects_to", name, f"data_store:{db.group(1).upper()}", _line(text, db.start()), store_type="database"))
    for n, line in enumerate(lines, 1):
        s = re.match(r"^\s*(SCREEN|TABLES|ATTRIBUTES|INSTRUCTIONS|END)\b", line, re.I)
        if s:
            section = s.group(1).upper()
        if section == "TABLES":
            for t in re.findall(r"\b([a-z_]\w*)\b", re.sub(r"(?i)^\s*TABLES", "", line)):
                relations.append(rel("reads", name, f"table:{t.upper()}", n))
        elif section == "ATTRIBUTES":
            a = re.match(r"^\s*(\w+)\s*=\s*(\w+)\.(\w+)", line)
            if a:
                entities.append(entity("ui_element", a.group(1), name, n, n, column=f"{a.group(2)}.{a.group(3)}".upper()))
                relations.append(rel("reads", name, f"table:{a.group(2).upper()}", n))
    prof = _profile("Informix form", "informix_form", "4gl", techs=[{"curated": "informix-4gl"}])
    return {"entities": entities, "relations": _dedupe(relations), "file_attrs": {"profile": prof}}


# ---------------------------------------------------------------- Delphi .dfm
def looks_dfm(text):
    return bool(re.match(r"\s*(object|inherited)\s+\w+\s*:\s*T\w+", text or ""))


def parse_dfm(text, filename=""):
    lines = (text or "").splitlines()
    top = re.match(r"\s*(?:object|inherited)\s+(\w+)\s*:\s*(T\w+)", text)
    form = top.group(1)
    entities = [entity("screen", form, None, 1, len(lines), technology="Delphi VCL form", form_class=top.group(2))]
    relations, cur, legacy = [], None, {}
    sql_buf, sql_start = None, None
    for n, line in enumerate(lines, 1):
        o = re.match(r"^\s*(?:object|inherited)\s+(\w+)\s*:\s*(T\w+)", line)
        if o and n > 1:
            cur = o.group(1)
            ctype = o.group(2)
            entities.append(entity("ui_element", cur, form, n, n, control=ctype))
            if ctype in ("TTable", "TQuery", "TDatabase", "TStoredProc"):
                legacy.setdefault("BDE data components", []).append(n)
            continue
        t = re.match(r"^\s*TableName\s*=\s*'([^']+)'", line)
        if t:
            relations.append(rel("reads", form, f"table:{t.group(1).upper()}", n, component=cur))
        d = re.match(r"^\s*(DatabaseName|AliasName|ConnectionString)\s*=\s*'([^']+)'", line)
        if d:
            val = d.group(2)
            target = (connection_target(val) or val).upper()
            entities.append(entity("data_store", target, None, n, n, store_type="database"))
            relations.append(rel("connects_to", form, f"data_store:{target}", n, store_type="database",
                                 connection=mask_connection(val)[:200],
                                 hardcoded_secret=bool(re.search(r"Password\s*=\s*[^;']+", val, re.I)) or None))
        if re.match(r"^\s*SQL\.Strings\s*=\s*\(", line):
            sql_buf, sql_start = [], n
            continue
        if sql_buf is not None:
            sql_buf.append(" ".join(re.findall(r"'([^']*)'", line)))
            if line.rstrip().endswith(")"):
                _sql_rels(" ".join(sql_buf), cur or form, sql_start, relations)
                sql_buf = None
    techs = [{"curated": "delphi-bde"}] if legacy else []
    prof = _profile("Delphi form (.dfm)", "dfm", "4gl", legacy=legacy, techs=techs)
    return {"entities": entities, "relations": _dedupe(relations), "file_attrs": {"profile": prof}}


# ---------------------------------------------------------------- XAML / Silverlight
def looks_xaml(text):
    return "schemas.microsoft.com/winfx/2006/xaml" in (text or "") or "schemas.microsoft.com/client/2007" in (text or "")


def parse_xaml(text, filename=""):
    cls = re.search(r'x:Class="([\w.]+)"', text)
    name = (cls.group(1).rsplit(".", 1)[-1] if cls else _stem(filename, "View"))
    silver = "schemas.microsoft.com/client/2007" in text or bool(re.search(r"System\.Windows\.Controls\.Navigation|RiaServices|"
                                                                            r"<navigation:Page|UserControl[^>]*sdk=", text))
    entities = [entity("screen", name, None, 1, len(text.splitlines()), technology="Silverlight" if silver else "WPF/XAML",
                       code_behind=cls.group(1) if cls else None)]
    relations = []
    for m in re.finditer(r"<(\w+(?::\w+)?)\b[^>]*\bx:Name=\"(\w+)\"", text):
        entities.append(entity("ui_element", m.group(2), name, _line(text, m.start()), _line(text, m.start()), control=m.group(1)))
    for m in re.finditer(r"\{Binding\s+(?:Path=)?([\w.\[\]]+)", text):
        relations.append(rel("depends_on", name, f"field:{m.group(1)}", _line(text, m.start()), binding=True))
    for m in re.finditer(r'(?:NavigateUri|Source)="/?([\w/]+)\.xaml"', text):
        relations.append(rel("navigates_to", name, f"screen:{m.group(1).rsplit('/', 1)[-1]}", _line(text, m.start())))
    if cls:
        relations.append(rel("uses", name, f"class:{cls.group(1)}", 1, code_behind=True))
    legacy = {"Silverlight (browser plug-in)": [1]} if silver else {}
    prof = _profile("XAML", "xaml", "cs", legacy=legacy, techs=[{"curated": "silverlight"}] if silver else [])
    return {"entities": entities, "relations": _dedupe(relations), "file_attrs": {"profile": prof}}


# ---------------------------------------------------------------- PowerBuilder DataWindow .srd
def looks_datawindow(text):
    return bool(re.search(r"^\s*(release\s+\d+;|datawindow\s*\()", text or "", re.M | re.I)) and "table(" in (text or "").lower()


def parse_datawindow(text, filename=""):
    name = _stem(filename, "d_datawindow")
    entities = [entity("screen", name, None, 1, len(text.splitlines()), technology="PowerBuilder DataWindow")]
    relations = []
    for m in re.finditer(r"column=\(type=([\w()]+)[^)]*?name=(\w+)\s+dbname=\"([\w.]+)\"", text, re.I):
        n = _line(text, m.start())
        entities.append(entity("ui_element", m.group(2), name, n, n, type=m.group(1), column=m.group(3).upper()))
        if "." in m.group(3):
            relations.append(rel("reads", name, f"table:{m.group(3).split('.')[0].upper()}", n))
    for m in re.finditer(r'TABLE\(NAME=~?"(\w+)~?"', text, re.I):
        relations.append(rel("reads", name, f"table:{m.group(1).upper()}", _line(text, m.start())))
    for m in re.finditer(r'retrieve="((?:[^"~]|~.)*)"', text, re.I):
        sql = m.group(1).replace('~"', '"')
        if not sql.upper().startswith("PBSELECT"):
            _sql_rels(sql, name, _line(text, m.start()), relations)
    for m in re.finditer(r'update="(\w+)"', text, re.I):
        relations.append(rel("writes", name, f"table:{m.group(1).upper()}", _line(text, m.start())))
    rel_m = re.search(r"release\s+(\d+)", text, re.I)
    prof = _profile("PowerBuilder DataWindow", "datawindow", "4gl", techs=[{"curated": "powerbuilder"}],
                    dialect=f"PowerBuilder release {rel_m.group(1)}" if rel_m else None)
    return {"entities": entities, "relations": _dedupe(relations), "file_attrs": {"profile": prof}}


# ---------------------------------------------------------------- dispatch
SPECIAL = [
    # id, extensions, detector, parser
    ("ims_dbd", ("dbd",), looks_ims_dbd, parse_ims_dbd),
    ("ims_psb", ("psb",), looks_ims_psb, parse_ims_psb),
    ("ims_mfs", ("mfs",), looks_ims_mfs, parse_ims_mfs),
    ("ssis", ("dtsx",), looks_ssis, parse_ssis),
    ("oracle_forms", ("fmb", "fmt", "fmx"), looks_oracle_forms, parse_oracle_forms),
    ("oracle_reports", ("rdf", "rex"), looks_oracle_reports, parse_oracle_reports),
    ("ispf_panel", ("pnl", "panel"), looks_ispf_panel, parse_ispf_panel),
    ("informix_form", ("per",), looks_informix_form, parse_informix_form),
    ("dfm", ("dfm", "xfm"), looks_dfm, parse_dfm),
    ("xaml", ("xaml",), looks_xaml, parse_xaml),
    ("datawindow", ("srd",), looks_datawindow, parse_datawindow),
]
SPECIAL_EXTS = {e for _, exts, _, _ in SPECIAL for e in exts}


def special_for(text, filename=""):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    for sid, exts, looks, fn in SPECIAL:
        if ext in exts:
            return sid, fn
    body = (text or "")[:20000]
    for sid, exts, looks, fn in SPECIAL:
        if sid in ("ispf_panel",) and ext not in ("", "txt"):
            continue
        try:
            if looks(body):
                return sid, fn
        except Exception:
            continue
    return None, None


def parse_special(text, filename=""):
    sid, fn = special_for(text, filename)
    if not fn:
        return None
    try:
        return fn(text, filename)
    except Exception:
        return None


# ---------------------------------------------------------------- COBOL enrichment: IDMS + IMS DL/I
_IDMS_VERB = R(r"\b(OBTAIN|FIND|GET|STORE|MODIFY|ERASE|CONNECT|DISCONNECT)\b\s+(?:(?:CALC|FIRST|LAST|NEXT|PRIOR|OWNER|CURRENT|"
               r"USING|WITHIN|DB-KEY|ANY|DUPLICATE|ALL|PERMANENT|SELECTIVE|MEMBERS?)\s+)*([A-Z][A-Z0-9-]+)", re.I)
_IDMS_MARK = R(r"\b(BIND\s+RUN-UNIT|READY\s+\w|FINISH\b|COPY\s+IDMS|DB-STATUS|ERROR-STATUS|SCHEMA\s+SECTION|SUBSCHEMA|IDMS-STATUS)\b", re.I)
_IDMS_WITHIN = R(r"\bWITHIN\s+([A-Z][A-Z0-9-]+)", re.I)
_DLI_CALL = R(r"CALL\s+'(CBLTDLI|AIBTDLI|PLITDLI|ASMTDLI)'\s+USING\s+([\w-]+)\s*,?\s*([\w-]+)?", re.I)
_EXEC_DLI = R(r"EXEC\s+DLI\s+(GU|GN|GNP|GHU|GHN|GHNP|ISRT|REPL|DLET|SCHD|TERM|CHKP)\b(.*?)(?:END-EXEC|$)", re.I | re.S)
_DLI_FUNC = {"GU": "reads", "GN": "reads", "GNP": "reads", "GHU": "reads", "GHN": "reads", "GHNP": "reads",
             "ISRT": "writes", "REPL": "writes", "DLET": "writes"}
_IDMS_WRITE = {"STORE", "MODIFY", "ERASE", "CONNECT", "DISCONNECT"}


def enrich_cobol(text, structure):
    """Add IDMS / IMS DL/I data access that the COBOL parser does not model. Mutates and returns structure."""
    if not structure or not text:
        return structure
    upper = text.upper()
    idms = bool(_IDMS_MARK.search(upper)) and bool(re.search(r"\b(OBTAIN|BIND\s+RUN-UNIT|DB-STATUS|SUBSCHEMA)\b", upper))
    dli = "CBLTDLI" in upper or "AIBTDLI" in upper or bool(re.search(r"EXEC\s+DLI\b", upper))
    if not (idms or dli):
        return structure
    ents, rels = structure.setdefault("entities", []), structure.setdefault("relations", [])
    units = [e for e in ents if e["kind"] in ("paragraph", "section") and e.get("line_start")]
    program = next((e["name"] for e in ents if e["kind"] == "program"), "PROGRAM")

    def owner(n):
        best = None
        for u in units:
            if u["line_start"] <= n <= (u.get("line_end") or n) and (best is None or u["line_start"] >= best["line_start"]):
                best = u
        return best["name"] if best else program

    lines = text.splitlines()
    legacy, evidence, techs, frameworks = {}, {}, [], {}
    known = {e["name"] for e in ents if e["kind"] == "table"}

    def table(name, n, **attrs):
        if name not in known:
            known.add(name)
            ents.append(entity("table", name, None, n, n, **attrs))

    fmt_seen = set()
    for n, raw in enumerate(lines, 1):
        code = raw[6:72] if len(raw) > 6 and (raw[:6].strip() == "" or raw[:6].strip().isdigit()) else raw
        if code[:1] in ("*", "/"):
            continue
        if idms:
            for m in _IDMS_VERB.finditer(code):
                verb, rec = m.group(1).upper(), m.group(2).upper()
                if rec in ("RECORD", "SET", "AREA", "WITHIN", "USING", "CALC", "DB-KEY", "CURRENT", "OWNER") or rec.endswith("-STATUS"):
                    continue
                if verb == "GET" and not re.search(r"\bGET\s+[A-Z]", code, re.I):
                    continue
                table(rec, n, idms_record=True)
                rels.append(rel("writes" if verb in _IDMS_WRITE else "reads", owner(n), f"table:{rec}", n, dml=verb))
                w = _IDMS_WITHIN.search(code)
                if w:
                    rels.append(rel("depends_on", rec, f"table:{w.group(1).upper()}", n, idms_set=w.group(1).upper()))
            b = re.search(r"\bBIND\s+RUN-UNIT\b|\bSUBSCHEMA-NAME\b|\bSS\s+([A-Z0-9-]+)\s+OF\s+([A-Z0-9-]+)", code, re.I)
            if b:
                evidence.setdefault("IDMS network database (DML)", []).append(n)
        if dli:
            for m in _DLI_CALL.finditer(code):
                func, pcb = (m.group(2) or "").upper(), (m.group(3) or "").upper()
                verb = next((k for k in _DLI_FUNC if func.endswith(k) or func.endswith("-" + k)), None)
                kind = _DLI_FUNC.get(verb or func.replace("DLI-", "").replace("FUNC-", ""), "reads")
                rels.append(rel(kind, owner(n), f"data_store:{pcb or 'IMS-PCB'}", n, dli_call=func, interface=m.group(1).upper(),
                                store_type="IMS database"))
                evidence.setdefault("IMS DL/I calls", []).append(n)
            if re.search(r"EXEC\s+DLI\b", code, re.I):
                evidence.setdefault("IMS DL/I calls", []).append(n)
    if dli:
        for m in _EXEC_DLI.finditer(text):
            func, body = m.group(1).upper(), m.group(2)
            n = _line(text, m.start())
            for seg in re.findall(r"SEGMENT\s*\(\s*([\w-]+)\s*\)", body, re.I):
                table(seg.upper(), n, ims_segment=True)
                rels.append(rel(_DLI_FUNC.get(func, "reads"), owner(n), f"table:{seg.upper()}", n, dli_call=func))
        for m in re.finditer(r"\b01\s+([\w-]*SSA[\w-]*)\b.*?\bVALUE\s+'([A-Z0-9#@$]{1,8})\s*[ (*]", text, re.I | re.S):
            n = _line(text, m.start())
            seg = m.group(2).upper()
            if seg not in fmt_seen:
                fmt_seen.add(seg)
                table(seg, n, ims_segment=True)
    if idms:
        structure["relations"] = rels = [r for r in rels if not (r["kind"] == "includes" and r["target"] in
                                                                  ("copybook:IDMS", "copybook:IDMS-CONTROL"))]
        legacy["IDMS network database (DML)"] = sorted(set(evidence.get("IDMS network database (DML)", [])))[:5] or [1]
        techs.append({"curated": "idms"})
    if dli:
        legacy["IMS DL/I calls"] = sorted(set(evidence.get("IMS DL/I calls", [])))[:5] or [1]
        techs.append({"curated": "ims"})
    fa = structure.setdefault("file_attrs", {})
    prof = fa.setdefault("profile", {"language": "COBOL", "dialect": None, "frameworks": [], "legacy_markers": [], "evidence": {},
                                     "techs": [], "pack": "cobol", "family": "cobol"})
    prof["legacy_markers"] = sorted(set(prof.get("legacy_markers", [])) | set(legacy))
    prof["evidence"] = {**prof.get("evidence", {}), **legacy}
    prof["techs"] = list(prof.get("techs", [])) + techs
    prof["frameworks"] = sorted(set(prof.get("frameworks", [])) | ({"IDMS"} if idms else set()) | ({"IMS DB/DC"} if dli else set()))
    structure["relations"] = _dedupe(rels)
    return structure
