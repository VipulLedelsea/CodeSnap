"""Analysis engine — multi-image explain + .docx export.

Shared brain used by hotkey_capture.py. Sends all images in ONE API call so
Claude analyses them as a single continuous document, returning a JSON object
with an "explanation" (overview) and "extracted_text" (structure-preserving
Markdown). build_docx() turns the extracted text into a Word document.

Public API:
  load_env()                  -> load ANTHROPIC_API_KEY from .env
  analyse_images(client, ps)  -> {"explanation": str, "extracted_text": str}
  build_docx(result)          -> python-docx Document
"""

import base64
import hashlib
import itertools
import json
import sys
import re as _re
import threading
import os as _os
import time
from pathlib import Path

from core import robust as _robust
from core.langpacks.formats import PROMPT_CLAUSE as _LEGACY_FORMAT_CLAUSE

MODEL = _os.environ.get("CODESNAP_MODEL", "claude-opus-5-5")
TEXT_MODEL = _os.environ.get("CODESNAP_TEXT_MODEL", "claude-sonnet-5-5")
# Per-image extraction is an OCR-like task — use a cheaper/faster model to cut cost.
# Reasoning steps (classify, fix) keep MODEL. Change if this model isn't available.
EXTRACT_MODEL = MODEL  # Sonnet for extraction: follows the verbatim/no-correct rule far better than Haiku (higher cost)

# Strict JSON response keeps explanation and extracted text cleanly separated.
SYSTEM_PROMPT = (
    "You are a screen-reading assistant that analyses a sequence of screenshots as one continuous piece of content.\n"
    "The images are ordered and together represent a single document, page, or screen flow.\n"
    "Return a JSON object with exactly two keys:\n"
    "\n"
    '  "explanation": A detailed plain-English overview of what is shown across all the images combined. '
    "Lead with the content type (e.g. 'Spreadsheet:', 'Document:', 'Code editor:'), then describe "
    "the full picture — layout, key elements, how the images relate to each other.\n"
    "\n"
    '  "extracted_text": All visible text from all images stitched together in order as one '
    "continuous document, preserving the original structure throughout. Use Markdown:\n"
    "    - Headings → # / ## / ### etc.\n"
    "    - Bullet lists → -\n"
    "    - Numbered lists → 1. 2. 3.\n"
    "    - Plain paragraphs → plain paragraphs separated by blank lines\n"
    "    Continue structure naturally across images — do not restart or add separators.\n"
    '    If there is no meaningful text, use an empty string "".\n'
    "\n"
    "Return ONLY the raw JSON object. No code fences, no extra keys, no commentary."
)

USER_PROMPT = "Analyse all these screenshots as one continuous document and return the JSON as instructed."


def load_env() -> None:
    """Load ANTHROPIC_API_KEY. Searches, in order: the existing environment, the
    working directory's .env (dev), a .env next to the executable/bundle, and
    ~/.codesnap/.env (installed .app; ~/.code_capture/.env still read for older installs). First hit wins."""
    import os
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    import sys
    from pathlib import Path
    load_dotenv()  # 1) cwd / project .env (development)
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    for cand in (Path(sys.executable).resolve().parent / ".env",   # 2) next to the app binary
                 Path.home() / ".codesnap" / ".env",               # 3) installed-app config
                 Path.home() / ".code_capture" / ".env"):          # legacy (pre-rename installs)
        try:
            if cand.exists():
                load_dotenv(cand)
                if os.environ.get("ANTHROPIC_API_KEY"):
                    return
        except Exception:  # noqa: BLE001
            pass


# ── Spinner ────────────────────────────────────────────────────────────────────

PROCESSING_MESSAGES = [
    "Reading pixel data across all images...",
    "Identifying content types and layout structures...",
    "Cross-referencing text regions between images...",
    "Analysing visual hierarchy and document flow...",
    "Stitching content together into a single document...",
    "Extracting and preserving text formatting...",
    "Resolving structure across image boundaries...",
    "Almost there — finalising the analysis...",
]


def _spinner(stop_event: threading.Event) -> None:
    spinner = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    messages = itertools.cycle(PROCESSING_MESSAGES)
    current_msg = next(messages)
    msg_timer = time.time()

    while not stop_event.is_set():
        print(f"\r  {next(spinner)}  {current_msg}   ", end="", flush=True)
        time.sleep(0.1)
        if time.time() - msg_timer > 3:
            current_msg = next(messages)
            msg_timer = time.time()

    print("\r" + " " * 70 + "\r", end="", flush=True)


# ── API call ───────────────────────────────────────────────────────────────────

# All images go in one API call so Claude has full cross-image context.
# Streaming is hidden — the spinner keeps the user informed instead.
def analyse_images(client, image_paths: list) -> dict:
    content = []
    for path in image_paths:
        b64 = base64.standard_b64encode(_robust.read_bytes(path)).decode()
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": _media_type(path), "data": b64},
        })
    content.append({"type": "text", "text": USER_PROMPT})

    stop_event = threading.Event()
    spinner_thread = threading.Thread(target=_spinner, args=(stop_event,), daemon=True)
    spinner_thread.start()

    raw = ""
    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        ) as stream:
            for text in stream.text_stream:
                raw += text
    finally:
        stop_event.set()
        spinner_thread.join()

    raw = raw.strip()

    # Attempt 1: parse directly.
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Attempt 2: find the outermost { } block in case Claude added preamble text.
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass

    print("\n[Warning] Could not parse structured response — showing raw output.", file=sys.stderr)
    return {"explanation": raw, "extracted_text": ""}


def _media_type(path: Path) -> str:
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/png")



# ── Incremental (per-image) pipeline ─────────────────────────────────────────────
#
# For long sessions, sending every image in one call is slow, costly, and can
# overflow the response (truncated JSON). Instead we read ONE image at a time,
# cache each result by content hash (so identical frames are never re-read),
# stitch the per-image text together locally, then make a single cheap text-only
# call for the overview. This is the Milestone 5 path used by the hotkey tool.

EXTRACT_SYSTEM_PROMPT = (
    "You are a LITERAL OCR engine, not a programmer. Your ONLY job is to copy the exact "
    "characters visible on screen into text — like a photocopier. You do NOT understand or "
    "improve code; you transcribe it verbatim, mistakes included.\n"
    "CRITICAL — reproduce errors EXACTLY as shown, never fix them:\n"
    "  - If a line is missing a colon (e.g. `def add(a, b)` with no `:`), copy it WITHOUT the "
    "colon. Do NOT add one.\n"
    "  - If indentation is wrong or inconsistent, copy the exact wrong indentation "
    "space-for-space. Do NOT re-align it.\n"
    "  - If a bracket, quote, keyword, or name is misspelled or missing, copy it as-is.\n"
    "  - It is CORRECT and REQUIRED to output invalid, non-runnable code if that is what is "
    "on screen. Producing clean code from broken input is a FAILURE.\n"
    "Output PLAIN TEXT only — no Markdown: no # headings, no ``` code fences, no - bullets. "
    "FIXED-COLUMN SOURCE (COBOL, copybooks, JCL, BMS/assembler): every column is significant. Keep each line's characters in their exact columns, including sequence numbers in columns 1-6 and the indicator character in column 7 (* / - D) — these are part of the source, NOT an editor gutter. Never shift, re-align or trim leading spaces on these lines. Count spaces exactly, both leading spaces and runs of spaces inside a line (aligned PIC/VALUE clauses must land in the same column as on screen); in assembler/BMS keep continuation characters in the columns actually shown, even when nonstandard. Preserve observed Unicode characters and quotes. "
    + _LEGACY_FORMAT_CLAUSE +
    "Do NOT include the editor's line-number gutter, fold arrows, breakpoint dots, minimaps, "
    "scrollbars, tab bars, or status bars — only the content itself, keeping its own indentation. "
    "If several windows are visible, transcribe ONLY the primary code/document (the focused "
    "editor pane); ignore other windows, the dock, and menu bars. "
    "If a line is cut off at the screen edge or truly unreadable, transcribe what is visible and "
    "append the marker [CUT OFF] — never guess the hidden part. "
    "If there is no meaningful text, output nothing."
)

FINALIZE_SYSTEM_PROMPT = (
    "You are given the full text extracted from a sequence of screenshots that "
    "together form one document. Classify it and summarise it.\n"
    "Return ONLY a JSON object with exactly these keys:\n"
    '  "overview": a concise plain-English overview, leading with the content type.\n'
    '  "is_code": true if the content is primarily source code, otherwise false.\n'
    '  "language": if code, the programming language name (e.g. "Python", "C++", '
    '"C#", "JavaScript"); otherwise "".\n'
    '  "extension": if code, the conventional source-file extension WITHOUT a dot '
    '(e.g. "py", "cpp", "cs", "js"); otherwise "".\n'
    "Return only the raw JSON object — no code fences, no commentary."
)


_FIXED_COLUMN_CLAUSE = (
    "FIXED-COLUMN SOURCE (COBOL, copybooks, JCL, BMS/assembler): every column is significant. Keep each line's characters in their exact columns, including sequence numbers in columns 1-6 and the indicator character in column 7 (* / - D) — these are part of the source, NOT an editor gutter. Never shift, re-align or trim leading spaces on these lines. Count spaces exactly, both leading spaces and runs of spaces inside a line (aligned PIC/VALUE clauses must land in the same column as on screen); in assembler/BMS keep continuation characters in the columns actually shown, even when nonstandard. Preserve observed Unicode characters and quotes. "
)

_PANE_CLAUSE = (
    "Do NOT include the editor's line-number gutter, fold arrows, breakpoint dots, minimaps, "
    "scrollbars, tab bars, or status bars \u2014 only the content itself. If several windows are "
    "visible, transcribe ONLY the primary focused editor pane; ignore other windows, the dock, and "
    "menu bars. If a line is cut off at the screen edge or truly unreadable, transcribe what is "
    "visible and end that line's string with the marker [CUT OFF] \u2014 never guess the hidden part. "
)

