import re

RULES = {
    "cpp": [
        ("legacy", "pre-standard C++ headers", r"#\s*include\s*<(iostream|fstream|iomanip|strstream|stdiostr|vector|list|stack)\.h>"),
        ("legacy", "void main", r"\bvoid\s+main\s*\("),
        ("legacy", "no std namespace (pre-1998 style)", None),
        ("legacy", "strstream (deprecated)", r"\bstrstream\b|<strstream>"),
        ("legacy", "auto_ptr (removed in C++17)", r"\bauto_ptr\s*<"),
        ("legacy", "register storage class (removed in C++17)", r"\bregister\s+(int|char|long|short|unsigned)\b"),
        ("legacy", "far/near/huge pointers (16-bit)", r"\b(far|near|huge|_far|__far)\s*\*"),
        ("framework", "MFC", r"#\s*include\s*[<\"](afx\w*\.h)[>\"]|\bCWinApp\b|\bCDialog\b|DECLARE_MESSAGE_MAP"),
        ("framework", "Borland OWL", r"#\s*include\s*<owl/|\bTApplication\b|\bTFrameWindow\b"),
        ("framework", "Borland VCL / C++Builder", r"#\s*include\s*<vcl\.h>|__fastcall|#pragma\s+package"),
        ("framework", "COM / ATL", r"#\s*include\s*<(atlbase|atlcom|objbase)\.h>|\bCoCreateInstance\b|\bIUnknown\b"),
        ("framework", "Win32 API", r"#\s*include\s*<windows\.h>|\bWinMain\b|\bHWND\b"),
        ("framework", "Win16 API", r"#\s*include\s*<toolhelp\.h>|\bFAR\s+PASCAL\b|\bMakeProcInstance\b|\bGlobalLock\b"),
        ("framework", "ODBC", r"#\s*include\s*<sql(ext)?\.h>|\bSQLExecDirect\b|\bSQLConnect\b"),
        ("level", "C++11 or later", r"\bauto\s+\w+\s*=|\bnullptr\b|\bstd::(unique_ptr|shared_ptr)\b|\[\s*&?\s*\]\s*\("),
        ("level", "STL (C++98)", r"\bstd::(vector|map|string|list)\b|using\s+namespace\s+std"),
    ],
    "c_sharp": [
        ("framework", "ASP.NET Web Forms", r"\bSystem\.Web\.UI\b|:\s*(System\.Web\.UI\.)?Page\b|\bPage_Load\b"),
        ("framework", "ASP.NET MVC", r"\bSystem\.Web\.Mvc\b|:\s*Controller\b|\bActionResult\b"),
        ("framework", "ASP.NET Web API", r"\bSystem\.Web\.Http\b|:\s*ApiController\b"),
        ("framework", "ASP.NET Core", r"\bMicrosoft\.AspNetCore\b|\bIActionResult\b"),
        ("framework", "ASMX web services", r"\bSystem\.Web\.Services\b|\[\s*WebMethod\b"),
        ("framework", "WCF", r"\bSystem\.ServiceModel\b|\[\s*(ServiceContract|OperationContract)\b"),
        ("framework", ".NET Remoting (obsolete)", r"\bSystem\.Runtime\.Remoting\b|\bMarshalByRefObject\b"),
        ("framework", "ADO.NET", r"\bSystem\.Data\.(SqlClient|OleDb|Odbc|OracleClient)\b|\bSqlCommand\b|\bSqlConnection\b"),
        ("framework", "Entity Framework", r"\bSystem\.Data\.Entity\b|\bDbContext\b|\bMicrosoft\.EntityFrameworkCore\b"),
        ("framework", "WinForms", r"\bSystem\.Windows\.Forms\b|:\s*Form\b"),
        ("framework", "WPF", r"\bSystem\.Windows\.Controls\b|\bINotifyPropertyChanged\b"),
        ("framework", "Enterprise Library", r"\bMicrosoft\.Practices\.EnterpriseLibrary\b"),
        ("cobol_net", "Micro Focus COBOL runtime", r"\bMicroFocus\.COBOL\b|\bMicroFocus\.COBOL\.Program\b"),
        ("cobol_net", "Fujitsu NetCOBOL runtime", r"\bFujitsu\.COBOL\b|\bNetCOBOL\b"),
        ("cobol_net", "COBOL-style names (WS_/LS_/FD_)", r"\b(WS|LS|FD|WK)_[A-Z0-9_]{3,}\b"),
        ("cobol_net", "COBOL-style paragraph methods", r"\bvoid\s+(P?\d{3,4}_[A-Z0-9_]+|[A-Z0-9]+_(PARA|SECTION|EXIT))\s*\("),
        ("cobol_net", "GOTO labels", r"\bgoto\s+\w+\s*;"),
        ("level", "C# 2.0 generics", r"\b(List|Dictionary)<"),
        ("level", "C# 3.0 LINQ/var", r"\bvar\s+\w+\s*=|\bfrom\s+\w+\s+in\b|\.Where\s*\("),
        ("level", "C# 5.0 async", r"\basync\s+\w+|\bawait\s+"),
        ("level", "C# 6+ features", r"\?\.\w|\$\"|nameof\s*\("),
        ("legacy", "non-generic collections (ArrayList/Hashtable)", r"\b(ArrayList|Hashtable)\b"),
    ],
    "java": [
        ("framework", "Servlet API (javax)", r"\bjavax\.servlet\b|\bextends\s+HttpServlet\b"),
        ("framework", "Jakarta EE", r"\bjakarta\.(servlet|ejb|persistence|ws)\b"),
        ("framework", "JSP tag libs", r"\bjavax\.servlet\.jsp\b"),
        ("framework", "EJB 2.x (home/remote)", r"\bEJBHome\b|\bEJBObject\b|\bSessionBean\b|\bEntityBean\b"),
        ("framework", "EJB 3", r"@(Stateless|Stateful|MessageDriven)\b"),
        ("framework", "Struts 1", r"\borg\.apache\.struts\.action\b|\bextends\s+Action\b|\bActionForm\b"),
        ("framework", "Spring", r"\borg\.springframework\b|@(Controller|RestController|Service|Autowired)\b"),
        ("framework", "JAX-RS", r"\bjavax\.ws\.rs\b|@Path\s*\("),
        ("framework", "JAX-WS / SOAP", r"\bjavax\.jws\b|@WebService\b|\bjavax\.xml\.rpc\b"),
        ("framework", "JDBC", r"\bjava\.sql\b|\bDriverManager\b|\bprepareStatement\b|\bResultSet\b"),
        ("framework", "Hibernate / JPA", r"\borg\.hibernate\b|\bjavax\.persistence\b|@Entity\b"),
        ("framework", "Swing / AWT", r"\bjavax\.swing\b|\bjava\.awt\b|\bextends\s+JFrame\b"),
        ("framework", "Applet (removed)", r"\bjava\.applet\b|\bextends\s+(J?Applet)\b"),
        ("framework", "log4j 1.x (EOL)", r"\borg\.apache\.log4j\.(Logger|Category)\b"),
        ("level", "Java 5 generics/annotations", r"\b(List|Map|Set)<\w|@Override\b"),
        ("level", "Java 7 try-with-resources/diamond", r"\btry\s*\(|<>\s*\("),
        ("level", "Java 8 lambdas/streams", r"->|\.stream\(\)|::\w"),
        ("level", "Java 10+ var", r"\bvar\s+\w+\s*="),
        ("legacy", "legacy collections (Vector/Hashtable/Enumeration)", r"\b(Vector|Hashtable|Enumeration|StringTokenizer)\b"),
    ],
}

