"""Scan the reports/ folder into a JSON-serialisable list. Pure — no web deps.

Prefers report_<ts>.json bundles (full report: language, overview, errors,
tech_stack, code). Loose files (docx, orphan code) are listed with metadata only.
"""

import json
import time
from datetime import datetime
from pathlib import Path


def _read_retry(p, tries=8):
    """Read text, retrying past transient iCloud file locks (errno 35)."""
    for _ in range(tries):
        try:
            return p.read_text()
        except OSError:
            time.sleep(0.12)
    return None


def _stat_retry(p, tries=8):
    for _ in range(tries):
        try:
            return p.stat()
        except OSError:
            time.sleep(0.12)
    return None

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


_CACHE: dict = {}   # (path, mtime_ns, size) -> built item; avoids re-reading unchanged bundles on every poll


def _mtime(p) -> float:
    try:
        return p.stat().st_mtime
    except OSError:      # file vanished mid-scan (moved/deleted by another request)
        return 0.0


def _cached(key, build):
    hit = _CACHE.get(key)
    if hit is None:
        hit = build()
        if hit is not None:
            if len(_CACHE) > 2000:
                _CACHE.clear()
            _CACHE[key] = hit
    return dict(hit) if hit is not None else None


def scan_reports(reports_dir) -> list:
    reports_dir = Path(reports_dir)
    if not reports_dir.exists():
        return []
    files = []
    try:
        for p in reports_dir.iterdir():
            try:
                if not p.name.startswith(".") and p.is_file():
                    files.append(p)
            except OSError:      # vanished or locked between listing and stat
                continue
    except OSError:
        return []
    files.sort(key=_mtime, reverse=True)

    out = []
    covered = set()  # code files already shown via their bundle

    # bundles first
    for p in files:
        if p.suffix.lower() != ".json":
            continue
        st = _stat_retry(p)
        if st is None:
            continue
        item = _cached((str(p), st.st_mtime_ns, st.st_size, "bundle"), lambda p=p, st=st: _bundle_item(p, st))
        if item is None:
            continue
        covered.add(item.get("code_file", ""))
        out.append(item)

    # loose files not covered by a bundle
    for p in files:
        if p.suffix.lower() == ".json" or p.name in covered:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        item = _cached((str(p), st.st_mtime_ns, st.st_size, "loose"), lambda p=p, st=st: _loose_item(p, st))
        if item is not None:
            out.append(item)

    out.sort(key=lambda r: r.get("modified", ""), reverse=True)
    return out


def _bundle_item(p, st):
    _txt = _read_retry(p)
    if _txt is None:
        return None
    try:
        meta = json.loads(_txt)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(meta, dict):
        return None
    code_file = meta.get("code_file", "")
    return {
        "kind": "report",
        "name": p.stem,
        "language": meta.get("language", ""),
        "overview": meta.get("overview", ""),
        "errors": meta.get("errors", ""),
        "tech_stack": meta.get("tech_stack", ""),
        "diagrams": meta.get("diagrams", ""),
        "extension": meta.get("extension", ""),
        "code": meta.get("code", ""),
        "code_file": code_file,
        "members": meta.get("members", []),
        "modified": meta.get("created") or datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
    }


def _loose_item(p, st):
    ext = p.suffix.lstrip(".").lower()
    kind = _kind(ext)
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
    return item
