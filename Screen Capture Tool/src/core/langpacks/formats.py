import re

FORMATS = {
    "rpg_fixed": "RPG fixed-form (form type in column 6)",
    "asm": "Assembler / macro source (label col 1, opcode col 10, operands col 16, continuation col 72)",
    "natural": "Natural (line-numbered source)",
    "basic": "Line-numbered BASIC",
    "pli": "PL/I (source margins 2-72)",
    "fortran": "Fortran fixed-form",
    "ispf_panel": "ISPF panel definition",
    "informix_form": "Informix screen form (box characters and field columns)",
}
_RPG_SPEC = re.compile(r"^.{5}[HFDICOP][ A-Z*]", re.I)
_RPG_OPS = re.compile(r"\b(BEGSR|ENDSR|EXSR|CHAIN|SETLL|READE?|WRITE|UPDATE|EVAL|IFEQ|DOWEQ|MOVEL?|Z-ADD|CALLB?)\b", re.I)
_ASM_OP = re.compile(r"^(?:[A-Z@#$][A-Z0-9@#$]{0,7})?\s+(CSECT|DSECT|USING|DROP|BALR|BAL|BR|LA|LR|L|ST|STM|LM|MVC|CLC|CLI|"
                     r"DC|DS|EQU|ENTRY|EXTRN|AMODE|RMODE|MACRO|MEND|DBD|DATASET|SEGM|FIELD|LCHILD|PCB|SENSEG|PSBGEN|DBDGEN|"
                     r"FMT|DEV|DIV|DPAGE|DFLD|MSG|LPAGE|SEG|MFLD|FMTEND|MSGEND|DFHMSD|DFHMDI|DFHMDF|DCB|OPEN|CLOSE|GET|PUT|"
                     r"END|LTORG|PRINT|TITLE|EJECT)\b", re.I)
_NATURAL = re.compile(r"^\d{4}\s+(DEFINE|END-DEFINE|READ|FIND|IF|END-IF|WRITE|DISPLAY|INPUT|CALLNAT|FETCH|PERFORM|"
                      r"MOVE|COMPUTE|ASSIGN|FOR|END-FOR|DECIDE|END-DECIDE|ESCAPE|END|REPEAT|END-REPEAT|STORE|UPDATE|"
                      r"DELETE|INCLUDE|LOCAL|PARAMETER|GLOBAL|1|2|3|\*)", re.I)
_BASIC = re.compile(r"^\s*\d{1,5}\s+(?:(PRINT|LET|IF|GOTO|GOSUB|RETURN|INPUT|DIM|FOR|NEXT|REM|OPEN|CLOSE|END|ON|DATA|READ|RESTORE|DEF\s+FN|POKE|WHILE|WEND|DO|LOOP|ELSE|ERROR|RESUME|CALL)\b|[A-Z_][\w$%]*(?:\([^)]*\))?\s*=)", re.I)
_PLI = re.compile(r"\b(PROC(EDURE)?\s+OPTIONS\s*\(\s*MAIN|DCL\s+\w+\s+(FIXED|CHAR|BIN|DEC)|%INCLUDE)\b", re.I)
_FORTRAN = re.compile(r"^(C|\*|\s{5}[^ 0]|\s{6})\s*(PROGRAM|SUBROUTINE|FUNCTION|DIMENSION|COMMON|FORMAT|CALL|DO\s+\d+)\b", re.I)
_FORTRAN_LABEL = re.compile(r"^ {0,4}\d{1,5}\s+(CONTINUE|GO\s*TO|STOP|RETURN|FORMAT|END)\b", re.I)
_ISPF = re.compile(r"^\)(ATTR|BODY|INIT|PROC|MODEL|END|REINIT|HELP)\b", re.I)
EXT_FORMATS = {"rpg": "rpg_fixed", "rpg38": "rpg_fixed", "rpg36": "rpg_fixed", "asm": "asm", "mac": "asm", "mlc": "asm",
               "hlasm": "asm", "dbd": "asm", "psb": "asm", "mfs": "asm", "nsp": "natural", "nsn": "natural",
               "nss": "natural", "nsl": "natural", "nsm": "natural", "nsc": "natural", "nsg": "natural", "nsh": "natural",
               "nat": "natural", "f": "fortran", "for": "fortran", "f77": "fortran", "pnl": "ispf_panel"}


def _lines(text):
    return [l.expandtabs(8) for l in (text or "").splitlines() if l.strip()]


