"""Taint tracing by rule, no model call: follow data from where it enters (a request, a form field, the server's response in a page) through
assignments and string building to where it does harm (a SQL statement, a file path, a command, the page as HTML). It reads one function at
a time; a function that passes its own parameter to such a place is remembered, so a call elsewhere that hands it request data is found too.
Applies to Python, JavaScript/TypeScript, PHP, Java and C#; any other family is left alone."""
import re

_SOURCES = {
    "python": r"request\.(?:args|form|json|values|data|files|cookies|headers|get_json|GET|POST|FILES|COOKIES|META)\b|\binput\s*\(|sys\.argv|self\.request\b",
    "js": r"\breq\.(?:query|body|params|headers|cookies)\b|\blocation\.(?:search|hash|href)\b|document\.(?:cookie|referrer|URL)\b|window\.name\b|"
          r"\.json\s*\(\s*\)|\.value\b|localStorage\.getItem|\bprompt\s*\(",
    "php": r"\$_(?:GET|POST|REQUEST|COOKIE|FILES|SERVER)\b",
    "java": r"\.getParameter\s*\(|\.getHeader\s*\(|\.getQueryString\s*\(|\.getCookies\s*\(|@RequestParam|@PathVariable|@RequestBody",
    "cs": r"Request\.(?:QueryString|Form|Params|Cookies|Headers)\b|\[From(?:Body|Query|Route)\]|Request\[",
}
_SANITIZER = re.compile(r"\b(?:int|float|bool|len|str\.isdigit|parseInt|parseFloat|Number|escape|html\.escape|escapeHtml|encodeURIComponent|encodeURI|quote|"
                        r"secure_filename|basename|os\.path\.basename|Path\(\w+\)\.name|htmlspecialchars|htmlentities|intval|floatval|Integer\.parseInt|"
                        r"Long\.parseLong|int\.Parse|Convert\.To\w+|HttpUtility\.\w*Encode|DOMPurify\.sanitize|bleach\.clean)\s*\(")
_ASSIGN = re.compile(r"^\s*(?:(?:const|let|var|final|auto)\s+)?(?:[A-Z]\w*(?:<[^>]*>)?(?:\[\])?\s+|string\s+|int\s+|long\s+)?([A-Za-z_$][\w$]*)\s*(\+|\.)?=(?!=)\s*(.+)$")
_PY_DEF = re.compile(r"^(\s*)(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)")
_JS_DEF = re.compile(r"(?:function\s+(\w+)\s*\(([^)]*)\)|(?:^|\s)(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:function\s*)?\(([^)]*)\)\s*(?:=>)?\s*\{)")
_BRACE_DEF = re.compile(r"^\s*(?:public|private|protected|static|final|async|override|virtual)[\w\s<>\[\],.?]*?\b(\w+)\s*\(([^)]*)\)\s*(?:throws[\w\s,.]+)?\{?\s*$")
_ROUTE = re.compile(r"@\w+(?:\.\w+)*\.(?:route|get|post|put|delete|patch)\(\s*[\"']([^\"']*)[\"']")
_ROUTE_PARAM = re.compile(r"<(?:\w+:)?(\w+)>")
_LOOP = re.compile(r"(?:for\s*\(?\s*(?:const|let|var)?\s*(\w+)\s+(?:of|in)\s+(\w+)|(\w+)\.(?:forEach|map|filter|flatMap)\(\s*(?:function\s*)?\(?\s*(\w+)|for\s+(\w+)\s+in\s+(\w+))")

