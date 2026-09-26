import re

from .compile import to_fixed_layout
from .detect import detect_format, detect_kind

_INDICATORS = set(" *-/Dd$")
_DIVISION = re.compile(r"^(IDENTIFICATION|ID|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b", re.I)
_SECTION = re.compile(r"^[A-Z0-9][A-Z0-9-]*\s+SECTION\s*\.", re.I)
_FD = re.compile(r"^(FD|SD)\s+[A-Z0-9]", re.I)
_TOP_LEVEL = re.compile(r"^(01|1|77)\s+[A-Z0-9]", re.I)
_PARAGRAPH = re.compile(r"^([A-Z0-9][A-Z0-9-]*)\s*\.\s*$", re.I)
_PERFORM = re.compile(r"\bPERFORM\s+([A-Z0-9][A-Z0-9-]*)", re.I)
_VERB = re.compile(r"^(ACCEPT|ADD|CALL|CLOSE|COMPUTE|CONTINUE|DELETE|DISPLAY|DIVIDE|ELSE|END-[A-Z]+|EVALUATE|EXEC|"
                   r"EXIT|GO|GOBACK|IF|INITIALIZE|INSPECT|MOVE|MULTIPLY|OPEN|PERFORM|READ|RETURN|REWRITE|SEARCH|"
                   r"SET|SORT|START|STOP|STRING|SUBTRACT|UNSTRING|WHEN|WRITE)\b", re.I)


def _issue(line_no, line, problem, note):
    return {"line": line_no, "line_text": line.strip(), "problem": problem, "note": note}


def lint_columns(text: str) -> list:
    if detect_kind(text) not in ("cobol", "copybook"):
        return []
    layout = to_fixed_layout(text)
    if detect_format(layout) == "free":
        return []
    raw_lines = text.splitlines()
    lines = [l.expandtabs(8) for l in layout.splitlines()]
    targets = {m.group(1).upper() for l in lines for m in _PERFORM.finditer(l[7:72] if len(l) > 7 else "")}
    issues, division = [], None
    for n, line in enumerate(lines, 1):
        original = raw_lines[n - 1] if n - 1 < len(raw_lines) else line
        if "\t" in original:
            issues.append(_issue(n, original, "tab", "tab character — column positions depend on tab width"))
        if len(line) <= 6 or not line[6:].strip():
            continue
        indicator = line[6]
        if indicator not in _INDICATORS:
            issues.append(_issue(n, line[6:72], "column 7",
                                 f"'{indicator}' in column 7 is not a valid indicator (blank, *, /, -, D)"))
            continue
        if indicator in "*/":
            continue
        area = line[7:72]
        code = area.strip()
        starts_in_a = area[:4].strip() != ""
        start_col = 8 + (len(area) - len(area.lstrip()))
        d = _DIVISION.match(code)
        if d:
            division = d.group(1).upper()
        needs_a = bool(d or _SECTION.match(code) or _FD.match(code) or
                       (division in (None, "DATA") and _TOP_LEVEL.match(code)))
        para = _PARAGRAPH.match(code)
        if division == "PROCEDURE" and para and para.group(1).upper() in targets:
            needs_a = True
        if needs_a and not starts_in_a:
            issues.append(_issue(n, code, "Area A",
                                 f"starts in column {start_col}; headers, paragraph names, FD and 01/77 levels "
                                 "must start in Area A (columns 8-11)"))
        elif division == "PROCEDURE" and starts_in_a and _VERB.match(code) and not para:
            issues.append(_issue(n, code, "Area B",
                                 f"statement starts in column {start_col}; statements belong in Area B (column 12+)"))
        if len(line) > 72 and line[71] != " " and line[72] != " ":
            issues.append(_issue(n, code, "column 72",
                                 "text runs past column 72 — the compiler ignores columns 73-80"))
    return issues


COLUMN_REVIEW_SYSTEM = (
    "You compare a screenshot of fixed-format COBOL (or a copybook) with its transcription and report COLUMN "
    "placement differences ONLY. In fixed format, columns 1-6 are the sequence area, column 7 is the indicator "
    "(blank, *, /, -, D), columns 8-11 are Area A (division/section/paragraph headers, FD, 01/77 levels) and "
    "columns 12-72 are Area B (statements). For each line where the SCREENSHOT places the text in a different area "
    "than the transcription, or shows a different column-7 indicator, report it. Judge only by visible horizontal "
    "position on screen; do not report what the code should be.\n"
    "Return ONLY a JSON object: {\"issues\": [{\"line_text\": <the line's code, trimmed>, \"problem\": "
    "<\"Area A\"|\"Area B\"|\"column 7\">, \"note\": <what the screenshot shows, e.g. 'paragraph name starts in "
    "Area B on screen'>}]}. Return an EMPTY issues array if the columns match. Be CONSERVATIVE: only report a line "
    "you are confident about."
)


def review_columns(client, image_paths, code: str) -> list:
    import base64
    from pathlib import Path
    from core.analysis import MODEL, _media_type, _parse_json
    content = []
    for p in sorted(image_paths or [])[:8]:
        try:
            p = Path(p)
            content.append({"type": "image", "source": {"type": "base64", "media_type": _media_type(p),
                                                          "data": base64.standard_b64encode(p.read_bytes()).decode()}})
        except Exception:
            pass
    if not content or not (code or "").strip():
        return []
    ruler = "         1         2         3         4         5         6         7\n" \
            "123456789012345678901234567890123456789012345678901234567890123456789012"
    content.append({"type": "text", "text": f"Transcription (column ruler first):\n{ruler}\n{code}\n\n"
                                            "Report column placement differences. Return only the JSON object."})
    try:
        msg = client.messages.create(model=MODEL, max_tokens=1024, system=COLUMN_REVIEW_SYSTEM,
                                     messages=[{"role": "user", "content": content}])
        data = _parse_json("".join(getattr(b, "text", "") for b in msg.content).strip()) or {}
        issues = data.get("issues", []) if isinstance(data, dict) else []
        return [i for i in issues if isinstance(i, dict) and str(i.get("line_text", "")).strip()]
    except Exception:
        return []


def merge_column_review(errors: str, lint: list, seen: list, code: str) -> str:
    grounded = [i for i in seen or [] if str(i.get("line_text", "")).strip() in (code or "")]
    lint_texts = {i["line_text"] for i in lint or []}
    grounded = [i for i in grounded if str(i.get("line_text", "")).strip() not in lint_texts]
    parts = []
    if lint:
        parts.append("Column layout issues in the transcription:\n" + "\n".join(
            f"- line {i['line']} ({i['problem']}): {i['line_text']} — {i['note']}" for i in lint))
    if grounded:
        parts.append("Column differences seen in the screenshot (lower confidence — verify against the original):\n"
                     + "\n".join(f"- {i.get('problem', 'column')}: {str(i.get('line_text', '')).strip()}"
                                 + (f" ({i.get('note', '').strip()})" if i.get("note") else "") for i in grounded))
    if not parts:
        return errors
    note = "\n\n".join(parts)
    return note if errors in ("", "None", None) else errors + "\n\n" + note
