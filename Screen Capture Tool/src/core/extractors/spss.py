import re
from pathlib import Path

from .common import entity, rel

_READ = re.compile(r"^\s*(GET\s+(?:FILE|DATA|SAS|STATA|TRANSLATE|CAPTURE)|DATA\s+LIST|MATCH\s+FILES|ADD\s+FILES|"
                   r"UPDATE)\b[^.]*?\b(?:FILE|OUTFILE)?\s*=\s*['\"]([^'\"]+)['\"]", re.I | re.S)
_FILE_ARG = re.compile(r"/?\b(?:FILE|TABLE)\s*=\s*['\"]([^'\"]+)['\"]", re.I)
_WRITE = re.compile(r"^\s*(SAVE(?:\s+(?:TRANSLATE|OUTFILE|DATA\s+COLLECTION))?|XSAVE|EXPORT|WRITE|OUTPUT\s+EXPORT)\b[^.]*?"
                    r"\bOUTFILE\s*=\s*['\"]([^'\"]+)['\"]", re.I | re.S)
_INCLUDE = re.compile(r"^\s*(INSERT|INCLUDE)\s+(?:FILE\s*=\s*)?['\"]([^'\"]+)['\"]", re.I)
_COMMAND = re.compile(r"^\s*([A-Z][A-Z-]+(?:\s+[A-Z][A-Z-]+)?)", re.I)
_FEATURES = {
    "Python programmability": r"^\s*BEGIN\s+PROGRAM\s+PYTHON",
    "R programmability": r"^\s*BEGIN\s+PROGRAM\s+R\b",
    "Macros (DEFINE-!ENDDEFINE)": r"^\s*DEFINE\s+!",
    "Output Management System (OMS)": r"^\s*OMS\b",
    "Custom tables (CTABLES)": r"^\s*CTABLES\b",
    "Legacy SPSS/PC+ syntax": r"^\s*(SET\s+MORE|PROCEDURE\s+OUTPUT|FINISH)\b",
}
_ANALYSES = {"FREQUENCIES", "DESCRIPTIVES", "CROSSTABS", "REGRESSION", "LOGISTIC", "ANOVA", "ONEWAY", "T-TEST",
             "CORRELATIONS", "FACTOR", "CLUSTER", "MEANS", "EXAMINE", "GLM", "UNIANOVA", "NPAR", "CTABLES", "TABLES",
             "REPORT", "GRAPH", "GGRAPH", "AGGREGATE"}


def _commands(text: str):
    start, buf = 1, []
    for n, line in enumerate(text.splitlines(), 1):
        if not buf:
            start = n
            if not line.strip() or line.strip().startswith("*") or line.strip().upper().startswith("COMMENT"):
                if line.strip().endswith(".") or not line.strip():
                    continue
        buf.append(line)
        if line.rstrip().endswith("."):
            yield start, "\n".join(buf)
            buf = []
    if buf:
        yield start, "\n".join(buf)


def parse_spss(text: str, filename: str = "") -> dict:
    job = Path(filename).name if filename else "syntax.sps"
    entities = [entity("job", job, None, 1, len(text.splitlines()), tool="SPSS")]
    relations, counts, features = [], {}, set()
    for line, cmd in _commands(text):
        head = _COMMAND.match(cmd)
        if head:
            name = head.group(1).upper().split()[0]
            counts[name] = counts.get(name, 0) + 1
        for label, rx in _FEATURES.items():
            if re.search(rx, cmd, re.I | re.M):
                features.add(label)
        w = _WRITE.match(cmd)
        if w:
            relations.append(rel("writes", job, f"data_store:{Path(w.group(2)).name}", line, verb=w.group(1).upper(),
                                 path=w.group(2), store_type="file"))
            continue
        if _READ.match(cmd) or re.match(r"^\s*(GET|DATA\s+LIST|MATCH\s+FILES|ADD\s+FILES)\b", cmd, re.I):
            for f in _FILE_ARG.findall(cmd):
                if f != "*":
                    relations.append(rel("reads", job, f"data_store:{Path(f).name}", line, path=f, store_type="file"))
        inc = _INCLUDE.match(cmd)
        if inc:
            relations.append(rel("includes", job, f"job:{Path(inc.group(2)).name}", line))
    analyses = sorted(k for k in counts if k in _ANALYSES)
    profile = {"language": "SPSS syntax", "frameworks": ["IBM SPSS Statistics"] + sorted(features),
               "settings": {"commands": len(sum(([k] * v for k, v in counts.items()), [])),
                            "distinct_commands": len(counts), "analyses": ", ".join(analyses) or None}}
    return {"entities": entities, "relations": relations, "file_attrs": {"profile": profile}}


def looks_like_spss(text: str) -> bool:
    body = text or ""
    hits = len(re.findall(r"^\s*(GET\s+FILE|DATA\s+LIST|FREQUENCIES|COMPUTE|RECODE|EXECUTE\s*\.|SAVE\s+OUTFILE|"
                          r"VARIABLE\s+LABELS|VALUE\s+LABELS|SELECT\s+IF|DESCRIPTIVES|CROSSTABS)\b", body, re.I | re.M))
    return hits >= 2