EXTRACT_JSON_SYSTEM_PROMPT = (
    "You are a LITERAL OCR engine, not a programmer. Copy the exact characters visible on "
    "screen \u2014 like a photocopier. You do NOT understand or improve code; you transcribe it "
    "verbatim, mistakes included.\n"
    "Return ONLY a JSON object with these two keys:\n"
    '  "raw_transcription": an array of strings, ONE per visible line, each copied EXACTLY as '
    "shown \u2014 preserve wrong indentation space-for-space, keep missing colons/brackets/quotes, "
    "keep misspellings. Never add, remove, or re-align anything. Producing clean, runnable code "
    "from broken input is a FAILURE.\n"
    '  "corrections_applied": an array noting anything that looked WRONG or suspicious \u2014 one '
    'object per item: {"line": <1-based index into raw_transcription>, "saw": <the exact text as '
    'written>, "suggested": <what you think it should be>}. This is where your instinct to fix '
    "things goes: note it HERE, but do NOT change raw_transcription. Empty array if nothing looked "
    "off.\n"
    + _FIXED_COLUMN_CLAUSE
    + _LEGACY_FORMAT_CLAUSE +
    _PANE_CLAUSE +
    'If there is no meaningful text, return {"raw_transcription": [], "corrections_applied": []}.\n'
    'Also return a third key "line_numbers": when the editor shows a line-number gutter, an array with the gutter '
    "number of each entry of raw_transcription (same length and order; null for a row with no number, such as the "
    "continuation of a word-wrapped line). Use [] when no line numbers are visible. These numbers go ONLY in "
    "line_numbers, never in raw_transcription. COBOL/RPG sequence numbers typed in the source are text, not line numbers."
)


EXTRACT_PLAIN_SYSTEM_PROMPT = (
    "You are a LITERAL OCR engine, not a programmer. Copy the exact characters visible on screen, like a "
    "photocopier. You do NOT understand or improve code; you transcribe it verbatim, mistakes included.\n"
    "Output ONLY the transcription as plain text: one output line per visible line, each copied EXACTLY as shown. "
    "Preserve wrong indentation space-for-space, keep missing colons/brackets/quotes and misspellings. Never add, "
    "remove, or re-align anything. No JSON, no code fences, no commentary, no corrections.\n"
    + _FIXED_COLUMN_CLAUSE
    + _LEGACY_FORMAT_CLAUSE
    + _PANE_CLAUSE
    + "If there is no meaningful text, output nothing."
)

READER = _os.environ.get("CODESNAP_READER", "plain").lower()
PLAIN_MODEL = _os.environ.get("CODESNAP_PLAIN_MODEL", "claude-sonnet-5")
PLAIN_MAX_BAD = float(_os.environ.get("CODESNAP_PLAIN_MAX_BAD", "0.10"))
PLAIN_REQUIRE_CALIBRATION = _os.environ.get("CODESNAP_PLAIN_REQUIRE_CALIBRATION", "1") != "0"




def _recover_transcription_array(text: str):
    """Recover only fully decoded source strings from an interrupted JSON reply."""
    match = _re.search(r'"raw_transcription"\s*:\s*\[', text)
    if not match:
        return None
    decoder, lines, offset = json.JSONDecoder(), [], match.end()
    while offset < len(text):
        while offset < len(text) and text[offset].isspace():
            offset += 1
        if offset >= len(text) or text[offset] == ']':
            break
        try:
            value, end = decoder.raw_decode(text, offset)
        except json.JSONDecodeError:
            break
        if not isinstance(value, str):
            break
        lines.append(value)
        offset = end
        while offset < len(text) and text[offset].isspace():
            offset += 1
        if offset >= len(text) or text[offset] != ',':
            break
        offset += 1
    return lines


def _normalize_extract(text: str) -> dict:
    """Turn the model's reply into {'raw': <verbatim text>, 'corrections': [ ... ]}.

    Accepts the structured JSON (raw_transcription line-array + corrections_applied[]).
    Falls back to treating the whole reply as raw text so extraction never hard-fails.
    """
    data = _parse_json(text)
    if not isinstance(data, dict) or "raw_transcription" not in data:
        recovered = _recover_transcription_array(text)
        if recovered is not None:
            if not recovered:
                raise ValueError("The structured screenshot response was incomplete and contained no complete source lines.")
            return {"raw": "\n".join(recovered).strip("\n"), "corrections": [], "recovered": True}
        return {"raw": text.strip("\r\n"), "corrections": []}
    rt = data.get("raw_transcription", "")
    raw = "\n".join(str(x) for x in rt) if isinstance(rt, list) else str(rt)
    corr = data.get("corrections_applied", [])
    corr = [c for c in corr if isinstance(c, dict)] if isinstance(corr, list) else []
    nums = data.get("line_numbers") or []
    rejected = 0
    if isinstance(rt, list) and isinstance(nums, list) and len(nums) == len(rt):
        # keep the numbers aligned with raw after the blank lines at either end are trimmed
        lines = [str(x) for x in rt]
        while lines and not lines[0].strip():
            lines.pop(0)
            nums = nums[1:]
        while lines and not lines[-1].strip():
            lines.pop()
            nums = nums[:-1]
        from core.verify import valid_numbers
        raw_n = len([n for n in nums if n is not None])
        nums = valid_numbers(nums, lines)
        if raw_n and not nums:
            rejected = raw_n
    else:
        nums = []
    out = {"raw": raw.strip("\n"), "corrections": corr, "numbers": nums,
           "numbers_seen": "line_numbers" in data, "numbers_rejected": rejected}
    return out


EXTRACT_INDENT_SYSTEM_PROMPT = (
    "You are a LITERAL OCR engine, not a programmer. Copy the exact characters visible on "
    "screen \u2014 like a photocopier. You do NOT understand or improve code.\n"
    "Return ONLY a JSON object with these two keys:\n"
    '  "raw_transcription": an array with ONE object per visible line: '
    '{"indent": <the EXACT number of leading space characters on that line, COUNTED off the '
    'screen \u2014 not what you think it should be>, "text": <the rest of the line after the '
    "leading spaces, copied verbatim, mistakes included>}. Count indentation like counting dots; "
    "do NOT round it to a 'correct' value. If a line is blank, use indent 0 and text \"\".\n"
    '  "corrections_applied": an array of {"line": <1-based index>, "saw": <exact text>, '
    '"suggested": <what you think it should be>} for anything that looked wrong \u2014 your outlet; '
    "do NOT change raw_transcription. Empty array if nothing looked off.\n"
    "FIXED-COLUMN SOURCE (COBOL, copybooks, JCL, BMS/assembler): every column is significant. Keep each line's characters in their exact columns, including sequence numbers in columns 1-6 and the indicator character in column 7 (* / - D) — these are part of the source, NOT an editor gutter. Never shift, re-align or trim leading spaces on these lines. Count spaces exactly, both leading spaces and runs of spaces inside a line (aligned PIC/VALUE clauses must land in the same column as on screen); in assembler/BMS keep continuation characters in the columns actually shown, even when nonstandard. Preserve observed Unicode characters and quotes. "
    + _LEGACY_FORMAT_CLAUSE +
    "Ignore the editor's line-number gutter, fold arrows, minimaps, scrollbars, tabs, and status "
    "bars. Transcribe ONLY the primary focused editor pane. For a line cut off at the edge, end its "
    "text with [CUT OFF]. If there is no meaningful text, return "
    '{"raw_transcription": [], "corrections_applied": []}.'
)


def _normalize_extract_indent(text: str) -> dict:
    """Reconstruct raw from the indent-aware shape [{indent:int, text:str}, ...].

    Rebuilds each line as (indent spaces) + text. Falls back to the plain
    line-array normaliser, then to raw text, so it never hard-fails.
    """
    data = _parse_json(text)
    if not isinstance(data, dict) or "raw_transcription" not in data:
        return {"raw": text.strip("\r\n"), "corrections": []}
    rt = data.get("raw_transcription", [])
    lines = []
    for item in rt if isinstance(rt, list) else [rt]:
        if isinstance(item, dict):
            try:
                n = max(0, int(item.get("indent", 0) or 0))
            except (TypeError, ValueError):
                n = 0
            lines.append(" " * n + str(item.get("text", "")))
        else:
            lines.append(str(item))
    corr = data.get("corrections_applied", [])
    corr = [c for c in corr if isinstance(c, dict)] if isinstance(corr, list) else []
    return {"raw": "\n".join(lines).strip("\n"), "corrections": corr}


def extract_structured_indent(client, path: Path) -> dict:
    """Experimental (#2b): indent-aware extraction \u2014 the model reports leading-space
    COUNTS per line instead of reproducing indentation by feel. A/B this against
    extract_structured() on the fidelity eval before adopting."""
    b64 = base64.standard_b64encode(_robust.read_bytes(path)).decode()
    msg = client.messages.create(
        model=EXTRACT_MODEL,
        max_tokens=4096,
        system=EXTRACT_INDENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": _media_type(path), "data": b64}},
            {"type": "text", "text": "Transcribe this screenshot. Return only the JSON object."},
        ]}],
    )
    text = "".join(getattr(b, "text", "") for b in msg.content).strip()
    return _normalize_extract_indent(text)


def _accepts_temperature(model: str) -> bool:
    """Opus 5.5 rejects `temperature` with a 400; everything else keeps the A/B switch."""
    return not str(model or "").startswith("claude-opus-5-5")


def extract_json(client, path: Path, *, calibration=None) -> dict:
    """Send ONE image; return {'raw': verbatim text, 'corrections': [ {line, saw, suggested} ]}.

    Asking for the transcription as a JSON array of line strings nudges the model into
    copy-strings mode (not write-code mode), and the corrections_applied[] list gives its
    urge to 'fix' broken code somewhere to go \u2014 so raw stays faithful. raw is what the
    compiler checks; corrections is an advisory second signal for the report.
    """
    b64 = base64.standard_b64encode(_robust.read_bytes(path)).decode()
    temp = _os.environ.get("CODESNAP_EXTRACT_TEMPERATURE")   # A/B switch for the fidelity evals; unset = API default
    if temp and not _accepts_temperature(EXTRACT_MODEL):
        temp = None   # newer models reject sampling parameters outright
    msg = client.messages.create(
        model=EXTRACT_MODEL,
        max_tokens=8192,
        **({"temperature": float(temp)} if temp else {}),
        system=EXTRACT_JSON_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": _media_type(path), "data": b64}},
            {"type": "text", "text": "Transcribe this screenshot. Return only the JSON object."},
        ]}],
    )
    if getattr(msg, "stop_reason", None) == "max_tokens":
        raise ValueError("Screenshot transcription was truncated; the frame must be read again before accepting the file.")
    text = "".join(getattr(b, "text", "") for b in msg.content).strip("\r\n")
    out = _normalize_extract(text)
    out['observed_raw'] = out['raw']
    out['raw'],out['verify'],out['respaced_lines'] = measured_frame(client,path,out['raw'],calibration=calibration)
    out["verify"]["numbers"] = out.get("numbers") or []
    out["verify"]["numbers_seen"] = out.get("numbers_seen", False)          # did the model return the key at all?
    out["verify"]["numbers_rejected"] = out.get("numbers_rejected", 0)      # numbers returned but not consistent
    return out


