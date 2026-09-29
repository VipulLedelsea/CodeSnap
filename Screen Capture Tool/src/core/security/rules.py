import re
from pathlib import PurePath

_EXT_FAMILY = {
    "cs": "cs", "java": "java", "cpp": "cpp", "cc": "cpp", "cxx": "cpp", "c": "cpp", "h": "cpp", "hpp": "cpp",
    "hh": "cpp", "hxx": "cpp", "cbl": "cobol", "cob": "cobol", "cpy": "cobol", "aspx": "web", "ascx": "web",
    "master": "web", "jsp": "web", "html": "web", "htm": "web", "js": "js", "config": "config", "xml": "config",
    "properties": "props", "ini": "props", "json": "json", "yaml": "json", "yml": "json", "sql": "sql", "ddl": "sql",
    "vb": "vb", "bas": "vb", "cls": "vb", "asp": "web",
}
_LANG_FAMILY = {"c#": "cs", "c_sharp": "cs", "csharp": "cs", "java": "java", "c++": "cpp", "cpp": "cpp", "c": "cpp",
                "cobol": "cobol", "html": "web", "javascript": "js", "xml": "config", "sql": "sql"}
CODE = {"cs", "java", "cpp", "js", "vb", "web"}
SQL_WORDS = re.compile(r"\b(SELECT\s.+\sFROM|INSERT\s+INTO|UPDATE\s+[\w.\[\]]+\s+SET|DELETE\s+FROM|WHERE\s+\w|"
                       r"EXEC(UTE)?\s+\w|VALUES\s*\()", re.I)
_LITERAL = re.compile(r'@?"(?:\\.|""|[^"\\])*"')


PACK_IDS = {"vb6", "vba", "vbnet", "vbscript", "rpg", "cl", "natural", "pli", "asm", "rexx", "clist", "easytrieve", "sas",
            "plsql", "tsql", "powerbuilder", "coldfusion", "php", "perl", "shell", "batch", "powershell", "python",
            "javascript", "delphi", "foxpro", "informix4gl", "progress", "fortran", "basic"}
VB_LIKE = {"vb", "vb6", "vba", "vbnet", "vbscript", "basic", "web"}
CODE |= PACK_IDS - {"plsql", "tsql"}


def family(filename: str, language: str = "", text: str = "") -> str:
    ext = PurePath(filename or "").suffix.lower().lstrip(".")
    if ext in _EXT_FAMILY:
        return _EXT_FAMILY[ext]
    if text:
        try:
            from core.langpacks import AMBIGUOUS_EXTS, pack_for
            if ext in AMBIGUOUS_EXTS:
                p = pack_for(filename, language, text)
                if p:
                    return "js" if p["id"] == "javascript" else p["id"]
        except Exception:
            pass
    fam = _LANG_FAMILY.get((language or "").lower())
    if fam:
        return fam
    try:
        from core.langpacks import EXT_INDEX, _by_name
    except Exception:
        return "other"
    named = _by_name(language)
    cands = EXT_INDEX.get(ext) or []
    if named and (not cands or named in cands):
        return "js" if named["id"] == "javascript" else named["id"]
    if cands:
        return "js" if cands[0]["id"] == "javascript" else cands[0]["id"]
    return "other"


def _strip_c(lines):
    out, block = [], False
    for line in lines:
        buf, i, quote = [], 0, None
        while i < len(line):
            ch = line[i]
            if block:
                if line.startswith("*/", i):
                    block, i = False, i + 2
                    buf.append("  ")
                else:
                    buf.append(" ")
                    i += 1
                continue
            if quote:
                buf.append(ch)
                if ch == "\\" and i + 1 < len(line):
                    buf.append(line[i + 1])
                    i += 2
                    continue
                if ch == quote:
                    quote = None
                i += 1
                continue
            if ch in "\"'":
                quote = ch
                buf.append(ch)
                i += 1
                continue
            if line.startswith("//", i):
                break
            if line.startswith("/*", i):
                block, i = True, i + 2
                buf.append("  ")
                continue
            buf.append(ch)
            i += 1
        out.append("".join(buf))
    return out


