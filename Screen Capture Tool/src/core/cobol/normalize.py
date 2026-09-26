import re

from .detect import detect_kind

_ASCII = str.maketrans({"—": "-", "–": "-", "‒": "-", "−": "-", "‘": "'", "’": "'",
                        "“": '"', "”": '"', " ": " ", "…": "..."})
_CONTINUATION = re.compile(r"^(.*?[^ ])( {2,})([^ ])$")


def normalize_transcription(text: str) -> str:
    kind = detect_kind(text)
    if kind is None:
        return text
    lines = [l.translate(_ASCII).expandtabs(8).rstrip() for l in text.split("\n")]
    if kind in ("cobol", "copybook"):
        lines = _fix_comment_indicator(lines)
    if kind == "bms":
        lines = [_place_continuation(l) for l in lines]
        for i in range(1, len(lines)):
            if len(lines[i - 1]) >= 72 and lines[i - 1][71] != " " and lines[i].strip():
                lines[i] = " " * 15 + lines[i].lstrip()
    return "\n".join(lines)


def _place_continuation(line: str) -> str:
    m = _CONTINUATION.match(line)
    if not m or not m.group(1).rstrip().endswith(","):
        return line
    body = m.group(1)
    if len(body) >= 71:
        return line
    return body.ljust(71) + m.group(3)


def _fix_comment_indicator(lines: list) -> list:
    fixed = sum(1 for l in lines if len(l) > 7 and l[:6].strip(" 0123456789") == "" and l[6] in " *-/")
    if fixed < 0.6 * max(1, sum(1 for l in lines if l.strip())):
        return lines
    out = []
    for l in lines:
        star = l.find("*")
        if 0 <= star < 6 and l[:star].strip() == "" and not l[:6].strip(" *"):
            l = " " * 6 + l[star:]
        out.append(l)
    return out
