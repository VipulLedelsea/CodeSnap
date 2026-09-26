"""Legacy language packs: deterministic structure extraction, validation and security/EOL signals for languages
beyond COBOL / C++ / C# / Java (VB6, VBA, Classic ASP, RPG, CL, Natural, PL/I, HLASM, REXX, CLIST, Easytrieve, SAS,
PL/SQL, T-SQL, PowerBuilder, ColdFusion, PHP, Perl, shell, batch, PowerShell, Python, JavaScript, Delphi, FoxPro,
Informix 4GL, Progress ABL, Fortran, line-numbered BASIC) plus special artifacts (IMS DBD/PSB/MFS, SSIS, Oracle
Forms/Reports, ISPF panels, Informix forms, Delphi forms, XAML/Silverlight, PowerBuilder DataWindows)."""
import re

from .engine import blank_comments, block_check, parse_with
from .special import SPECIAL_EXTS, enrich_cobol, parse_special, special_for
from .specs import BY_ID, EXT_INDEX, PACKS

PARSER_VERSION = "langpacks-v1"
R = re.compile

EXTRA = [
    {"id": "fortran", "label": "Fortran", "family": "fortran", "exts": ["f", "for", "f77", "f90", "ftn"], "names": ["fortran"],
     "detect": [r"^\s*(PROGRAM|SUBROUTINE|FUNCTION)\s+\w+", r"^\s+COMMON\s*/", r"^\s+DO\s+\d+\s+\w+\s*=", r"^\s+FORMAT\s*\(", r"^[Cc*]\s"],
     "quotes": "'", "fixed_comment": lambda l: l[:1] in ("C", "c", "*", "!") and not l[1:2].isalnum() or l.lstrip().startswith("!"),
     "upper_names": True,
     "units": [("function", r"^\s+(?:\w+\s+)?(?:SUBROUTINE|FUNCTION)\s+(?P<name>\w+)"), ("program", r"^\s+PROGRAM\s+(?P<name>\w+)")],
     "unit_end": {"function": R(r"^\s+END\s*(SUBROUTINE|FUNCTION)?\s*\w*\s*$", re.I)},
     "calls": [("calls", r"\bCALL\s+(?P<target>\w+)", "function")],
     "includes": [(r"^\s+INCLUDE\s+'(?P<target>[^']+)'", "copybook")],
     "files": [("uses", r"\bOPEN\s*\(\s*(?:UNIT\s*=\s*)?\d+\s*,\s*FILE\s*=\s*'(?P<target>[^']+)'", "file")],
     "legacy": [("Arithmetic IF / computed GOTO", r"\bIF\s*\([^)]*\)\s*\d+\s*,\s*\d+|\bGO\s*TO\s*\("), ("COMMON blocks", r"^\s+COMMON\b"),
                ("GOTO", r"\bGO\s*TO\s+\d+"), ("EQUIVALENCE", r"\bEQUIVALENCE\b")],
     "dialects": [("Fortran 90+ free-form", r"^\s*(MODULE|USE)\s+\w+|::"), ("FORTRAN 77 fixed-form", r"^\s{6}\S")],
     "blocks": [(r"^\s+(SUBROUTINE|FUNCTION|PROGRAM)\b", r"^\s+END\s*(SUBROUTINE|FUNCTION|PROGRAM)?\s*\w*\s*$", "unit/END")]},
    {"id": "basic", "label": "Line-numbered BASIC", "family": "vb", "exts": ["bas", "gwb", "qb"], "names": ["gw-basic", "qbasic", "quickbasic", "basic"],
     "detect": [r"^\s*\d+\s+(PRINT|LET|IF|GOTO|GOSUB|REM|DIM|INPUT)\b", r"^\s*\d+\s+GOSUB\s+\d+", r"^\s*\d+\s+RETURN\b"],
     "quotes": '"', "line_comment": [R(r"'"), R(r"(?i)^\s*\d+\s+REM\b")], "upper_names": True,
     "units": [("paragraph", r"^\s*(?P<name>\d+)\s+REM\s+\*+\s*\w")],
     "calls": [("calls", r"\bGOSUB\s+(?P<target>\d+)", "paragraph")],
     "files": [("reads", r"\bOPEN\s+\"(?P<target>[^\"]+)\"\s+FOR\s+INPUT", "file"), ("writes", r"\bOPEN\s+\"(?P<target>[^\"]+)\"\s+FOR\s+(OUTPUT|APPEND)", "file"),
               ("reads", r"\bOPEN\s+\"I\",\s*#?\d+,\s*\"(?P<target>[^\"]+)\"", "file")],
     "legacy": [("Line numbers + GOTO/GOSUB", r"\bGO(TO|SUB)\s+\d+"), ("DOS-era BASIC interpreter", r"^\s*\d+\s")],
     "techs": [{"curated": "gwbasic"}]},
]
ALL = PACKS + EXTRA
for _p in EXTRA:
    BY_ID[_p["id"]] = _p
    for _e in _p["exts"]:
        EXT_INDEX.setdefault(_e, []).append(_p)