def _strip_markup(text):
    text = re.sub(r"<!--(?!\[if).*?-->|<%--.*?--%>", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    return text.splitlines()


def _strip_cobol(lines):
    out = []
    for line in lines:
        fixed = len(line) > 6 and (line[:6].strip() == "" or line[:6].strip().isdigit())
        if fixed and line[6:7] in ("*", "/"):
            out.append("")
        else:
            out.append(line.split("*>")[0])
    return out


def code_lines(text: str, fam: str) -> list:
    lines = (text or "").splitlines()
    if fam in ("cs", "java", "cpp", "js"):
        return _strip_c(lines)
    if fam in ("web", "config"):
        return _strip_markup(text or "")
    if fam == "cobol":
        return _strip_cobol(lines)
    if fam == "sql":
        return [re.sub(r"--.*$", "", l) for l in lines]
    if fam in ("props",):
        return ["" if l.strip().startswith(("#", ";", "!")) else l for l in lines]
    if fam == "vb":
        from core.langpacks import strip_comments
        return strip_comments(text or "", "vbnet")
    if fam in PACK_IDS:
        from core.langpacks import strip_comments
        return strip_comments(text or "", fam)
    return lines


_SECRET_VALUE = re.compile(r'''((?:password|passwd|pwd|secret|api_?key|access_?key|token)\w*["']?\s*[:=]\s*["'])([^"']{3,})(["'])''', re.I)
_CONN_PWD = re.compile(r"((?:Password|Pwd)\s*=\s*)([^;\"'\s]+)", re.I)


def mask_snippet(line: str) -> str:
    line = _SECRET_VALUE.sub(lambda m: m.group(1) + "****" + m.group(3), line)
    line = _CONN_PWD.sub(lambda m: m.group(1) + "****", line)
    line = re.sub(r"(VALUE\s+['\"])([^'\"]+)(['\"])", lambda m: m.group(1) + "****" + m.group(3), line) \
        if re.search(r"(PASSWORD|PASSWD|PWD)", line, re.I) else line
    return line.strip()[:200]


LINE_RULES = [
    ("SEC-CRED", {"cs", "java", "cpp", "js", "vb", "web"} | PACK_IDS, "high",
     r'''(?<![\w.])\w{0,40}?(password|passwd|pwd|secret|apikey|api_key|accesskey|access_key)\w{0,40}\s*(=|:|==|\.Equals\()\s*@?["'][^"'\s]{3,}["']''',
     "credential literal in code"),
    ("SEC-CRED", {"cobol"}, "high", r"(PASSWORD|PASSWD|PWD)[\w-]*\s+PIC\s+\S+\s+VALUE\s+['\"][^'\"]{2,}['\"]",
     "password stored in a VALUE clause"),
    ("SEC-SQLDYN", {"cobol"}, "medium", r"\bEXEC\s+SQL\s+(PREPARE\s+\S+\s+FROM|EXECUTE\s+IMMEDIATE)\b|^\s*(PREPARE\s+\S+\s+FROM|EXECUTE\s+IMMEDIATE)\b",
     "dynamic SQL — confirm the statement text is not built from user input"),
    ("SEC-XSS", {"cs", "web", "vb"}, "high", r"Response\.Write\s*\([^;]*Request\s*(\.|\[)", "request value written straight to the response"),
    ("SEC-XSS", {"cs", "vb"}, "medium", r"\.(Text|InnerHtml)\s*=\s*[^;]*Request\s*(\.QueryString|\.Form|\.Params|\[)",
     "request value assigned to a control without encoding"),
    ("SEC-XSS", {"java", "web"}, "high", r"\bout\.print(ln)?\s*\([^;]*request\.getParameter", "request parameter printed without encoding"),
    ("SEC-XSS", {"web"}, "high", r"<%=\s*(Request\b|request\.getParameter)", "request value echoed in the page"),
    ("SEC-XSS", {"web", "config"}, "medium", r'''validateRequest\s*=\s*["']false["']''', "ASP.NET request validation turned off"),
    ("SEC-XSS", {"web", "js"}, "low", r"\.innerHTML\s*=|document\.write\s*\(|\beval\s*\(", "script writes raw HTML / evaluates strings"),
    ("SEC-CMD", {"cs", "vb"}, "high", r"Process\.Start\s*\([^;]*\+", "process started with a concatenated command"),
    ("SEC-CMD", {"java"}, "high", r"Runtime\.getRuntime\(\)\.exec\s*\([^;]*\+|new\s+ProcessBuilder\s*\([^;]*\+", "OS command concatenated from variables"),
    ("SEC-CMD", {"cpp"}, "high", r"\b(system|popen|WinExec|ShellExecuteA?)\s*\(\s*(?!\")[^)]", "OS command from a variable buffer"),
    ("SEC-PATH", {"java"}, "medium", r"new\s+File(InputStream|OutputStream|Reader|Writer)?\s*\([^;]*request\.getParameter", "file path from a request parameter"),
    ("SEC-PATH", {"cs", "vb"}, "medium", r"\b(File|Directory)\.\w+\s*\([^;]*Request\s*(\.|\[)|Server\.MapPath\s*\([^;]*Request", "file path from request input"),
    ("SEC-DESER", {"cs", "vb"}, "high", r"\b(BinaryFormatter|NetDataContractSerializer|SoapFormatter|LosFormatter|ObjectStateFormatter)\b|TypeNameHandling\.(All|Auto|Objects)",
     "deserializer that can instantiate arbitrary types"),
    ("SEC-DESER", {"java"}, "high", r"\bnew\s+ObjectInputStream\b|\.readObject\s*\(\s*\)|\bXMLDecoder\b", "Java object deserialization"),
    ("SEC-CRYPTO", {"cs", "vb"}, "medium", r"\b(MD5CryptoServiceProvider|MD5\.Create|SHA1Managed|SHA1CryptoServiceProvider|SHA1\.Create|DESCryptoServiceProvider|TripleDESCryptoServiceProvider|RC2CryptoServiceProvider)\b|HashPasswordForStoringInConfigFile|CipherMode\.ECB",
     "weak hash or cipher"),
    ("SEC-CRYPTO", {"java"}, "medium", r'''MessageDigest\.getInstance\s*\(\s*"(MD5|SHA-?1|MD2)"|Cipher\.getInstance\s*\(\s*"(DES|DESede|RC2|RC4)[/"]''',
     "weak hash or cipher"),
    ("SEC-CRYPTO", {"java"}, "medium", r'''Cipher\.getInstance\s*\(\s*"(AES"|[^"]*/ECB/)''', "AES in ECB mode (Java's default when no mode is given)"),
    ("SEC-CRYPTO", {"cpp"}, "medium", r"\b(MD5_Init|MD5Init|DES_ecb_encrypt|DES_set_key|CALG_MD5|CALG_DES|CALG_RC4|CALG_SHA1)\b", "weak hash or cipher"),
    ("SEC-TLS", CODE | {"config", "props", "json"}, "medium", r'''["'=>\s](http|ftp|telnet)://(?!(localhost|127\.0\.0\.1|www\.w3\.org|schemas\.|java\.sun\.com|xmlns\.|tempuri\.org))[\w.-]+''',
     "plain-text protocol endpoint"),
    ("SEC-TLS", {"cs", "config", "props", "json", "java"}, "medium", r"Encrypt\s*=\s*(False|no)\b|TrustServerCertificate\s*=\s*(True|yes)\b", "database connection without verified encryption"),
    ("SEC-TLS", {"config"}, "medium", r'''<security\s+mode\s*=\s*["']None["']|requireSSL\s*=\s*["']false["']''', "transport security disabled"),
    ("SEC-TLS", {"cs", "vb"}, "high", r"ServerCertificateValidationCallback\s*\+?=.*(=>\s*true|return\s+true)|SecurityProtocolType\.(Ssl3|Tls\b|Tls11)",
     "TLS certificate validation disabled or obsolete protocol"),
    ("SEC-TLS", {"java"}, "high", r"ALLOW_ALL_HOSTNAME_VERIFIER|NoopHostnameVerifier|TrustAllCerts|X509TrustManager\s*\(\s*\)\s*\{", "TLS certificate / hostname checks disabled"),
    ("SEC-AUTH", {"config"}, "high", r'''<authentication\s+mode\s*=\s*["']None["']''', "authentication disabled"),
    ("SEC-AUTH", {"config"}, "high", r'''passwordFormat\s*=\s*["']Clear["']''', "clear-text credentials in config"),
    ("SEC-AUTH", {"config"}, "medium", r'''<allow\s+users\s*=\s*["']\*["']''', "all users (including anonymous) allowed"),
    ("SEC-AUTH", {"config"}, "medium", r'''cookieless\s*=\s*["'](true|UseUri|AutoDetect)["']''', "session / auth id carried in the URL"),
    ("SEC-AUTH", {"web", "config"}, "medium", r'''enableViewStateMac\s*=\s*["']false["']|EnableEventValidation\s*=\s*["']false["']''', "ViewState / event validation disabled"),
    ("SEC-CONF", {"config"}, "medium", r'''<compilation[^>]*debug\s*=\s*["']true["']''', "debug compilation enabled in production config"),
    ("SEC-CONF", {"config"}, "medium", r'''<customErrors[^>]*mode\s*=\s*["']Off["']''', "detailed errors shown to users"),
    ("SEC-CONF", {"config"}, "medium", r'''<trace[^>]*enabled\s*=\s*["']true["']|errorMode\s*=\s*["']Detailed["']''', "trace / detailed errors enabled"),
    ("SEC-CONF", {"cs", "vb", "java", "web"}, "low", r"(Response\.Write|\.Text\s*=|out\.print(ln)?)\s*\(?[^;]*\b(ex|e|exc|exception|err)\.(Message|ToString\(\)|StackTrace|getMessage\(\))",
     "exception details shown to the user"),
    ("SEC-CONF", {"java"}, "low", r"\.printStackTrace\s*\(\s*(response\.getWriter\(\)|out)\s*\)", "stack trace written to the response"),
    ("SEC-MEM", {"cpp"}, "high", r"\bgets\s*\(", "gets() cannot limit input length"),
    # ---- legacy language packs (M3.5)
    ("SEC-SQLI", VB_LIKE, "high", r'''"[^"]*\b(SELECT\s|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|WHERE\s)[^"]*"\s*&\s*(?!vbCrLf|vbNewLine|vbTab|")[A-Za-z_(]''',
     "SQL text concatenated with & (VB / VBScript)"),
    ("SEC-SQLI", VB_LIKE, "high", r'''(SELECT|INSERT|UPDATE|DELETE|WHERE)\b[^"\n]*"\s*&\s*Request(\.(Form|QueryString))?\s*\(''',
     "request value concatenated into SQL"),
    ("SEC-CMD", VB_LIKE, "high", r"\bShell\b\s*\(?[^\n]*&\s*[A-Za-z_(]|\.Run\b\s*\(?\s*[^\n]*&\s*\w|\.Exec\s*\([^)]*&", "OS command built by concatenation"),
    ("SEC-CMD", {"vbscript", "web"}, "medium", r"(?<![.\w])(Execute|ExecuteGlobal|Eval)\s*\(?\s*(?!\")[A-Za-z_]", "VBScript Execute/Eval of a runtime string"),
    ("SEC-XSS", VB_LIKE, "high", r"Response\.Write\b[^\n]*&\s*Request\s*(\.|\()", "request value written straight to the response"),
    ("SEC-SQLI", {"php"}, "high", r"\b(mysql_query|mysqli_query|pg_query|mssql_query|odbc_exec|->query|->exec)\s*\([^;]*\$_(GET|POST|REQUEST|COOKIE)",
     "request value passed straight into a query"),
    ("SEC-SQLI", {"php"}, "high", r'''"[^"]*\b(SELECT\s|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|WHERE\s)[^"]*(\$\w+|"\s*\.\s*\$\w+)|'[^']*\b(SELECT\s|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|WHERE\s)[^']*'\s*\.\s*\$\w+''',
     "SQL text built from PHP variables"),
    ("SEC-PATH", {"php"}, "high", r"\b(include|require)(_once)?\s*\(?\s*[^;]*\$_(GET|POST|REQUEST|COOKIE)", "file include from request input"),
    ("SEC-CMD", {"php"}, "high", r"\b(system|exec|shell_exec|passthru|popen|proc_open)\s*\([^;]*\$", "OS command built from a variable"),
    ("SEC-CMD", {"php"}, "medium", r"\beval\s*\(|preg_replace\s*\(\s*['\"][^'\"]*/e['\"]", "eval() / preg_replace /e code execution"),
    ("SEC-XSS", {"php"}, "high", r"\b(echo|print)\b[^;]*\$_(GET|POST|REQUEST|COOKIE)", "request value echoed without encoding"),
    ("SEC-CRYPTO", {"php", "perl", "python", "coldfusion"}, "medium", r"\b(md5|sha1|crypt)\s*\(\s*\$?\w*(pass|pwd)", "weak hash used for passwords"),
    ("SEC-CMD", {"perl"}, "high", r"\b(system|exec)\s*\(?\s*\"[^\"]*\$\w|`[^`]*\$\w|\bopen\s*\(?\s*\w+\s*,\s*\"[^\"]*\$\w+[^\"]*\|\"",
     "shell command interpolates a variable"),
    ("SEC-SQLI", {"perl"}, "high", r'''\b(prepare|do|selectrow_\w+|selectall_\w+)\s*\(\s*"[^"]*\b(SELECT|INSERT|UPDATE|DELETE|WHERE)\b[^"]*\$\w''',
     "SQL text interpolates a Perl variable (use placeholders)"),
    ("SEC-CRED", {"php"}, "high", r'''\b(mysql_connect|mysqli_connect|mssql_connect|new\s+PDO|new\s+mysqli)\s*\([^)]*,\s*["'][^"']*["']\s*,\s*["'][^"'$]{3,}["']''',
     "database password hard-coded in the connect call"),
    ("SEC-CRED", {"perl"}, "high", r'''DBI->connect\s*\([^)]*,\s*["'][^"']*["']\s*,\s*["'][^"'$]{3,}["']''', "database password hard-coded in DBI->connect"),
    ("SEC-CRED", {"foxpro"}, "high", r'''SQLCONNECT\s*\([^)]*,\s*["'][^"']*["']\s*,\s*["'][^"']{2,}["']''', "database password hard-coded in SQLCONNECT"),
    ("SEC-SQLI", {"foxpro", "informix4gl", "progress"}, "high", r'''["'][^"']*\b(SELECT\s|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|WHERE\s)[^"']*["']\s*(\+|\|\|)\s*[A-Za-z_]''',
     "SQL text concatenated with a variable"),
    ("SEC-CMD", {"shell"}, "medium", r"(^|[;&|]\s*)eval\s", "eval of a constructed command"),
    ("SEC-CRED", {"shell", "batch", "powershell"}, "high",
     r"\b(sqlplus|isql|sqlcmd|osql|bcp|mysql|db2)\b[^|\n]*(\s-P\s*\S+|\s-p\S+|\s\w+/\S+@\w+)", "database password on the command line"),
    ("SEC-CRED", {"batch"}, "high", r"(?i)net\s+use\s+(?:[A-Z*]:\s+)?\\\\\S+\s+(?!/)\S+(?:\s|$)", "share password in a batch file"),
    ("SEC-TLS", {"shell", "batch", "perl", "python", "rexx", "clist"}, "medium", r"(?<![\w-])(ftp|telnet)(\s|$|\.exe|\s+-)|Net::FTP|ftplib",
     "plain FTP / Telnet transfer"),
    ("SEC-CMD", {"powershell"}, "medium", r"\b(Invoke-Expression|iex)\b", "Invoke-Expression of a constructed string"),
    ("SEC-CRED", {"powershell"}, "high", r'''ConvertTo-SecureString\s+["'][^"']+["']\s+-AsPlainText|-Password\s+["'][^"']{3,}["']''',
     "plain-text password in script"),
    ("SEC-CMD", {"rpg", "cl"}, "medium", r"\bQCMDEXC\b[^;\n]*(\+|%trim|\*CAT|\*TCAT|\*BCAT)", "system command string built at run time (QCMDEXC)"),
    ("SEC-SQLDYN", {"rpg", "pli", "informix4gl", "powerbuilder", "natural"}, "medium",
     r"\b(PREPARE\s+\S+\s+FROM|EXECUTE\s+IMMEDIATE)\b", "dynamic SQL — confirm the statement text is not built from user input"),
    ("SEC-SQLI", {"plsql"}, "high", r"\bEXECUTE\s+IMMEDIATE\b[^;]*\|\||\bOPEN\s+\w+\s+FOR\s+[^;]*\|\||DBMS_SQL\.PARSE\s*\([^;]*\|\|",
     "dynamic SQL concatenated with ||"),
    ("SEC-CRED", {"plsql", "tsql", "sql"}, "high", r"\bIDENTIFIED\s+BY\s+\"?\w{3,}|\bPASSWORD\s*=\s*N?'[^']{3,}'", "password in SQL source"),
    ("SEC-AUTH", {"plsql", "tsql", "sql"}, "medium", r"\bGRANT\b[^;]*\bTO\s+PUBLIC\b", "privileges granted to PUBLIC"),
    ("SEC-CMD", {"tsql", "sql"}, "high", r"\bxp_cmdshell\b", "xp_cmdshell runs OS commands from SQL"),
    ("SEC-SQLI", {"tsql", "sql"}, "high", r"\bEXEC(UTE)?\s*\(\s*@\w+|\bEXEC(UTE)?\s*\([^)]*\+\s*@\w+", "dynamic SQL built by concatenation (EXEC(@sql))"),
    ("SEC-SQLDYN", {"tsql", "sql"}, "medium", r"\bsp_executesql\s+@\w+", "dynamic SQL via sp_executesql — confirm it is parameterised"),
    ("SEC-CRED", {"sas"}, "high", r'''\b(password|pw|pwd|dbpass)\s*=\s*["']?(?!\{sas\d+\})[^"'\s;)&%]{3,}''', "database password in SAS code (use PROC PWENCODE / authdomain)"),
    ("SEC-CMD", {"sas"}, "medium", r"^\s*X\s+['\"]|%SYSEXEC\b|CALL\s+SYSTEM\s*\(|\bPIPE\s+['\"]", "SAS runs operating-system commands"),
    ("SEC-SQLI", {"coldfusion"}, "high", r"\b(WHERE|AND|OR|VALUES|SET|IN)\b[^<\n]*#(?!\s)(url|form|cookie|arguments|attributes)?\.?\w+#(?![^<]*cfqueryparam)",
     "variable interpolated into a cfquery without cfqueryparam"),
    ("SEC-CMD", {"coldfusion"}, "medium", r"<cfexecute\b", "cfexecute runs OS commands"),
    ("SEC-XSS", {"coldfusion"}, "medium", r"^(?!.*\b(WHERE|AND|OR|VALUES|SET)\b).*#(url|form|cookie)\.\w+#", "request value output without encodeForHTML"),
    ("SEC-SQLI", {"delphi"}, "high", r"(SQL\.(Add|Text)\s*(\(|:=)|CommandText\s*:=)\s*'[^']*\b(SELECT|INSERT|UPDATE|DELETE|WHERE)\b[^']*'\s*\+",
     "SQL text concatenated with + (Delphi)"),
    ("SEC-SQLI", {"foxpro"}, "high", r"SQLEXEC\s*\([^)]*(\+\s*\w|&\w)", "SQL pass-through built by concatenation / macro substitution"),
    ("SEC-CRED", {"powerbuilder"}, "high", r'''SQLCA\.(DBPass|LogPass)\s*=\s*"[^"]{2,}"''', "database password hard-coded in SQLCA"),
    ("SEC-SQLI", {"python"}, "high", r'''\.execute\s*\(\s*[fr]?["'][^"']*\b(SELECT|INSERT|UPDATE|DELETE|WHERE)\b[^"']*["']\s*(%|\+|\.format)|\.execute\s*\(\s*f["'][^"']*\{''',
     "SQL text built with string formatting (use parameters)"),
    ("SEC-CMD", {"python"}, "medium", r"\bos\.(system|popen)\s*\(|subprocess\.\w+\([^)]*shell\s*=\s*True|\bcommands\.getoutput\(", "shell command execution"),
    ("SEC-DESER", {"python"}, "high", r"\b(pickle|cPickle)\.loads?\s*\(|yaml\.load\s*\((?![^)]*Loader)", "unsafe deserialization"),
    ("SEC-CMD", {"rexx", "clist"}, "medium", r"\bINTERPRET\b|ADDRESS\s+TSO\s+[^'\"\n]*\w", "command string interpreted at run time"),
    ("SEC-MEM", {"cpp"}, "medium", r"\b(strcpy|strcat|sprintf|vsprintf|wsprintf[AW]?|lstrcpy[AW]?|lstrcat[AW]?|_mbscpy)\s*\(", "unbounded string copy / format"),
    ("SEC-MEM", {"cpp"}, "medium", r'''\b(scanf|sscanf|fscanf)\s*\([^;]*"[^"]*%s''', "%s read without a width limit"),
]
_COMPILED = [(rid, fams, sev, re.compile(rx, re.I if rid not in ("SEC-MEM",) else 0), desc)
             for rid, fams, sev, rx, desc in LINE_RULES]


def _is_constant(token: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_]*|\d+|(this\.)?[A-Z][A-Z0-9_]+", token))


def _sql_concat(lines: list, fam: str) -> list:
    if fam not in ("cs", "java", "cpp", "js", "vb", "web"):
        return []
    hits, stmt, start = [], "", None
    sql_vars = set()
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        if start is None:
            start = n
        stmt += " " + line
        if ";" not in line and fam != "vb" and not line.rstrip().endswith(("{", "}")):
            continue
        s, stmt_start, stmt = stmt, start, ""
        start = None
        literals = _LITERAL.findall(s)
        has_sql = any(SQL_WORDS.search(l) for l in literals)
        assign = re.match(r"\s*(?:[\w<>\[\]]+\s+)?(\w+)\s*(\+?=)\s*(.*)", s)
        if has_sql and assign and assign.group(2) == "=":
            sql_vars.add(assign.group(1))
        bare = _LITERAL.sub(" S ", s)
        concat = [t for t in re.findall(r"S\s*\+\s*([A-Za-z_][\w.\[\]()]*)|([A-Za-z_][\w.\]\)]*)\s*\+\s*S", bare)
                  for t in t if t]
        concat = [t for t in concat if not _is_constant(t.split(".")[-1].rstrip("()")) and t not in ("S",)]
        reason = None
        if has_sql and concat:
            reason = f"SQL text concatenated with {concat[0]}"
        elif has_sql and re.search(r'(String\.Format|string\.Format|String\.format)\s*\(', s) and any(
                re.search(r"\{\d+\}|%s|%d", l) for l in literals if SQL_WORDS.search(l)):
            reason = "SQL text built with string formatting"
        elif re.search(r'\$@?"[^"]*' + SQL_WORDS.pattern + r'[^"]*\{', s, re.I):
            reason = "SQL text built with string interpolation"
        elif fam == "cpp" and has_sql and re.search(r"\b(sprintf|strcat|wsprintf)\w*\s*\(", s) and any(
                "%s" in l or "%d" in l for l in literals):
            reason = "SQL text built with sprintf/strcat"
        elif assign and assign.group(2) == "+=" and assign.group(1) in sql_vars and re.search(
                r"[A-Za-z_]", _LITERAL.sub("", assign.group(3))):
            reason = f"SQL variable {assign.group(1)} extended with a variable"
        if reason:
            hits.append((stmt_start, reason))
    return hits


MAX_LINE = 2000


def _windows(line: str) -> list:
    if len(line) <= MAX_LINE:
        return [line]
    step = MAX_LINE - 200
    return [line[i:i + MAX_LINE] for i in range(0, len(line), step)]


def scan_text(text: str, filename: str, language: str = "") -> list:
    fam = family(filename, language, text)
    raw = (text or "").splitlines()
    lines = code_lines(text, fam)
    out, seen = [], set()

    def add(rule, severity, line_no, desc):
        key = (rule, line_no)
        if key in seen:
            return
        seen.add(key)
        snippet = mask_snippet(raw[line_no - 1]) if 0 < line_no <= len(raw) else ""
        out.append({"rule": rule, "severity": severity, "line": line_no, "detail": desc, "snippet": snippet,
                    "family": fam})

    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        windows = _windows(line)
        for rid, fams, sev, rx, desc in _COMPILED:
            if fam in fams and any(rx.search(w) for w in windows):
                add(rid, sev, n, desc)
    for n, reason in _sql_concat([l if len(l) <= MAX_LINE else l[:MAX_LINE] for l in lines], fam):
        add("SEC-SQLI", "high", n, reason)
    return out


_PII = [
    (r"^(SSN|SOC_?SEC\w*|SOCIAL_?SECURITY\w*|SSNO)$", "social security number", "critical"),
    (r"^(DOB|BIRTH_?(DATE|DT)|DATE_?OF_?BIRTH|BIRTHDAY)$", "date of birth", "high"),
    (r"^(MARSS\w*|SSID|STATE_?STUDENT_?ID|STUDENT_?(ID|NUM|NBR|NO|NUMBER|KEY)|STU_?(ID|NUM|NBR))$", "student identifier", "high"),
    (r"^(STUDENT_?NAME|STU_?NAME|PUPIL_?(NAME|FIRST\w*|LAST\w*)|FIRST_?NAME|LAST_?NAME|MIDDLE_?NAME)$", "student / person name", "medium"),
    (r"^(GUARDIAN\w*|PARENT_?NAME\w*)$", "parent / guardian", "medium"),
    (r"^(HOME_?ADDR\w*|STREET\w*|ADDRESS\d?|ADDR\d?|PHONE\w*|EMAIL\w*)$", "contact details", "medium"),
    (r"^(FREE_?REDUCED\w*|FRL|FRPL|LUNCH_?STATUS|ECON\w*_?DISADV\w*)$", "free/reduced lunch (economic status)", "high"),
    (r"^(IEP|SPED|SPECIAL_?ED\w*|DISABILIT\w*|SECTION_?504|PRIMARY_?DISABILITY)$", "special education / disability", "high"),
    (r"^(LEP|ELL|EL_?STATUS|ENGLISH_?LEARNER\w*)$", "English learner status", "medium"),
    (r"^(RACE\w*|ETHNIC\w*|HOMELESS\w*|MIGRANT\w*)$", "demographic / protected status", "high"),
    (r"^(GRADE_?LEVEL|GRADE|ENROLL\w*|ATTENDANCE\w*)$", "education record", "low"),
]
_PII_RX = [(re.compile(rx, re.I), label, sev) for rx, label, sev in _PII]


def _norm(name: str) -> str:
    name = re.sub(r"([a-z])([A-Z])", r"\1_\2", name.split(".")[-1])
    return re.sub(r"[-\s]+", "_", name).upper().strip("_")


def pii_class(name: str):
    n = _norm(name or "")
    n = re.sub(r"_(IN|OUT|I|O|L|A|F)$", "", n)
    parts = n.split("_")
    for drop in range(0, min(3, len(parts))):
        cand = "_".join(parts[drop:])
        for rx, label, sev in _PII_RX:
            if rx.match(cand):
                return label, sev
    return None


def text_has_student_data(lines) -> bool:
    for line in lines:
        for token in re.findall(r"[A-Za-z][\w-]{1,40}", line):
            if token.islower():
                continue
            hit = pii_class(token)
            if hit and hit[1] in ("critical", "high"):
                return True
    return False
