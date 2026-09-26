import os
import re
import tempfile
from pathlib import Path

from .detect import detect_format, detect_kind

DIALECT = os.environ.get("CODESNAP_COBOL_DIALECT", "ibm")
_EXEC = re.compile(r"\bEXEC\s+(CICS|SQL|DLI)\b(.*?)\bEND-EXEC\b", re.I | re.S)
_SQL_INCLUDE = re.compile(r"^\s*INCLUDE\s+([A-Z0-9][A-Z0-9-]*)\s*$", re.I)
_PROCEDURE = re.compile(r"\bPROCEDURE\s+DIVISION\b", re.I)
_WORKING = re.compile(r"^.*\bWORKING-STORAGE\s+SECTION\s*\..*$", re.I | re.M)
_DFH_FUNC = re.compile(r"\bDFH(RESP|VALUE)\s*\(\s*[A-Z0-9-]+\s*\)", re.I)
_EIB = re.compile(r"\bEIB[A-Z0-9]+\b", re.I)
_MISSING = re.compile(r"([A-Za-z0-9][\w-]*(?:\.\w+)?):\s*(?:No such file or directory|not found)", re.I)
_LINE_REF = re.compile(r"(?m)^([^:\n]+):(\d+):")

SQLCA = """       01  SQLCA.
           05  SQLCAID     PIC X(8).
           05  SQLCABC     PIC S9(9) COMP.
           05  SQLCODE     PIC S9(9) COMP.
           05  SQLERRM.
               10  SQLERRML PIC S9(4) COMP.
               10  SQLERRMC PIC X(70).
           05  SQLERRP     PIC X(8).
           05  SQLERRD     PIC S9(9) COMP OCCURS 6 TIMES.
           05  SQLWARN     PIC X(11).
           05  SQLSTATE    PIC X(5).
"""

EIB = """       01  CSNAP-EIB.
           05  EIBTIME     PIC S9(7) COMP-3.
           05  EIBDATE     PIC S9(7) COMP-3.
           05  EIBTRNID    PIC X(4).
           05  EIBTASKN    PIC S9(7) COMP-3.
           05  EIBTRMID    PIC X(4).
           05  EIBCPOSN    PIC S9(4) COMP.
           05  EIBCALEN    PIC S9(4) COMP.
           05  EIBAID      PIC X.
           05  EIBFN       PIC X(2).
           05  EIBRCODE    PIC X(6).
           05  EIBDS       PIC X(8).
           05  EIBREQID    PIC X(8).
           05  EIBRSRCE    PIC X(8).
           05  EIBRESP     PIC S9(8) COMP.
           05  EIBRESP2    PIC S9(8) COMP.
"""


def to_fixed_layout(text: str) -> str:
    if detect_format(text) != "shifted":
        return text
    out = []
    for line in text.splitlines():
        line = line.expandtabs(8)
        if not line.strip():
            out.append("")
        elif line[:1] in "*/":
            out.append("      " + line)
        else:
            out.append("       " + line)
    return "\n".join(out)


def _blank_comments(text: str, fixed: bool) -> str:
    out = []
    for line in text.split("\n"):
        if (fixed and len(line) > 6 and line[6] in "*/") or (not fixed and line.lstrip().startswith("*>")):
            out.append(" " * len(line))
        else:
            out.append(line)
    return "\n".join(out)


def _overwrite(chars: list, start: int, text: str):
    chars[start:start + len(text)] = list(text)


def stub_exec_blocks(text: str, fixed: bool = True) -> tuple:
    masked = _blank_comments(text, fixed)
    proc = _PROCEDURE.search(masked)
    proc_at = proc.start() if proc else len(text)
    chars = list(text)
    blocks, includes = [], []
    for m in _EXEC.finditer(masked):
        for i in range(m.start(), m.end()):
            if chars[i] != "\n":
                chars[i] = " "
        kind = m.group(1).upper()
        include = _SQL_INCLUDE.match(" ".join(m.group(2).split())) if kind == "SQL" else None
        if include and m.start() < proc_at:
            name = include.group(1).upper()
            follows = masked[m.end():m.end() + 80].lstrip(" \n")
            stmt = f"COPY {name}" + ("" if follows.startswith(".") else ".")
            if len(stmt) <= m.end() - m.start():
                _overwrite(chars, m.start(), stmt)
                includes.append(name)
        elif m.start() >= proc_at:
            _overwrite(chars, m.start(), "CONTINUE")
        blocks.append({"kind": kind, "start": text.count("\n", 0, m.start()) + 1,
                       "end": text.count("\n", 0, m.end()) + 1,
                       "body": " ".join(m.group(2).split())})
    out = "".join(chars)
    masked_out = _blank_comments(out, fixed)
    for m in reversed(list(_DFH_FUNC.finditer(masked_out))):
        out = out[:m.start()] + "0".ljust(m.end() - m.start()) + out[m.end():]
    return out, blocks, includes


