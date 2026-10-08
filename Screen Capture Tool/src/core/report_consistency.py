"""Reads a finished report from start to end and lists statements that contradict each other. Both quotes of every
contradiction must occur in the report, so nothing is reported that the text does not contain."""
import io
import re
import time

from core import deepdive as D

MAX_CHARS = 400000
MAX_PARAGRAPH = 800
TOOL = {
    "name": "record_inconsistencies",
    "description": "Record each place where the report contradicts itself.",
    "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
        "topic": {"type": "string"},
        "kind": {"type": "string", "enum": ["number", "count", "range", "rating", "date", "description", "recommendation"]},
        "first_quote": {"type": "string", "description": "Exact text of the first statement, copied from the report"},
        "first_section": {"type": "string"},
        "second_quote": {"type": "string", "description": "Exact text of the second statement, copied from the report"},
        "second_section": {"type": "string"},
        "why": {"type": "string"}},
        "required": ["topic", "kind", "first_quote", "second_quote", "why"]}}}, "required": ["items"]},
}
SYSTEM = """You read a finished assessment report from start to end and find places where it contradicts itself.
Report only a contradiction between two statements in the report. Never report problems with the code, the writing or missing information.
Typical cases:
- the same quantity given as different numbers or ranges: effort, durations, counts of files, lines, findings, components, data stores, vulnerabilities
- the same item given different ratings, tiers, priorities, dates or deadlines
- a recommendation that the report's own scoring does not support
- a description that says opposite things in two places (batch and interactive, shares data and shares none)
Not contradictions: figures about different things, a figure inside a stated range, rounding in a summary, a statement and its own stated exception.
For each one copy the exact text of both statements as first_quote and second_quote, and name each section.
If you are not sure both statements are about the same thing, leave it out. Return an empty list when the report is consistent."""


NOT_ONE = re.compile(r"\b(actually consistent|(?:is |are )?consistent,? (?:not|-)|not a (?:real )?contradiction|skip\b|remove\b|not an? (?:real )?(?:issue|inconsisten))", re.I)


def _norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


def report_text(docx_bytes):
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    doc = Document(io.BytesIO(docx_bytes))
    lines = []
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, doc)
            text = p.text.strip()
            if not text:
                continue
            style = p.style.name if p.style is not None else ""
            lines.append(("## " + text) if style.startswith(("Heading", "Title")) else text[:MAX_PARAGRAPH])
        elif tag == "tbl":
            for row in Table(child, doc).rows:
                cells = [c.text.strip().replace("\n", " ")[:MAX_PARAGRAPH // 2] for c in row.cells]
                if any(cells):
                    lines.append(" | ".join(cells))
    return "\n".join(lines)


def verified(items, text):
    flat = _norm(text)
    out, seen = [], set()
    for it in items or []:
        if not isinstance(it, dict):
            continue
        a, b = _norm(it.get("first_quote")), _norm(it.get("second_quote"))
        if len(a) < 8 or len(b) < 8 or a == b or a not in flat or b not in flat:
            continue
        if NOT_ONE.search(it.get("why") or ""):
            continue       # the reader said, in its own words, that this is not a contradiction
        key = tuple(sorted((a, b)))
        if key in seen:
            continue
        seen.add(key)
        out.append({"topic": (it.get("topic") or "").strip(), "kind": it.get("kind"), "first": a, "first_section": it.get("first_section", ""),
                    "second": b, "second_section": it.get("second_section", ""), "why": (it.get("why") or "")[:300]})
    return out


def chunks(text, limit=None, lead=40000):
    """The report as pieces that each fit one read. Every piece starts with the executive summary section, because a
    contradiction between the summary and a later section is the one that matters most."""
    limit = limit or MAX_CHARS
    if len(text) <= limit:
        return [text]
    parts = re.split(r"(?m)^(?=## )", text)
    first = parts[0] if not parts[0].startswith("## ") else ""
    sections = [p for p in parts if p.startswith("## ")]
    summary = next((p for p in sections if re.match(r"## 1[. ]", p) or "Application summary" in p[:80]), "")[:lead]
    room = limit - len(summary) - 200
    out, cur, size = [], [], 0
    for sec in ([first] if first else []) + sections:
        if sec is summary:
            continue
        pieces = [sec[i:i + room] for i in range(0, len(sec), room)] if len(sec) > room else [sec]
        for piece in pieces:
            if cur and size + len(piece) > room:
                out.append(summary + "".join(cur))
                cur, size = [], 0
            cur.append(piece)
            size += len(piece)
    if cur:
        out.append(summary + "".join(cur))
    return out


def run(store, client, report_docx, model=None) -> dict:
    from core import pipeline
    model = model or pipeline.FINAL_MODEL
    text = report_text(report_docx)
    pieces = chunks(text)

    def ask(piece):
        msg, ms = D._call(client, model, SYSTEM, TOOL, "Report:\n\n" + piece)
        D._log(store, "report_consistency", None, model, msg, ms)
        if getattr(msg, "stop_reason", None) == "max_tokens":
            raise ValueError("consistency read was truncated")
        return (D._tool(msg, TOOL["name"]) or {}).get("items") or []

    found = [it for part in D.parallel(ask, pieces) for it in part]
    items = verified(found, text)
    store.set_meta("report_consistency", {"ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": model, "items": items,
                                          "pieces": len(pieces)})
    return {"items": items}


def items(store) -> list:
    return (store.get_meta("report_consistency") or {}).get("items") or []
