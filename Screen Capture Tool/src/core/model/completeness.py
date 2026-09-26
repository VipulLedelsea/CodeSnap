"""Detect partially captured files (cut-off end, missing start, gaps) from the transcription alone. 0 tokens."""
import re

from core.validate import looks_truncated

_BRACE_FAMS = {"cs", "java", "cpp", "js", "php", "perl", "powershell", "delphi"}
_SEQ = re.compile(r"^(\d{6})[ *\-/Dd$]")
_NAT = re.compile(r"^(\d{4})\s")


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
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
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
    return {"partial": bool(reasons), "reasons": reasons}