def _plain_unverified(out: dict):
    verify = out["verify"]
    rows = [s for s, l in zip(verify.get("status") or [], out["raw"].split("\n")) if l.strip()]
    bad = sum(1 for s in rows if s in ("mismatch", "unchecked"))
    return "unverified" if rows and bad / len(rows) > PLAIN_MAX_BAD else None


def extract_plain(client, path: Path, *, calibration=None):
    """Cheap first read: PLAIN_MODEL, plain lines, then the same pixel spacing and verification as the JSON path.
    Returns (result, None) or (None, reason) when the frame must go to the JSON reader."""
    from core import spacing
    if PLAIN_REQUIRE_CALIBRATION:
        with spacing.frame(path, calibration) as (_, origin, _evidence):
            if origin is None:
                return None, "uncalibrated"
    b64 = base64.standard_b64encode(_robust.read_bytes(path)).decode()
    msg = client.messages.create(
        model=PLAIN_MODEL,
        max_tokens=8192,
        system=EXTRACT_PLAIN_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": _media_type(path), "data": b64}},
            {"type": "text", "text": "Transcribe this screenshot as plain text."},
        ]}],
    )
    if getattr(msg, "stop_reason", None) == "max_tokens":
        return None, "truncated"
    text = "".join(getattr(b, "text", "") for b in msg.content).strip("\r\n")
    raw = "\n".join(l for l in text.splitlines() if not l.strip().startswith("```")).strip("\n")
    if not raw.strip():
        return None, "empty"
    out = {"raw": raw, "observed_raw": raw, "corrections": []}
    out["raw"], out["verify"], out["respaced_lines"] = measured_frame(client, path, raw, calibration=calibration)
    out["verify"].update(numbers=[], numbers_seen=False, numbers_rejected=0, reader=PLAIN_MODEL)
    reason = _plain_unverified(out)
    return (None, reason) if reason else (out, None)


def extract_structured(client, path: Path, *, calibration=None) -> dict:
    """One screenshot -> {'raw', 'corrections', 'verify', ...}. With CODESNAP_READER=plain the frame is read by
    PLAIN_MODEL first and only goes to the JSON reader (EXTRACT_MODEL) when that read is not trustworthy."""
    reason = None
    if READER == "plain":
        try:
            out, reason = extract_plain(client, path, calibration=calibration)
        except Exception as exc:
            out, reason = None, "error:" + type(exc).__name__
        if out is not None:
            return out
    result = extract_json(client, path, calibration=calibration)
    if reason:
        result.setdefault("verify", {})["reader_fallback"] = reason
    return result


def _left_edge_cut(raw):
    """A row with nothing visible before the marker, away from the top and bottom of the frame.

    Rows clipped by the top or bottom of the screenshot also read as a bare marker, but they say nothing
    about the left edge, so they must not discard the measured margin for the whole frame."""
    rows = raw.splitlines()
    first = next((i for i, r in enumerate(rows) if r.strip()), 0)
    last = max((i for i, r in enumerate(rows) if r.strip()), default=0)
    return any(r.lstrip().startswith('[CUT OFF]') and first + 3 <= i <= last - 3 for i, r in enumerate(rows))


def measured_frame(client,path,raw,*,calibration=None):
    """One spacing path for fresh OCR, cached frames and saved rebuilding."""
    from core import spacing, colfix
    from core.text import literal_continuations
    with spacing.frame(path,calibration) as (image,origin,evidence):
        if _left_edge_cut(raw):
            origin=None
            evidence.update(calibrated=False,reason='The left edge is cut off; source column one is not visible.')
        if not _left_edge_cut(raw):
            auto=spacing.anchored_origin(image,raw)
            if auto is not None and origin is not None:
                pitch=(evidence.get('calibration') or {}).get('pitch') or 9
                if abs(auto-origin)<0.5*pitch:
                    auto=None
                else:
                    origin=None
            if auto is not None:
                origin=auto
                evidence.update(calibrated=True,reason='',auto=True,calibration={'source_x':auto,'box':[0,0]+list(__import__('PIL.Image',fromlist=['Image']).open(image).size)})
        fixed,changed=(colfix.respace(image,raw,source_x=origin) if origin is not None else colfix.respace(image,raw)) if _os.environ.get('CODESNAP_COLUMN_FIX','1')!='0' else (raw,0)
        verified=verify_screenshot(client,image,fixed,source_x=origin)
        result=verified.pop('text')
        protected=literal_continuations(result)
        evidence['line_status']=[('literal' if i in protected or '\t' in line else
            'measured' if evidence['calibrated'] and verified['status'][i] in ('verified','reread') else
            'relative' if verified['status'][i] in ('verified','reread') else 'unmeasured')
            if line.strip() else '' for i,line in enumerate(result.split('\n'))]
        verified['spacing']=evidence
        return result,verified,changed


REREAD_SYSTEM_PROMPT = (
    "You are a LITERAL OCR engine. Each image is ONE line of source code cut from an editor screenshot and zoomed in. "
    "Copy every visible character of that line exactly, mistakes included; count repeated characters (------, ======, "
    "spaces) exactly. Return ONLY a JSON object: {\"lines\": [{\"text\": <the line>, \"overlay\": <true if a mouse "
    "pointer, text cursor or selection box covers part of the text, else false>}, ...]}, one entry per image, in order."
)
REREAD_MAX = 24


KIND_PROMPT = (
    "Look at this screenshot and answer with one word.\n"
    "code: it shows source code, SQL, a config or data file, a log, or other text as it appears in an editor, IDE, "
    "terminal session or file viewer.\n"
    "screen: it shows a running application's user interface: a web page, a desktop or mobile form, a dialog, or a "
    "mainframe/green-screen terminal form with fields and labels.\n"
    "Answer code or screen.")


def is_fatal_api_error(exc) -> bool:
    """True for errors a retry cannot fix (bad key, bad request, no permission) so callers surface them."""
    try:
        import anthropic
        return isinstance(exc, (anthropic.AuthenticationError, anthropic.BadRequestError, anthropic.PermissionDeniedError))
    except Exception:  # noqa: BLE001
        return False


def detect_kind(client, path: Path) -> str:
    """Whether a capture shows code or an application screen, from its first frame ("code" when unsure)."""
    try:
        b64 = base64.standard_b64encode(_robust.read_bytes(path)).decode()
        msg = client.messages.create(model=TEXT_MODEL, max_tokens=5, messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": _media_type(path), "data": b64}},
            {"type": "text", "text": KIND_PROMPT}]}])
        word = "".join(getattr(b, "text", "") for b in msg.content).strip().lower()
        return "screen" if word.startswith("screen") else "code"
    except Exception as exc:  # noqa: BLE001 - a failed guess falls back to reading it as code
        if is_fatal_api_error(exc):
            print(f"(auto-detect failed, reading as code: {type(exc).__name__}: {exc})", file=sys.stderr)
        return "code"


def verify_screenshot(client, path: Path, raw: str, *, source_x=None) -> dict:
    """Check every transcribed line against the pixels (core.colfix.check). Lines whose pixels show a different
    character count are fixed for free when only the spacing was wrong; otherwise only those lines are cropped, zoomed
    and read again, and a re-read is kept only if it now matches the pixels. Returns
    {"text", "grid", "status": [per line], "reread": n}. Never raises: a failed check leaves the lines "unchecked"."""
    from core import capture_gate, colfix
    capture_gate.wait()
    lines = raw.split("\n")
    try:
        chk = colfix.check(path, raw, source_x=source_x) if source_x is not None else colfix.check(path, raw)
    except Exception:  # noqa: BLE001
        return {"text": raw, "grid": False, "status": ["" if not l.strip() else "unchecked" for l in lines],
                "reread": 0, "absolute_columns": False}
    status, rows = chk["status"], chk["rows"]
    from core.text import literal_continuations
    protected = literal_continuations(raw)
    todo = {}
    for i, row in rows.items():
        if i in protected or '\t' in lines[i]:
            continue  # A pixel spacing repair cannot rewrite a literal body or guess tab stops.
        fixed = colfix.accept_reread(lines[i], row)
        if fixed is not None and max(abs(a - b) for a, b in zip(colfix._starts(fixed), colfix._starts(lines[i]))) <= colfix.MAX_SHIFT:
            lines[i], status[i] = fixed, "verified"
        else:
            todo[i] = row
    n_re = 0
    if todo and client is not None and _os.environ.get("CODESNAP_REREAD", "1") != "0":
        items = list(todo.items())[:REREAD_MAX]
        for k in range(0, len(items), 12):
            batch = dict(items[k:k + 12])
            try:
                crops = colfix.crop_rows(path, batch, x0=chk.get("x0", 0), pitch=chk.get("pitch", 10.0))
                content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                        "data": base64.standard_b64encode(c).decode()}} for c in crops]
                content.append({"type": "text", "text": f"{len(crops)} images. Return only the JSON object."})
                msg = client.messages.create(model=EXTRACT_MODEL, max_tokens=2048, system=REREAD_SYSTEM_PROMPT,
                                             messages=[{"role": "user", "content": content}])
                data = _parse_json("".join(getattr(b, "text", "") for b in msg.content).strip()) or {}
                got = data.get("lines") if isinstance(data, dict) else None
            except Exception:  # noqa: BLE001 - the re-read is an extra; the first read stands
                got = None
            if not isinstance(got, list):
                continue
            for (i, row), g in zip(batch.items(), got):
                text = str(g.get("text", "")) if isinstance(g, dict) else str(g)
                fixed = colfix.accept_reread(text, row)
                if fixed is not None:
                    status[i] = "reread"
                    lines[i] = fixed
                    n_re += 1
                elif isinstance(g, dict) and g.get("overlay") and text.split() == lines[i].split():
                    status[i] = "confirmed"      # a pointer over the text explains the pixels; both reads agree
    return {"text": "\n".join(lines), "grid": chk["grid"], "status": status, "reread": n_re,
            "absolute_columns": chk.get("absolute_columns", False)}


def extract_legacy(client, path: Path) -> str:
    """Pre-#2 extraction: the old text-only prompt (no JSON, no corrections outlet).
    Kept ONLY so the fidelity eval can measure a true before/after against #2."""
    b64 = base64.standard_b64encode(_robust.read_bytes(path)).decode()
    msg = client.messages.create(
        model=EXTRACT_MODEL,
        max_tokens=4096,
        system=EXTRACT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": _media_type(path), "data": b64}},
            {"type": "text", "text": "Extract the text from this screenshot as Markdown."},
        ]}],
    )
    return "".join(getattr(b, "text", "") for b in msg.content).strip()


