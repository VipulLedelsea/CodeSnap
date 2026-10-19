"""Is the first line captured really the top of the file, and the last line really the end?

A screenshot cannot show that the lines above or below it are missing, and a capture that starts a little way down a file
loses its head without any error (the first screenshot of a 1,000-line SQL file began at line 13). So each file's start and
end are either proved by evidence or put to the person as a question that names the first or last line shown.

Evidence for the start: the language's own opener (a COBOL IDENTIFICATION DIVISION, a BMS DFHMSD, a JCL JOB card, a REXX
opening comment, an XML prolog, a Java package line ...) or an editor gutter that starts at 1.
Evidence for the end: a blank band under the last line of the final screenshot (core.model.completeness.end_reached) or an
editor gutter that reaches the last line.
A person's confirmation is stored like any confirmed line, so it survives a rebuild of the file.
"""
import re

from . import confirmed

START_ASK = ("This is the first line the screenshots show. Is it the very top of the file? If lines above it are missing, "
             "choose \"Lines are missing here\", then scroll to the top of the file and add a screenshot of it.")
END_ASK = ("This is the last line the screenshots show. Is it the very end of the file? If lines below it are missing, "
           "choose \"Lines are missing here\", then scroll to the bottom of the file and add a screenshot of it.")

_FIRST = [
    re.compile(r"^<\?xml\b|^<!DOCTYPE\b|^<\?php\b|^#!\s*/", re.I),
    re.compile(r"^package\s+[\w.]+\s*;|^namespace\s+[\w.]+|^using\s+[\w.]+\s*;|^#include\b|^#pragma\b"),
    re.compile(r"^//\S*\s+JOB\b", re.I),                                  # a JCL JOB card
]


def _code_lines(lines, limit=12):
    out = []
    for line in lines:
        if line.strip():
            out.append(line)
        if len(out) >= limit:
            break
    return out


def start_evidence(art) -> str | None:
    """Why the first line is the top of the file, or None when nothing proves it."""
    name = (art.get("name") or "").lower()
    text = art.get("transcription") or ""
    first = _code_lines(text.splitlines())
    if not first:
        return None
    body = "\n".join(first)
    if re.search(r"\b(IDENTIFICATION|ID)\s+DIVISION\b", body, re.I):
        return "the file opens with its IDENTIFICATION DIVISION"
    if re.search(r"\bDFHMSD\b(?!\s+TYPE=FINAL)", "\n".join(l for l in first[:4] if not l.lstrip().startswith("*")), re.I):
        return "the map opens with its DFHMSD header"
    if name.endswith((".rexx", ".rex", ".exec")) and first[0].lstrip().startswith("/*"):
        return "a REXX program opens with a comment"
    for line in first[:3]:
        if not line.startswith((" ", "\t")) and any(rx.match(line) for rx in _FIRST):
            return "the file opens with " + line.strip()[:40]
    return None


def top_proven(store, art) -> bool:
    """Was the file scrolled to its first line before its first screenshot? The capture does that and records it with the session."""
    try:
        first = store.artifact_evidence(art["id"])[:1]
        sid = first[0].get("session_id") if first else None
        row = store._one("SELECT note FROM capture_session WHERE id = ?", (sid,)) if sid else None
        return bool(row and "top_proven" in (row["note"] or ""))
    except Exception:  # noqa: BLE001 - older programs have no such record
        return False


def end_evidence(store, art) -> str | None:
    from .completeness import end_reached
    ver = store.verification(art["id"]) or {}
    lines = (art.get("transcription") or "").splitlines()
    if ver.get("numbers") and ver.get("last_line") and ver.get("last_line") >= len(lines):
        return "the editor's line numbers reach the last line"
    if end_reached(store, art):
        return "the last screenshot shows empty space under the last line"
    return None


def _confirmed(store, art, n):
    sigs = (store.get_meta("confirmed_lines") or {}).get(art.get("name"))
    return confirmed.is_confirmed(sigs, (art.get("transcription") or "").splitlines(), n)


def flags(store, art) -> list:
    """[{line, kind: 'start' | 'end', reason}] for the edges of a source file that nothing has yet proved or confirmed."""
    if art.get("artifact_type") not in (None, "code"):
        return []
    lines = (art.get("transcription") or "").splitlines()
    if not lines:
        return []
    out = []
    ver = store.verification(art["id"]) or {}
    start_known = (bool(ver.get("numbers") and ver.get("first_line") == 1) or start_evidence(art) or _confirmed(store, art, 1)
                   or top_proven(store, art))
    if not start_known:
        out.append({"line": 1, "kind": "start", "reason": START_ASK})
    last = len(lines)
    if not (end_evidence(store, art) or _confirmed(store, art, last)):
        out.append({"line": last, "kind": "end", "reason": END_ASK})
    return out


def marked_missing(store, art, kind) -> bool:
    n = 1 if kind == "start" else len((art.get("transcription") or "").splitlines())
    return confirmed.is_marked_missing(store, art.get("name"), art.get("transcription"), n)


def settle(store, art, result):
    """Drop the completeness reasons about a file's start or end once that edge is proved or a person confirmed it.
    Without this a confirmed first or last line stops the question being asked, yet the file stays "partial" because the
    structure check still says its start or end was not captured."""
    if not result.get("partial"):
        return result
    from .completeness import drop_end_reasons, drop_start_reasons
    lines = (art.get("transcription") or "").splitlines()
    ver = store.verification(art["id"]) or {}
    if ((ver.get("numbers") and ver.get("first_line") == 1) or start_evidence(art) or _confirmed(store, art, 1)
            or top_proven(store, art)):
        result = drop_start_reasons(result)
    if lines and (end_evidence(store, art) or _confirmed(store, art, len(lines))):
        result = drop_end_reasons(result)
    return result