def _inject_eib(text: str, blocks: list) -> tuple:
    if not (any(b["kind"] == "CICS" for b in blocks) or _EIB.search(text)):
        return text, None
    ws = _WORKING.search(text)
    if not ws:
        return text, None
    line_no = text.count("\n", 0, ws.end()) + 1
    pad = "       " if ws.group(0)[:7].strip() == "" or ws.group(0)[:6].isdigit() else ""
    return text[:ws.end()] + f"\n{pad}COPY CSNAPEIB." + text[ws.end():], line_no


def _remap_lines(out: str, target_name: str, shown_name: str, inserted_after: int | None) -> str:
    def fix(m):
        name, line = m.group(1), int(m.group(2))
        if Path(name).name != target_name:
            return m.group(0)
        if inserted_after is not None and line > inserted_after:
            line = max(inserted_after, line - 1)
        return f"{shown_name}:{line}:"
    return _LINE_REF.sub(fix, out)


def _include_dirs(work: Path, include_dirs) -> list:
    dirs = [str(work)]
    dirs += [str(d) for d in include_dirs or () if d and Path(d).is_dir()]
    env = os.environ.get("CODESNAP_COPYBOOK_DIRS", "")
    dirs += [d for d in env.split(os.pathsep) if d and Path(d).is_dir()]
    return dirs


def _cobc():
    from core.validate import _which
    return _which("cobc")


def _copybook_wrapper(name: str, text: str, fixed: bool) -> str:
    pad = "       " if fixed else ""
    data_items = bool(re.search(r"^.{0,11}\b(0[1-9]|[1-4][0-9]|77)\s", text, re.M))
    head = [f"{pad}IDENTIFICATION DIVISION.", f"{pad}PROGRAM-ID. CPYCHK."]
    if data_items:
        body = [f"{pad}DATA DIVISION.", f"{pad}WORKING-STORAGE SECTION.", f"{pad}COPY {name}.",
                f"{pad}PROCEDURE DIVISION.", f"{pad}    GOBACK."]
    else:
        body = [f"{pad}PROCEDURE DIVISION.", f"{pad}    COPY {name}.", f"{pad}    GOBACK."]
    return "\n".join(head + body) + "\n"


def check_cobol(path, include_dirs=None) -> dict:
    from core.validate import _result, _run
    path = Path(path)
    cobc = _cobc()
    if not cobc:
        return _result(False, False, "cobc", note="GnuCOBOL (cobc) not installed — brew install gnucobol")
    text = path.read_text(errors="replace").expandtabs(8)
    kind = detect_kind(text, extension=path.suffix)
    if kind in ("bms", "jcl"):
        return _result(False, False, "cobc", note=f"no compiler check for {kind.upper()}")
    layout = to_fixed_layout(text)
    fixed = detect_format(layout) != "free"
    stubbed, blocks, includes = stub_exec_blocks(layout, fixed=fixed)
    stubbed, inserted_after = _inject_eib(stubbed, blocks)
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        (work / "SQLCA.cpy").write_text(SQLCA)
        (work / "CSNAPEIB.cpy").write_text(EIB)
        dirs = _include_dirs(work, include_dirs)
        if kind == "copybook":
            name = re.sub(r"[^A-Za-z0-9-]", "", path.stem.upper())[:30] or "CPYCHK"
            (work / f"{name}.cpy").write_text(stubbed)
            target = work / "CPYCHK.cbl"
            target.write_text(_copybook_wrapper(name, stubbed, fixed))
            shown = path.name
            target_name = f"{name}.cpy"
        else:
            target = work / ((re.sub(r"[^A-Za-z0-9_-]", "", path.stem) or "PROGRAM") + ".cbl")
            target.write_text(stubbed)
            shown, target_name = path.name, target.name
        args = [cobc, "-fsyntax-only", f"-std={DIALECT}", "-fixed" if fixed else "-free"]
        for d in dirs:
            args += ["-I", d]
        rc, out = _run(args + [str(target)], timeout=60)
        out = out.replace(str(work) + os.sep, "")
    out = _remap_lines(out, target_name, shown, inserted_after)
    missing = sorted({m.group(1).split(".")[0].upper() for m in _MISSING.finditer(out)})
    notes = []
    if blocks:
        counts = {}
        for b in blocks:
            counts[b["kind"]] = counts.get(b["kind"], 0) + 1
        notes.append("stubbed " + ", ".join(f"{n} EXEC {k}" for k, n in sorted(counts.items())))
    if layout is not text:
        notes.append("sequence area hidden on screen; checked with columns 1-7 restored")
    tool = f"cobc -fsyntax-only -std={DIALECT} {'-fixed' if fixed else '-free'}"
    if missing:
        notes.append("missing copybooks: " + ", ".join(missing) + " — capture them to complete the compile check")
        res = _result(False, False, tool, note="; ".join(notes))
    else:
        res = _result(True, rc == 0, tool, errors="" if rc == 0 else out, note="; ".join(notes))
    res.update({"missing_copybooks": missing, "exec_blocks": blocks, "sql_includes": includes})
    return res