def extract_one(client, path: Path) -> str:
    """Return just the verbatim text of ONE image (thin wrapper over extract_structured).

    For callers that only need the text (single-agent path, background cache). The
    structured prompt still improves fidelity here even though corrections are dropped.
    """
    return extract_structured(client, path)["raw"]


def _parse_json(raw: str) -> dict:
    """Best-effort JSON parse: direct, then the outermost { } block."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


def synthesize_final(client, full_text: str) -> dict:
    """One cheap text-only call: classify the document AND summarise it.

    Returns {"overview", "is_code", "language", "extension"}.
    """
    fallback = {"overview": "", "is_code": False, "language": "", "extension": ""}
    if not full_text.strip():
        return fallback
    msg = client.messages.create(
        model=TEXT_MODEL,
        max_tokens=1024,
        system=FINALIZE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": full_text}],
    )
    raw = "".join(getattr(b, "text", "") for b in msg.content).strip()
    data = _parse_json(raw)
    if not isinstance(data, dict):
        # Couldn't parse (or not an object) — keep the raw text as the overview, treat as non-code.
        return {**fallback, "overview": raw}
    return {
        "overview": str(data.get("overview", "")).strip(),
        "is_code": bool(data.get("is_code", False)),
        "language": str(data.get("language", "")).strip(),
        "extension": str(data.get("extension", "")).strip().lstrip(".").lower(),
    }


import difflib as _difflib


_SEQNO = _re.compile(r"^\s*(\d{6})")
_SOURCE_LABEL = _re.compile(r"(?:\d{2,}-[\w-]+\.|[A-Za-z_][\w]*:)")


def _sim(x: str, y: str) -> float:
    # two COBOL lines with different sequence numbers are different lines, however alike the code
    mx, my = _SEQNO.match(x), _SEQNO.match(y)
    if mx and my and mx.group(1) != my.group(1):
        return 0.0
    x, y = x.replace("[CUT OFF]", "").strip(), y.replace("[CUT OFF]", "").strip()
    if x == y:
        return 1.0
    # Repeated legacy blocks often differ only in a receipt code, amount or
    # paragraph number. Similar typography is not proof that they are one line.
    if _re.findall(r"\d+", x) != _re.findall(r"\d+", y):
        return 0.0
    if _re.fullmatch(r"[\w-]+\.", x) and _re.fullmatch(r"[\w-]+\.", y):
        return 0.0
    sql_object = r'(?:CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|(?:UNIQUE\s+)?INDEX)|INSERT\s+INTO)\s+([\w."\[\]]+)'
    sx, sy = _re.match(sql_object, x, _re.I), _re.match(sql_object, y, _re.I)
    if sx and sy and sx.group(1).upper() != sy.group(1).upper():
        return 0.0
    sx, sy = _re.search(r'\bFROM\s+([\w."\[\]]+)', x, _re.I), _re.search(r'\bFROM\s+([\w."\[\]]+)', y, _re.I)
    if sx and sy and sx.group(1).upper() != sy.group(1).upper():
        return 0.0
    return _difflib.SequenceMatcher(None, x, y).ratio()


def _mostly_contained(b: list, merged: list) -> bool:
    """True if every non-blank line of b already appears exactly in merged —
    i.e. b is a re-capture of content we already have, so it adds nothing."""
    # OCR may add whitespace immediately after a legacy comment indicator.
    norm = lambda line: _re.sub(r'^\*\s+', '* ', line.replace('[CUT OFF]', '').strip())
    bl = [norm(l) for l in b if l.strip()]
    if not bl:
        return True
    ms = [norm(l) for l in merged if l.strip()]
    if not ms or len(bl) > len(ms):
        return False
    # b must reappear as a contiguous run, not just as lines scattered through merged —
    # otherwise a short last frame ("    }" / "end-proc;") is thrown away as "already seen"
    sticky = _re.compile(r"(?:[\w-]+:\s*(?:PROC|PROCEDURE)\b.*|DCL\s+1\s+\w+[,;]?|SELECT\s*\(.*)", _re.I)
    runs = [bl]
    # editors with sticky scroll pin the enclosing header on top of the screen, away from the lines that follow it
    if len(bl) > 4 and sticky.fullmatch(bl[0]) and bl[0] in ms:
        runs.append(bl[1:])
    for run in runs:
        for o in range(len(ms) - len(run) + 1):
            # A frame cannot be discarded when even one of its source lines is new.
            if all(x == y for x, y in zip(run, ms[o:o + len(run)])):
                return True
    return False


_FENCE_RE = _re.compile(r"```[^\n`]*\n(.*?)```", _re.S)
# leading line-number gutter: digits, an optional gutter glyph (Eclipse fold marker,
# middot, colon), then whitespace — e.g. "12  ", "5⊖ ", "3: "
_GUTTER_RE = _re.compile(r"^[ \t]*\d{1,4}(?!\d)[ \t\u00b7:.\u2296\u2299\u25cb\u2d54]?[ \t]+")


# capturing form: leading ws (group1) + line number (group2) + optional gutter glyph (group3)
_GUTTER_CAP = _re.compile(r"^([ \t]*)(\d{1,4})(?!\d)([ \t\u00b7:.\u2296\u2299\u25cb\u2d54]?)")


def _strip_gutter(text: str) -> str:
    """Remove an editor's line-number gutter WITHOUT destroying the code's own
    indentation. The old approach greedily ate the number and every space after
    it, which flattened nesting (turning '5    def' into 'def') and left bare
    numbers on blank lines. Instead we blank the gutter field in place (preserving
    column positions) and then dedent, so the gutter width falls away uniformly
    while each line's real indentation survives. Only fires when most non-blank
    lines look gutter-numbered, so ordinary code is untouched."""
    import textwrap
    from core.text import literal_continuations
    if literal_continuations(text):
        return text  # Numeric literal/data rows cannot establish an editor gutter.
    lines = text.split("\n")
    matches = [_GUTTER_CAP.match(l) for l in lines]
    nonempty = [l for l in lines if l.strip()]
    hits = sum(1 for l, m in zip(lines, matches) if l.strip() and m)
    if not nonempty or hits < 0.6 * len(nonempty):
        return text
    out = []
    for l, m in zip(lines, matches):
        if m:
            end = m.end()                      # blank leading ws + number + glyph, keep width
            out.append(" " * end + l[end:])
        else:
            out.append(l)
    return textwrap.dedent("\n".join(out))


def _indent_score(t: str) -> int:
    return sum(len(l) - len(l.lstrip()) for l in t.splitlines())


def _dedup_best(items: list) -> list:
    """Collapse content duplicates, retaining the first observed spacing.

    More indentation is not stronger evidence; calibrated reconciliation and
    spacing-conflict reporting happen after positional frame alignment.
    """
    from core.text import normalized_line, literal_continuations
    groups, order = {}, []
    for c in items:
        protected = literal_continuations(c)
        key = tuple(line if i in protected else normalized_line(line) for i, line in enumerate(c.splitlines()))
        if not any(key):
            continue
        if key not in groups:
            groups[key] = c
            order.append(key)
    return [groups[k] for k in order]


_CODE_KW = _re.compile(
    r"^(public|private|protected|class|interface|abstract|import|package|def|function|"
    r"const|let|var|int|float|double|char|bool|void|static|final|return|new|struct|enum|"
    r"namespace|using|include|from|export|func|fn|type)\b")


def _strip_md_headers(text: str) -> str:
    """Drop Markdown ATX header lines a screen-reader adds over code — only when they're
    clearly code artifacts: a bare filename, a line starting with a code keyword, or text
    that appears in a real code line. Preserves ordinary comments and prose headers, and
    C preprocessor directives (which have no space after '#')."""
    lines = text.split("\n")
    from core.text import literal_continuations
    protected = literal_continuations(text)
    codeset = [l.strip() for l in lines if l.strip() and not l.lstrip().startswith("#")]
    out = []
    for index, l in enumerate(lines):
        if index in protected:
            out.append(l)
            continue
        m = _re.match(r"^\s*#{1,6}\s+(.+?)\s*$", l)
        if m:
            h = m.group(1).strip()
            is_file = bool(_re.match(r"^[\w./-]+\.[A-Za-z0-9]{1,5}$", h))
            is_kw = bool(_CODE_KW.match(h))
            in_code = len(h) > 4 and any(h in c or c in h for c in codeset)
            if is_file or is_kw or in_code:
                continue
        out.append(l)
    return "\n".join(out)



# Editors draw faint vertical indent-guide lines in the indentation; OCR reads them as
# pipes/box-drawing bars (e.g. "    |   return x;"). Strip them from the LEADING region
# only, so real code (bitwise |, F#/OCaml leading "|") is untouched.
_GUIDE_BOX = "\u2502\u2503\u2506\u2507\u250a\u250b\u254e\u254f\u00a6\u2551"


def _strip_indent_guides(text: str) -> str:
    """Blank indent-guide bars in the LEADING region. Box-drawing bars are always
    guides. An ASCII '|' is a guide only when it pads toward the next indent stop —
    i.e. it is followed by 2+ whitespace chars ("|   return"). A real leading '|'
    (F#/OCaml match arm) is "| Some": one space then code, so it is left intact."""
    out = []
    from core.text import literal_continuations
    protected = literal_continuations(text)
    for index, line in enumerate(text.split("\n")):
        if index in protected:
            out.append(line)
            continue
        j, n, buf, changed = 0, len(line), [], False
        while j < n:
            c = line[j]
            if c in " \t":
                buf.append(c); j += 1
            elif c in _GUIDE_BOX:
                buf.append(" "); j += 1; changed = True
            elif c == "|" and j + 2 < n and line[j + 1] in " \t" and line[j + 2] in " \t":
                buf.append(" "); j += 1; changed = True
            else:
                break
        out.append(("".join(buf) + line[j:]) if changed else line)
    return "\n".join(out)


def clean_source(text: str, mode: str | None = None) -> str:
    return _clean_source(text, mode)


def source_mode(raw_parts: list) -> str | None:
    """Decide once, from all frames together, whether the source is fixed-column
    ("columns") or another column-sensitive format ("format"). A single mid-file frame
    of COBOL has no DIVISION headers, so judging frames one by one mis-cleaned them."""
    from core.cobol import is_column_sensitive
    from core.langpacks.formats import detect_format, looks_dedented_asm
    joined = "\n".join(_FENCE_RE.sub(lambda m: m.group(1), p or "") for p in raw_parts)
    if not joined.strip():
        return None
    if is_column_sensitive(joined):
        return "columns"
    # Markup and template bodies may contain real bars or apparent headings.
    # Preserve these rather than treating their text as editor decoration.
    if _re.search(r"^\s*(?:<\?xml\b|<!DOCTYPE\b|<[A-Za-z][\w:.-]*(?:\s[^>]*|/?)>|<%@|@page\b)", joined, _re.M | _re.I):
        return "format"
    if _re.search(r"^\s*\|\s+.+?->", joined, _re.M) and _re.search(r"\bmatch\b.+\bwith\b", joined):
        return "format"
    if detect_format(joined) or looks_dedented_asm(joined):
        return "format"
    return None


def _clean_source(text: str, mode: str | None = None) -> str:
    """Turn a raw OCR'd code extraction into compiler-ready source: unwrap markdown
    code fences (dropping ```lang, ``` and any # headers/prose outside them), remove
    an editor line-number gutter, and drop identical duplicate blocks. Faithful — it
    only strips transcription/formatting noise, never changes the code itself."""
    if not text or not text.strip():
        return text or ""
    # An explicit generic-language wrapper distinguishes numbered editor output
    # from BASIC's otherwise indistinguishable numbered assignment statements.
    if mode != 'columns' and _re.search(r'^\s*```(?:py|python|java|js|javascript|c|cpp|csharp|cs)\s*$', text, _re.M | _re.I):
        mode = 'plain'
    from core.cobol import is_column_sensitive
    if mode == "columns" or (mode is None and is_column_sensitive(_FENCE_RE.sub(lambda m: m.group(1), text))):
        blocks = _FENCE_RE.findall(text)
        text = "\n\n".join(blocks) if blocks else _re.sub(r"^[ \t]*```.*$", "", text, flags=_re.M)
        # Capture records observed source, including possibly invalid columns.
        # Compiler-format adapters must not silently rewrite that evidence.
        return text.strip("\n")
    from core.langpacks.formats import detect_format, looks_dedented_asm
    unfenced = _FENCE_RE.sub(lambda m: m.group(1), text)
    if mode == "format" or (mode is None and (detect_format(unfenced) or looks_dedented_asm(unfenced))):
        blocks = _FENCE_RE.findall(text)
        text = "\n\n".join(blocks) if blocks else _re.sub(r"^[ \t]*```.*$", "", text, flags=_re.M)
        return text.strip("\n")
    blocks = _FENCE_RE.findall(text)
    if blocks:
        cleaned = [_strip_gutter(b).strip("\n") for b in blocks]
        text = "\n\n".join(_dedup_best(cleaned) or cleaned)
    else:
        text = _re.sub(r"^[ \t]*```.*$", "", text, flags=_re.M)  # stray fence lines
        text = _strip_gutter(text)
    text = _strip_md_headers(text)
    text = _strip_indent_guides(text)
    return text.strip("\n")


def _has_dup_headers(text: str) -> bool:
    """True if the text repeats a class name or a top-level function name — a strong
    signal that frame-stitching mis-merged and duplicated a block."""
    classes, funcs = [], []
    for l in text.splitlines():
        mc = _re.match(r"^\s*(?:public\s+|static\s+|final\s+|abstract\s+)*class\s+(\w+)", l)
        if mc:
            classes.append(mc.group(1))
        mf = _re.match(r"^(?:def|function|func|fn)\s+(\w+)", l)  # module-level only (no indent)
        if mf:
            funcs.append(mf.group(1))
    return len(classes) != len(set(classes)) or len(funcs) != len(set(funcs))


def _fix_leading_indent(code: str) -> str:
    """A source file's first logical line can never be indented (Python raises
    'unexpected indent' at line 1). OCR sometimes adds a spurious leading indent
    to the top line \u2014 e.g. a module docstring picking up the editor's left
    margin. Strip it. Safe: no valid file starts indented, so this only removes a
    transcription artifact, never real structure."""
    lines = code.split("\n")
    for i, ln in enumerate(lines):
        if ln.strip() == "":
            continue
        rest = [l for l in lines[i + 1:] if l.strip()]
        # only a lone indented first line is an artifact; if the whole file is indented
        # (e.g. IBM i CL, labels in column 2) the indent is real source
        if ln[:1] in (" ", "\t") and (not rest or any(l[:1] not in (" ", "\t") for l in rest)):
            lines[i] = ln.lstrip()
        break
    return "\n".join(lines)


def merge_frames(raw_parts: list, metas: list | None = None):
    """Clean each frame (fences/gutters/dup blocks), collapse frames that are the
    same code (keeping the best-indented copy), stitch overlapping ones. Returns
    (merged_code, clean_parts). Safety net: if stitching duplicated a class/function
    (a mis-merge on messy OCR), fall back to the longest single frame with no such
    duplication — one clean copy beats tripled garbage."""
    code, parts, _, _ = merge_verified(raw_parts, metas)
    return code, parts


def _observed_cobol_columns(parts):
    """Use an observed valid copy of a misaligned paragraph/comment, never invent padding."""
    from collections import Counter
    labels = _re.compile(r"\d{2,}-[\w-]+\.")
    choices = {}
    for part in parts:
        for line in part.splitlines():
            text = line.strip()
            if labels.fullmatch(text) or text.startswith("*"):
                if len(line) > 6 and (line[6] == "*" if text.startswith("*") else
                                      line[6] == " " and 7 <= len(line) - len(line.lstrip()) <= 10):
                    choices.setdefault(text, Counter())[line] += 1
    output = []
    for part in parts:
        lines = []
        for line in part.split("\n"):
            matches = choices.get(line.strip())
            if matches and len(line) > 6 and (line[6] != "*" if line.strip().startswith("*") else
                                             not (line[6] == " " and 7 <= len(line) - len(line.lstrip()) <= 10)):
                line = matches.most_common(1)[0][0]
            lines.append(line)
        output.append("\n".join(lines))
    return output


def merge_verified(raw_parts: list, metas: list | None = None):
    """merge_frames plus verification: returns (code, clean_parts, notes, statuses). `metas` are the per-screenshot
    checks (verify_for); when every screenshot has editor line numbers the lines are placed by number, otherwise by
    overlap. statuses maps each line's text to the best check any screenshot gave it (core.verify)."""
    from core import verify
    metas = list(metas or [])
    metas += [{}] * (len(raw_parts) - len(metas))
    raw_parts = _drop_margin_offset(raw_parts, metas)
    mode = source_mode(raw_parts)
    statuses = verify.lookup(raw_parts, metas)
    from core.cobol import is_column_sensitive
    from core.langpacks.formats import detect_format
    byn = verify.merge_by_numbers(raw_parts, metas)
    if byn is not None:
        text, notes, st = byn
        for k, v in st.items():
            statuses[k] = verify.best(statuses.get(k, ""), v) if v != "joined" else "joined"
        best = clean_source(text, mode)
        parts = [c for c in (clean_source(r, mode) for r in raw_parts) if c.strip()]
        keep = mode or is_column_sensitive(best) or detect_format(best)
        final = best
        from core.spacing import reconcile
        final,spacing_notes=reconcile(final,raw_parts,metas)
        notes.update(spacing_notes)
        verify.remap_line_evidence(text, final, notes)
        verify.spacing_agreement(final, raw_parts, metas, notes)
        return final, parts, notes, statuses
    notes = {"numbers": False, "gaps": [], "sideways": 0, "wrapped": 0}
    cleaned = [clean_source(r, mode) for r in raw_parts]
    from core.cobol.detect import detect_kind as source_kind
    if (mode == "columns" and not any((m or {}).get('spacing', {}).get('calibrated') for m in metas)
            and source_kind('\n'.join(raw_parts)) in ('cobol', 'copybook')):
        cleaned = _observed_cobol_columns(cleaned)
    parts = _dedup_best(cleaned) or [c for c in cleaned if c.strip()]
    prefer = {k for k, v in statuses.items() if v in ("verified", "reread")}
    stitched = _stitch(parts, prefer, notes)
    candidates = [stitched] + parts
    clean = [c for c in candidates if c.strip() and not _has_dup_headers(c)]
    best = max(clean or candidates, key=lambda c: len(c.splitlines())) if candidates else stitched
    if best is not stitched:
        notes["sideways"] = 0
    for j in notes.pop("joined", []):
        k = j.rstrip()
        if "[CUT OFF]" not in k and statuses.get(k) not in ("verified", "reread"):
            statuses[k] = "joined"
    keep = mode or is_column_sensitive(best) or detect_format(best)
    final = best
    from core.spacing import reconcile
    final,spacing_notes=reconcile(final,cleaned,metas)
    notes.update(spacing_notes)
    verify.align_line_evidence(final, raw_parts, cleaned, metas, notes)
    verify.spacing_agreement(final, cleaned, metas, notes)
    # Conflicting reads are evidence of uncertainty even if either isolated row
    # happened to match a pixel grid. Preserve the selected text and flag its join.
    final_lines = final.splitlines()
    disagreed = set()
    if notes.get("overlap_conflicts"):
        flat = lambda text: " ".join(text.split())
        for part in cleaned:
            rows = part.split("\n")
            mapping = verify._line_map(part, final, carry_replacements=True)
            for i, j in enumerate(mapping):
                if j is None and i and mapping[i - 1] is not None:
                    j = mapping[i - 1] + 1
                    after = mapping[i + 1] if i + 1 < len(mapping) else None
                    if j >= len(rows) or (j + 1 < len(rows) and after != j + 1) or (j + 1 >= len(rows) and after is not None):
                        j = None
                    elif j is not None and flat(final_lines[i]).startswith(flat(rows[j])):
                        j = None
                if (j is not None and final_lines[i].strip() and rows[j].strip() and "[CUT OFF]" not in final_lines[i] + rows[j]
                        and flat(final_lines[i]) != flat(rows[j])):
                    disagreed.add(i)
    for context in notes.get("overlap_conflicts", []):
        hits = [i for i in range(len(context) - 1, len(final_lines))
                if [l.strip() for l in final_lines[i - len(context) + 1:i + 1]] == list(context)]
        ordinal = getattr(context, "ordinal", 0)
        for i in (hits[ordinal:ordinal + 1] or hits[:1]):
            if i in disagreed:
                notes["line_statuses"][i] = "mismatch"
    return final, parts, notes, statuses


def _drop_margin_offset(raw_parts, metas):
    """A click placed one column left of the text leaves every line one space too far right. Source files have
    something at column one (a label, a comment, a declaration), so a whole capture whose leftmost line sits at
    exactly column two is that click offset. Fixed-format sources start at column 6 or later and are untouched."""
    shown = [m for m in metas if m]
    clicked = [m for m in shown if (m.get('spacing') or {}).get('calibrated') is True and not (m.get('spacing') or {}).get('auto')]
    if not clicked or len(clicked) < 0.8 * len(shown):
        return raw_parts
    body = [l for r in raw_parts for l in r.split('\n') if l.strip() and '[CUT OFF]' not in l and '\t' not in l]
    indents = [len(l) - len(l.lstrip(' ')) for l in body]
    if len(body) < 20 or sum(i == 0 for i in indents) > 0.02 * len(indents) or sum(i == 1 for i in indents) < 3:
        return raw_parts
    return ['\n'.join(l[1:] if l.startswith(' ') and l.strip() and '[CUT OFF]' not in l else l for l in r.split('\n'))
            for r in raw_parts]


class _Context(list):
    ordinal = 0


_OWNER = _re.compile(r"(?:\d{2,}-[\w-]+\.|[\w$#@.-]+:\s*(?:PROC\b.*)?|[\w-]+\s+BEGSR)", _re.I)


def _conflict_context(lines, at):
    """Keep the owning paragraph in a warning so repeated statements don't inherit it."""
    start = max(0, at - 5)
    for index in range(at, max(-1, at - 60), -1):
        if _OWNER.fullmatch(lines[index].strip()):
            start = index
            break
    context = _Context(line.strip() for line in lines[start:at + 1])
    size = len(context)
    context.ordinal = sum(1 for i in range(size - 1, at)
                          if [l.strip() for l in lines[i - size + 1:i + 1]] == list(context))
    return context


def _stitch_two(merged: list, b: list, min_overlap: int = 2, thresh: float = 0.8, prefer=frozenset(), notes=None) -> "list | None":
    """Merge frame b onto merged. Finds where the TAIL of merged reappears *inside* b
    (frames often re-show earlier lines), then appends only what follows. Returns the
    merged list, or None if no overlap is found."""
    max_k = min(len(merged), 60)
    old_labels = {row.strip() for row in merged}
    sql_identity = _re.compile(r'^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|(?:UNIQUE\s+)?INDEX)\s+([\w."\[\]]+)', _re.I)
    old_objects = {m.group(0).strip().upper() for row in merged if (m := sql_identity.match(row))}
    for k in range(max_k, min_overlap - 1, -1):
        tail = merged[-k:]
        # a 2-3 line overlap made only of punctuation ("}", "{", "END-IF.") is not evidence
        if k < 4 and sum(len(_re.sub(r"\W", "", x)) for x in tail) < 12:
            continue
        for o in range(0, len(b) - k + 1):
            window = b[o:o + k]
            sims = []
            for x, y in zip(tail, window):
                score = _sim(x, y)
                if score < 0.7:
                    break
                sims.append(score)
            # every line must match (OCR noise allowed), not just the average
            if len(sims) == k and sum(sims) / len(sims) >= thresh:
                # A later repeated END-IF window cannot discard a new paragraph
                # visible before it in this frame.
                new_prefix = b[:o]
                if any(_SOURCE_LABEL.fullmatch(line.strip()) and
                       line.strip() not in old_labels for line in new_prefix):
                    continue
                if any(m.group(0).strip().upper() not in old_objects for row in new_prefix
                       if (m := sql_identity.match(row))):
                    continue
                # a line cut off at the bottom of one screen is usually whole on the next — keep the whole copy
                tail = [w if "[CUT OFF]" in t and "[CUT OFF]" not in w else t for t, w in zip(tail, window)]
                # two screenshots read a line differently: keep the copy the pixel check verified
                tail = [w if w != t and w.rstrip() in prefer and t.rstrip() not in prefer else t
                        for t, w in zip(tail, window)]
                result = merged[:-k] + tail + b[o + k:]
                if notes is not None:
                    for i, (x, y) in enumerate(zip(merged[-k:], window)):
                        if (x.strip() != y.strip() and len(x.strip()) >= 6 and len(y.strip()) >= 6 and
                                "[CUT OFF]" not in x + y and
                                (x.rstrip() in prefer) == (y.rstrip() in prefer)):
                            at = len(merged) - k + i
                            notes.setdefault("overlap_conflicts", []).append(
                                _conflict_context(result, at))
                return result
    # A unique paragraph label or numbered maintenance comment establishes
    # position independently of repeated logic. Retain rows a later read skipped.
    marker = _re.compile(r"\d{2,}-[\w-]+\.|[A-Za-z_][\w]*:|\*.*\d.*")
    old_keys, new_keys = [l.strip() for l in merged], [l.strip() for l in b]
    for pos in range(max(0, len(merged) - 60), len(merged)):
        anchor = old_keys[pos]
        if not marker.fullmatch(anchor) or old_keys.count(anchor) != 1 or new_keys.count(anchor) != 1:
            continue
        offset = new_keys.index(anchor)
        left, right = merged[pos:], b[offset:]
        equal = sum(block.size for block in _difflib.SequenceMatcher(
            None, old_keys[pos:], new_keys[offset:], autojunk=False).get_matching_blocks())
        if equal < max(2, 0.6 * min(len(left), len(right))):
            continue
        # Align each paragraph separately; repeated END-IF and MOVE rows must not
        # carry a match across distinct paragraph identities.
        labels = _SOURCE_LABEL
        def sections(lines):
            blocks, key = {"anchor": []}, "anchor"
            for line in lines:
                if labels.fullmatch(line.strip()) and blocks[key]:
                    key = line.strip()
                    if key in blocks:
                        return None
                    blocks[key] = []
                blocks[key].append(line)
            return blocks
        old_blocks, new_blocks = sections(left), sections(right)
        if old_blocks is None or new_blocks is None:
            continue
        order = list(old_blocks)
        for i, key in enumerate(new_blocks):
            if key not in order:
                previous = list(new_blocks)[i - 1]
                order.insert(order.index(previous) + 1, key)
        joined, disputed = [], []
        for key in order:
            if key not in old_blocks:
                joined.extend(new_blocks[key])
                continue
            if key not in new_blocks:
                joined.extend(old_blocks[key])
                continue
            old_rows, new_rows = old_blocks[key], new_blocks[key]
            opcodes = _difflib.SequenceMatcher(None, [l.strip() for l in old_rows],
                                               [l.strip() for l in new_rows], autojunk=False).get_opcodes()
            for tag, a0, a1, b0, b1 in opcodes:
                xs, ys = old_rows[a0:a1], new_rows[b0:b1]
                if tag == "equal":
                    joined.extend(y if y.rstrip() in prefer and x.rstrip() not in prefer else x
                                  for x, y in zip(xs, ys))
                elif tag == "delete":
                    joined.extend(xs)
                elif tag == "insert":
                    joined.extend(ys)
                elif len(xs) == len(ys):
                    for x, y in zip(xs, ys):
                        chosen = x if x.rstrip() in prefer and y.rstrip() not in prefer else y
                        if (x.rstrip() in prefer) == (y.rstrip() in prefer):
                            disputed.append(len(joined))
                        joined.append(chosen)
                elif len(xs) == 1 and a1 == len(old_rows) and xs[0].strip().split()[:1] == ys[0].strip().split()[:1]:
                    disputed.append(len(joined))
                    joined.extend(ys)  # a conflicting last screen row plus the newly exposed continuation
                else:
                    disputed.append(len(joined))
                    joined.extend(xs + ys)
        result = merged[:pos] + joined
        if notes is not None:
            for i in disputed:
                at = pos + i
                notes.setdefault("overlap_conflicts", []).append(
                    _conflict_context(result, at))
        return result
    return None


def _anchored_frame(merged, incoming, prefer, notes):
    """Reconcile an overlap using unique source rows, including sticky editor headers."""
    norm = lambda line: line.replace('[CUT OFF]', '').strip()
    old, new = [norm(line) for line in merged], [norm(line) for line in incoming]
    sticky = _re.compile(r"(?:[\w-]+:\s*(?:PROC|PROCEDURE)\b.*|DCL\s+1\s+\w+[,;]?|SELECT\s*\(.*)", _re.I)
    candidates = []
    for offset, anchor in enumerate(new):
        if ((len(anchor) < 12 and not sticky.fullmatch(anchor)) or sum(c.isalnum() for c in anchor) < 6
                or old.count(anchor) != 1 or new.count(anchor) != 1):
            continue
        pos = old.index(anchor)
        if pos < max(0, len(old)-100):
            continue
        prefix = new[:offset]
        revisited = False
        if prefix:
            pinned = sticky.fullmatch(prefix[0]) and all(not row or
                (sticky.fullmatch(row) and row in old[:pos]) for row in prefix)
            known = all(not row or old[:pos].count(row) == 1 for row in prefix)
            positions = [old[:pos].index(row) for row in prefix if row and row in old[:pos]]
            revisited = known and len(positions) >= 2 and positions == sorted(positions)
            if not pinned and not revisited:
                continue
        matcher = _difflib.SequenceMatcher(None, old[pos:], new[offset:], autojunk=False)
        blocks = matcher.get_matching_blocks()
        equal = sum(block.size for block in blocks)
        if equal < max(1 if revisited else 3, 0.65*min(len(old)-pos, len(new)-offset)):
            continue
        candidates.append((equal, -offset, pos, offset, matcher))
    if not candidates:
        return None
    _, _, pos, offset, matcher = max(candidates, key=lambda c:c[:2])
    left, right = merged[pos:], incoming[offset:]
    joined, disputed = [], []
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        xs, ys = left[a0:a1], right[b0:b1]
        if tag == 'equal':
            joined.extend(y if ('[CUT OFF]' in x and '[CUT OFF]' not in y) or
                          (y.rstrip() in prefer and x.rstrip() not in prefer and '[CUT OFF]' not in y)
                          else x for x,y in zip(xs,ys))
        elif tag == 'delete':
            joined.extend(xs)
        elif tag == 'insert':
            joined.extend(ys)
        elif len(xs)==1 and '[CUT OFF]' in xs[0] and ys and ys[0].strip().startswith(xs[0].replace('[CUT OFF]','').strip()):
            joined.extend(ys)
        elif len(xs)==len(ys):
            for x,y in zip(xs,ys):
                chosen = x if x.rstrip() in prefer and y.rstrip() not in prefer else y
                if x.strip()!=y.strip() and (x.rstrip() in prefer)==(y.rstrip() in prefer):
                    disputed.append(len(joined))
                joined.append(chosen)
        else:
            disputed.append(len(joined))
            joined.extend(xs+ys)
    result = merged[:pos]+joined
    for index in disputed:
        notes.setdefault('overlap_conflicts',[]).append(_conflict_context(result,pos+index))
    return result


def _rpg_section_frame(merged, incoming):
    """Place a revisited RPG routine by its unique change comment, preserving its tail."""
    marker = _re.compile(r'\*\s+(?:CHG|ENH)-[\w-]+:.*')
    norm = lambda row: row.replace('[CUT OFF]', '').strip().rstrip('.')
    for offset, row in enumerate(incoming):
        key = norm(row)
        if not marker.fullmatch(key):
            continue
        positions = [i for i, old in enumerate(merged) if norm(old) == key]
        if len(positions) != 1:
            continue
        start = positions[0]
        prefix = [norm(line) for line in incoming[:offset] if line.strip()]
        preceding = [norm(line) for line in merged[:start] if line.strip()]
        if prefix and (len(prefix) < 2 or prefix[-2:] != preceding[-2:]):
            continue
        end = next((i for i in range(start+1, len(merged))
                    if marker.fullmatch(norm(merged[i]))), len(merged))
        fresh = incoming[offset:]
        if not any(_re.fullmatch(r'C\s+\w+\s+BEGSR', norm(line), _re.I) for line in fresh):
            continue
        # This frame must revisit one routine, rather than span another routine.
        if any(marker.fullmatch(norm(line)) for line in fresh[1:]):
            continue
        old = [line for line in merged[start:end] if line.strip()]
        new = [line for line in fresh if line.strip()]
        matcher = _difflib.SequenceMatcher(None, list(map(norm, old)), list(map(norm, new)), autojunk=False)
        if sum(block.size for block in matcher.get_matching_blocks()) < 3:
            continue
        joined = []
        for tag, a0, a1, b0, b1 in matcher.get_opcodes():
            if tag == 'equal':
                joined.extend(y if '[CUT OFF]' in x and '[CUT OFF]' not in y else x
                              for x, y in zip(old[a0:a1], new[b0:b1]))
            elif tag == 'delete':
                joined.extend(old[a0:a1])
            elif tag == 'insert' or not any(line.strip() for line in old[a0:a1]):
                joined.extend(new[b0:b1])
            else:
                # Differing meaningful source is ambiguous; retain the review warning.
                break
        else:
            return merged[:start] + joined + merged[end:]
    return None


def _prepend(merged: list, b: list, min_overlap: int = 2) -> "list | None":
    """b is an earlier part of the file when its last lines are where merged begins. Editors with sticky scroll pin the
    enclosing lines (<html>, a class or function header) at the top of every screen, so the match may start a few rows
    into merged; those pinned rows are dropped."""
    for skip in range(0, 7):
        head_all = merged[skip:]
        for k in range(min(len(b), len(head_all), 60), max(min_overlap, 3 if skip else min_overlap) - 1, -1):
            head, tail = head_all[:k], b[-k:]
            if k < 4 and sum(len(_re.sub(r"\W", "", x)) for x in head) < 12:
                continue
            if min(_sim(x, y) for x, y in zip(tail, head)) >= 0.85:
                return b[:-k] + head_all
    return None


def _upgrade_cut(merged: list, b: list) -> list:
    """Replace a line cut off at a screen edge with the whole copy of it from another screenshot."""
    whole = [l for l in b if l.strip() and "[CUT OFF]" not in l]
    out = []
    for line in merged:
        if "[CUT OFF]" in line:
            stem = line.replace("[CUT OFF]", "").rstrip()
            matches = list(dict.fromkeys(w for w in whole if len(w.rstrip()) >= len(stem) and w.rstrip().startswith(stem)))
            full = matches[0] if len(matches) == 1 else None
            line = full if full is not None else line
        out.append(line)
    return out


def _bridge(merged: list, incoming: list):
    """A screenshot added later can fill the gap where two screens never overlapped: it holds the line that starts the
    far side of the gap, and ends on the line that follows it. Returns (merged, resolved_break) or None."""
    norm = lambda line: line.replace('[CUT OFF]', '').strip()
    inc = [norm(l) for l in incoming]
    for b in range(1, len(merged) - 2):
        if merged[b].strip() or not merged[b-1].strip() or not merged[b+1].strip():
            continue
        head, after = norm(merged[b+1]), norm(merged[b+2])
        if len(head) < 4 or len(after) < 4 or inc.count(head) != 1:
            continue
        h = inc.index(head)
        if h < 1:
            continue
        ends = [j for j in range(h+1, len(inc)) if inc[j] and after.startswith(inc[j]) and (inc[j] == after or '[CUT OFF]' in incoming[j])]
        if not ends:
            continue
        j = ends[-1]
        return merged[:b] + incoming[:j] + merged[b+2:], (merged[b-1].rstrip(), merged[b+1].rstrip())
    return None


def stitch_parts(parts: list) -> str:
    """Join per-image text, merging the overlap between consecutive chunks so
    scroll captures don't repeat their shared lines."""
    return _stitch(parts, frozenset(), {})


def _stitch(parts: list, prefer, notes: dict) -> str:
    from core.verify import sideways_merge_ex, sideways_views
    frames = []
    for k, part in enumerate(parts):
        lines = part.split("\n")
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        # a row clipped by the top or bottom of a screenshot is only a marker; the neighbouring screenshot shows it
        # whole, so it is dropped unless it is the very start or end of the capture
        if len(parts) > 1:
            while len(lines) > 1 and k < len(parts) - 1 and lines[-1].strip() == "[CUT OFF]":
                lines.pop()
            while len(lines) > 1 and k > 0 and lines[0].strip() == "[CUT OFF]":
                lines.pop(0)
        if lines:
            frames.append(lines)
    # screens taken after scrolling right show pieces of lines: stitch the whole-line screens first, then join the
    # pieces onto them, so a capture that starts (or wanders) sideways never becomes the base of the file
    sidx = sideways_views(frames)
    if len(sidx) == len(frames):
        sidx = set()
    order = [f for i, f in enumerate(frames) if i not in sidx] + [f for i, f in enumerate(frames) if i in sidx]
    side_ids = {id(frames[i]) for i in sidx}
    merged: list = []
    for fi, lines in enumerate(order):
        if not merged:
            merged = lines
            continue
        if id(lines) in side_ids:
            got = sideways_merge_ex(merged, lines, force=True)
            if got is not None:
                merged = got[0]
                notes["sideways"] = notes.get("sideways", 0) + got[1]
                notes.setdefault("joined", []).extend(got[2])
            else:
                notes["sideways_unmatched"] = notes.get("sideways_unmatched", 0) + 1
            continue
        if _mostly_contained(lines, merged):
            merged = _upgrade_cut(merged, lines)  # a re-capture adds nothing new, but may show cut lines whole
            continue
        side = sideways_merge_ex(merged, lines)      # scrolled right: the rest of long lines, not new lines
        if side is not None:
            merged = side[0]
            notes["sideways"] = notes.get("sideways", 0) + side[1]
            notes.setdefault("joined", []).extend(side[2])
            continue
        stitched = _rpg_section_frame(merged, lines)
        if stitched is None:
            stitched = _stitch_two(merged, lines, prefer=prefer, notes=notes)
        if stitched is None:
            stitched = _anchored_frame(merged, lines, prefer, notes)
        if stitched is None:
            stitched = _prepend(merged, lines)   # a screenshot added later can show an earlier part of the file
        if stitched is None:
            bridged = _bridge(merged, lines)
            if bridged is not None:
                stitched = bridged[0]
                notes["breaks"] = [x for x in notes.get("breaks", []) if tuple(x) != bridged[1]]
        if stitched is None:
            # no overlap with anything read so far: lines between these two screens may never have been on screen
            prev = next((l for l in reversed(merged) if l.strip()), "")
            nxt = next((l for l in lines if l.strip()), "")
            notes.setdefault("breaks", []).append((prev.rstrip(), nxt.rstrip()))
        merged = _upgrade_cut(stitched if stitched is not None else merged + [""] + lines, lines)
    return "\n".join(merged)


def analyse_incremental(client, image_paths: list, cache_dir: Path = None) -> dict:
    """Per-image extraction (+ content-hash cache) -> stitched text -> overview.

    Returns the same {"explanation", "extracted_text"} shape as analyse_images,
    so build_docx() and the callers work unchanged.
    """
    parts, metas = [], []
    for path in image_paths:
        if cache_dir is not None:
            extract_to_cache(client, path, cache_dir)
            text = cache_path_for(path, cache_dir).read_text()
            meta = verify_for(path, cache_dir)
        else:
            extracted = extract_structured(client, path)
            text, meta = extracted["raw"], extracted.get("verify") or {}
        if not text.strip():
            raise ValueError(f"No readable text in screenshot {path.name}; incomplete captures cannot be finalized.")
        parts.append(text.strip("\r\n"))
        metas.append(meta)
    full_text, _, notes, statuses = merge_verified(parts, metas)
    if not full_text.strip():
        return {"explanation": "", "extracted_text": "",
                "is_code": False, "language": "", "extension": ""}

    print("  classifying + writing overview...")
    meta = synthesize_final(client, full_text)
    return {
        "explanation": meta["overview"],
        "extracted_text": full_text,
        "is_code": meta["is_code"],
        "language": meta["language"],
        "extension": meta["extension"],
    }




def cache_path_for(path: Path, cache_dir: Path) -> Path:
    """Content-addressed cache location for an image's extracted text."""
    return cache_dir / f"{_content_digest(path)}.md"


_digest_memo: dict = {}
_digest_lock = threading.Lock()


def _content_digest(path: Path) -> str:
    """sha256 of the file, memoized by (path, mtime, size) so unchanged PNGs are hashed once."""
    try:
        st = Path(path).stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return hashlib.sha256(_robust.read_bytes(path)).hexdigest()
    with _digest_lock:
        hit = _digest_memo.get(key)
    if hit:
        return hit
    digest = hashlib.sha256(_robust.read_bytes(path)).hexdigest()
    with _digest_lock:
        if len(_digest_memo) > 4096:
            _digest_memo.clear()
        _digest_memo[key] = digest
    return digest


import threading as _cache_threading
_cache_locks_guard = _cache_threading.Lock()
import weakref as _cache_weakref
_cache_locks = _cache_weakref.WeakValueDictionary()


def _publish_cache(path, text):
    import tempfile
    import os
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def extract_to_cache(client, path: Path, cache_dir: Path) -> None:
    """Share one in-flight extraction per cache entry and publish complete text atomically."""
    from core import capture_gate
    capture_gate.wait()
    cf = cache_path_for(path, cache_dir)
    key = str(cf.resolve())
    with _cache_locks_guard:
        lock = _cache_locks.setdefault(key, _cache_threading.Lock())
    with lock:
        if cf.exists():
            from core import spacing
            calibration=spacing.calibration_for(path)
            old=verify_for(path,cache_dir)
            if (old.get('spacing') or {}).get('revision')!=spacing.REVISION or old.get('spacing_signature')!=spacing.signature(calibration):
                original=cf.read_text()
                if not cf.with_suffix('.ocr.md').exists():
                    _publish_cache(cf.with_suffix('.ocr.md'),original)
                legacy = _normalize_extract(original) if original.lstrip().startswith('{') and '"raw_transcription"' in original else None
                fixed,checked,_=measured_frame(None,path,legacy['raw'] if legacy else original,calibration=calibration)
                if legacy:
                    checked.update({k:legacy[k] for k in ('numbers','numbers_seen','numbers_rejected') if k in legacy})
                checked.update({k:old[k] for k in ('numbers','numbers_seen','numbers_rejected') if k in old})
                checked['spacing_signature']=spacing.signature(calibration)
                checked['source_sha256']=hashlib.sha256(fixed.encode()).hexdigest()
                _publish_cache(cf.with_suffix('.verify.json'),json.dumps(checked))
                _publish_cache(cf,fixed)
            return
        res = extract_structured(client, path)
        cache_dir.mkdir(parents=True, exist_ok=True)
        from core import spacing
        res.setdefault('verify',{})['spacing_signature']=spacing.signature(spacing.calibration_for(path))
        res['verify']['source_sha256']=hashlib.sha256(res['raw'].encode()).hexdigest()
        _publish_cache(cf.with_suffix('.ocr.md'),res.get('observed_raw',res['raw']))
        try:
            _publish_cache(cf.with_suffix(".corr.json"), json.dumps(res["corrections"]))
        except Exception:  # noqa: BLE001 - corrections are advisory; never fail the cache write
            pass
        try:
            if res.get("verify"):
                _publish_cache(cf.with_suffix(".verify.json"), json.dumps(res["verify"]))
        except Exception:  # noqa: BLE001
            pass
        _publish_cache(cf, res["raw"])


def verify_for(path: Path, cache_dir: Path) -> dict:
    """The pixel check and line numbers cached next to an image's text ({} for older captures)."""
    cf = cache_path_for(path, cache_dir).with_suffix(".verify.json")
    try:
        data = json.loads(cf.read_text()) if cf.exists() else {}
        if isinstance(data,dict) and data.get('source_sha256') and data['source_sha256']!=hashlib.sha256(cache_path_for(path,cache_dir).read_text().encode()).hexdigest():
            return {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


# ── Code fix loop (Milestone 7, Layer C) ─────────────────────────────────────────

def corrections_for(path: Path, cache_dir: Path) -> list:
    """Read the corrections_applied[] cached next to an image's raw text (or [])."""
    cf = cache_path_for(path, cache_dir).with_suffix(".corr.json")
    if cf.exists():
        try:
            data = json.loads(cf.read_text())
            return data if isinstance(data, list) else []
        except Exception:  # noqa: BLE001
            return []
    return []


FIX_SYSTEM_PROMPT = (
    "You are correcting a source file that was transcribed from screenshots and "
    "failed to compile. You are given the language, the compiler/parser errors, "
    "and the current code. The errors are TRANSCRIPTION mistakes (a mis-read "
    "character, a missing bracket/colon/semicolon, a wrong quote, a broken indent).\n"
    "Fix ONLY what the errors point to, with the MINIMAL change needed. Do NOT add, "
    "remove, rename, or invent functionality, imports, comments, or logic that is "
    "not clearly required to resolve the specific reported error. Preserve the "
    "original code exactly everywhere else. If a fix is genuinely ambiguous, leave "
    "that line unchanged rather than guessing.\n"
    "Return ONLY the corrected, complete source file — no commentary, no markdown."
)


FIX_MAX_TOKENS = 64000   # a whole source file comes back, so the output must not be capped at a few thousand tokens


class FixRejected(ValueError):
    """The model's fix cannot be trusted (truncated, refused, or drastically shorter than the original)."""


def fix_source(client, code: str, language: str, errors: str) -> str:
    """One API call: return a corrected version of the code given compiler errors.

    Streams (large output). Raises FixRejected when the reply was cut off or refused, so a
    truncated file is never mistaken for a fix.
    """
    kwargs = dict(
        model=MODEL,
        max_tokens=FIX_MAX_TOKENS,
        system=FIX_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": (
            f"Language: {language or 'unknown'}\n\n"
            f"Compiler/parser errors:\n{errors}\n\n"
            f"Current code:\n{code}"
        )}],
    )
    stream = getattr(getattr(client, "messages", None), "stream", None)
    if callable(stream):
        with stream(**kwargs) as s:
            msg = s.get_final_message()
    else:
        msg = client.messages.create(**kwargs)
    reason = getattr(msg, "stop_reason", None)
    if reason == "max_tokens":
        raise FixRejected("the fix was cut off at the output limit; the original was kept")
    if reason == "refusal":
        raise FixRejected("the model declined to produce a fix; the original was kept")
    return "".join(getattr(b, "text", "") for b in msg.content).strip()


