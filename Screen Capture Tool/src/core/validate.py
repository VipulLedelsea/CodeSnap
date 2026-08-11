"""Syntax / compile checks for generated source files (Milestone 7, Layer B).

CHECK ONLY — these never RUN the captured program. Each checker invokes the
language's own parser/compiler in a syntax-check mode and reports any errors.
If the required toolchain isn't installed, the check is skipped (checked=False)
and the file is still delivered, just unverified.

Tools are resolved to ABSOLUTE paths (searching PATH plus common Homebrew/JDK
locations), so checks also work inside a Finder-launched .app, whose PATH is
stripped down and would otherwise miss /opt/homebrew/bin etc.

check_source(path) -> {
    "checked": bool,   # was a check actually run?
    "ok": bool,        # did it pass? (only meaningful if checked)
    "tool": str,       # what ran (e.g. "gcc -fsyntax-only")
    "errors": str,     # compiler/parser output on failure
    "note": str,       # why a check was skipped, if so
}
"""

import ast
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

TIMEOUT = 30  # seconds per check

# macOS GUI apps inherit a minimal PATH (/usr/bin:/bin:...), so Homebrew- and
# JDK-installed compilers won't be found by name. Search these too.
_EXTRA_DIRS = [
    "/opt/homebrew/bin", "/usr/local/bin",
    "/opt/homebrew/opt/openjdk/bin", "/usr/local/opt/openjdk/bin",
    "/opt/homebrew/opt/node/bin", "/usr/local/opt/node/bin",
    "/Library/Frameworks/Mono.framework/Versions/Current/bin",
    "/usr/local/share/dotnet", "/opt/homebrew/share/dotnet",
    "/usr/bin", "/bin", "/usr/sbin", "/sbin",
]


def _which(cmd: str):
    """Absolute path to a tool, or None. Falls back to common install dirs when
    the tool isn't on PATH (the .app case)."""
    p = shutil.which(cmd)
    if p:
        return p
    search = (os.environ.get("PATH", "") + os.pathsep + os.pathsep.join(_EXTRA_DIRS))
    return shutil.which(cmd, path=search)


def _have(cmd: str) -> bool:
    return _which(cmd) is not None


def _run(args: list, timeout: int = TIMEOUT):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, ((p.stderr or "") + (p.stdout or "")).strip()
    except subprocess.TimeoutExpired:
        return 1, f"check timed out after {timeout}s"
    except Exception as exc:  # noqa: BLE001
        return 1, f"{type(exc).__name__}: {exc}"


def _result(checked, ok, tool, errors="", note=""):
    return {"checked": checked, "ok": ok, "tool": tool, "errors": errors, "note": note}


def _check_python(path: Path):
    # Python's own parser, in-process — always available, no external toolchain.
    src = path.read_text()
    try:
        ast.parse(src, filename=str(path))
        return _result(True, True, "python ast.parse")
    except SyntaxError as e:
        lines = src.splitlines()
        snippet = lines[e.lineno - 1].strip() if e.lineno and 1 <= e.lineno <= len(lines) else ""
        loc = f"line {e.lineno}" + (f", col {e.offset}" if e.offset else "")
        detail = f' -> "{snippet}"' if snippet else ""
        return _result(True, False, "python ast.parse",
                       errors=f"{type(e).__name__}: {e.msg} ({loc}){detail}")


def _check_js(path: Path):
    node = _which("node")
    if not node:
        return _result(False, False, "node --check", note="node not installed")
    rc, out = _run([node, "--check", str(path)])
    return _result(True, rc == 0, "node --check", errors=out)


def _check_c(path: Path):
    cc = _which("gcc") or _which("clang")
    if not cc:
        return _result(False, False, "gcc/clang", note="no C compiler installed")
    rc, out = _run([cc, "-fsyntax-only", str(path)])
    return _result(True, rc == 0, f"{Path(cc).name} -fsyntax-only", errors=out)


def _check_cpp(path: Path):
    cc = _which("g++") or _which("clang++")
    if not cc:
        return _result(False, False, "g++/clang++", note="no C++ compiler installed")
    rc, out = _run([cc, "-fsyntax-only", str(path)])
    return _result(True, rc == 0, f"{Path(cc).name} -fsyntax-only", errors=out)


def _check_csharp(path: Path):
    csc = _which("csc")
    if not csc:
        return _result(False, False, "csc", note="csc (.NET/Mono) not installed")
    with tempfile.TemporaryDirectory() as td:
        out_dll = Path(td) / "out.dll"
        rc, out = _run([csc, "-nologo", "-target:library", f"-out:{out_dll}", str(path)])
    return _result(True, rc == 0, "csc", errors=out)


def _check_java(path: Path):
    javac = _which("javac")
    if not javac:
        return _result(False, False, "javac", note="javac not installed")
    src = path.read_text()
    import re
    m = re.search(r"\bpublic\s+(?:final\s+|abstract\s+)?class\s+([A-Za-z_]\w*)", src)
    with tempfile.TemporaryDirectory() as td:
        # javac requires a public class to live in <ClassName>.java — name it to match
        # so we don't report a false "should be declared in a file named X.java" error.
        target = Path(td) / (f"{m.group(1)}.java" if m else path.name)
        target.write_text(src)
        rc, out = _run([javac, "-d", td, str(target)])
    return _result(True, rc == 0, "javac", errors=out)


_CHECKERS = {
    "py": _check_python,
    "js": _check_js, "mjs": _check_js, "cjs": _check_js,
    "c": _check_c, "h": _check_c,
    "cpp": _check_cpp, "cc": _check_cpp, "cxx": _check_cpp, "hpp": _check_cpp,
    "cs": _check_csharp,
    "java": _check_java,
}


_TRUNCATION_MARKERS = (
    "unterminated", "was never closed", "unexpected eof", "unexpected end of input",
    "eof while parsing", "reached end of file while parsing", "at end of input",
    "expected declaration", "premature end", "unexpected end of file",
)


def looks_truncated(errors: str) -> bool:
    """True if the compiler error smells like the capture was cut off (an open
    string/brace never closed, EOF reached mid-statement) rather than a real code
    bug — i.e. the closing part probably wasn't captured."""
    e = (errors or "").lower()
    return any(m in e for m in _TRUNCATION_MARKERS)


def check_source(path) -> dict:
    """Syntax/compile-check a source file by extension. Never runs the program."""
    path = Path(path)
    ext = path.suffix.lower().lstrip(".")
    checker = _CHECKERS.get(ext)
    if checker is None:
        return _result(False, False, "", note=f"no checker for .{ext}")
    return checker(path)