def detect_format(text: str = "", language: str = "", extension: str = "") -> str | None:
    ext = (extension or "").strip().lstrip(".").lower()
    lang = (language or "").lower()
    lines = _lines(text)
    if ext in ("rpgle", "sqlrpgle"):
        return None if (text or "").lstrip().upper().startswith("**FREE") else ("rpg_fixed" if lines and sum(
            1 for l in lines if _RPG_SPEC.match(l)) >= 0.5 * len(lines) else None)
    if ext in EXT_FORMATS:
        return EXT_FORMATS[ext]
    if not lines:
        return None
    n = len(lines)
    if "natural" in lang or sum(1 for l in lines if _NATURAL.match(l)) >= max(2, 0.5 * n):
        return "natural"
    if ("rpg" in lang and "free" not in lang) or (sum(1 for l in lines if _RPG_SPEC.match(l)) >= max(3, 0.6 * n)
                                                and _RPG_OPS.search("\n".join(lines))):
        return "rpg_fixed"
    if sum(1 for l in lines if _ASM_OP.match(l)) >= max(3, 0.5 * n) or "assembler" in lang or "hlasm" in lang:
        return "asm"
    if sum(1 for l in lines if _BASIC.match(l)) >= max(3, 0.6 * n):
        return "basic"
    if sum(1 for l in lines if _ISPF.match(l)) >= 2:
        return "ispf_panel"
    if (re.search(r'^\s*SCREEN\s*(?:\{|$)', text or '', re.M | re.I)
            and re.search(r'^\s*ATTRIBUTES\b', text or '', re.M | re.I)):
        return 'informix_form'
    if sum(1 for l in lines if _FORTRAN.match(l) or _FORTRAN_LABEL.match(l)) >= max(2, 0.3 * n) and "fortran" in (lang or "fortran"):
        return "fortran"
    if "pl/i" in lang or "pli" in lang or _PLI.search("\n".join(lines)):
        return "pli"
    return None


from core.transcription_formats import PROMPT_CLAUSE as _MULTIFORMAT_CLAUSE

PROMPT_CLAUSE = (
    "OTHER COLUMN- OR LINE-NUMBER-SENSITIVE SOURCE: in RPG, assembler and IMS/MFS macros copy the actually visible "
    "columns, including unusual or invalid spacing. Never place text in conventional compiler columns by assumption. In "
    "Natural and line-numbered BASIC the line numbers at the start of each line (e.g. 0010, 0020 or 10, 20) are PART OF "
    "THE SOURCE — keep them, they are not an editor gutter; PL/I source preserves its observed margin; ISPF panels keep their "
    ")ATTR/)BODY sections and column layout exactly. ") + _MULTIFORMAT_CLAUSE


_MACRO_OPS = ("DBD|DATASET|SEGM|FIELD|LCHILD|XDFLD|PCB|SENSEG|SENFLD|PSBGEN|DBDGEN|FINISH|PRINT|FMT|DEV|DIV|DPAGE|DFLD|"
              "MSG|LPAGE|SEG|MFLD|FMTEND|MSGEND|DFHMSD|DFHMDI|DFHMDF|CSECT|DSECT|USING|DROP|EQU|DC|DS|LTORG|END")
_MACRO_LINE = re.compile(r"^(" + _MACRO_OPS + r")(\s+\S|\s*$)", re.I)


def looks_dedented_asm(text: str) -> bool:
    """IMS DBD/PSB/MFS and assembler macros whose opcodes landed in column 1 (a transcription that
    dropped the leading blanks). Column 1 is the label field, so these lines lost their columns."""
    lines = [l for l in (text or "").splitlines() if l.strip() and not l.lstrip().startswith("*")]
    hits = sum(1 for l in lines if _MACRO_LINE.match(l))
    return len(lines) >= 3 and hits >= 0.6 * len(lines)


def restore_asm_columns(text: str) -> str:
    """Put an unlabelled macro/assembler statement back at column 10 when its opcode sits in column 1.
    Only fires when the source is mostly such lines (see looks_dedented_asm); labelled lines, comments
    and anything already indented are left exactly as transcribed."""
    if not looks_dedented_asm(text):
        return text
    out = []
    for l in text.split("\n"):
        m = _MACRO_LINE.match(l)
        nxt = l.split()[1] if len(l.split()) > 1 else ""
        if m and not _MACRO_LINE.match(nxt):
            l = " " * 9 + l
        out.append(l)
    return "\n".join(out)


def minimal_clean(text: str) -> str:
    lines = [l.expandtabs(8).rstrip() for l in (text or "").replace("\r\n", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(l.replace("—", "-").replace("–", "-").replace("‘", "'").replace("’", "'")
                     .replace("“", '"').replace("”", '"') for l in lines)
