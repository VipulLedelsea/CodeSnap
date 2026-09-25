import time

from .kinds import ENTITY_KINDS, RELATION_KINDS

PROMPT_VERSION = "structure-v1"
CHUNK_LINES = 600
CHUNK_OVERLAP = 20
MAX_TOKENS = 16000

STRUCTURE_SYSTEM = f"""You map the structure of ONE source file from a legacy program so it can be stored in a program model.

You receive the file with line numbers ("  12| code"). Record, using the record_structure tool:

ENTITIES defined or declared IN THIS FILE: modules/namespaces/programs, classes, interfaces, functions/methods,
COBOL sections and paragraphs, fields/variables that matter to data flow (class fields, COBOL records and 01/05 items
that are read or written), database tables and columns declared here, screens/maps, API endpoints, CICS transactions,
jobs, and config items.
- kind: one of {sorted(ENTITY_KINDS)}
- name: the exact identifier as written (no parent prefix).
- parent: the exact name of the enclosing entity defined in this file (class for a method, section for a paragraph,
  table for a column), or null.
- line_start / line_end: the line numbers from the listing.
- attrs: only facts visible in the code, e.g. signature, params, returns, visibility, bases, type, picture, level,
  method, path, transid.

RELATIONS from something in this file to anything (in this file or elsewhere): calls, imports/includes/COPY,
inheritance, reads/writes of tables, files or records, screens displayed, CICS LINK/XCTL/START, SQL access,
network/API calls, connections to external systems.
- kind: one of {sorted(RELATION_KINDS)}
- source: the name of the entity in this file where it happens (use Parent.name for members, or the file's top-level
  module/program name if it happens at top level).
- target: the target's name exactly as written in the code.
- target_kind: best-guess kind of the target, or null.
- line: line number.

Rules:
- Record ONLY what the code shows. Never invent entities, calls, tables or systems.
- Targets that are not defined in this file are still recorded; they will be matched to other files later.
- Skip language built-ins and standard-library calls unless they touch data stores, files, the network or the screen.
- If the listing is a fragment of a larger file, record what is visible."""

STRUCTURE_TOOL = {
    "name": "record_structure",
    "description": "Record the entities and relations found in the file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": sorted(ENTITY_KINDS)},
                        "name": {"type": "string"},
                        "parent": {"type": ["string", "null"]},
                        "line_start": {"type": ["integer", "null"]},
                        "line_end": {"type": ["integer", "null"]},
                        "attrs": {"type": "object"},
                    },
                    "required": ["kind", "name"],
                },
            },
            "relations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": sorted(RELATION_KINDS)},
                        "source": {"type": "string"},
                        "target": {"type": "string"},
                        "target_kind": {"type": ["string", "null"]},
                        "line": {"type": ["integer", "null"]},
                    },
                    "required": ["kind", "source", "target"],
                },
            },
        },
        "required": ["entities", "relations"],
    },
}


def numbered(lines: list, start: int = 1) -> str:
    width = len(str(start + len(lines)))
    return "\n".join(f"{str(i).rjust(width)}| {line}" for i, line in enumerate(lines, start))


def chunks(code: str, size: int = CHUNK_LINES, overlap: int = CHUNK_OVERLAP):
    lines = code.splitlines()
    if len(lines) <= size:
        yield 1, lines
        return
    start = 0
    while start < len(lines):
        yield start + 1, lines[start:start + size]
        if start + size >= len(lines):
            return
        start += size - overlap


def _tool_input(message) -> dict:
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", "") == "tool_use" and getattr(block, "name", "") == STRUCTURE_TOOL["name"]:
            return dict(getattr(block, "input", {}) or {})
    return {}


def extract_structure(client, code: str, *, filename: str = "", language: str = "", model: str | None = None) -> dict:
    if model is None:
        from core.analysis import MODEL as model
    entities, relations, calls = [], [], []
    parts = list(chunks(code))
    for index, (start, lines) in enumerate(parts, 1):
        header = f"File: {filename or 'unknown'}\nLanguage: {language or 'unknown'}\n"
        if len(parts) > 1:
            header += f"Part {index} of {len(parts)} (lines {start}-{start + len(lines) - 1}).\n"
        began = time.monotonic()
        message = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=STRUCTURE_SYSTEM,
            tools=[STRUCTURE_TOOL],
            tool_choice={"type": "tool", "name": STRUCTURE_TOOL["name"]},
            messages=[{"role": "user", "content": header + "\n" + numbered(lines, start)}],
        )
        usage = getattr(message, "usage", None)
        calls.append({
            "model": model,
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "ms": int((time.monotonic() - began) * 1000),
            "stop_reason": getattr(message, "stop_reason", None),
        })
        data = _tool_input(message)
        entities += [e for e in data.get("entities") or [] if isinstance(e, dict)]
        relations += [r for r in data.get("relations") or [] if isinstance(r, dict)]
    return {"entities": entities, "relations": relations, "calls": calls, "prompt_version": PROMPT_VERSION}