def fix_looks_complete(original: str, fixed: str, min_ratio: float = 0.7):
    """None when `fixed` is plausibly a whole corrected file, else the reason it must not replace the original."""
    if not fixed.strip():
        return "the fix was empty"
    before = len([l for l in original.splitlines() if l.strip()])
    after = len([l for l in fixed.splitlines() if l.strip()])
    if before and after < before * min_ratio:
        return f"the fix has {after} lines against {before} in the original (looks truncated)"
    return None


# ── Document builder ───────────────────────────────────────────────────────────

# Converts Markdown returned by Claude into native Word paragraph styles.
def markdown_to_docx(doc, md_text: str) -> None:
    if not md_text.strip():
        doc.add_paragraph("(No text content detected.)")
        return

    for line in md_text.splitlines():
        if line.startswith("### "):
            doc.add_heading(line[4:].strip(), level=3)
        elif line.startswith("## "):
            doc.add_heading(line[3:].strip(), level=2)
        elif line.startswith("# "):
            doc.add_heading(line[2:].strip(), level=1)
        elif line.startswith("- ") or line.startswith("* "):
            doc.add_paragraph(line[2:].strip(), style="List Bullet")
        elif len(line) > 2 and line[0].isdigit() and line[1:3] in (". ", ") "):
            doc.add_paragraph(line[3:].strip(), style="List Number")
        elif line.strip() == "":
            doc.add_paragraph("")
        else:
            doc.add_paragraph(line.strip())


