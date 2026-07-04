"""Scan the reports/ folder into a JSON-serialisable list. Pure — no web deps.

Prefers report_<ts>.json bundles (full report: language, overview, errors,
tech_stack, code). Loose files (docx, orphan code) are listed with metadata only.
"""

import json
from datetime import datetime
from pathlib import Path

CODE_EXTS = {"py", "js", "ts", "jsx", "tsx", "c", "h", "cpp", "cc", "cxx", "hpp",
             "cs", "java", "go", "rb", "rs", "swift", "kt", "php", "sh"}
MAX_INLINE = 200_000


def _kind(ext: str) -> str:
    if ext == "docx":
        return "doc"
    if ext in CODE_EXTS:
        return "code"
    if ext in ("txt", "md"):
        return "text"
    return "file"


def scan_reports(reports_dir) -> list:
    reports_dir = Path(reports_dir)
    if not reports_dir.exists():
        return []
    files = [p for p in reports_dir.iterdir() if p.is_file() and not p.name.startswith(".")]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    out = []
    covered = set()  # code files already shown via their bundle

    # bundles first
    for p in files:
        if p.suffix.lower() != ".json":
            continue
        try:
            meta = json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            continue
        st = p.stat()
        code_file = meta.get("code_file", "")
        covered.add(code_file)
        out.append({
            "kind": "report",
            "name": p.stem,
            "language": meta.get("language", ""),
            "overview": meta.get("overview", ""),
            "errors": meta.get("errors", ""),
            "tech_stack": meta.get("tech_stack", ""),
            "extension": meta.get("extension", ""),
            "code": meta.get("code", ""),
            "code_file": code_file,
            "modified": meta.get("created") or datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        })

    # loose files not covered by a bundle
    for p in files:
        if p.suffix.lower() == ".json" or p.name in covered:
            continue
        ext = p.suffix.lstrip(".").lower()
        kind = _kind(ext)
        st = p.stat()
        item = {
            "kind": kind, "name": p.name, "ext": ext,
            "size": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            "content": None, "code_file": p.name,
        }
        if kind in ("code", "text") and st.st_size <= MAX_INLINE:
            try:
                item["content"] = p.read_text(errors="replace")
            except Exception:  # noqa: BLE001
                item["content"] = None
        out.append(item)

    out.sort(key=lambda r: r.get("modified", ""), reverse=True)
    return out