_DETECT = {p["id"]: [R(rx, re.M | re.I) for rx in p.get("detect", [])] for p in ALL}
WEB_MERGE = {"vbscript", "coldfusion", "php"}
AMBIGUOUS_EXTS = {e for e, ps in EXT_INDEX.items() if len(ps) > 1}


def _ext(filename):
    name = (filename or "").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def score(pack, text) -> int:
    body = (text or "")[:40000]
    return sum(1 for rx in _DETECT.get(pack["id"], []) if rx.search(body))


def _by_name(language):
    lang = (language or "").strip().lower()
    if not lang or lang in ("text", "plain text", "unknown"):
        return None
    for p in ALL:
        if any(lang == n for n in p.get("names", [])):
            return p
    for p in ALL:
        if any(lang.startswith(n + " ") or lang.startswith(n + "(") for n in p.get("names", []) if len(n) > 3):
            return p
    return None


def pack_for(filename: str = "", language: str = "", text: str = "", min_score: int = 3):
    """Pick the language pack: extension first (content decides ambiguous extensions), then the language name,
    then content alone (needs `min_score` distinct signals)."""
    ext = _ext(filename)
    cands = EXT_INDEX.get(ext) or []
    if len(cands) == 1:
        return cands[0]
    if cands:
        named = _by_name(language)
        if named in cands:
            return named
        if ext == "bas":
            if re.search(r"^\s*\d+\s+(PRINT|LET|IF|GOTO|GOSUB|REM|DIM)\b", text or "", re.M | re.I) and \
                    len(re.findall(r"^\s*\d+\s", text or "", re.M)) >= 0.6 * max(1, len([l for l in (text or "").splitlines() if l.strip()])):
                return BY_ID["basic"]
            if re.search(r"DoCmd\.|CurrentDb|Forms!|ThisWorkbook|Worksheets?\(|Application\.(Run|Workbooks)", text or ""):
                return BY_ID["vba"]
            if re.search(r"^Attribute VB_Name", text or "", re.M):
                return BY_ID["vb6"]
            return BY_ID["vba"]
        ranked = sorted(cands, key=lambda p: -score(p, text))
        return ranked[0]
    named = _by_name(language)
    if named:
        return named
    if ext in ("sql", "ddl", "db2", "prc", "pkg"):
        ranked = sorted((BY_ID["plsql"], BY_ID["tsql"]), key=lambda p: -score(p, text))
        return ranked[0] if score(ranked[0], text) >= 2 else None
    if ext not in ("", "txt", "text", "src", "mbr", "source"):
        return None
    best, best_score = None, 0
    for p in ALL:
        s = score(p, text)
        if s > best_score:
            best, best_score = p, s
    return best if best_score >= min_score else None


def claims(text: str, filename: str = "", language: str = "", artifact_type: str = "") -> bool:
    """True when a pack should run before the generic extractors (web/sql/config artifacts)."""
    sid, _ = special_for(text, filename)
    if sid:
        return True
    p = pack_for(filename, language, text)
    if not p:
        return False
    if p["id"] in WEB_MERGE:
        return True
    if p.get("merge_sql"):
        return score(p, text) >= 2
    return artifact_type not in ("sql", "db_schema", "config", "api", "web", "ui_screen")