# Writes only the extracted text to a Word doc — no headers or labels.
def build_docx(result: dict) -> "Document":
    from docx import Document

    doc = Document()
    extracted = result.get("extracted_text", "").strip("\r\n")
    if extracted.strip():
        for line in extracted.splitlines():
            doc.add_paragraph(line)
    else:
        doc.add_paragraph("(No text content was extracted from the images.)")
    return doc


EXPLAIN_SYSTEM_PROMPT = (
    "You are given a compiler/parser error from source code that was transcribed from a "
    "screenshot. In 1-2 short, plain-English sentences, explain what the error means and which "
    "LINE it is on. If it looks like a transcription/scan artifact \u2014 an extra or missing "
    "brace, bracket, parenthesis, quote, semicolon, or colon rather than a real logic bug \u2014 "
    "say it is likely a scan artifact and exactly what to add or remove to fix it. Always name the "
    "line number. Be concise and friendly; do NOT output code or restate the raw error verbatim."
)


def explain_error(client, language: str, errors: str, code: str = "") -> str:
    """One cheap call: a plain-English, line-referenced explanation of a compiler error."""
    if not errors or errors.strip().lower() == "none":
        return ""
    try:
        msg = client.messages.create(
            model=TEXT_MODEL, max_tokens=300, system=EXPLAIN_SYSTEM_PROMPT,
            messages=[{"role": "user", "content":
                       f"Language: {language or 'unknown'}\n\nCompiler error:\n{errors}\n\nCode:\n{code[:4000]}"}],
        )
        return "".join(getattr(b, "text", "") for b in msg.content).strip()
    except Exception:  # noqa: BLE001
        return ""