# (rule, severity, description, regex that finds the call, how its first argument is checked)
_SINKS = {
    "python": [
        ("SEC-SQLI", "high", "request input reaches a SQL statement built by joining text", r"\.(?:execute|executemany|executescript|raw)\s*\(", "first"),
        ("SEC-PATH", "high", "request input decides which file is opened, saved or sent", r"\b(?:open|send_file|send_from_directory|remove|unlink|rmtree)\s*\(|\.save\s*\(", "any"),
        ("SEC-CMD", "high", "request input reaches an operating-system command", r"\bos\.(?:system|popen)\s*\(|\bsubprocess\.\w+\s*\(|\bexec\s*\(|\beval\s*\(", "any"),
        ("SEC-XSS", "high", "request input is written into a page as HTML without escaping", r"\brender_template_string\s*\(|\bMarkup\s*\(|\bHttpResponse\s*\(|\bmark_safe\s*\(", "any"),
    ],
    "js": [
        ("SEC-SQLI", "high", "input reaches a SQL statement built by joining text", r"\.(?:query|execute|raw|run|all|get)\s*\(", "first"),
        ("SEC-PATH", "high", "input decides which file is opened or sent", r"\b(?:readFile|readFileSync|createReadStream|writeFile|writeFileSync|sendFile|unlink|unlinkSync)\s*\(", "any"),
        ("SEC-CMD", "high", "input reaches an operating-system command", r"\b(?:exec|execSync|spawn|eval)\s*\(|new\s+Function\s*\(", "any"),
        ("SEC-XSS", "high", "data from the request or the server's response is written into the page as HTML without escaping",
         r"\.(?:innerHTML|outerHTML)\s*\+?=|\bdocument\.write(?:ln)?\s*\(|\.insertAdjacentHTML\s*\(|\.html\s*\(", "any"),
    ],
    "php": [
        ("SEC-SQLI", "high", "request input reaches a SQL statement built by joining text", r"\b(?:mysql_query|mysqli_query|pg_query)\s*\(|->(?:query|exec)\s*\(", "any"),
        ("SEC-PATH", "high", "request input decides which file is opened or included", r"\b(?:fopen|file_get_contents|include|require|include_once|require_once|unlink|readfile)\b", "any"),
        ("SEC-CMD", "high", "request input reaches an operating-system command", r"\b(?:system|exec|shell_exec|passthru|popen|proc_open|eval)\s*\(", "any"),
        ("SEC-XSS", "high", "request input is written into the page as HTML without escaping", r"\b(?:echo|print)\b", "any"),
    ],
    "java": [
        ("SEC-SQLI", "high", "request input reaches a SQL statement built by joining text", r"\.(?:executeQuery|executeUpdate|execute|createQuery|createNativeQuery)\s*\(", "first"),
        ("SEC-PATH", "high", "request input decides which file is opened", r"new\s+(?:File|FileInputStream|FileOutputStream|FileReader|FileWriter)\s*\(|Paths\.get\s*\(", "any"),
        ("SEC-CMD", "high", "request input reaches an operating-system command", r"Runtime\.getRuntime\(\)\.exec\s*\(|new\s+ProcessBuilder\s*\(", "any"),
        ("SEC-XSS", "high", "request input is written into the response as HTML without encoding", r"\.(?:print|println|write)\s*\(", "any"),
    ],
    "cs": [
        ("SEC-SQLI", "high", "request input reaches a SQL statement built by joining text", r"new\s+Sql(?:Command|DataAdapter)\s*\(|\.(?:ExecuteReader|ExecuteNonQuery|ExecuteScalar|FromSqlRaw)\s*\(", "first"),
        ("SEC-PATH", "high", "request input decides which file is opened", r"File\.(?:Open|ReadAll\w+|WriteAll\w+|Delete)\s*\(|new\s+FileStream\s*\(|Server\.MapPath\s*\(", "any"),
        ("SEC-CMD", "high", "request input reaches an operating-system command", r"Process\.Start\s*\(", "any"),
        ("SEC-XSS", "high", "request input is written into the page as HTML without encoding", r"Response\.Write\s*\(|new\s+HtmlString\s*\(|Html\.Raw\s*\(", "any"),
    ],
}


def _family(fam):
    return {"python": "python", "js": "js", "typescript": "js", "php": "php", "java": "java", "cs": "cs"}.get(fam)


def _strip(line):
    out, q = [], None
    for ch in line:
        if q:
            out.append(ch)
            if ch == q:
                q = None
        elif ch in "\"'`":
            q = ch
            out.append(ch)
        elif ch == "#" or (out and out[-1] == "/" and ch == "/"):
            if ch == "/":
                out.pop()
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _first_arg(line, m):
    """The text of a call's first argument: from just after the '(' to the first top-level comma or the closing bracket."""
    i = m.end()
    depth, q, buf = 1, None, []
    while i < len(line):
        ch = line[i]
        if q:
            buf.append(ch)
            if ch == q:
                q = None
        elif ch in "\"'`":
            q = ch
            buf.append(ch)
        elif ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                break
            buf.append(ch)
        elif ch == "," and depth == 1:
            break
        else:
            buf.append(ch)
        i += 1
    return "".join(buf)


