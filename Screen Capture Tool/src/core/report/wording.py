"""Client-facing wording for the exported report.

The report is handed to an architect as-is (Word / PDF), so it describes the program, not how the review was produced:
no tool or AI names and no mention of screenshots, capture, transcription or scans. Upstream modules (scores, roadmap,
end-of-life notes, diagrams) keep their working vocabulary for the app; this pass rewrites it for the export only.
Matching is case-sensitive on purpose (lowercase and Capitalised words), so upper-case code in evidence snippets such
as the RPG opcode SCAN is never touched.
"""
import re

_RULES = [
    (r" \(FERPA scope\)", ""),
    (r" \(FERPA\)", ""),
    (r"student data", "personal data"),
    (r"student identifiers", "personal identifiers"),
    (r"student fields", "personal data fields"),
    (r"screen review \(vision-observed\)", "screen review"),
    (r"vision-observed", "observed"),
    (r"visible in a screenshot", "shown on screen"),
    (r"Capture File > Account", "Check File > Account"),
    (r"capture or transcription failed", "source could not be read"),
    (r"captured app screens", "application screens"),
    (r"partially captured", "incomplete"),
    (r"not yet captured", "not yet provided"),
    (r"(not|never) captured", r"\1 provided"),
    (r"no (\w+(?: \w+)?) captured", r"no \1 provided"),
    (r"(\d+) captured files", r"\1 files"),
    (r"captured files?", "files reviewed"),
    (r"screenshots", "screens"),
    (r"screenshot", "screen"),
    (r"transcriptions?", "source"),
    (r"transcribed", "reviewed"),
    (r"captured", "reviewed"),
    (r"captures", "provides"),
    (r"capture", "provide"),
    (r"live scan", "website review"),
    (r"website scan", "website review"),
    (r"scanned", "reviewed"),
    (r"scans", "reviews"),
    (r"scan", "review"),
    (r"vision model", "review"),
    (r"vision", "screen"),
    (r"deterministic ", ""),
]
_COMPILED = []
for pat, rep in _RULES:
    for p, r in ((pat, rep), (pat[:1].upper() + pat[1:], rep[:1].upper() + rep[1:] if rep else rep)):
        pre = r"(?<![A-Za-z_\-])" if p[:1].isalpha() else ""
        post = r"(?![A-Za-z_\-])" if p[-1:].isalpha() else ""
        _COMPILED.append((re.compile(pre + p + post), r))

_SKIP_KEYS = {"id", "kind", "type", "from", "to", "source", "target", "slug", "group", "parent", "ref", "src", "dst",
              "href", "status", "level", "bucket", "sev", "category", "rule", "snippet", "quote", "source_line"}


_VERBATIM_COLS = {"Evidence", "Location", "Text", "Files", "File", "Component"}   # quoted code and file names


_PLURAL = re.compile(r"\b(\d+|one|no)((?:[ -][A-Za-z][\w/-]*){0,3}?)[ -]([A-Za-z]+)\((e?s)\)")
_NOUNS = ("component|control|credential|file|finding|interface|issue|job|place|platform|program|routine|screen|set|"
          "statement|store|table|version|class|item|step|risk|user|system|service|library|record|report|rule|error|line|"
          "field|entity|skill|dependency|gap|account|node|flag|module|page|form|query|test|copy|batch|source|tool")
_STRAY_PLURAL = re.compile(rf"\b((?:{_NOUNS}))\((e?s)\)(?![\w(])", re.I)
_ECHO = re.compile(r"\b([A-Za-z0-9][\w ()/-]{3,40}?) in \1\b")


def _plural(word, suffix):
    if word.endswith(("s", "ss", "x", "ch", "sh")):
        return word + "es"
    if word.endswith("y") and word[-2:-1] not in "aeiou":
        return word[:-1] + "ies"
    return word + suffix


def humanize(text: str) -> str:
    """Write counts the way a person would ("1 file", "3 classes", never "file(s)") and drop echoed phrases."""
    def fix(m):
        n, mid, word, suf = m.groups()
        one = n in ("1", "one")
        return f"{n}{mid} {word if one else _plural(word, suf)}"
    text = _PLURAL.sub(fix, text)
    text = _STRAY_PLURAL.sub(lambda m: _plural(m.group(1), m.group(2)), text)
    text = _ECHO.sub(r"\1", text)
    return re.sub(r"(?<=\S)  +(?=\S)", " ", text)


def clean(text: str, verbatim=()) -> str:
    protected = sorted({value for value in verbatim if value}, key=len, reverse=True)
    if protected:
        pattern = "(" + "|".join(re.escape(value) for value in protected) + ")"
        return "".join(part if part in protected else clean(part) for part in re.split(pattern, text))
    for rx, rep in _COMPILED:
        text = rx.sub(rep, text)
    return humanize(text)


def scrub(obj, key=None, verbatim=()):
    """Rewrite every human-readable string in a report or diagram structure (ids and codes are left alone)."""
    if isinstance(obj, str):
        return obj if key in _SKIP_KEYS else clean(obj, verbatim=verbatim)
    if isinstance(obj, dict):
        if obj.get("type") == "table" and isinstance(obj.get("rows"), list):
            keep = {i for i, h in enumerate(obj.get("head") or []) if h in _VERBATIM_COLS}
            rows = [[c if i in keep else scrub(c, verbatim=verbatim) for i, c in enumerate(r)] if isinstance(r, list) else scrub(r, verbatim=verbatim)
                    for r in obj["rows"]]
            return {**{k: scrub(v, k, verbatim) for k, v in obj.items() if k != "rows"}, "rows": rows}
        return {k: scrub(v, k, verbatim) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v, key, verbatim) for v in obj]
    if isinstance(obj, tuple):
        return tuple(scrub(v, key, verbatim) for v in obj)
    return obj
