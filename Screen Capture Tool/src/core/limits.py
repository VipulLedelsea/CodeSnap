"""Keeps one model call inside its input limit. A file of tens of thousands of lines cannot be sent whole."""

MAX_CHARS = 150000   # about 40,000 tokens of code


def fit_text(text: str, max_chars: int = MAX_CHARS) -> str:
    """The text itself when it fits; otherwise its start and end (cut at line breaks) with a note of what was left out."""
    text = text or ""
    if len(text) <= max_chars:
        return text
    lines = text.split("\n")
    head, tail, used = [], [], 0
    budget_head, budget_tail = int(max_chars * 0.7), int(max_chars * 0.3)
    for line in lines:
        if used + len(line) + 1 > budget_head:
            break
        head.append(line)
        used += len(line) + 1
    used = 0
    for line in reversed(lines[len(head):]):
        if used + len(line) + 1 > budget_tail:
            break
        tail.append(line)
        used += len(line) + 1
    tail.reverse()
    omitted = len(lines) - len(head) - len(tail)
    return "\n".join(head) + f"\n[... {omitted} lines of {len(lines)} left out of the middle of this file ...]\n" + "\n".join(tail)
