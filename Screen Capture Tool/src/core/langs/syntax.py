from .grammars import parse


def syntax_errors(code: str, lang: str, limit: int = 20) -> list:
    tree = parse(code, lang)
    lines = code.splitlines()
    out = []
    stack = [tree.root_node]
    while stack and len(out) < limit:
        node = stack.pop()
        if node.is_missing:
            row, col = node.start_point
            out.append({"line": row + 1, "col": col + 1, "kind": "missing", "text": f"missing '{node.type}'",
                        "source": lines[row].strip() if row < len(lines) else ""})
            continue
        if node.type == "ERROR":
            row, col = node.start_point
            snippet = node.text.decode("utf-8", errors="replace").splitlines()[0][:60] if node.text else ""
            out.append({"line": row + 1, "col": col + 1, "kind": "error", "text": f"unexpected '{snippet}'",
                        "source": lines[row].strip() if row < len(lines) else ""})
            continue
        if node.has_error:
            stack.extend(reversed(node.children))
    return sorted(out, key=lambda e: (e["line"], e["col"]))


def format_errors(errors: list, filename: str) -> str:
    return "\n".join(f"{filename}:{e['line']}:{e['col']}: syntax error: {e['text']}"
                     + (f" -> \"{e['source']}\"" if e["source"] else "") for e in errors)