_LITERAL = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`")


def _code_only(expr):
    """The expression with string contents removed (words inside a SQL string are not variables), keeping what sits in {braces} / ${braces}."""
    return _LITERAL.sub(lambda m: " " + " ".join(re.findall(r"\{([^}]*)\}", m.group(0))) + " ", expr)


def _names_in(expr, labels):
    expr = _code_only(expr)
    found = set()
    for name, lab in labels.items():
        if lab and re.search(rf"(?<![\w$.]){re.escape(name)}(?![\w$])", expr):
            found |= lab
    return found


def _logical_lines(text):
    """(first line number, text) with a statement that continues on the next line (it ends in =, +, (, a comma or an operator) joined up."""
    raw = text.splitlines()
    i = 0
    while i < len(raw):
        if len(raw[i]) > 1500:         # minified or hostile: not worth tracing, and must never be slow
            i += 1
            continue
        n, cur = i + 1, _strip(raw[i])
        while i + 1 < len(raw) and re.search(r"(?:[=+(,&|]|&&|\|\|)\s*$", cur) and not re.match(r"\s*(?:def|function)\b", cur) and len(cur) < 600:
            i += 1
            cur = cur + " " + _strip(raw[i]).strip()
        yield n, cur
        i += 1


_PROPAGATORS = {"join", "format", "replace", "strip", "lstrip", "rstrip", "lower", "upper", "title", "str", "encode", "decode", "get", "getlist", "pop",
                "split", "concat", "substring", "slice", "trim", "tostring", "cstr", "string", "toLowerCase", "toUpperCase", "append", "add", "json", "text",
                "read", "load", "loads", "get_json"}


def _taints_result(rhs, src_rx):
    """A call to some other function does not hand its argument's taint to its result (reports.export_csv(request.args...) returns a path it
    chose); string building, formatting and the source calls themselves do."""
    m = re.match(r"\s*(?:await\s+|new\s+)?([\w.$]+)\s*\(", rhs)
    if not m or src_rx.search(m.group(0)):
        return True
    if re.search(r"(?<![\w$])[\"'`]|\+|%|\bf[\"']|\$\{", rhs.split("(", 1)[0]):
        return True
    return m.group(1).split(".")[-1].lower() in {x.lower() for x in _PROPAGATORS}


def analyse(text, fam):
    """-> (flows, summaries). flows: [(rule, severity, line, description)]. summaries: {function name: {param index: rule}}."""
    fam = _family(fam)
    if not fam or len(text) > 600_000:
        return [], {}
    src_rx = re.compile(_SOURCES[fam])
    sinks = [(r, s, d, re.compile(rx), mode) for r, s, d, rx, mode in _SINKS[fam]]
    flows, summaries = [], {}
    labels, func, params, route_params = {}, None, [], set()
    py_indent = None

    def begin(name, plist, tainted=()):
        nonlocal labels, func, params
        func = name
        params = [p.strip().split("=")[0].split(":")[0].strip().lstrip("*") for p in plist.split(",") if p.strip()]
        labels = {p: ({"SRC"} if p in tainted else {f"P:{i}"}) for i, p in enumerate(params) if re.match(r"^[A-Za-z_$][\w$]*$", p)}

    pending_route = set()
    for n, line in _logical_lines(text):
        if not line.strip():
            continue
        if fam == "python":
            rm = _ROUTE.search(line)
            if rm:
                pending_route = set(_ROUTE_PARAM.findall(rm.group(1)))
                continue
            dm = _PY_DEF.match(line)
            if dm:
                begin(dm.group(2), dm.group(3), tainted=pending_route)
                pending_route = set()
                continue
        else:
            dm = _JS_DEF.search(line) if fam == "js" else _BRACE_DEF.match(line)
            if dm:
                g = [x for x in dm.groups() if x is not None]
                begin(g[0], g[1] if len(g) > 1 else "")
                if fam != "js" or "=>" not in line:
                    continue
        lm = _LOOP.search(line)
        if lm:
            var, it = (lm.group(1), lm.group(2)) if lm.group(1) else (lm.group(4), lm.group(3)) if lm.group(4) else (lm.group(5), lm.group(6))
            if var and it and labels.get(it):
                labels[var] = set(labels[it])
        am = _ASSIGN.match(line)
        rhs_all = am.group(3) if am else ""
        if am and not _SANITIZER.search(rhs_all):
            got = _names_in(rhs_all, labels) if _taints_result(rhs_all, src_rx) else set()
            if src_rx.search(rhs_all) and _taints_result(rhs_all, src_rx):
                got = got | {"SRC"}
            if got:
                labels[am.group(1)] = (labels.get(am.group(1), set()) if am.group(2) == "+" else set()) | got
            elif am.group(2) != "+":
                labels.pop(am.group(1), None)
        elif am and am.group(2) != "+":
            labels.pop(am.group(1), None)       # int(...) / escape(...) / basename(...) makes the value safe
        for rule, sev, desc, rx, mode in sinks:
            m = rx.search(line)
            if not m or (am and rx.pattern.startswith(r"\.(?:innerHTML") and False):
                continue
            region = _first_arg(line, m) if mode == "first" else line[m.start():]
            if _SANITIZER.search(region) and mode != "first":
                region = _SANITIZER.sub("(", region)
            got = _names_in(region, labels) | ({"SRC"} if src_rx.search(region) else set())
            if rule == "SEC-XSS" and fam == "js" and re.search(r"\.(?:innerHTML|outerHTML)\s*\+?=\s*(?:[\"'`][^\"'`$<]*[\"'`]|)\s*;?\s*$", line):
                continue                      # clearing an element, not writing data into it
            if rule == "SEC-XSS" and fam == "php" and not re.search(r"\becho\b|\bprint\b", line):
                continue
            if rule == "SEC-CMD" and fam == "python" and "subprocess" in m.group(0) and "shell" not in line and "SRC" not in got and not re.search(r"[\"']\s*[+%]|\{|\.format", region):
                continue                      # a list of arguments without a shell is not command injection
            if not got:
                continue
            if "SRC" in got:
                flows.append((rule, sev, n, desc))
            for lab in got:
                if lab.startswith("P:") and func:
                    summaries.setdefault(func, {}).setdefault(int(lab[2:]), rule)
    return flows, summaries


