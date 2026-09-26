import re

from core.extractors.common import entity, mask, rel
from core.langs.structure import connection_target, mask_connection
from core.security.rules import SQL_WORDS

SQL_READ = re.compile(r"\b(?:FROM|JOIN)\s+([A-Z_#@$\[][\w#@$\].]*)", re.I)
SQL_WRITE = re.compile(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|MERGE\s+INTO|TRUNCATE\s+TABLE)\s+([A-Z_#@$\[][\w#@$\].]*)", re.I)
SQL_SKIP = {"DUAL", "SYSIBM.SYSDUMMY1", "SELECT", "WHERE", "SET", "VALUES", "TABLE", "(", "LATERAL", "UNNEST"}
CONN = re.compile(r"(Data Source|Server|Initial Catalog|Database|Provider|DSN|Driver|Uid|User ID)\s*=|jdbc:[a-z0-9]+:", re.I)


def blank_comments(text, pack):
    lines = (text or "").splitlines()
    out, block = [], False
    bstart, bend = pack.get("block_comment") or (None, None)
    quotes = pack.get("quotes", "\"'")
    line_tokens = pack.get("line_comment") or []
    fixed = pack.get("fixed_comment")
    for raw in lines:
        if fixed and fixed(raw):
            out.append("")
            continue
        buf, i, q = [], 0, None
        while i < len(raw):
            ch = raw[i]
            if block:
                if bend and raw.startswith(bend, i):
                    block = False
                    buf.append(" " * len(bend))
                    i += len(bend)
                else:
                    buf.append(" ")
                    i += 1
                continue
            if q:
                buf.append(ch)
                if ch == q:
                    q = None
                i += 1
                continue
            if ch in quotes:
                q = ch
                buf.append(ch)
                i += 1
                continue
            if bstart and raw.startswith(bstart, i):
                block = True
                buf.append(" " * len(bstart))
                i += len(bstart)
                continue
            hit = False
            for tok in line_tokens:
                if (isinstance(tok, str) and raw.startswith(tok, i)) or (not isinstance(tok, str) and tok.match(raw, i)):
                    hit = True
                    break
            if hit:
                break
            buf.append(ch)
            i += 1
        out.append("".join(buf))
    return out


def _unit_end(lines, start, pack, unit_kind):
    ends = pack.get("unit_end")
    if not ends:
        return None
    rx = ends.get(unit_kind) if isinstance(ends, dict) else ends
    if rx is None:
        return None
    for j in range(start, len(lines)):
        if rx.search(lines[j]):
            return j + 1
    return None


def parse_with(pack, text: str, filename: str = "") -> dict:
    flags = re.I if pack.get("ci", True) else 0
    lines = blank_comments(text, pack)
    raw = (text or "").splitlines()
    stem = (filename.rsplit("/", 1)[-1].rsplit(".", 1)[0] or pack["id"]).upper() if pack.get("upper_names") else \
        (filename.rsplit("/", 1)[-1].rsplit(".", 1)[0] or pack["id"])
    container_kind = pack.get("container", "program")
    container = stem
    for rx in pack.get("container_name") or []:
        m = next((re.search(rx, l, flags) for l in lines if re.search(rx, l, flags)), None)
        if m:
            container = m.group("name").strip("'\"")
            break
    entities = [entity(container_kind, container, None, 1, len(raw), language=pack["label"])]
    relations, seen_ent = [], {(container_kind, container)}
    units = []
    for n, line in enumerate(lines, 1):
        for kind, rx in pack.get("units", []):
            m = re.search(rx, line, flags)
            if m and m.group("name"):
                name = m.group("name").strip()
                if pack.get("upper_names"):
                    name = name.upper()
                if (kind, name) in seen_ent:
                    continue
                seen_ent.add((kind, name))
                end = _unit_end(lines, n, pack, kind)
                units.append({"kind": kind, "name": name, "start": n, "end": end})
                break
    for i, u in enumerate(units):
        if u["end"] is None:
            nxt = next((v["start"] - 1 for v in units[i + 1:] if v["kind"] == u["kind"] or v["kind"] in ("function", "class")), None)
            u["end"] = nxt or len(raw)
        entities.append(entity(u["kind"], u["name"], container, u["start"], u["end"]))

    def owner(n):
        best = None
        for u in units:
            if u["start"] <= n <= (u["end"] or len(raw)):
                if best is None or u["start"] >= best["start"]:
                    best = u
        return best["name"] if best else container

    fields = 0
    for n, line in enumerate(lines, 1):
        src = owner(n)
        for kind, rx, tkind in pack.get("calls", []):
            for m in re.finditer(rx, line, flags):
                t = (m.groupdict().get("target") or "").strip("'\" ")
                member = re.match(r"^[\w.#@$]+\(([\w#@$]+)\)\)?$", t)
                t = member.group(1) if member else t.strip("() ")
                if pack.get("upper_names"):
                    t = t.upper()
                if t and t.upper() not in {"IF", "WHILE", "FOR", "SELECT", "RETURN", "NOT", "AND", "OR"}:
                    relations.append(rel(kind, src, f"{tkind}:{t}" if tkind else t, n))
        for rx, tkind in pack.get("includes", []):
            for m in re.finditer(rx, line, flags):
                t = (m.group("target") or "").strip("'\"<>() ;")
                if t:
                    relations.append(rel("includes", container, f"{tkind}:{t}", n))
        for kind, rx, store_type in pack.get("files", []):
            for m in re.finditer(rx, line, flags):
                t = (m.group("target") or "").strip("'\"() ;")
                if t:
                    tgt = f"data_store:{t.upper() if pack.get('upper_names') else t}"
                    if ("data_store", tgt) not in seen_ent:
                        seen_ent.add(("data_store", tgt))
                        entities.append(entity("data_store", tgt.split(":", 1)[1], None, n, n, store_type=store_type))
                    relations.append(rel(kind, src, tgt, n, store_type=store_type))
        for rx in pack.get("screens", []):
            for m in re.finditer(rx, line, flags):
                t = (m.groupdict().get("target") or "").strip("'\" ")
                member = re.match(r"^[\w.#@$]+\(([\w#@$]+)\)\)?$", t)
                t = member.group(1) if member else t.strip("() ")
                if pack.get("upper_names"):
                    t = t.upper()
                if t:
                    relations.append(rel("displays", src, f"screen:{t}", n))
        for rx in pack.get("fields", []):
            m = re.search(rx, line, flags)
            if m and fields < 200:
                fields += 1
                entities.append(entity("field", m.group("name"), src if src != container else container, n, n,
                                       type=(m.groupdict().get("type") or None)))
    sql_text = []
    for rx in pack.get("sql_blocks", []):
        joined = "\n".join(lines)
        for m in re.finditer(rx, joined, flags | re.S):
            n = joined.count("\n", 0, m.start()) + 1
            sql_text.append((n, m.group("sql")))
    for n, line in enumerate(raw, 1):
        if not lines[n - 1].strip():
            continue
        for lit in re.findall(r'"((?:[^"\\]|\\.){6,})"' + ("|'((?:[^'\\\\]|\\\\.){6,})'" if pack.get("single_quote_strings", True) else ""), line):
            s = lit if isinstance(lit, str) else next((x for x in lit if x), "")
            if SQL_WORDS.search(s):
                sql_text.append((n, s))
            if CONN.search(s):
                target = connection_target(s)
                if target:
                    tgt = f"data_store:{target.upper()}"
                    if ("data_store", tgt) not in seen_ent:
                        seen_ent.add(("data_store", tgt))
                        entities.append(entity("data_store", target.upper(), None, n, n, store_type="database"))
                    secret = bool(re.search(r"(Password|Pwd)\s*=\s*[^;\"'\s]+", s, re.I))
                    relations.append(rel("connects_to", owner(n), tgt, n, store_type="database",
                                         connection=mask_connection(s)[:200], hardcoded_secret=secret or None))
    if pack.get("sql_lines"):
        for n, line in enumerate(lines, 1):
            if re.search(pack["sql_lines"], line, flags):
                sql_text.append((n, line))
    for n, s in sql_text:
        src = owner(n)
        for m in SQL_READ.finditer(s):
            t = m.group(1).strip("[]").upper()
            if t and t not in SQL_SKIP and not t.startswith(":"):
                relations.append(rel("reads", src, f"table:{t}", n))
        for m in SQL_WRITE.finditer(s):
            t = m.group(1).strip("[]").upper()
            if t and t not in SQL_SKIP:
                relations.append(rel("writes", src, f"table:{t}", n))
    text_all = "\n".join(lines)
    legacy = {}
    for label, rx in pack.get("legacy", []):
        hits = [n for n, l in enumerate(lines, 1) if re.search(rx, l, flags)]
        if hits:
            legacy[label] = hits[:5]
    frameworks = {}
    for label, rx in pack.get("frameworks", []):
        hits = [n for n, l in enumerate(lines, 1) if re.search(rx, l, flags)]
        if hits:
            frameworks[label] = hits[:5]
    techs = []
    for t in pack.get("techs", []):
        cond = t.get("when")
        if cond is None or re.search(cond, text_all, flags):
            techs.append({k: v for k, v in t.items() if k != "when"})
    dialect = next((label for label, rx in pack.get("dialects", []) if re.search(rx, text_all, flags)), None)
    uniq, seen = [], set()
    for r in relations:
        k = (r["kind"], r["source"], r["target"], r["line"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    profile = {"language": pack["label"], "dialect": dialect, "frameworks": sorted(frameworks),
               "legacy_markers": sorted(legacy), "evidence": {**legacy, **frameworks}, "techs": techs,
               "pack": pack["id"], "family": pack.get("family", pack["id"])}
    return {"entities": entities, "relations": uniq, "file_attrs": {"profile": profile}}


def block_check(pack, text: str) -> tuple:
    pairs = pack.get("blocks") or []
    if not pairs:
        return True, "", "codesnap-structure"
    lines = blank_comments(text, pack)
    flags = re.I if pack.get("ci", True) else 0
    problems = []
    for open_rx, close_rx, label in pairs:
        stack = []
        for n, line in enumerate(lines, 1):
            opens = len(re.findall(open_rx, line, flags))
            closes = len(re.findall(close_rx, line, flags))
            for _ in range(opens):
                stack.append(n)
            for _ in range(closes):
                if stack:
                    stack.pop()
                else:
                    problems.append(f"line {n}: {label} closed without being opened")
        for n in stack[:3]:
            problems.append(f"line {n}: {label} opened but never closed")
    return (not problems), "\n".join(problems[:10]), "codesnap-structure"
