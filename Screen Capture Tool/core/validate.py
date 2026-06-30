"""Syntax / compile checks for generated source files (Milestone 7, Layer B).

CHECK ONLY — these never RUN the captured program. Each checker invokes the
language's own parser/compiler in a syntax-check mode and reports any errors.
If the required toolchain isn't installed, the check is skipped (checked=False)
and the file is still delivered, just unverified.

check_source(path) -> {
    "checked": bool,   # was a check actually run?
    "ok": bool,        # did it pass? (only meaningful if checked)
    "tool": str,       # what ran (e.g. "gcc -fsyntax-only")
    "errors": str,     # compiler/parser output on failure
    "note": str,       # why a check was skipped, if so
}
"""

import ast
import shutil
import subprocess
import tempfile
from pathlib import Path

TIMEOUT = 30  # seconds per check


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


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
    try:
        ast.parse(path.read_text(), filename=str(path))
        return _result(True, True, "python ast.parse")
    except SyntaxError as e:
        return _result(True, False, "python ast.parse",
                       errors=f"{type(e).__name__}: {e.msg} (line {e.lineno}, col {e.offset})")


def _check_js(path: Path):
    if not _have("node"):
        return _result(False, False, "node --check", note="node not installed")
    rc, out = _run(["node", "--check", str(path)])
    return _result(True, rc == 0, "node --check", errors=out)


def _check_c(path: Path):
    cc = "gcc" if _have("gcc") else ("clang" if _have("clang") else None)
    if cc is None:
        return _result(False, False, "gcc/clang", note="no C compiler installed")
    rc, out = _run([cc, "-fsyntax-only", str(path)])
    return _result(True, rc == 0, f"{cc} -fsyntax-only", errors=out)


def _check_cpp(path: Path):
    cc = "g++" if _have("g++") else ("clang++" if _have("clang++") else None)
    if cc is None:
        return _result(False, False, "g++/clang++", note="no C++ compiler installed")
    rc, out = _run([cc, "-fsyntax-only", str(path)])
    return _result(True, rc == 0, f"{cc} -fsyntax-only", errors=out)


def _check_csharp(path: Path):
    if not _have("csc"):
        return _result(False, False, "csc", note="csc (.NET/Mono) not installed")
    with tempfile.TemporaryDirectory() as td:
        out_dll = Path(td) / "out.dll"
        rc, out = _run(["csc", "-nologo", "-target:library", f"-out:{out_dll}", str(path)])
    return _result(True, rc == 0, "csc", errors=out)


def _check_java(path: Path):
    if not _have("javac"):
        return _result(False, False, "javac", note="javac not installed")
    with tempfile.TemporaryDirectory() as td:
        rc, out = _run(["javac", "-d", td, str(path)])
    return _result(True, rc == 0, "javac", errors=out)


_CHECKERS = {
    "py": _check_python,
    "js": _check_js, "mjs": _check_js, "cjs": _check_js,
    "c": _check_c, "h": _check_c,
    "cpp": _check_cpp, "cc": _check_cpp, "cxx": _check_cpp, "hpp": _check_cpp,
    "cs": _check_csharp,
    "java": _check_java,
}


def check_source(path) -> dict:
    """Syntax/compile-check a source file by extension. Never runs the program."""
    path = Path(path)
    ext = path.suffix.lower().lstrip(".")
    checker = _CHECKERS.get(ext)
    if checker is None:
        return _result(False, False, "", note=f"no checker for .{ext}")
    return checker(path)