def flows(text, fam):
    return analyse(text, fam)[0]


def conflicts(store):
    """Cross-file: a call that hands request data to a function whose parameter reaches a dangerous place."""
    from core.security.rules import family
    parsed = {}
    summaries = {}
    for a in store.artifacts():
        t = a.get("transcription") or ""
        fam = family(a["name"], a.get("language") or "", t)
        if not t.strip() or not _family(fam):
            continue
        fl, sm = analyse(t, fam)
        parsed[a["id"]] = (a, t, fam)
        for fn, ps in sm.items():
            summaries.setdefault(fn, []).append((a["name"], ps))
    out = []
    for aid, (a, t, fam) in parsed.items():
        src_rx = re.compile(_SOURCES[_family(fam)])
        labels = {}
        func_tainted = set()
        for n, line in _logical_lines(t):
            am = _ASSIGN.match(line)
            if am and src_rx.search(am.group(3)) and not _SANITIZER.search(am.group(3)) and _taints_result(am.group(3), src_rx):
                labels[am.group(1)] = {"SRC"}
            elif am and _names_in(am.group(3), labels) and not _SANITIZER.search(am.group(3)):
                labels[am.group(1)] = {"SRC"}
            for fn, defs in summaries.items():
                for cm in re.finditer(rf"(?<![\w.]){re.escape(fn)}\s*\(", line):
                    if re.match(r"\s*(?:async\s+)?def\s", line) or re.match(r"\s*function\s", line):
                        continue
                    args = _call_args(line, cm)
                    for def_file, ps in defs:
                        if def_file == a["name"]:
                            continue
                        for idx, rule in ps.items():
                            if idx < len(args) and (_names_in(args[idx], labels) or src_rx.search(args[idx])) and not _SANITIZER.search(args[idx]):
                                out.append({"title": f"{a['name']} passes request input to {fn}(), which uses it unsafely",
                                            "statement": f"{a['name']} line {n} hands request data to {fn}() in {def_file}, which uses that argument in a place that "
                                                         f"{dict((r, d) for r, _, d, _, _ in _SINKS[_family(fam)]).get(rule, 'is unsafe')} ({rule}).",
                                            "facts": [], "basis": "observed", "files": sorted({a["name"], def_file}),
                                            "cites": [f"{a['name']} lines {n}–{n}"], "source": "taint", "severity": "high"})
    seen, uniq = set(), []
    for o in out:
        k = (o["title"], o["cites"][0])
        if k not in seen:
            seen.add(k)
            uniq.append(o)
    return uniq


def _call_args(line, m):
    i, depth, q, cur, args = m.end(), 1, None, [], []
    while i < len(line):
        ch = line[i]
        if q:
            cur.append(ch)
            if ch == q:
                q = None
        elif ch in "\"'`":
            q = ch
            cur.append(ch)
        elif ch in "([{":
            depth += 1
            cur.append(ch)
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                break
            cur.append(ch)
        elif ch == "," and depth == 1:
            args.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    if cur:
        args.append("".join(cur))
    return args