_LEVEL_ORDER = {
    "cpp": ["STL (C++98)", "C++11 or later"],
    "c_sharp": ["C# 2.0 generics", "C# 3.0 LINQ/var", "C# 5.0 async", "C# 6+ features"],
    "java": ["Java 5 generics/annotations", "Java 7 try-with-resources/diamond", "Java 8 lambdas/streams",
             "Java 10+ var"],
}


def _strip_comments(code: str, lang: str) -> list:
    out, in_block = [], False
    for line in code.splitlines():
        text, i = "", 0
        while i < len(line):
            if in_block:
                end = line.find("*/", i)
                if end < 0:
                    i = len(line)
                else:
                    in_block, i = False, end + 2
                continue
            if line.startswith("/*", i):
                in_block, i = True, i + 2
                continue
            if line.startswith("//", i):
                break
            text += line[i]
            i += 1
        out.append(text)
    return out


def technology_profile(code: str, lang: str) -> dict:
    lines = _strip_comments(code, lang)
    found = {}
    for category, label, pattern in RULES.get(lang, []):
        if pattern is None:
            continue
        rx = re.compile(pattern, re.I if category == "framework" and lang == "cpp" else 0)
        hits = [n for n, line in enumerate(lines, 1) if rx.search(line)]
        if hits:
            found.setdefault(category, {})[label] = hits[:5]
    if lang == "cpp":
        uses_iostream = any(re.search(r"\b(cout|cin|cerr|endl)\b", l) for l in lines)
        has_std = any(re.search(r"\bstd::|using\s+namespace\s+std", l) for l in lines)
        if uses_iostream and not has_std:
            hits = [n for n, l in enumerate(lines, 1) if re.search(r"\b(cout|cin|cerr)\b", l)]
            found.setdefault("legacy", {})["no std namespace (pre-1998 style)"] = hits[:5]
    level = None
    for label in _LEVEL_ORDER.get(lang, []):
        if label in found.get("level", {}):
            level = label
    dialect = None
    if lang == "cpp":
        legacy = found.get("legacy", {})
        if any(k.startswith(("pre-standard", "no std")) for k in legacy):
            dialect = "pre-standard C++ (before ISO C++98)"
        elif level == "C++11 or later":
            dialect = "C++11 or later"
        elif level:
            dialect = "C++98/03"
    cobol_net = found.get("cobol_net", {})
    translated = len(cobol_net) >= 2 or any("runtime" in k for k in cobol_net)
    return {
        "language": {"cpp": "C++", "c_sharp": "C#", "java": "Java"}.get(lang, lang),
        "dialect": dialect,
        "level_signal": level,
        "frameworks": sorted(found.get("framework", {})),
        "legacy_markers": sorted(found.get("legacy", {})),
        "cobol_translated": translated,
        "evidence": {label: lines_ for cat in found.values() for label, lines_ in cat.items()},
    }
