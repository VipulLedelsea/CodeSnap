import re
import tempfile
from pathlib import Path

from .grammars import available, lang_for
from .syntax import format_errors, syntax_errors

SHIMS = {
    "iostream.h": "#include <iostream>\nusing namespace std;\n",
    "fstream.h": "#include <fstream>\nusing namespace std;\n",
    "iomanip.h": "#include <iomanip>\nusing namespace std;\n",
    "strstream.h": "#include <sstream>\nusing namespace std;\n",
    "strstrea.h": "#include <sstream>\nusing namespace std;\n",
    "stdiostr.h": "#include <cstdio>\n#include <iostream>\nusing namespace std;\n",
    "vector.h": "#include <vector>\nusing namespace std;\n",
    "list.h": "#include <list>\nusing namespace std;\n",
    "stack.h": "#include <stack>\nusing namespace std;\n",
    "bool.h": "",
}
_MISSING = [
    re.compile(r"fatal error:\s*'?([^':\s]+)'?\s*(?:file not found|: No such file or directory)", re.I),
    re.compile(r"package ([\w.]+) does not exist"),
    re.compile(r"cannot find symbol\s*\n?\s*symbol:\s*(?:class|variable|method)\s+(\w+)"),
    re.compile(r"error CS0246: The type or namespace name '([^']+)'"),
    re.compile(r"error CS0234: The type or namespace name '([^']+)'"),
]
_FOLLOW_ON = re.compile(r"cannot find symbol|does not exist|CS0246|CS0234|CS0103|was not declared in this scope|"
                        r"unknown type name|has not been declared|incomplete type|No such file|file not found|"
                        r"^\s*\d+ errors? generated|compilation terminated", re.I)


def _missing(output: str) -> list:
    found = []
    for rx in _MISSING:
        found += rx.findall(output or "")
    return sorted(set(found))


def _compiler_pass(path: Path, lang: str, code: str):
    from core import validate
    if lang == "cpp":
        cc = validate._which("g++") or validate._which("clang++")
        if not cc:
            return None
        with tempfile.TemporaryDirectory() as td:
            shim = Path(td) / "shim"
            shim.mkdir()
            for name, body in SHIMS.items():
                (shim / name).write_text(body)
            from .grammars import prepare
            target = Path(td) / path.name
            target.write_text(prepare(code, lang))
            rc, out = validate._run([cc, "-fsyntax-only", "-std=gnu++98", "-fpermissive", "-w", "-I", str(shim),
                                     "-x", "c++", str(target)])
            out = out.replace(str(target), path.name)
        return rc, out, f"{Path(cc).name} -fsyntax-only -std=gnu++98 -fpermissive"
    if lang == "java":
        res = validate._check_java(path)
    elif lang == "c_sharp":
        res = validate._check_csharp(path)
    else:
        return None
    if not res.get("checked"):
        return None
    return (0 if res.get("ok") else 1), res.get("errors", ""), res.get("tool", "")


def check_legacy_source(path) -> dict:
    from core.validate import _result
    path = Path(path)
    lang = lang_for(extension=path.suffix)
    if lang is None or not available():
        return _result(False, False, "tree-sitter", note="tree-sitter grammars not installed")
    code = path.read_text(errors="replace")
    errors = syntax_errors(code, lang)
    if errors:
        return _result(True, False, "tree-sitter syntax", errors=format_errors(errors, path.name))
    compiled = _compiler_pass(path, lang, code)
    if compiled is None:
        return _result(True, True, "tree-sitter syntax", note="syntax checked; no compiler for a deeper check")
    rc, out, tool = compiled
    if rc == 0:
        return _result(True, True, f"tree-sitter syntax + {tool}")
    missing = _missing(out)
    real = [l for l in out.splitlines() if re.search(r"\berror\b", l, re.I) and not _FOLLOW_ON.search(l)]
    if missing and not real:
        return _result(True, True, f"tree-sitter syntax + {tool}",
                       note="missing dependencies (not captured or not installed): " + ", ".join(missing[:10])
                       + " — compiler check limited to syntax")
    return _result(True, False, f"tree-sitter syntax + {tool}", errors=out)