INDENT_REVIEW_SYSTEM = (
    "You are inspecting a screenshot of source code for INDENTATION mistakes ONLY. Judge by the "
    "visible horizontal alignment of each line \u2014 NOT by what the code 'should' look like. Flag a "
    "line only when its indentation is visibly inconsistent with the block it belongs to: e.g. a "
    "line indented MORE or LESS than its siblings, a body not indented under its header, or a "
    "sudden unexplained jump in indentation. Do NOT normalise in your head \u2014 if a line sticks out, "
    "report it exactly as it appears.\n"
    "Return ONLY a JSON object: {\"issues\": [{\"line_text\": <the code on the mis-aligned line, "
    "trimmed of leading spaces>, \"problem\": <\"over-indented\"|\"under-indented\"|\"inconsistent\">, "
    "\"note\": <short reason, e.g. 'one level deeper than the lines around it'>}]}. Return an EMPTY "
    "issues array if the indentation looks consistent. Be CONSERVATIVE: only flag a line you are "
    "confident is visibly misaligned; when in doubt, do not flag it."
)


def review_indentation(client, image_paths, language: str = "") -> list:
    """Image-level indentation check: look at the screenshot(s) and report lines whose
    indentation is visibly inconsistent with their block. Catches indent errors the
    faithful transcription may have silently auto-corrected. Returns a list of
    {line_text, problem, note}. Conservative; [] on any failure."""
    imgs = sorted(image_paths or [])[:8]
    content = []
    for p in imgs:
        try:
            p = Path(p)
            b64 = base64.standard_b64encode(_robust.read_bytes(p)).decode()
            content.append({"type": "image", "source": {"type": "base64",
                            "media_type": _media_type(p), "data": b64}})
        except Exception:  # noqa: BLE001
            pass
    if not content:
        return []
    content.append({"type": "text", "text":
                    f"Language: {language or 'unknown'}. Inspect the code for indentation mistakes. "
                    "Return only the JSON object."})
    try:
        msg = client.messages.create(model=MODEL, max_tokens=1024, system=INDENT_REVIEW_SYSTEM,
                                     messages=[{"role": "user", "content": content}])
        raw = "".join(getattr(b, "text", "") for b in msg.content).strip()
        data = _parse_json(raw) or {}
        issues = data.get("issues", []) if isinstance(data, dict) else []
        return [i for i in issues if isinstance(i, dict) and str(i.get("line_text", "")).strip()]
    except Exception:  # noqa: BLE001
        return []
