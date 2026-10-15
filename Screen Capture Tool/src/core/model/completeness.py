"""Detect partially captured files (cut-off end, missing start, gaps) from the transcription alone. 0 tokens."""
import re

from core.validate import looks_truncated

_BRACE_FAMS = {"cs", "java", "cpp", "js", "php", "perl", "powershell", "delphi"}
_SEQ = re.compile(r"^(\d{6})[ *\-/Dd$]")
_NAT = re.compile(r"^(\d{4})\s")
_LABEL = re.compile(r"^\s{0,4}([A-Za-z_]{1,8}?)(\d{1,5}):\s*(?:PROC|PROCEDURE|BEGIN|DO|ENTRY|\s*$)", re.I)     # R18: PROC;
_PARAGRAPH = re.compile(r"^.{6} \s{0,3}(\d{3,5})-([A-Za-z][\w-]*)\.\s*$")                                    # 5050-CHECK-05.


def _balance(lines, open_ch, close_ch):
    depth, low = 0, 0
    for line in lines:
        for ch in line:
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                low = min(low, depth)
    return depth, low


def _seq_gaps(lines, rx, width):
    nums = [int(m.group(1)) for m in (rx.match(l) for l in lines) if m]
    if len(nums) < 8:
        return []
    steps = sorted(b - a for a, b in zip(nums, nums[1:]) if b > a)
    step = steps[len(steps) // 2] if steps else 0
    if step <= 0:
        return []
    return [(a, b) for a, b in zip(nums, nums[1:]) if b - a > max(step * 25, step + 10 ** (width - 3))]


def shifted_spacing(raw, min_run=20) -> list:
    """(first line, last line) of runs of COBOL statements indented one column off the file's own step pattern.
    COBOL statements sit at steps of four from the margin, so in a file where 90% or more share one indent remainder, a
    run of 20 or more lines with the next remainder is a screenshot that was read one column to the side. Flagged, not
    rewritten: the transcription is evidence."""
    import collections
    rows = []
    for i, line in enumerate(raw, 1):
        text = line.strip()
        if not text or len(line) < 8 or line[6:7] == "*" or text.startswith("*"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent >= 11:      # area A names and divisions are not statements
            rows.append((i, indent % 4))
    if len(rows) < 60:
        return []
    major, count = collections.Counter(m for _, m in rows).most_common(1)[0]
    if count / len(rows) < 0.9:
        return []
    out, run = [], []

    def flush():
        if len(run) >= min_run:
            out.append((run[0], run[-1]))
    for number, mod in rows:
        if (mod - major) % 4 in (1, 3):
            if run and number - run[-1] > 6:
                flush()
                run = []
            run.append(number)
        elif run and number - run[-1] > 6:
            flush()
            run = []
    flush()
    return out


def label_gaps(raw) -> list:
    """Numbered labels or paragraphs that run in a steady sequence with one or two members missing: (name, before, after,
    line). Files of near-identical routines lose a whole block when stitched, and nothing else shows it. Needs six or more
    in the sequence, and a gap of exactly one to three steps, so an original that skips numbers is not flagged."""
    import statistics
    runs = {}
    for i, line in enumerate(raw, 1):
        m = _LABEL.match(line)
        if m:
            runs.setdefault(("label", m.group(1).upper()), []).append((int(m.group(2)), i))
        m = _PARAGRAPH.match(line)
        if m:
            runs.setdefault(("paragraph", len(m.group(1))), []).append((int(m.group(1)), i))
    out = []
    for (kind, name), items in runs.items():
        diffs = [b - a for (a, _), (b, _) in zip(items, items[1:]) if b > a]
        if len(items) < 6 or len(diffs) < 5:
            continue
        step = statistics.median(diffs)
        if step <= 0:
            continue
        for (a, line), (b, _) in zip(items, items[1:]):
            if b - a > step and (b - a) % step == 0 and (b - a) <= step * 3:
                out.append((f"{name}{a + step:g}" if kind == "label" else f"paragraph {int(a + step)}", a, b, line))
    return out


def check(text: str, filename: str = "", language: str = "", errors: str = "") -> dict:
    from core.security.rules import code_lines, family
    reasons = []
    raw = (text or "").rstrip("\n").splitlines()
    body = [l for l in raw if l.strip()]
    if not body:
        return {"partial": False, "reasons": []}
    fam = family(filename, language, text)
    lines = code_lines(text, fam)
    if errors and looks_truncated(errors):
        reasons.append("compiler reports the file ends mid-construct")
    if fam in _BRACE_FAMS:
        depth, low = _balance(lines, "{", "}")
        if depth > 0:
            reasons.append(f"{depth} unclosed '{{' at end of file — end probably not captured")
        if low < 0:
            reasons.append("closing '}' before any opening — start probably not captured")
    if fam == "cobol":
        up = "\n".join(lines).upper()
        if re.search(r"\b(IDENTIFICATION|ID)\s+DIVISION\b", up) and not re.search(r"\bPROCEDURE\s+DIVISION\b", up) \
                and not filename.lower().endswith((".cpy", ".copy")):
            reasons.append("COBOL program has no PROCEDURE DIVISION — rest of the program not captured")
        if not re.search(r"\b(IDENTIFICATION|ID)\s+DIVISION\b", up) and re.search(r"\bPROCEDURE\s+DIVISION\b", up):
            reasons.append("PROCEDURE DIVISION without IDENTIFICATION DIVISION — start not captured")
        for a, b in _seq_gaps(raw, _SEQ, 6)[:3]:
            reasons.append(f"sequence numbers jump {a:06d} → {b:06d} — lines missing between screenshots")
    if fam == "cobol" and not filename.lower().endswith((".cpy", ".copy")):
        code = [l for l in lines if l.strip()]
        tail = code[-1].rstrip() if code else ""
        if len(tail) > 72 and tail[:6].strip().isdigit():
            tail = tail[:72].rstrip()
        if tail and not tail.endswith(".") and re.search(r"\bPROCEDURE\s+DIVISION\b", "\n".join(lines), re.I):
            reasons.append("last COBOL statement has no closing period — end probably not captured")
    for missing, a, b, line in label_gaps(raw)[:3]:
        reasons.append(f"{missing} is missing between {a} and {b} (near line {line}) — a block was probably lost between screenshots")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if re.search(r"\bDFHM(?:DI|DF)\b", text or "") and not re.search(r"\bDFHMSD\b(?!\s+TYPE=FINAL)", text or "", re.I):
        reasons.append("BMS map has no DFHMSD header — start of the file probably not captured")
    if ext in ("py", "pyw"):
        # A docstring or string block whose opening quotes are missing: the text before the first triple quote is prose, not code
        quotes = [i for i, l in enumerate(raw) if '"""' in l or "'''" in l]
        if quotes and sum(l.count('"""') + l.count("'''") for l in raw) % 2 == 1:
            above = [l for l in raw[:quotes[0]] if l.strip() and not l.lstrip().startswith("#")]
            codey = re.compile(r"^\s*(import |from \S+ import |def |class |@|[\w.\[\]]+\s*[:=(]|if |for |while |try:|with |return\b)")
            if above and not any(codey.match(l) for l in above):
                reasons.append("a docstring closes here but its opening quotes are missing — start probably not captured")
    if ext in ("js", "jsx", "ts", "tsx", "java", "cs", "css", "scss", "go", "kt", "swift", "php", "c", "cpp", "h"):
        flat = "\n".join(raw)
        close, opener = flat.find("*/"), flat.find("/*")
        if close != -1 and (opener == -1 or close < opener):
            reasons.append("a block comment closes before it opens — start probably not captured")
        elif raw and re.match(r"^\s*\*(?!/)", next((l for l in raw if l.strip()), "")):
            reasons.append("the file opens inside a block comment — start probably not captured")
    stripped = (text or "").lstrip()
    if ext in ("xml", "config", "wsdl", "xaml", "dtsx", "xsd", "fmb") or stripped.startswith("<?xml"):
        import xml.etree.ElementTree as ET
        try:
            ET.fromstring(text.strip())
        except ET.ParseError as exc:
            if "no element found" in str(exc) or "unclosed token" in str(exc) or exc.position[0] >= len(raw) - 1:
                reasons.append("XML ends before its root element is closed — end not captured")
    if ext in ("json",) or (stripped.startswith(("{", "[")) and ext in ("", "txt")):
        import json
        try:
            json.loads(text)
        except ValueError as exc:
            if getattr(exc, "pos", 0) >= len(text.rstrip()) - 2:
                reasons.append("JSON ends before it is closed — end not captured")
    if fam in ("web",) or ext in ("html", "htm", "aspx", "jsp", "asp", "cshtml"):
        low = (text or "").lower()
        for tag in ("html", "body", "form", "table"):
            if low.count(f"<{tag}") > low.count(f"</{tag}>"):
                reasons.append(f"<{tag}> never closed — end of page probably not captured")
                break
    if fam in ("sql", "plsql", "tsql", "pli", "sas"):
        depth, _ = _balance(lines, "(", ")")
        if depth > 0:
            reasons.append(f"{depth} unclosed '(' at end of file — end probably not captured")
    try:
        from core import langpacks
        pack = langpacks.pack_for(filename, language, text)
    except Exception:
        pack = None
    if pack and pack.get("blocks"):
        ok, msgs, _ = langpacks.check(text, filename, language)
        if not ok:
            opened = [m for m in msgs.splitlines() if "never closed" in m]
            stray = [m for m in msgs.splitlines() if "without being opened" in m]
            if opened and not stray:
                reasons.append(f"{len(opened)} block(s) never closed ({opened[0].split(': ', 1)[-1]}) — end probably not captured")
            elif stray and not opened:
                reasons.append(f"block closed before it opens ({stray[0].split(': ', 1)[-1]}) — start probably not captured")
    if pack and pack["id"] == "natural":
        for a, b in _seq_gaps(raw, _NAT, 4)[:3]:
            reasons.append(f"line numbers jump {a:04d} → {b:04d} — lines missing between screenshots")
    if pack and pack["id"] == "natural" and not re.search(r"^\s*(\d{4}\s+)?END\s*$", "\n".join(body[-3:]), re.M | re.I):
        reasons.append("Natural program has no closing END — end not captured")
    asm_like = (pack and pack["id"] == "asm") or ext in ("bms", "dbd", "psb", "mfs") or fam == "cobol" and ext == "bms"
    if asm_like and not re.search(r"^\S*\s+END\b", "\n".join(body[-4:]), re.M | re.I):
        reasons.append("assembler/macro source has no END statement — end not captured")
    if ext == "sql" or fam in ("sql", "plsql", "tsql"):
        # A schema script that opens by loading a table it never creates has lost its top: the CREATE TABLE for that table was above.
        code_text = "\n".join(l for l in lines if not l.lstrip().startswith("--"))
        first = re.search(r"^\s*(?:INSERT\s+INTO|UPDATE|ALTER\s+TABLE)\s+([\w.\"\[\]]+)", code_text, re.I | re.M)
        created = {m.group(1).lower() for m in re.finditer(r"CREATE\s+(?:OR\s+REPLACE\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.\"\[\]]+)", code_text, re.I)}
        statements = [m.group(0) for m in re.finditer(r"^\s*[A-Za-z]+", code_text, re.M)]
        if first and created and statements and re.match(r"\s*(INSERT|UPDATE|ALTER)\b", statements[0], re.I) \
                and first.group(1).lower() not in created:
            reasons.append(f"the first statement loads {first.group(1)}, which this script never creates — start probably not captured")
    if ext == "bms":
        head = [l for l in body if not l.lstrip().startswith("*")][:6]
        if head and not any(re.search(r"\bDFHMSD\b(?!\s+TYPE=FINAL)", l) for l in head):
            reasons.append("map set has no DFHMSD header — start probably not captured")
    if ext == "sps" and not body[-1].rstrip().endswith("."):
        reasons.append("last SPSS command has no terminating period — end not captured")
    if ext in ("cfm", "cfc", "cfml"):
        low = (text or "").lower()
        for tag in ("cfquery", "cfoutput", "cffunction", "cfcomponent", "cfloop", "cfif"):
            if low.count(f"<{tag}") > low.count(f"</{tag}>"):
                reasons.append(f"<{tag}> never closed — end probably not captured")
                break
    if ext in ("py", "pyw") or (pack and pack["id"] == "python"):
        import ast
        try:
            ast.parse(text)
        except ValueError:
            pass
        except SyntaxError as exc:
            msg = str(exc.msg or "")
            if (exc.lineno or 0) >= len(raw) - 1 and re.search(r"never closed|unexpected EOF|expected an indented block|EOF", msg):
                reasons.append("Python source ends mid-block — end probably not captured")
    last = body[-1].rstrip()
    if fam not in ("cobol",) and (last.count('"') % 2 == 1) and not last.endswith(("_", "\\")):
        reasons.append("last line ends inside a string — cut off mid-line")
    spacing = []
    if fam == "cobol":
        spacing = [f"lines {a}-{b} are indented one column off the rest of the file — spacing probably shifted; "
                   "recapture them or answer the line questions" for a, b in shifted_spacing(raw)[:3]]
    return {"partial": bool(reasons), "reasons": reasons, "spacing": spacing}


END_REASONS = ("unclosed", "no PROCEDURE DIVISION", "ends mid-construct", "end probably not captured",
               "rest of the program not captured")


START_REASONS = ("start not captured", "start probably not captured", "start of the file probably not captured")


def drop_start_reasons(result):
    reasons = [r for r in result["reasons"] if not any(k in r for k in START_REASONS)]
    return {**result, "reasons": reasons, "partial": bool(reasons)}


def blank_tail(path):
    """Rows of empty editor space below the last line of text in a screenshot, or None if it cannot be measured."""
    try:
        import numpy as np
        from core import colfix
        ink = colfix._ink(path)
        bands = []
        colfix._rows(ink, bands_out=bands)
        if len(bands) < 3:
            return None
        pitch = float(np.median(np.diff([b[0] for b in bands])))
        return (ink.shape[0] - bands[-1][1]) / pitch if pitch > 0 else None
    except Exception:
        return None


def end_reached(store, art, min_rows=2.5):
    """A big empty gap under the last line of the final screenshot can only mean the file ended there."""
    try:
        evidence = sorted(store.artifact_evidence(art["id"]), key=lambda e: e["ord"])
        if not evidence:
            return False
        from pathlib import Path
        path = Path(store.evidence(evidence[-1]["id"])["abs_path"])
        gap = blank_tail(path) if path.exists() else None
        return gap is not None and gap >= min_rows
    except Exception:
        return False


def drop_end_reasons(result):
    reasons = [r for r in result["reasons"] if not any(k in r for k in END_REASONS)]
    return {**result, "reasons": reasons, "partial": bool(reasons)}
