"""Remove paragraphs that stitching copied twice.

On highly repetitive COBOL the overlap between two screenshots is ambiguous, so a frame is sometimes appended again,
leaving a paragraph (and sometimes a cut-short copy of it) twice in the stitched text. A paragraph name must be unique
in a COBOL program, so a repeated name is a capture artifact, not a code defect. Only the paragraph name is used as the
signal: the real files are full of near-identical template blocks, so repeated text alone proves nothing.

Of the copies of a name, the most complete one is kept and the others are dropped, but only when they agree with it
(most of the shorter copy's lines appear in order in the longer one). Copies that really differ are left alone: that
may be a genuine defect in the source.
"""
import difflib
import re

_HEADER = re.compile(r"^([A-Za-z0-9][A-Za-z0-9-]*)\s*\.\s*$")
_NOT_PARAGRAPHS = {
    "EXIT", "GOBACK", "CONTINUE", "STOP", "ELSE", "END-IF", "END-PERFORM", "END-EVALUATE", "END-READ", "END-CALL",
    "END-STRING", "END-EXEC", "END-WRITE", "END-REWRITE", "END-DELETE", "END-ADD", "END-SUBTRACT", "END-MULTIPLY",
    "END-DIVIDE", "END-COMPUTE", "END-SEARCH", "END-START", "END-RETURN", "END-UNSTRING", "END-ACCEPT", "END-DISPLAY",
}
MIN_AGREEMENT = 0.8


def paragraph_headers(lines: list) -> list:
    """(index, NAME) of each line that is only a paragraph name in area A (columns 8 to 11, or the margin if the
    capture has no sequence area)."""
    found = []
    for i, line in enumerate(lines):
        match = _HEADER.match(line.strip())
        if not match or match.group(1).isdigit() or match.group(1).upper() in _NOT_PARAGRAPHS:
            continue
        indent = len(line) - len(line.lstrip())
        if (7 <= indent <= 10 and line[6:7] == " ") or indent <= 3:
            found.append((i, match.group(1).upper()))
    return found


def _agreement(shorter: list, longer: list) -> float:
    a = [x.strip() for x in shorter if x.strip()]
    b = [x.strip() for x in longer if x.strip()]
    if not a:
        return 1.0
    blocks = difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()
    return sum(block.size for block in blocks) / len(a)


def drop_repeated_paragraphs(lines: list) -> tuple:
    """(lines without the repeated paragraph copies, names of the paragraphs that were repeated)."""
    headers = paragraph_headers(lines)
    if len({name for _, name in headers}) == len(headers):
        return lines, []
    ends = [i for i, _ in headers[1:]] + [len(lines)]
    copies = {}
    for (start, name), end in zip(headers, ends):
        copies.setdefault(name, []).append((start, end))
    kill, repeated = set(), []
    for name, spans in copies.items():
        if len(spans) < 2:
            continue
        body = lambda span: lines[span[0] + 1:span[1]]
        best = max(spans, key=lambda span: (sum(1 for x in body(span) if x.strip()), -span[0]))
        others = [span for span in spans if span is not best]
        if all(max(_agreement(body(s), body(best)), _agreement(body(best), body(s))) >= MIN_AGREEMENT for s in others):
            for start, end in others:
                kill.update(range(start, end))
            repeated.append(name)
    if not kill:
        return lines, []
    return [line for i, line in enumerate(lines) if i not in kill], repeated
