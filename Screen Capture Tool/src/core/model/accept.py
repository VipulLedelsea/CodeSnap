"""Let the person accept everything a file is flagged for, whatever kind it is.

The review lists questions that belong to a line, and each can be confirmed one at a time. Some findings belong to the whole file ("the
start looks missing", "paragraph 5120 is missing between 5110 and 5130") and nothing in a line review resolves them, so a file could stay
"needs attention" for good. Accepting says: I have looked, this is how the file is. Everything stays visible in the report's open items;
it just stops holding the file back.
"""
from . import confirmed


def accept_all(store, art) -> dict:
    """Confirm every flagged line of the file and accept its whole-file findings. Returns what was accepted."""
    from core.model import edges
    from core.model.completeness import check
    from core.model.line_review import items
    text = art.get("transcription") or ""
    lines = text.splitlines()
    name = art["name"]
    accepted_lines = [it["line"] for it in items(store, art)]
    for n in accepted_lines:
        confirmed.add(store, name, text, n)
    if lines:                                           # the first and last line: the start and end questions
        confirmed.add(store, name, text, 1)
        confirmed.add(store, name, text, len(lines))
    for n, line in enumerate(lines, 1):                 # a line cut off at the screen edge, accepted as it reads
        if "[CUT OFF]" in line:
            confirmed.add(store, name, text, n)
    verification = store.verification(art["id"])
    if verification:
        store.set_verification(art["id"], verification)      # drops the flags that are now confirmed
    found = edges.settle(store, art, check(text, name, art.get("language") or ""))
    reasons = list(found.get("reasons") or []) if found.get("partial") else []
    if reasons:
        confirmed.accept_reasons(store, art, reasons)
    return {"lines": sorted(set(accepted_lines)), "findings": reasons}