def _merge(base, extra):
    if not extra:
        return base
    base["entities"] = base.get("entities", []) + extra.get("entities", [])
    base["relations"] = base.get("relations", []) + extra.get("relations", [])
    xp = (extra.get("file_attrs") or {}).get("profile") or {}
    bp = base.setdefault("file_attrs", {}).setdefault("profile", {})
    for key in ("libraries", "frameworks", "legacy_markers"):
        if xp.get(key):
            bp[key] = sorted(set(bp.get(key) or []) | set(xp[key]))
    for key, val in (xp.get("evidence") or {}).items():
        bp.setdefault("evidence", {}).setdefault(key, val)
    for key in ("settings", "doctype"):
        if xp.get(key) and not bp.get(key):
            bp[key] = xp[key]
    return base


LLM_FIRST = {"python", "javascript"}


def parse(text: str, filename: str = "", language: str = "", skip_llm_first: bool = False) -> dict | None:
    """Deterministic structure for a legacy file, or None. `skip_llm_first` leaves modern languages (Python, JS) to
    the LLM extractor, which models nesting better; their profile is still attached afterwards."""
    ext = _ext(filename)
    if ext in SPECIAL_EXTS or special_for(text, filename)[0]:
        out = parse_special(text, filename)
        if out is not None:
            return out
    pack = pack_for(filename, language, text)
    if pack is None or (skip_llm_first and pack["id"] in LLM_FIRST):
        return None
    out = parse_with(pack, text, filename)
    if pack["id"] == "vb6":
        _vb6_forms(text, out)
    if pack["id"] in ("powershell", "batch"):
        local = {e["name"].lower() for e in out["entities"]}
        out["relations"] = [r for r in out["relations"] if r["kind"] != "calls" or ":" not in r["target"]
                            or r["target"].split(":", 1)[0] not in ("function", "paragraph")
                            or r["target"].split(":", 1)[1].lower() in local]
    try:
        if pack["id"] in WEB_MERGE and re.search(r"<\s*(html|form|body|input|table|div|script)\b|<%", text or "", re.I):
            from core.extractors.web import parse_web_page
            out = _merge(out, parse_web_page(text, filename))
        if pack.get("merge_sql"):
            from core.extractors.sql import parse_sql
            out = _merge(out, parse_sql(text, filename))
    except Exception:
        pass
    out["lang"] = pack["id"]
    return out


def _vb6_forms(text, out):
    from core.extractors.common import entity
    form = None
    for n, line in enumerate((text or "").splitlines(), 1):
        m = re.match(r"^\s*Begin\s+VB\.(\w+)\s+(\w+)", line)
        if not m:
            continue
        if m.group(1) in ("Form", "MDIForm") and form is None:
            form = m.group(2)
            out["entities"].append(entity("screen", form, None, n, None, technology="VB6 form"))
        elif form and sum(1 for e in out["entities"] if e["kind"] == "ui_element") < 150:
            cap = re.search(r'Caption\s*=\s*"([^"]*)"', "\n".join((text or "").splitlines()[n:n + 12]))
            out["entities"].append(entity("ui_element", m.group(2), form, n, n, control=m.group(1),
                                          label=cap.group(1) if cap else None))


def strip_comments(text: str, pack_id: str) -> list:
    pack = BY_ID.get(pack_id)
    return blank_comments(text, pack) if pack else (text or "").splitlines()


def check(text: str, filename: str = "", language: str = ""):
    """Structural check (balanced blocks) for languages with no compiler on the Mac. Returns (ok, errors, tool) or None."""
    pack = pack_for(filename, language, text)
    if pack is None:
        return None
    return block_check(pack, text)


__all__ = ["ALL", "BY_ID", "PARSER_VERSION", "check", "claims", "enrich_cobol", "pack_for", "parse", "score", "strip_comments"]
