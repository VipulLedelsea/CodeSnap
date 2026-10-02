import re

KINDS = {
    "cobol": ("COBOL", "cbl"),
    "copybook": ("COBOL copybook", "cpy"),
    "bms": ("CICS BMS map", "bms"),
    "jcl": ("JCL", "jcl"),
}

EXTENSIONS = {"cbl": "cobol", "cob": "cobol", "cobol": "cobol", "cpy": "copybook", "copy": "copybook",
              "bms": "bms", "jcl": "jcl"}

_DIVISION = re.compile(r"\b(IDENTIFICATION|ID|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b", re.I)
_PROGRAM_ID = re.compile(r"\bPROGRAM-ID\s*\.", re.I)
_LEVEL = re.compile(r"^(?:\d{6}[ */Dd-])?\s*(0[1-9]|[1-4][0-9]|66|77|88)\s+[A-Z0-9][A-Z0-9-]*\b", re.I)
_PIC = re.compile(r"\bPIC(TURE)?\s+(IS\s+)?[SX9AVZ(]", re.I)
_BMS = re.compile(r"\bDFHM(SD|DI|DF)\b", re.I)
_JCL_CARD = re.compile(r"^//[A-Z0-9#@$]*\s+(JOB|EXEC|DD|PROC|PEND|SET|INCLUDE|JCLLIB|IF|ENDIF)\b", re.I)
_JCL_ANY = re.compile(r"^//")
_FREE_DIRECTIVE = re.compile(r">>\s*SOURCE\s+(FORMAT\s+)?(IS\s+)?FREE|\$\s*SET\s+SOURCEFORMAT\s*\(?\s*\"?FREE", re.I)
_SEQ = re.compile(r"^[0-9 ]{6}[ *\-/Dd$]")


def _lines(text: str) -> list:
    return [l.expandtabs(8) for l in (text or "").splitlines() if l.strip()]


def detect_kind(text: str, language: str = "", extension: str = "") -> str | None:
    ext = (extension or "").strip().lstrip(".").lower()
    if ext in EXTENSIONS and EXTENSIONS[ext] != "cobol":
        return EXTENSIONS[ext]
    lines = _lines(text)
    if not lines:
        return EXTENSIONS.get(ext)
    body = "\n".join(lines)
    jcl = sum(1 for l in lines if _JCL_ANY.match(l))
    if jcl >= max(2, 0.6 * len(lines)) and any(_JCL_CARD.match(l) for l in lines):
        return "jcl"
    if len(_BMS.findall(body)) >= 2:
        return "bms"
    if _DIVISION.search(body) or _PROGRAM_ID.search(body):
        return "cobol"
    levels = sum(1 for l in lines if _LEVEL.match(l))
    if levels >= max(2, 0.4 * len(lines)) and _PIC.search(body):
        return "copybook"
    if ext in EXTENSIONS:
        return EXTENSIONS[ext]
    lang = (language or "").strip().lower()
    if "cobol" in lang:
        return "copybook" if "copy" in lang else "cobol"
    if lang == "jcl":
        return "jcl"
    if "bms" in lang:
        return "bms"
    return None


def kind_for(language: str = "", extension: str = "", text: str = "") -> str | None:
    return detect_kind(text, language, extension)


def looks_cobol_family(text: str) -> bool:
    return detect_kind(text) is not None


def is_column_sensitive(text: str = "", language: str = "", extension: str = "") -> bool:
    return detect_kind(text, language, extension) is not None


def detect_format(text: str) -> str:
    if _FREE_DIRECTIVE.search(text or ""):
        return "free"
    lines = _lines(text)
    if not lines:
        return "fixed"
    seq_style = sum(1 for l in lines if len(l) >= 7 and _SEQ.match(l))
    if seq_style >= 0.8 * len(lines):
        return "fixed"
    starts = [len(l) - len(l.lstrip()) for l in lines]
    if min(starts) == 0 and sum(1 for s in starts if s == 0) >= 0.3 * len(lines):
        return "shifted" if max(len(l) for l in lines) <= 65 else "free"
    return "free"
