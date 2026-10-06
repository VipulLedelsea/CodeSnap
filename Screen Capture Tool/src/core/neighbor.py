import base64
import difflib
import os
import re
from pathlib import Path

from core import verify
from core import analysis as A

MODEL = os.environ.get("CODESNAP_NEIGHBOR_MODEL", A.PLAIN_MODEL)
BAD = ("mismatch", "cut", "rows")
MAX_LINES = int(os.environ.get("CODESNAP_NEIGHBOR_MAX_LINES", "60"))
TOOL = {
    "name": "record_lines",
    "description": "Record what this screenshot shows for each numbered line.",
    "input_schema": {"type": "object", "properties": {"lines": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "integer"},
        "found": {"type": "boolean", "description": "true only when this exact line is fully and clearly visible"},
        "text": {"type": "string", "description": "the line copied exactly as shown, no cut-off marker"}},
        "required": ["id", "found"]}}}, "required": ["lines"]},
}
SYSTEM = ("You are a literal OCR engine. Each numbered entry is a line of source code that an earlier screenshot showed "
          "unclearly, with the lines around it. Find that line in THIS screenshot. If it is fully and clearly visible, "
          "copy it exactly as shown, character for character, mistakes included. If it is cut off, blurry, "
          "or not visible, set found to false. Never guess, complete or correct a line.")


def _bad_lines(final, notes, statuses):
    aligned = list(notes.get("line_statuses") or [])
    out = []
    for i, line in enumerate(final.split("\n")):
        if not line.strip():
            continue
        s = aligned[i] if i < len(aligned) else None
        if "[CUT OFF]" in line or s in BAD or (s is None and (statuses or {}).get(line.rstrip()) in BAD):
            out.append(i)
    return out[:MAX_LINES]


def _visible(line):
    return re.sub(r"\s+", " ", line.replace("[CUT OFF]", "")).strip()


def _same_line(old, new):
    a, b = _visible(old), _visible(new)
    if not a:
        return bool(b)
    if "[CUT OFF]" in old and b.startswith(a[:max(3, len(a) - 2)]):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.6


def _neighbours(frames, bad, final, paths):
    near = {}
    for k, part in enumerate(frames):
        mapped = verify._line_map(part, final)
        for i in bad:
            if i < len(mapped) and mapped[i] is not None:
                for j in (k - 1, k + 1):
                    if 0 <= j < len(paths):
                        near.setdefault(j, set()).add(i)
    return near


def _ask(client, path, entries):
    body = "\n\n".join(f"{n}. before: {b!r}\n   line: {l!r}\n   after: {a!r}" for n, (b, l, a) in enumerate(entries, 1))
    data = base64.standard_b64encode(Path(path).read_bytes()).decode()
    msg = client.messages.create(
        model=MODEL, max_tokens=4096, system=SYSTEM, tools=[TOOL], tool_choice={"type": "tool", "name": TOOL["name"]},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": A._media_type(Path(path)), "data": data}},
            {"type": "text", "text": body}]}])
    for block in msg.content:
        if getattr(block, "type", "") == "tool_use":
            return {int(x["id"]): x for x in (block.input or {}).get("lines") or [] if isinstance(x, dict) and "id" in x}
    return {}


def repair(client, paths, raws, final, notes, statuses):
    """Lines still unclear after stitching are looked for in the screenshots just before and after the ones that
    showed them. A clearer, matching reading replaces the weak one. Returns (final, repaired)."""
    if client is None or len(paths) < 2 or not final.strip():
        return final, []
    bad = _bad_lines(final, notes, statuses)
    if not bad:
        return final, []
    mode = A.source_mode(raws)
    frames = [A.clean_source(r, mode) for r in raws]
    lines = final.split("\n")
    near = _neighbours(frames, bad, final, paths)
    found = {}
    for j, idx in sorted(near.items()):
        order = sorted(idx)
        entries = [(lines[i - 1] if i else "", lines[i], lines[i + 1] if i + 1 < len(lines) else "") for i in order]
        try:
            got = _ask(client, paths[j], entries)
        except Exception:  # noqa: BLE001
            continue
        for n, i in enumerate(order, 1):
            r = got.get(n) or {}
            text = (r.get("text") or "").rstrip()
            if r.get("found") and text.strip() and "[CUT OFF]" not in text and _same_line(lines[i], text):
                found.setdefault(i, (j, text))
    repaired = []
    aligned = list(notes.get("line_statuses") or [])
    for i, (j, text) in sorted(found.items()):
        old = lines[i]
        bare = old.lstrip().startswith("[CUT OFF]")
        indent = re.match(r"\s*", text).group(0) if bare else re.match(r"\s*", old).group(0)
        lines[i] = indent + text.lstrip()
        if i < len(aligned):
            aligned[i] = "reread"
        statuses[lines[i].rstrip()] = "reread"
        repaired.append({"line": i + 1, "screenshot": j + 1, "was": old, "now": lines[i]})
    if aligned:
        notes["line_statuses"] = aligned
    notes["neighbor_reread"] = repaired
    return "\n".join(lines), repaired
